"""
Benchmark every sample workload against a running server.

Prints, per workload, each algorithm's metrics plus the Pareto frontier -- the
set of policies that nothing else beats on both energy and turnaround at once.
That is a more honest summary than a single weighted winner, which hides the
weighting inside itself.

Usage:
    uvicorn server:app --port 8000      # in another terminal
    python test_samples.py [--url http://localhost:8000] [--csv out.csv]

Uses only the standard library, and prints plain ASCII so it works in a
Windows console (cp1252 cannot encode emoji).
"""

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request

samples = {
    "fcfs1": {
        "name": "Sequential Optimal - FCFS Wins",
        "processes": [
            {"pid": 1, "arrival": 0, "burst": 3, "priority": 3},
            {"pid": 2, "arrival": 4, "burst": 5, "priority": 3},
            {"pid": 3, "arrival": 10, "burst": 4, "priority": 3}
        ]
    },
    "sjf1": {
        "name": "Burst Disparity - SJF Wins",
        "processes": [
            {"pid": 1, "arrival": 0, "burst": 25, "priority": 3},
            {"pid": 2, "arrival": 0, "burst": 1, "priority": 3},
            {"pid": 3, "arrival": 0, "burst": 2, "priority": 3},
            {"pid": 4, "arrival": 0, "burst": 18, "priority": 3},
            {"pid": 5, "arrival": 0, "burst": 3, "priority": 3}
        ]
    },
    "srtf1": {
        "name": "Late Short Jobs - SRTF Wins",
        "processes": [
            {"pid": 1, "arrival": 0, "burst": 18, "priority": 3},
            {"pid": 2, "arrival": 2, "burst": 1, "priority": 3},
            {"pid": 3, "arrival": 5, "burst": 1, "priority": 3},
            {"pid": 4, "arrival": 8, "burst": 2, "priority": 3}
        ]
    },
    "rr1": {
        "name": "Interactive Fairness Test",
        "processes": [
            {"pid": 1, "arrival": 0, "burst": 30, "priority": 3},
            {"pid": 2, "arrival": 2, "burst": 4, "priority": 3},
            {"pid": 3, "arrival": 4, "burst": 4, "priority": 3},
            {"pid": 4, "arrival": 6, "burst": 4, "priority": 3},
            {"pid": 5, "arrival": 8, "burst": 4, "priority": 3}
        ]
    },
    "priority1": {
        "name": "Urgent Task Test",
        "processes": [
            {"pid": 1, "arrival": 0, "burst": 15, "priority": 5},
            {"pid": 2, "arrival": 2, "burst": 2, "priority": 1},
            {"pid": 3, "arrival": 0, "burst": 15, "priority": 5},
            {"pid": 4, "arrival": 5, "burst": 2, "priority": 1},
            {"pid": 5, "arrival": 3, "burst": 3, "priority": 2}
        ]
    },
    "eah1": {
        "name": "Energy Optimization Test",
        "processes": [
            {"pid": 1, "arrival": 0, "burst": 1, "priority": 3},
            {"pid": 2, "arrival": 0, "burst": 1, "priority": 3},
            {"pid": 3, "arrival": 0, "burst": 1, "priority": 3},
            {"pid": 4, "arrival": 0, "burst": 25, "priority": 3},
            {"pid": 5, "arrival": 0, "burst": 25, "priority": 3},
            {"pid": 6, "arrival": 0, "burst": 2, "priority": 3}
        ]
    },
    "rr2": {
        "name": "Convoy Effect Test",
        "processes": [
            {"pid": 1, "arrival": 0, "burst": 15, "priority": 3},
            {"pid": 2, "arrival": 0, "burst": 8, "priority": 3},
            {"pid": 3, "arrival": 0, "burst": 6, "priority": 3},
            {"pid": 4, "arrival": 0, "burst": 4, "priority": 3},
            {"pid": 5, "arrival": 0, "burst": 3, "priority": 3}
        ]
    },
    "priority2": {
        "name": "Emergency Response Test",
        "processes": [
            {"pid": 1, "arrival": 0, "burst": 20, "priority": 5},
            {"pid": 2, "arrival": 3, "burst": 1, "priority": 1},
            {"pid": 3, "arrival": 0, "burst": 20, "priority": 5},
            {"pid": 4, "arrival": 7, "burst": 1, "priority": 1},
            {"pid": 5, "arrival": 10, "burst": 2, "priority": 2}
        ]
    },
    "eah2": {
        "name": "Mobile Device Test",
        "processes": [
            {"pid": 1, "arrival": 0, "burst": 1, "priority": 3},
            {"pid": 2, "arrival": 0, "burst": 1, "priority": 3},
            {"pid": 3, "arrival": 0, "burst": 1, "priority": 3},
            {"pid": 4, "arrival": 0, "burst": 1, "priority": 3},
            {"pid": 5, "arrival": 0, "burst": 30, "priority": 3},
            {"pid": 6, "arrival": 0, "burst": 30, "priority": 3},
            {"pid": 7, "arrival": 0, "burst": 2, "priority": 3}
        ]
    }
}



