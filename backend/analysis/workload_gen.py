"""
Seeded random workload generation.

Everything is driven from one integer seed, so any result can be reproduced
exactly. That is the point: the report's own Limitations section concedes that
the evaluation rests on single runs with no variability, and you cannot fix
that with randomness you cannot replay.
"""

import random
from typing import Any, Dict, List, Optional

# Burst distributions. `bimodal` is the default because a short/long mix is
# the workload EAH is designed for -- its whole premise is classifying tasks
# by length. A unimodal generator would flatten that distinction and quietly
# understate every policy that exploits it.
BURST_KINDS = ("bimodal", "uniform", "exponential", "lognormal")
ARRIVAL_KINDS = ("poisson", "uniform", "all_zero")

DEFAULT_SPEC: Dict[str, Any] = {
    "n_processes": {"min": 5, "max": 10},
    # rate 0.25 puts the default workload at an offered load near 2.8: the
    # queue builds, but idle gaps still occur, so the governor and EAH both
    # exercise all three frequency states. Heavier loads pin the clock to
    # HIGH and flatten the comparison; lighter ones hide the queueing.
    "arrival": {"kind": "poisson", "rate": 0.25, "span": None},
    "burst": {"kind": "bimodal", "short_mean": 3, "long_mean": 14,
              "p_long": 0.35, "min": 1, "max": 40},
    "priority": {"min": 1, "max": 5},
    "deadline": None,
}


def _merge(spec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = {k: (dict(v) if isinstance(v, dict) else v)
              for k, v in DEFAULT_SPEC.items()}
    for key, value in (spec or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def _draw_burst(rng: random.Random, cfg: Dict[str, Any]) -> int:
    kind = (cfg.get("kind") or "bimodal").lower()
    lo = int(cfg.get("min", 1))
    hi = int(cfg.get("max", 40))

    if kind == "uniform":
        value = rng.randint(lo, hi)
    elif kind == "exponential":
        mean = float(cfg.get("mean", 6))
        value = int(round(rng.expovariate(1.0 / max(0.5, mean))))
    elif kind == "lognormal":
        value = int(round(rng.lognormvariate(
            float(cfg.get("mu", 1.6)), float(cfg.get("sigma", 0.6)))))
    elif kind == "bimodal":
        if rng.random() < float(cfg.get("p_long", 0.35)):
            mean = float(cfg.get("long_mean", 14))
        else:
            mean = float(cfg.get("short_mean", 3))
        # Jitter around the mode so bursts are not all identical.
        value = int(round(rng.gauss(mean, max(0.5, mean * 0.25))))
    else:
        raise ValueError(
            "unknown burst distribution '{0}'. Available: {1}".format(
                kind, ", ".join(BURST_KINDS)))
    return max(lo, min(hi, value))


def _draw_arrivals(rng: random.Random, n: int,
                   cfg: Dict[str, Any]) -> List[int]:
    kind = (cfg.get("kind") or "poisson").lower()

    if kind == "all_zero":
        return [0] * n
    if kind == "uniform":
        span = int(cfg.get("span") or max(1, n * 2))
        return sorted(rng.randint(0, span) for _ in range(n))
    if kind == "poisson":
        # Exponential inter-arrival gaps, i.e. a Poisson arrival process.
        rate = max(1e-3, float(cfg.get("rate", 0.5)))
        arrivals = []
        t = 0.0
        for _ in range(n):
            arrivals.append(int(t))
            t += rng.expovariate(rate)
        return arrivals
    raise ValueError(
        "unknown arrival process '{0}'. Available: {1}".format(
            kind, ", ".join(ARRIVAL_KINDS)))


def generate_workload(rng: random.Random,
                      spec: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Draw one random workload."""
    cfg = _merge(spec)

    n_cfg = cfg["n_processes"]
    if isinstance(n_cfg, int):
        n = n_cfg
    else:
        n = rng.randint(int(n_cfg.get("min", 5)), int(n_cfg.get("max", 10)))
    n = max(1, min(60, n))

    arrivals = _draw_arrivals(rng, n, cfg["arrival"])
    bursts = [_draw_burst(rng, cfg["burst"]) for _ in range(n)]

    prio = cfg["priority"]
    p_lo, p_hi = int(prio.get("min", 1)), int(prio.get("max", 5))

    processes = []
    for i in range(n):
        proc = {
            "pid": i + 1,
            "arrival": arrivals[i],
            "burst": bursts[i],
            "priority": rng.randint(p_lo, p_hi),
        }
        dl = cfg.get("deadline")
        if dl:
            # Deadline as a multiple of the burst, measured from arrival.
            slack = rng.uniform(float(dl.get("min_factor", 1.5)),
                                float(dl.get("max_factor", 4.0)))
            proc["deadline"] = int(round(arrivals[i] + bursts[i] * slack))
        processes.append(proc)
    return processes


def summarize_workloads(workloads: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Describe what was actually generated, so a run is self-documenting."""
    if not workloads:
        return {}
    counts = [len(w) for w in workloads]
    works = [sum(p["burst"] for p in w) for w in workloads]
    spans = []
    for w in workloads:
        arrivals = [p["arrival"] for p in w]
        spans.append(max(arrivals) - min(arrivals) if arrivals else 0)

    def mean(xs):
        return round(sum(xs) / len(xs), 2) if xs else 0

    return {
        "mean_processes": mean(counts),
        "mean_total_work": mean(works),
        "mean_arrival_span": mean(spans),
        # Offered load: work arriving per unit of arrival time. Above ~1.0 the
        # CPU is saturated and queues build, which is where frequency choices
        # start to matter.
        "mean_offered_load": round(
            sum(w / s if s else float(w) for w, s in zip(works, spans))
            / len(works), 2) if works else 0,
    }
