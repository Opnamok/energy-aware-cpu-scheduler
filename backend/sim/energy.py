"""
Energy reporting.

The engine already accumulates energy as the simulation runs, so this module's
job is to summarise it: totals, the breakdown by source and by frequency
state, residency percentages, and the per-time-unit timelines the UI charts.

Timelines are expanded only when asked for. They cost one dict per time unit,
which is fine for a single run and ruinous across thousands of trials, so the
repeated-trial and sweep endpoints switch them off.
"""

from typing import Any, Dict, List, Optional

from sim.params import (ACTIVE_STATES, ALL_STATES, DEFAULT_PARAMS, EnergyParams,
                        HIGH, IDLE, LOW, MED)


def power_table(params: EnergyParams) -> Dict[str, float]:
    return {s: round(params.power(s), 4) for s in ALL_STATES}


def summarize_energy(segments: List[Dict[str, Any]], context_switches: int,
                     frequency_switches: int, params: EnergyParams,
                     internal: Optional[Dict[str, Any]] = None,
                     include_timelines: bool = True) -> Dict[str, Any]:
    """Build the `energy` block of a result."""
    tpu = params.ticks_per_unit

    busy_energy = 0.0
    idle_energy = 0.0
    busy_ticks = 0
    idle_ticks = 0
    energy_by_state = {s: 0.0 for s in ALL_STATES}
    ticks_by_state = {s: 0 for s in ALL_STATES}
    work_by_state = {s: 0.0 for s in ACTIVE_STATES}

    for seg in segments:
        state = seg.get("freq_state") or (
            IDLE if seg.get("process") == IDLE else HIGH)
        ticks = seg.get("end_tick")
        if ticks is None:
            # A client posted a legacy segment with no tick domain.
            ticks = int(round((seg["end"] - seg["start"]) * tpu))
        else:
            ticks = seg["end_tick"] - seg["start_tick"]
        energy = params.power(state) * ticks / tpu

        ticks_by_state[state] += ticks
        energy_by_state[state] += energy
        if state == IDLE:
            idle_energy += energy
            idle_ticks += ticks
        else:
            busy_energy += energy
            busy_ticks += ticks
            work_by_state[state] += float(seg.get("work") or 0.0)

    cs_energy = context_switches * params.context_switch_penalty
    fs_energy = frequency_switches * params.freq_switch_penalty
    total_energy = busy_energy + idle_energy + cs_energy + fs_energy

    total_ticks = busy_ticks + idle_ticks
    total_units = total_ticks / tpu if total_ticks else 0

    out = {
        "total_energy": round(total_energy, 2),
        "busy_energy": round(busy_energy, 2),
        "idle_energy": round(idle_energy, 2),
        "context_switch_energy": round(cs_energy, 2),
        "freq_switch_energy": round(fs_energy, 2),
        "frequency_switches": frequency_switches,
        "avg_power": round(total_energy / total_units, 2) if total_units else 0,
        "energy_by_state": {s: round(energy_by_state[s], 2) for s in ALL_STATES},
        "frequency_residency": _residency(ticks_by_state, busy_ticks),
        "residency_by_work": _work_residency(work_by_state),
        "residency_by_wall_time": _residency(ticks_by_state, total_ticks,
                                             include_idle=True),
        "busy_time": round(busy_ticks / tpu, 2),
        "idle_time": round(idle_ticks / tpu, 2),
        "parameters": params.to_api_dict(),
    }

    if include_timelines:
        power_tl, freq_tl = _timelines(segments, params)
        out["power_timeline"] = power_tl
        out["frequency_timeline"] = freq_tl
    else:
        out["power_timeline"] = []
        out["frequency_timeline"] = []

    return out


def _residency(ticks_by_state: Dict[str, int], denominator: int,
               include_idle: bool = False) -> Dict[str, float]:
    states = ALL_STATES if include_idle else ACTIVE_STATES
    if denominator <= 0:
        return {s: 0.0 for s in states}
    return {s: round(ticks_by_state[s] / denominator, 4) for s in states}


def _work_residency(work_by_state: Dict[str, float]) -> Dict[str, float]:
    total = sum(work_by_state.values())
    if total <= 0:
        return {s: 0.0 for s in ACTIVE_STATES}
    return {s: round(work_by_state[s] / total, 4) for s in ACTIVE_STATES}


