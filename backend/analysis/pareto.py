"""
Energy-delay metrics and Pareto analysis.

The report says, correctly, that "a single policy cannot be declared best in
all cases without specifying the workload and the relative importance of these
metrics". A weighted score hides that choice inside its weights. A Pareto
frontier states it plainly: these policies are not beaten on both axes at
once, and picking between them *is* the trade-off you have to make.
"""

from typing import Any, Dict, List, Optional, Sequence

# Objectives are all minimised. Anything not listed here is rejected rather
# than silently treated as "smaller is better".
MINIMIZED = ("total_energy", "avg_turnaround", "avg_waiting",
             "total_completion", "context_switches", "edp", "ed2p",
             "energy_per_process", "avg_response_time")


def _eps(value: float) -> float:
    """Tolerance that scales with magnitude, so float noise is not domination."""
    return max(1e-9, 1e-6 * abs(value))


def dominates(a: Dict[str, float], b: Dict[str, float],
              objectives: Sequence[str]) -> bool:
    """True if `a` is at least as good as `b` everywhere and better somewhere."""
    strictly_better = False
    for obj in objectives:
        av, bv = a.get(obj, 0.0), b.get(obj, 0.0)
        tol = _eps(bv)
        if av > bv + tol:
            return False
        if av < bv - tol:
            strictly_better = True
    return strictly_better


def pareto_analysis(points: List[Dict[str, Any]],
                    objectives: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Rank points by Pareto dominance.

    `points` are dicts carrying a `key` plus the objective values. Rank 1 is
    the frontier; rank 2 is the frontier of what remains once rank 1 is
    removed, and so on.
    """
    objectives = tuple(objectives or ("total_energy", "avg_turnaround"))
    unknown = [o for o in objectives if o not in MINIMIZED]
    if unknown:
        raise ValueError(
            "objective(s) {0} are not recognised as minimised. "
            "Available: {1}".format(", ".join(unknown), ", ".join(MINIMIZED)))

    valid = [p for p in points if not p.get("error")]

    # Rank by iterated peeling of the frontier.
    remaining = list(valid)
    rank = 1
    ranks: Dict[str, int] = {}
    while remaining:
        front = [p for p in remaining
                 if not any(dominates(q, p, objectives)
                            for q in remaining if q is not p)]
        if not front:   # guard against a pathological cycle
            front = list(remaining)
        for p in front:
            ranks[p["key"]] = rank
        remaining = [p for p in remaining if p not in front]
        rank += 1

    for p in valid:
        p["pareto_rank"] = ranks.get(p["key"], 0)
        p["non_dominated"] = p["pareto_rank"] == 1
        p["dominated_by"] = sorted(
            q["key"] for q in valid
            if q is not p and dominates(q, p, objectives))

    frontier = sorted((p["key"] for p in valid if p["non_dominated"]))

    best = {}
    for obj in MINIMIZED:
        candidates = [p for p in valid if obj in p]
        if candidates:
            best[obj] = min(candidates, key=lambda p: p[obj])["key"]

    return {
        "objectives": list(objectives),
        "pareto_frontier": frontier,
        "best": best,
        "knee": _knee(valid, objectives),
        "points": points,
    }


def _knee(points: List[Dict[str, Any]],
          objectives: Sequence[str]) -> Optional[str]:
    """The frontier point closest to the (unreachable) ideal.

    Each objective is normalised to its own observed range, so the answer does
    not depend on energy and time happening to share a scale. This is a
    suggestion for "balanced", not a verdict -- which is why the frontier is
    reported alongside it.
    """
    front = [p for p in points if p.get("non_dominated")]
    if not front:
        return None
    if len(front) == 1:
        return front[0]["key"]

    ranges = {}
    for obj in objectives:
        values = [p.get(obj, 0.0) for p in points]
        lo, hi = min(values), max(values)
        ranges[obj] = (lo, hi - lo if hi > lo else 1.0)

    def distance(p):
        total = 0.0
        for obj in objectives:
            lo, span = ranges[obj]
            total += ((p.get(obj, 0.0) - lo) / span) ** 2
        return total

    return min(front, key=lambda p: (distance(p), p["key"]))["key"]


def normalized_radar(points: List[Dict[str, Any]],
                     metrics: Sequence[str]) -> Dict[str, Any]:
    """Per-metric scores in 0..1 where 1 is best, for a radar chart.

    Normalising against the best observed value (rather than the range) keeps
    the chart readable when one policy is an outlier.
    """
    valid = [p for p in points if not p.get("error")]
    if not valid:
        return {"metrics": list(metrics), "series": []}

    bests = {}
    for metric in metrics:
        values = [p.get(metric) for p in valid if p.get(metric) is not None]
        bests[metric] = min(values) if values else None

    series = []
    for p in valid:
        scores = []
        for metric in metrics:
            best = bests.get(metric)
            value = p.get(metric)
            if not best or value is None or value <= 0:
                scores.append(1.0 if value == best else 0.0)
            else:
                # best/value, so the best scores 1.0 and worse scores less.
                scores.append(round(min(1.0, best / value), 4))
        series.append({"key": p["key"],
                       "algorithm": p.get("algorithm", p["key"]),
                       "scores": scores})
    return {"metrics": list(metrics), "series": series}
