"""
Tests for the DVFS coupling -- i.e. for the project's central claim.

The report says "lower frequency can reduce power but may increase execution
time". Before this refactor that sentence was not true of the code: energy was
computed after the fact from a finished Gantt chart, so frequency could not
affect anything. These tests are what make the claim checkable.

Run with:  python -m pytest tests/ -q
       or:  python tests/test_dvfs.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from sim.energy import summarize_energy                        # noqa: E402
from sim.params import (ACTIVE_STATES, EnergyParams, HIGH, LOW,  # noqa: E402
                        MED, SimConfig)
from sim.policies import (COMPARE_ORDER, energy_aware_hybrid,   # noqa: E402
                          fcfs, run_algorithm)

PARAMS = EnergyParams()

SATURATED = [
    {"pid": 1, "arrival": 0, "burst": 6, "priority": 2},
    {"pid": 2, "arrival": 0, "burst": 3, "priority": 1},
    {"pid": 3, "arrival": 1, "burst": 8, "priority": 3},
    {"pid": 4, "arrival": 2, "burst": 4, "priority": 1},
    {"pid": 5, "arrival": 3, "burst": 2, "priority": 2},
]


def _cfg(governor, **kw):
    kw.setdefault("include_timelines", False)
    return SimConfig(params=PARAMS, governor=governor, **kw)


def _energy(result, cfg):
    return summarize_energy(result["gantt"], result["context_switches"],
                            result["frequency_switches"], cfg.params,
                            include_timelines=False)


# ---------------------------------------------------------------- time base

def test_frequency_stretches_execution_time():
    """One process, three clocks. This is the claim, reduced to one number."""
    procs = [{"pid": 1, "arrival": 0, "burst": 4, "priority": 1}]
    expected = {HIGH: 4.0, MED: 6.0, LOW: 10.0}   # burst * 1.0 / 1.5 / 2.5

    for state, want in expected.items():
        cfg = _cfg("fixed:" + state.lower())
        result = fcfs(procs, cfg)
        got = result["metrics"]["total_completion"]
        assert got == want, "{0}: wanted completion {1}, got {2}".format(
            state, want, got)


def test_low_clock_is_two_and_a_half_times_slower():
    high = fcfs(SATURATED, _cfg("fixed:high"))["metrics"]["total_completion"]
    low = fcfs(SATURATED, _cfg("fixed:low"))["metrics"]["total_completion"]
    # The whole workload is CPU-bound after t=3, so the stretch is close to
    # the raw 2.5x ratio (early idle gaps keep it slightly under).
    ratio = low / high
    assert 2.3 < ratio < 2.6, "LOW/HIGH completion ratio was {0}".format(ratio)


def test_segment_boundaries_stay_on_exact_half_units():
    """Integer ticks mean no drift: every boundary is a multiple of 0.5."""
    for governor in ("fixed:low", "fixed:med", "utilization_window", "eah_score"):
        for algo in COMPARE_ORDER:
            cfg = _cfg(governor, quantum=3)
            result = run_algorithm(algo, SATURATED, cfg)
            for seg in result["gantt"]:
                assert isinstance(seg["start_tick"], int)
                assert isinstance(seg["end_tick"], int)
                for key in ("start", "end"):
                    doubled = seg[key] * 2
                    assert abs(doubled - round(doubled)) < 1e-9, (
                        "{0}/{1}: {2} boundary {3} is not a half unit".format(
                            governor, algo, key, seg[key]))


def test_all_work_is_accounted_for():
    """No work is lost or invented, whatever the clock does."""
    total_work = sum(p["burst"] for p in SATURATED)
    for governor in ("fixed:high", "fixed:low", "utilization_window",
                     "eah_score", "ondemand_queue", "race_to_idle"):
        for algo in COMPARE_ORDER:
            cfg = _cfg(governor, quantum=3)
            result = run_algorithm(algo, SATURATED, cfg)
            done = sum(s["work"] for s in result["gantt"])
            assert abs(done - total_work) < 1e-6, (
                "{0}/{1}: {2} work units executed, expected {3}".format(
                    governor, algo, done, total_work))


def test_waiting_time_is_never_negative():
    """The subtlest consequence of coupling frequency to time.

    Waiting time has to be turnaround minus *execution time*, not minus the
    burst. Under DVFS a 5-unit burst can occupy 12.5 time units, so the old
    `turnaround - burst` would report a negative wait.
    """
    for governor in ("fixed:low", "fixed:med", "utilization_window", "eah_score"):
        for algo in COMPARE_ORDER:
            cfg = _cfg(governor, quantum=3)
            result = run_algorithm(algo, SATURATED, cfg)
            for p in result["processes"]:
                assert p["waiting"] >= 0, (
                    "{0}/{1}: P{2} has waiting={3}".format(
                        governor, algo, p["pid"], p["waiting"]))
                assert abs((p["turnaround"] - p["exec_time"])
                           - p["waiting"]) < 1e-6


# ------------------------------------------------------------------- energy

def test_energy_components_sum_to_the_total():
    for governor in ("fixed:high", "utilization_window", "eah_score"):
        for algo in COMPARE_ORDER:
            cfg = _cfg(governor, quantum=3)
            result = run_algorithm(algo, SATURATED, cfg)
            e = _energy(result, cfg)
            parts = (e["busy_energy"] + e["idle_energy"]
                     + e["context_switch_energy"] + e["freq_switch_energy"])
            assert abs(parts - e["total_energy"]) < 0.02, (
                "{0}/{1}: parts {2} != total {3}".format(
                    governor, algo, parts, e["total_energy"]))


def test_busy_energy_matches_an_independent_recomputation():
    cfg = _cfg("utilization_window")
    result = fcfs(SATURATED, cfg)
    e = _energy(result, cfg)
    recomputed = sum(
        PARAMS.power(s["freq_state"])
        * (s["end_tick"] - s["start_tick"]) / PARAMS.ticks_per_unit
        for s in result["gantt"] if s["freq_state"] != "IDLE")
    assert abs(recomputed - e["busy_energy"]) < 0.02


def test_medium_clock_is_the_energy_optimum():
    """The power model has an interior optimum, so the trade-off is real.

    Dynamic energy per unit of work falls as V^2 when the clock drops, but
    static energy rises as 1/f. With the default leakage floor the sum is
    minimised at MED -- which means LOW is both slower and less efficient, and
    there is no single frequency that simply wins.
    """
    per_unit = {s: PARAMS.energy_per_work_unit(s) for s in ACTIVE_STATES}
    assert per_unit[MED] < per_unit[LOW] < per_unit[HIGH], per_unit

    energies = {}
    for state in ACTIVE_STATES:
        cfg = _cfg("fixed:" + state.lower())
        result = fcfs(SATURATED, cfg)
        energies[state] = _energy(result, cfg)["total_energy"]
    assert energies[MED] < energies[HIGH], energies


def test_leakage_floor_moves_the_optimum():
    """p_static is the knob that decides whether racing or crawling wins."""
    import dataclasses
    low_leak = dataclasses.replace(PARAMS, p_static=0.2)
    high_leak = dataclasses.replace(PARAMS, p_static=3.0)
    assert (low_leak.energy_per_work_unit(LOW)
            < low_leak.energy_per_work_unit(HIGH))
    assert (high_leak.energy_per_work_unit(HIGH)
            < high_leak.energy_per_work_unit(LOW))


# ---------------------------------------------------------------------- EAH

def test_eah_chooses_more_than_one_frequency():
    """EAH must actually exercise its frequency decision."""
    cfg = _cfg("eah_score", quantum=3)
    result = energy_aware_hybrid(SATURATED, None, cfg)
    states = {s["freq_state"] for s in result["gantt"] if s["freq_state"] != "IDLE"}
    assert len(states) >= 2, (
        "EAH picked only {0} -- the frequency rule is not discriminating".format(
            states))


def test_eah_is_deterministic():
    """Required for seeded repeated trials to be reproducible."""
    cfg = _cfg("eah_score", quantum=3)
    a = energy_aware_hybrid(SATURATED, None, cfg)
    b = energy_aware_hybrid(SATURATED, None, cfg)
    assert a["gantt"] == b["gantt"]
    assert a["metrics"] == b["metrics"]


def test_governor_and_ordering_are_separable():
    """The ablation that keeps the EAH claim honest.

    If EAH's energy advantage were just "fewer context switches", running FCFS
    under the EAH governor would change nothing. It does change the energy,
    which shows frequency choice is a real, separable effect.
    """
    window = fcfs(SATURATED, _cfg("utilization_window"))
    scored = fcfs(SATURATED, _cfg("eah_score"))
    e_window = _energy(window, _cfg("utilization_window"))["total_energy"]
    e_scored = _energy(scored, _cfg("eah_score"))["total_energy"]
    assert e_window != e_scored, (
        "the governor made no difference to FCFS energy ({0})".format(e_window))


def test_deadline_forces_the_top_clock():
    procs = [{"pid": 1, "arrival": 0, "burst": 4, "priority": 3, "deadline": 5},
             {"pid": 2, "arrival": 0, "burst": 2, "priority": 1}]
    cfg = _cfg("eah_score")
    result = energy_aware_hybrid(procs, None, cfg)
    p1 = [s for s in result["gantt"] if s["pid"] == 1]
    assert any(s["freq_state"] == HIGH for s in p1), (
        "a process with 1 unit of slack should have been raised to HIGH")


if __name__ == "__main__":
    failures = []
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("  ok   " + name)
            except AssertionError as exc:
                failures.append((name, str(exc)))
                print("  FAIL " + name)
    if failures:
        print()
        for name, msg in failures:
            print("{0}:\n  {1}".format(name, msg))
        sys.exit(1)
    print("\nAll DVFS coupling tests passed.")
