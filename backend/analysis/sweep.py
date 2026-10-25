"""
Parameter sweeps.

Answers the "Future Work" item about evaluating "multiple workload classes,
arrival patterns, burst distributions and Round Robin quantum values" by
plotting a metric against one parameter at a time.

The most instructive axis is `p_static`, the leakage floor. Sweeping it shows
the energy-optimal frequency migrating from LOW to MED to HIGH, which is the
physical reason real systems do not simply run as slowly as possible. Most
other sweeps change one policy's behaviour; this one changes the shape of the
trade-off itself.
"""

import random
import time
from typing import Any, Dict, List, Optional, Sequence

from analysis.montecarlo import DEFAULT_METRICS, _stats, run_once
from analysis.workload_gen import generate_workload
from sim.governors import list_governors
from sim.params import EAHWeights, EnergyParams, SimConfig
from sim.policies import COMPARE_ORDER

MAX_POINTS = 2000

# Which parameter affects which algorithms, so the UI can grey out flat lines.
AFFECTS = {
    "quantum": ("round_robin",),
    "eah_threshold": ("eah",),
    "urgency_high": ("eah",),
    "urgency_med": ("eah",),
    "w_short": ("eah",),
    "w_wait": ("eah",),
}

LABELS = {
    "quantum": "Round Robin quantum (work units)",
    "eah_threshold": "EAH short/long threshold",
    "p_static": "Static (leakage) power floor, W",
    "c_eff": "Effective switched capacitance",
    "governor": "Frequency governor",
    "util_threshold_high": "Governor HIGH utilisation threshold",
    "urgency_high": "EAH urgency threshold for HIGH",
    "urgency_med": "EAH urgency threshold for MED",
    "context_switch_penalty": "Context-switch energy penalty",
    "freq_switch_penalty": "Frequency-switch energy penalty",
    "w_short": "EAH weight on job shortness",
    "w_wait": "EAH weight on waiting time (aging)",
}

ENERGY_PARAM_FIELDS = set(EnergyParams().__dataclass_fields__)
EAH_WEIGHT_FIELDS = set(EAHWeights().__dataclass_fields__)
GOVERNOR_NAMES = {g["name"] for g in list_governors()}


def _values(spec: Dict[str, Any]) -> List[Any]:
    if spec.get("values") is not None:
        return list(spec["values"])
    start = spec.get("from")
    stop = spec.get("to")
    step = spec.get("step", 1)
    if start is None or stop is None:
        raise ValueError(
            "sweep for '{0}' needs either 'values' or 'from'/'to'/'step'"
            .format(spec.get("param")))
    out = []
    value = start
    # Integer stepping where possible, so the axis labels stay clean.
    if all(float(x).is_integer() for x in (start, stop, step)):
        for v in range(int(start), int(stop) + 1, int(step)):
            out.append(v)
    else:
        while value <= stop + 1e-9:
            out.append(round(value, 6))
            value += step
    if not out:
        raise ValueError("sweep for '{0}' produced no points".format(
            spec.get("param")))
    return out


def _apply(param: str, value: Any, base_params: EnergyParams,
           base_weights: EAHWeights, governor: str, quantum: int,
           threshold: Optional[float]):
    """Resolve one sweep point into a concrete configuration."""
    params, weights = base_params, base_weights

    if param == "quantum":
        quantum = int(value)
    elif param == "eah_threshold":
        threshold = float(value)
    elif param == "governor":
        if value not in GOVERNOR_NAMES:
            raise ValueError("unknown governor '{0}' in sweep".format(value))
        governor = value
    elif param in ENERGY_PARAM_FIELDS:
        params = base_params.with_overrides({param: value})
    elif param in EAH_WEIGHT_FIELDS:
        weights = base_weights.with_overrides({param: value})
    else:
        known = sorted({"quantum", "eah_threshold", "governor"}
                       | ENERGY_PARAM_FIELDS | EAH_WEIGHT_FIELDS)
        raise ValueError(
            "cannot sweep '{0}'. Available: {1}".format(param, ", ".join(known)))

    return params, weights, governor, quantum, threshold