def _timelines(segments, params: EnergyParams):
    """Expand segments into per-time-unit samples for the charts.

    Sampling is per display time unit (not per tick), which keeps the series
    the same length it was before DVFS was coupled in.
    """
    tpu = params.ticks_per_unit
    if not segments:
        return [], []

    end_tick = max(s["end_tick"] for s in segments)
    power_tl = []
    freq_tl = []

    # Walk the segments once, emitting a sample per time unit.
    idx = 0
    busy_window = []
    window_len = max(1, int(round(params.window_units)))

    for unit in range(int(end_tick / tpu) + (1 if end_tick % tpu else 0)):
        tick = unit * tpu
        while idx < len(segments) - 1 and segments[idx]["end_tick"] <= tick:
            idx += 1
        seg = segments[idx]
        state = seg.get("freq_state", IDLE)
        if seg["start_tick"] > tick:
            state = IDLE

        busy_window.append(0.0 if state == IDLE else 1.0)
        if len(busy_window) > window_len:
            busy_window.pop(0)
        util = sum(busy_window) / len(busy_window)

        power_tl.append({
            "time": unit,
            "power": round(params.power(state), 2),
            "state": state,
            "utilization": round(util, 2),
        })
        freq_tl.append({
            "time": unit,
            # Relative frequency: the frontend chart's y-axis is scaled 0..1.2.
            "frequency": round(params.f_rel(state), 2),
            "frequency_ghz": round(params.ghz(state), 2),
            "power": round(params.power(state), 2),
            "state": state,
        })

    return power_tl, freq_tl


def energy_delay(total_energy: float, avg_turnaround: float,
                 n: int) -> Dict[str, Any]:
    """Energy-delay products.

    EDP weights energy and delay equally; ED2P weights delay more heavily, so
    it favours policies that finish sooner even at some energy cost. Reporting
    both makes the weighting explicit instead of hiding it in one number.
    """
    return {
        "edp": round(total_energy * avg_turnaround, 2),
        "ed2p": round(total_energy * avg_turnaround * avg_turnaround, 2),
        "energy_per_process": round(total_energy / n, 2) if n else 0,
    }


def calculate_dvfs_energy(gantt: List[Dict], context_switches: int,
                          params: Optional[EnergyParams] = None) -> Dict[str, Any]:
    """Backward-compatible entry point for POST /api/energy.

    If the posted segments already carry `freq_state` (anything produced by
    this engine), they are summarised faithfully. If they do not -- an older
    client posting bare {process, start, end} -- we have no way to know what
    frequency the work ran at, so we assume HIGH and say so in the response
    rather than presenting a guess as a DVFS-aware figure.
    """
    params = params or DEFAULT_PARAMS
    if not gantt:
        return summarize_energy([], context_switches, 0, params)

    legacy = not any("freq_state" in seg for seg in gantt)
    tpu = params.ticks_per_unit
    prepared = []
    for seg in gantt:
        state = seg.get("freq_state")
        if state is None:
            state = IDLE if seg.get("process") == IDLE else HIGH
        start_tick = seg.get("start_tick")
        end_tick = seg.get("end_tick")
        if start_tick is None or end_tick is None:
            start_tick = int(round(seg["start"] * tpu))
            end_tick = int(round(seg["end"] * tpu))
        prepared.append({
            "process": seg.get("process"),
            "pid": seg.get("pid"),
            "freq_state": state,
            "start_tick": start_tick,
            "end_tick": end_tick,
            "start": seg.get("start"),
            "end": seg.get("end"),
            "work": seg.get("work", (end_tick - start_tick) / tpu),
        })

    out = summarize_energy(prepared, context_switches,
                           seg_frequency_switches(prepared), params)
    if legacy:
        out["legacy"] = True
        out["warning"] = ("Posted segments carried no frequency state, so HIGH "
                          "was assumed for all busy time. These figures are "
                          "not DVFS-aware; run the scheduler to get real ones.")
    return out


def seg_frequency_switches(segments: List[Dict[str, Any]]) -> int:
    """Count frequency transitions across busy segments."""
    count = 0
    prev = None
    for seg in segments:
        state = seg.get("freq_state")
        if state == IDLE or state is None:
            continue
        if prev is not None and state != prev:
            count += 1
        prev = state
    return count
