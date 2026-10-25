"""
Repeated-trial statistics.

The report's Future Work asks to "repeat experiments and report averages or
variability rather than relying on a single run". This does that.

The design is *paired*: within a trial, every algorithm is handed the exact
same workload. That matters more than it looks. Run-to-run variation between
random workloads is large -- easily 20% in energy -- so comparing independent
per-algorithm averages would drown a real 8% effect in noise. Comparing the
*differences* on shared workloads removes the workload variance entirely,
which is why `pairwise_vs` can resolve effects the raw standard deviations
cannot. This is the method known as common random numbers.
"""

import random
import time
from typing import Any, Dict, List, Optional, Sequence

from analysis.workload_gen import generate_workload, summarize_workloads
from sim.energy import energy_delay, summarize_energy
from sim.metrics import advanced_metrics
from sim.params import EAHWeights, EnergyParams, SimConfig
from sim.policies import COMPARE_ORDER, run_algorithm

DEFAULT_METRICS = ("avg_turnaround", "avg_waiting", "total_completion",
                   "context_switches", "total_energy", "edp", "ed2p",
                   "energy_per_process", "avg_response_time",
                   "cpu_utilization", "fairness_index")

MAX_TRIALS = 2000
MAX_SIMULATIONS = 12000


def run_once(algorithm: str, processes: List[Dict[str, Any]],
             cfg: SimConfig) -> Dict[str, Any]:
    """Run one algorithm on one workload and flatten the metrics we compare."""
    result = run_algorithm(algorithm, processes, cfg)
    energy = summarize_energy(result["gantt"], result["context_switches"],
                              result["frequency_switches"], cfg.params,
                              include_timelines=False)
    advanced = advanced_metrics(result, processes)
    ed = energy_delay(energy["total_energy"],
                      result["metrics"]["avg_turnaround"], len(processes))

    flat = {
        "algorithm": result["algorithm"],
        "avg_turnaround": result["metrics"]["avg_turnaround"],
        "avg_waiting": result["metrics"]["avg_waiting"],
        "total_completion": result["metrics"]["total_completion"],
        "context_switches": result["context_switches"],
        "frequency_switches": result["frequency_switches"],
        "total_energy": energy["total_energy"],
        "busy_energy": energy["busy_energy"],
        "idle_energy": energy["idle_energy"],
        "avg_power": energy["avg_power"],
    }
    flat.update(ed)
    flat.update(advanced)
    flat["residency_high"] = energy["frequency_residency"].get("HIGH", 0)
    flat["residency_med"] = energy["frequency_residency"].get("MED", 0)
    flat["residency_low"] = energy["frequency_residency"].get("LOW", 0)
    return flat


def _stats(values: List[float]) -> Dict[str, Any]:
    n = len(values)
    if n == 0:
        return {"mean": 0, "std": 0, "sem": 0, "min": 0, "p25": 0,
                "p50": 0, "p75": 0, "max": 0, "ci95": [0, 0]}
    ordered = sorted(values)
    mean = sum(values) / n
    if n > 1:
        var = sum((v - mean) ** 2 for v in values) / (n - 1)
    else:
        var = 0.0
    std = var ** 0.5
    sem = std / (n ** 0.5) if n else 0.0

    def pct(q):
        if n == 1:
            return ordered[0]
        pos = q * (n - 1)
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        return ordered[lo] * (1 - frac) + ordered[hi] * frac

    return {
        "mean": round(mean, 3),
        "std": round(std, 3),
        "sem": round(sem, 4),
        "min": round(ordered[0], 3),
        "p25": round(pct(0.25), 3),
        "p50": round(pct(0.50), 3),
        "p75": round(pct(0.75), 3),
        "max": round(ordered[-1], 3),
        # Normal approximation; with a few hundred paired trials this is fine.
        "ci95": [round(mean - 1.96 * sem, 3), round(mean + 1.96 * sem, 3)],
    }