ALGOS = ("fcfs", "sjf_non_preemptive", "sjf_preemptive",
         "round_robin", "priority", "eah")

SHORT = {"fcfs": "FCFS", "sjf_non_preemptive": "SJF", "sjf_preemptive": "SRTF",
         "round_robin": "RR", "priority": "PRIO", "eah": "EAH"}


def compare(base_url, processes, quantum=2, governor=None):
    payload = {"processes": processes, "quantum": quantum}
    if governor:
        payload["governor"] = governor
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/compare",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000",
                        help="base URL of a running server")
    parser.add_argument("--quantum", type=int, default=2)
    parser.add_argument("--governor", default=None,
                        help="frequency governor (default: server's own)")
    parser.add_argument("--csv", default=None,
                        help="also write the full metric matrix to this file")
    args = parser.parse_args()

    print("=" * 78)
    print("SAMPLE WORKLOAD BENCHMARK")
    print("=" * 78)

    rows = []
    frontier_counts = {}

    for sample_id, sample in samples.items():
        print()
        print("-" * 78)
        print("%s  --  %s" % (sample_id, sample["name"]))
        print("-" * 78)

        try:
            results = compare(args.url, sample["processes"], args.quantum,
                              args.governor)
        except urllib.error.URLError as exc:
            print("  could not reach %s (%s)" % (args.url, exc.reason))
            print("  start the server first:  uvicorn server:app --port 8000")
            return 1

        analysis = results.get("_analysis", {})
        pareto = analysis.get("pareto", {})
        frontier = set(pareto.get("pareto_frontier", []))

        print("  %-6s %9s %9s %9s %8s %7s %9s  %s" % (
            "algo", "complete", "turnarnd", "waiting", "energy", "switch",
            "EDP", "pareto"))
        for key in ALGOS:
            data = results.get(key)
            if not data or "error" in data:
                print("  %-6s  error: %s" % (
                    SHORT.get(key, key), (data or {}).get("error", "missing")))
                continue
            mark = "frontier" if key in frontier else ""
            print("  %-6s %9s %9s %9s %8s %7s %9s  %s" % (
                SHORT.get(key, key), data["completion_time"],
                data["avg_turnaround"], data["avg_waiting"],
                data["total_energy"], data["context_switches"],
                data["edp"], mark))
            rows.append({
                "workload": sample_id,
                "name": sample["name"],
                "algorithm": key,
                "completion": data["completion_time"],
                "avg_turnaround": data["avg_turnaround"],
                "avg_waiting": data["avg_waiting"],
                "total_energy": data["total_energy"],
                "context_switches": data["context_switches"],
                "frequency_switches": data.get("frequency_switches"),
                "edp": data["edp"],
                "ed2p": data["ed2p"],
                "on_pareto_frontier": key in frontier,
            })

        for key in frontier:
            frontier_counts[key] = frontier_counts.get(key, 0) + 1

        best = pareto.get("best", {})
        print()
        print("  lowest energy:     %s" % SHORT.get(best.get("total_energy"),
                                                    best.get("total_energy")))
        print("  lowest turnaround: %s" % SHORT.get(best.get("avg_turnaround"),
                                                    best.get("avg_turnaround")))
        print("  balanced (knee):   %s" % SHORT.get(pareto.get("knee"),
                                                    pareto.get("knee")))

    print()
    print("=" * 78)
    print("SUMMARY: times each policy was on the Pareto frontier (of %d workloads)"
          % len(samples))
    print("=" * 78)
    for key in ALGOS:
        count = frontier_counts.get(key, 0)
        bar = "#" * count
        print("  %-6s %2d  %s" % (SHORT.get(key, key), count, bar))
    print()
    print("A policy on the frontier is not beaten on both energy and")
    print("turnaround at once. Several can share it: that is the trade-off,")
    print("not a tie to be broken.")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print()
        print("Wrote %d rows to %s" % (len(rows), args.csv))

    return 0


if __name__ == "__main__":
    sys.exit(main())