def sweep(sweeps: Sequence[Dict[str, Any]],
          processes: Optional[List[Dict[str, Any]]] = None,
          workload: Optional[Dict[str, Any]] = None,
          seed: int = 7, trials_per_point: int = 1,
          algorithms: Optional[Sequence[str]] = None,
          metrics: Optional[Sequence[str]] = None,
          governor: str = "utilization_window",
          quantum: int = 2, threshold: Optional[float] = None,
          params: Optional[Dict[str, Any]] = None,
          eah_weights: Optional[Dict[str, Any]] = None,
          include_unaffected: bool = True) -> Dict[str, Any]:
    """Sweep each listed parameter independently.

    Pass `processes` to sweep over one fixed workload, or `workload` to average
    each point over `trials_per_point` seeded random workloads -- the latter
    being the honest option when the curve is noisy.
    """
    algorithms = list(algorithms or COMPARE_ORDER)
    metrics = list(metrics or ("avg_turnaround", "total_energy", "edp",
                               "context_switches"))
    if not sweeps:
        raise ValueError("no sweeps requested")

    base_params = EnergyParams().with_overrides(params)
    base_weights = EAHWeights().with_overrides(eah_weights)

    fixed = processes is not None
    trials_per_point = 1 if fixed else max(1, int(trials_per_point))

    total_points = sum(len(_values(s)) for s in sweeps)
    if total_points * trials_per_point * len(algorithms) > MAX_POINTS * 6:
        raise ValueError(
            "sweep too large: {0} points x {1} trials x {2} algorithms. "
            "Reduce the ranges or the trial count.".format(
                total_points, trials_per_point, len(algorithms)))

    started = time.time()

    # The same workloads are reused at every sweep point, so the curve shows
    # the parameter's effect rather than workload noise.
    if fixed:
        workloads = [processes]
    else:
        master = random.Random(seed)
        workloads = [generate_workload(random.Random(master.getrandbits(32)),
                                       workload)
                     for _ in range(trials_per_point)]

    series = []
    for spec in sweeps:
        param = spec.get("param")
        values = _values(dict(spec, param=param))
        affected = AFFECTS.get(param)
        shown = (list(algorithms) if (include_unaffected or not affected)
                 else [a for a in algorithms if a in affected])

        points = []
        for value in values:
            try:
                p, w, gov, q, thr = _apply(param, value, base_params,
                                           base_weights, governor, quantum,
                                           threshold)
            except ValueError as exc:
                points.append({"value": value, "error": str(exc)})
                continue

            per_algo: Dict[str, Dict[str, Any]] = {}
            for algo in shown:
                collected = {m: [] for m in metrics}
                for wl in workloads:
                    cfg = SimConfig(params=p, eah=w, governor=gov, quantum=q,
                                    threshold=thr, include_timelines=False)
                    try:
                        flat = run_once(algo, wl, cfg)
                    except Exception:
                        continue
                    for m in metrics:
                        if flat.get(m) is not None:
                            collected[m].append(float(flat[m]))
                per_algo[algo] = {m: _stats(collected[m]) for m in metrics}
            points.append({"value": value, "algorithms": per_algo})

        series.append({
            "param": param,
            "label": LABELS.get(param, param),
            "affects": list(affected) if affected else list(algorithms),
            "global": affected is None,
            "points": points,
        })

    return {
        "series": series,
        "seed": seed,
        "trials_per_point": trials_per_point,
        "fixed_workload": fixed,
        "algorithms": algorithms,
        "metrics": metrics,
        "governor": governor,
        "parameters": base_params.to_api_dict(),
        "eah_weights": base_weights.to_api_dict(),
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def sweepable() -> Dict[str, Any]:
    """Describe the sweepable axes, for the UI to offer."""
    out = []
    for name in sorted({"quantum", "eah_threshold", "governor"}
                       | ENERGY_PARAM_FIELDS | EAH_WEIGHT_FIELDS):
        out.append({
            "param": name,
            "label": LABELS.get(name, name),
            "affects": list(AFFECTS.get(name, ())) or "all",
            "kind": "categorical" if name == "governor" else "numeric",
        })
    return {"sweepable": out, "governors": sorted(GOVERNOR_NAMES)}