def monte_carlo(trials: int = 200, seed: int = 42,
                workload: Optional[Dict[str, Any]] = None,
                algorithms: Optional[Sequence[str]] = None,
                metrics: Optional[Sequence[str]] = None,
                governor: str = "utilization_window",
                quantum: int = 2, threshold: Optional[float] = None,
                params: Optional[Dict[str, Any]] = None,
                eah_weights: Optional[Dict[str, Any]] = None,
                baseline: str = "fcfs") -> Dict[str, Any]:
    """Run every algorithm over `trials` seeded random workloads."""
    algorithms = list(algorithms or COMPARE_ORDER)
    metrics = list(metrics or DEFAULT_METRICS)

    trials = int(trials)
    if trials < 1:
        raise ValueError("trials must be at least 1")
    if trials > MAX_TRIALS:
        raise ValueError(
            "trials capped at {0} (asked for {1})".format(MAX_TRIALS, trials))
    if trials * len(algorithms) > MAX_SIMULATIONS:
        raise ValueError(
            "trials x algorithms capped at {0} (asked for {1})".format(
                MAX_SIMULATIONS, trials * len(algorithms)))

    energy_params = EnergyParams().with_overrides(params)
    weights = EAHWeights().with_overrides(eah_weights)

    started = time.time()

    # One master RNG derives a per-trial seed, so trial t is reproducible on
    # its own and the sequence is reproducible as a whole.
    master = random.Random(seed)
    trial_seeds = [master.getrandbits(32) for _ in range(trials)]

    samples: Dict[str, Dict[str, List[float]]] = {
        algo: {m: [] for m in metrics} for algo in algorithms}
    failures: Dict[str, int] = {algo: 0 for algo in algorithms}
    deltas: Dict[str, Dict[str, List[float]]] = {
        algo: {m: [] for m in metrics} for algo in algorithms}
    wins: Dict[str, Dict[str, int]] = {m: {} for m in metrics}
    workloads = []

    for trial_seed in trial_seeds:
        rng = random.Random(trial_seed)
        processes = generate_workload(rng, workload)
        workloads.append(processes)

        # Every algorithm sees this identical workload -- the paired design.
        per_trial: Dict[str, Dict[str, Any]] = {}
        for algo in algorithms:
            cfg = SimConfig(params=energy_params, eah=weights,
                            governor=governor, quantum=quantum,
                            threshold=threshold, include_timelines=False)
            try:
                per_trial[algo] = run_once(algo, processes, cfg)
            except Exception:
                failures[algo] += 1

        for algo, flat in per_trial.items():
            for m in metrics:
                if flat.get(m) is not None:
                    samples[algo][m].append(float(flat[m]))

        base = per_trial.get(baseline)
        if base:
            for algo, flat in per_trial.items():
                for m in metrics:
                    ref = base.get(m)
                    own = flat.get(m)
                    if ref is None or own is None or ref == 0:
                        continue
                    deltas[algo][m].append((own - ref) / abs(ref) * 100.0)

        for m in metrics:
            scored = [(flat[m], algo) for algo, flat in per_trial.items()
                      if flat.get(m) is not None]
            if scored:
                winner = min(scored)[1]
                wins[m][winner] = wins[m].get(winner, 0) + 1

    results = {}
    for algo in algorithms:
        results[algo] = {
            "algorithm": algo,
            "trials_ok": trials - failures[algo],
            "trials_failed": failures[algo],
            "metrics": {m: _stats(samples[algo][m]) for m in metrics},
        }

    pairwise = {}
    for algo in algorithms:
        if algo == baseline:
            continue
        entry = {}
        for m in metrics:
            vals = deltas[algo][m]
            if not vals:
                continue
            st = _stats(vals)
            entry[m] = {
                "mean_delta_pct": st["mean"],
                "std_delta_pct": st["std"],
                "ci95_delta_pct": st["ci95"],
                "wins": sum(1 for v in vals if v < 0),
                "losses": sum(1 for v in vals if v > 0),
                "ties": sum(1 for v in vals if v == 0),
            }
        pairwise[algo] = entry

    return {
        "seed": seed,
        "trials": trials,
        "governor": governor,
        "quantum": quantum,
        "threshold": threshold,
        "algorithms": algorithms,
        "metrics": metrics,
        "workload_summary": summarize_workloads(workloads),
        "results": results,
        "win_counts": wins,
        "pairwise_vs": {"baseline": baseline, "comparisons": pairwise},
        "parameters": energy_params.to_api_dict(),
        "eah_weights": weights.to_api_dict(),
        "elapsed_ms": int((time.time() - started) * 1000),
        "note": ("All algorithms see an identical workload within each trial "
                 "(common random numbers), so pairwise differences are far "
                 "less noisy than the per-algorithm standard deviations."),
    }
