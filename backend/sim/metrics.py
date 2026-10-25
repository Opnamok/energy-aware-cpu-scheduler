"""
Performance metrics and drill-down statistics.

`advanced_metrics` keeps the four keys the UI already reads, with two notes:

* `avg_response_time` used to be hardcoded zero. It matched `g.get('pid')`
  against Gantt segments that only ever carried `process`, so the lookup
  always fell through to the default and every response time computed as
  `arrival - arrival`. Segments now carry `pid`, and the engine records the
  first dispatch directly, so the figure is real for the first time.

* `cpu_utilization` is now busy time over wall-clock time. Previously it was
  total burst over completion time, which was only the same thing while
  frequency could not stretch execution. The old quantity is still reported,
  under `work_per_time`, because it answers a different and still useful
  question: how much work got done per unit of elapsed time.
"""

from typing import Any, Dict, List, Optional

from sim.params import ACTIVE_STATES, DEFAULT_PARAMS, EnergyParams


def advanced_metrics(result: Dict[str, Any],
                     processes_input: List[Dict]) -> Dict[str, Any]:
    """CPU utilisation, throughput, response time and fairness."""
    processes = result.get("processes", [])
    internal = result.get("_internal", {})
    completion = result.get("metrics", {}).get("total_completion", 0) or 0

    if not processes or not completion:
        return {
            "cpu_utilization": 0,
            "work_per_time": 0,
            "throughput": 0,
            "avg_response_time": 0,
            "fairness_index": 0,
            "fairness_slowdown": 0,
        }

    busy_ticks = internal.get("busy_ticks")
    total_tick = internal.get("total_tick")
    if busy_ticks is not None and total_tick:
        cpu_utilization = round(busy_ticks / total_tick * 100, 2)
    else:
        cpu_utilization = 0

    total_work = sum(p.get("burst", 0) for p in processes_input)
    work_per_time = round(total_work / completion * 100, 2)

    throughput = round(len(processes) / completion, 4)

    response_times = [_response_time(p, result) for p in processes]
    avg_response = round(sum(response_times) / len(response_times), 2)

    tats = [p.get("turnaround", 0) for p in processes]
    fairness = _jain(tats)

    # Fairness over *slowdown* (turnaround / execution time) rather than raw
    # turnaround. Raw turnaround calls a schedule unfair simply for containing
    # jobs of different sizes; slowdown asks whether each job was treated
    # proportionately, which is the question fairness is meant to answer.
    slowdowns = []
    for p in processes:
        exec_time = p.get("exec_time") or p.get("burst") or 0
        if exec_time:
            slowdowns.append(p.get("turnaround", 0) / exec_time)
    fairness_slowdown = _jain(slowdowns)

    return {
        "cpu_utilization": cpu_utilization,
        "work_per_time": work_per_time,
        "throughput": throughput,
        "avg_response_time": avg_response,
        "fairness_index": fairness,
        "fairness_slowdown": fairness_slowdown,
    }


def _response_time(process: Dict[str, Any], result: Dict[str, Any]) -> float:
    """Time from arrival until the process first got the CPU."""
    if process.get("response_time") is not None:
        return process["response_time"]
    # Fall back to scanning the Gantt chart, which now carries pid.
    pid = process.get("pid")
    arrival = process.get("arrival", 0)
    for seg in result.get("gantt", []):
        if seg.get("pid") == pid and seg.get("process") != "IDLE":
            return seg["start"] - arrival
    return 0


def _jain(values: List[float]) -> float:
    """Jain's fairness index: 1.0 is perfectly fair, 1/n is maximally unfair."""
    values = [v for v in values if v is not None]
    n = len(values)
    if n == 0:
        return 0
    total = sum(values)
    total_sq = sum(v * v for v in values)
    if total_sq <= 0:
        return 1.0
    return round((total ** 2) / (n * total_sq), 4)


# --------------------------------------------------------------------------
# Drill-down
# --------------------------------------------------------------------------

def distribution(values: List[float], bins: int = 5) -> Dict[str, Any]:
    """Five-number summary plus a histogram."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return {"min": 0, "p25": 0, "median": 0, "p75": 0, "max": 0,
                "mean": 0, "std": 0,
                "histogram": {"bin_width": 0, "edges": [], "counts": []}}

    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    lo, hi = vals[0], vals[-1]

    width = (hi - lo) / bins if hi > lo else 1.0
    edges = [round(lo + i * width, 4) for i in range(bins + 1)]
    counts = [0] * bins
    for v in vals:
        if hi > lo:
            idx = min(bins - 1, int((v - lo) / width))
        else:
            idx = 0
        counts[idx] += 1

    return {
        "min": round(lo, 2),
        "p25": round(_percentile(vals, 0.25), 2),
        "median": round(_percentile(vals, 0.50), 2),
        "p75": round(_percentile(vals, 0.75), 2),
        "max": round(hi, 2),
        "mean": round(mean, 2),
        "std": round(var ** 0.5, 2),
        "histogram": {
            "bin_width": round(width, 4),
            "edges": edges,
            "counts": counts,
        },
    }


def _percentile(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def starvation_report(result: Dict[str, Any],
                      params: Optional[EnergyParams] = None) -> Dict[str, Any]:
    """Flag processes that waited disproportionately.

    Two independent tests, because either alone misses cases: an absolute one
    (waited more than `starvation_wait_factor` times its own execution time)
    and a normalised-turnaround one (took more than `starvation_ntat_factor`
    times as long as it needed). A short job stuck behind a long one trips the
    second but not always the first.
    """
    params = params or DEFAULT_PARAMS
    processes = result.get("processes", [])
    if not processes:
        return {"any_starved": False, "starved_pids": [], "max_wait": 0,
                "max_wait_pid": None, "max_normalized_turnaround": 0,
                "max_normalized_turnaround_pid": None,
                "wait_factor": params.starvation_wait_factor,
                "ntat_factor": params.starvation_ntat_factor}

    starved = []
    max_wait, max_wait_pid = -1.0, None
    max_ntat, max_ntat_pid = 0.0, None

    for p in processes:
        wait = p.get("waiting", 0) or 0
        exec_time = p.get("exec_time") or p.get("burst") or 1
        ntat = (p.get("turnaround", 0) or 0) / exec_time

        if wait > max_wait:
            max_wait, max_wait_pid = wait, p.get("pid")
        if ntat > max_ntat:
            max_ntat, max_ntat_pid = ntat, p.get("pid")

        if (wait > params.starvation_wait_factor * exec_time
                or ntat > params.starvation_ntat_factor):
            starved.append(p.get("pid"))

    return {
        "any_starved": bool(starved),
        "starved_pids": starved,
        "max_wait": round(max_wait, 2),
        "max_wait_pid": max_wait_pid,
        "max_normalized_turnaround": round(max_ntat, 2),
        "max_normalized_turnaround_pid": max_ntat_pid,
        "wait_factor": params.starvation_wait_factor,
        "ntat_factor": params.starvation_ntat_factor,
    }


def per_process_detail(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per-process rows for the drill-down table."""
    rows = []
    for p in result.get("processes", []):
        exec_time = p.get("exec_time") or p.get("burst") or 1
        row = dict(p)
        row["normalized_turnaround"] = round(
            (p.get("turnaround", 0) or 0) / exec_time, 3)
        rows.append(row)
    return sorted(rows, key=lambda r: r.get("pid", 0))


# Legacy alias: server.py and multicore_scheduler.py import this name.
def calculate_advanced_metrics(result: Dict[str, Any],
                               processes_input: List[Dict]) -> Dict[str, Any]:
    return advanced_metrics(result, processes_input)
