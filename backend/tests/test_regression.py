"""
The regression gate.

With the clock pinned to HIGH, one unit of work takes exactly one time unit,
so the refactored engine must reproduce the pre-DVFS schedules exactly: same
Gantt, same metrics, same context switches, same per-process figures. If this
fails, the refactor changed scheduling semantics rather than just adding
frequency to them.

`tests/golden_pre_dvfs.json` was captured from the original implementation
before any of the new code existed.

Run with:  python -m pytest tests/ -q      (from the backend/ directory)
       or:  python tests/test_regression.py
"""

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from sim.metrics import advanced_metrics                      # noqa: E402
from sim.params import EnergyParams, SimConfig                # noqa: E402
from sim.policies import (energy_aware_hybrid, fcfs,           # noqa: E402
                          priority_scheduling, round_robin,
                          sjf_non_preemptive, sjf_preemptive)

GOLDEN = json.load(io.open(os.path.join(HERE, "golden_pre_dvfs.json"),
                           encoding="utf-8"))

# Response time is deliberately excluded: it was a hardcoded zero in the
# original because of the pid-lookup bug, so matching it would mean preserving
# the bug. It gets its own test below.
COMPARED_ADVANCED = ("cpu_utilization", "throughput", "fairness_index")


def _fixed_high(quantum=2, threshold=None):
    return SimConfig(params=EnergyParams(), governor="fixed:high",
                     quantum=quantum, threshold=threshold,
                     include_timelines=False)


def _run(name, procs, quantum, threshold):
    cfg = _fixed_high(quantum, threshold)
    if name == "fcfs":
        return fcfs(procs, cfg)
    if name == "sjf_non_preemptive":
        return sjf_non_preemptive(procs, cfg)
    if name == "sjf_preemptive":
        return sjf_preemptive(procs, cfg)
    if name == "round_robin":
        return round_robin(procs, quantum, cfg)
    if name == "priority":
        return priority_scheduling(procs, False, cfg)
    if name == "priority_preemptive":
        return priority_scheduling(procs, True, cfg)
    if name == "eah":
        return energy_aware_hybrid(procs, threshold, cfg)
    raise AssertionError("unknown algorithm " + name)


def _collect_failures():
    failures = []
    for workload, entry in sorted(GOLDEN.items()):
        procs = entry["input"]["processes"]
        quantum = entry["input"]["quantum"]
        threshold = entry["input"]["threshold"]

        for algo, expected in sorted(entry["runs"].items()):
            # EAH's process-selection rule changed on purpose: the score-based
            # ordering with aging replaces "drain all short jobs first", which
            # could starve a long job indefinitely. Its schedule is checked by
            # invariants instead of against the golden file.
            if algo == "eah":
                continue

            got = _run(algo, procs, quantum, threshold)
            where = "{0}/{1}".format(workload, algo)

            got_gantt = [{"process": g["process"], "start": g["start"],
                          "end": g["end"]} for g in got["gantt"]]
            if got_gantt != expected["gantt"]:
                failures.append("{0}: gantt\n  want {1}\n  got  {2}".format(
                    where, expected["gantt"], got_gantt))

            for key in ("avg_turnaround", "avg_waiting", "total_completion"):
                if got["metrics"][key] != expected["metrics"][key]:
                    failures.append("{0}: metrics.{1} want {2} got {3}".format(
                        where, key, expected["metrics"][key],
                        got["metrics"][key]))

            if got["context_switches"] != expected["context_switches"]:
                failures.append("{0}: context_switches want {1} got {2}".format(
                    where, expected["context_switches"],
                    got["context_switches"]))

            got_procs = {p["pid"]: p for p in got["processes"]}
            for exp_p in expected["processes"]:
                pid = exp_p["pid"]
                if pid not in got_procs:
                    failures.append("{0}: P{1} missing".format(where, pid))
                    continue
                for key in ("completion", "turnaround", "waiting"):
                    if got_procs[pid][key] != exp_p[key]:
                        failures.append(
                            "{0}: P{1}.{2} want {3} got {4}".format(
                                where, pid, key, exp_p[key],
                                got_procs[pid][key]))

            got_adv = advanced_metrics(got, procs)
            for key in COMPARED_ADVANCED:
                if got_adv[key] != expected["advanced_metrics"][key]:
                    failures.append("{0}: advanced.{1} want {2} got {3}".format(
                        where, key, expected["advanced_metrics"][key],
                        got_adv[key]))
    return failures


def test_fixed_high_matches_pre_dvfs_behaviour():
    failures = _collect_failures()
    assert not failures, "\n".join(failures)


def test_response_time_is_no_longer_always_zero():
    """The pid-lookup bug made every response time zero. P2 waits 5 here."""
    procs = [{"pid": 1, "arrival": 0, "burst": 5, "priority": 1},
             {"pid": 2, "arrival": 1, "burst": 3, "priority": 2}]
    result = fcfs(procs, _fixed_high())
    adv = advanced_metrics(result, procs)
    # P1 starts immediately (0), P2 starts at 5 having arrived at 1 (4).
    assert adv["avg_response_time"] == 2.0, adv
    by_pid = {p["pid"]: p for p in result["processes"]}
    assert by_pid[1]["response_time"] == 0
    assert by_pid[2]["response_time"] == 4


if __name__ == "__main__":
    probs = _collect_failures()
    if probs:
        print("FAIL ({0} mismatch(es)):".format(len(probs)))
        for p in probs[:40]:
            print(" -", p)
        sys.exit(1)
    test_response_time_is_no_longer_always_zero()
    print("PASS: fixed-HIGH behaviour matches the pre-DVFS golden output")
    print("PASS: response time is computed rather than hardcoded to zero")
