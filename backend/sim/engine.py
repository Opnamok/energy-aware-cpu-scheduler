"""
The discrete-event dispatch engine.

Every policy shares this loop. The loop advances simulated time to the next
interesting event (an arrival, the end of a work atom, a completion), asks the
policy *which* process to run, asks the governor *how fast* to run it, and only
then executes -- so the frequency decision determines how much wall-clock time
the work consumes. Energy is accumulated as it goes, per segment, which is both
physically honest and fast enough for thousands of runs.

This is the structural difference from the previous design, where energy was
reconstructed from a finished Gantt chart and frequency could not affect
anything.
"""

from typing import Any, Dict, List, Optional

from sim.governors import make_governor, is_fixed
from sim.params import (ACTIVE_STATES, ATOM_WORK, IDLE, SimConfig)
from sim.process import Process, build_processes
from sim.timebase import to_units, work_to_ticks


class SimulationError(RuntimeError):
    """Raised when a simulation fails to make progress."""


class Dispatch(object):
    """A policy's answer: run this process for this much work."""

    __slots__ = ("pid", "work", "state_hint")

    def __init__(self, pid: int, work: float, state_hint: Optional[str] = None):
        self.pid = pid
        self.work = work
        self.state_hint = state_hint


class Policy(object):
    """Base class for scheduling policies."""

    label = "Policy"
    key = "policy"
    # Should consecutive dispatches of the same process merge into one Gantt
    # bar? True for everything except Round Robin -- see `emit`.
    coalesce_slices = True

    def on_admit(self, process: Process, state: "SchedState") -> None:
        """Called once, when a process arrives and joins the ready set."""

    def select(self, state: "SchedState") -> Optional[Dispatch]:
        raise NotImplementedError

    def on_slice_end(self, process: Process, finished: bool,
                     state: "SchedState") -> None:
        """Called after a dispatched slice completes or is cut short."""

    def extra_metrics(self, state: "SchedState") -> Dict[str, Any]:
        return {}

    def extra_result(self, state: "SchedState") -> Dict[str, Any]:
        return {}


class SchedState(object):
    """Mutable simulation state, handed to policies and governors."""

    def __init__(self, processes: List[Process], cfg: SimConfig):
        self.cfg = cfg
        self.params = cfg.params
        self.eah = cfg.eah
        self.now_tick = 0
        self.all_processes = processes
        self.ready: List[Process] = []
        self.completed: List[Process] = []
        self.last_pid: Optional[int] = None
        self.cur_state: Optional[str] = None

    # -- views the policies and governors use ---------------------------

    @property
    def now_units(self) -> float:
        return self.now_tick / self.params.ticks_per_unit

    def wait_ticks(self, process: Process) -> int:
        """Ticks this process has spent waiting, not executing."""
        return max(0, self.now_tick - process.arrival_tick - process.exec_ticks)

    def queue_len(self) -> int:
        return len(self.ready)

    def work_bounds(self):
        if not self.ready:
            return (0.0, 0.0)
        work = [p.remaining for p in self.ready]
        return (min(work), max(work))

    def priority_bounds(self):
        if not self.ready:
            return (0, 0)
        prios = [p.priority for p in self.ready]
        return (min(prios), max(prios))


def run_simulation(processes_input: List[Dict[str, Any]], policy: Policy,
                   cfg: Optional[SimConfig] = None,
                   algorithm_label: Optional[str] = None) -> Dict[str, Any]:
    """Run `policy` over a workload and return the full result dict."""
    cfg = cfg or SimConfig()
    params = cfg.params
    tpu = params.ticks_per_unit

    processes = build_processes(processes_input)
    for p in processes:
        p.arrival_tick = p.arrival * tpu

    state = SchedState(processes, cfg)
    governor = make_governor(cfg.governor, params, cfg.eah)
    governor_is_fixed = is_fixed(cfg.governor)

    by_pid = {p.pid: p for p in processes}
    pending = sorted(processes, key=lambda p: (p.arrival_tick, p.pid))
    next_arrival = 0

    segments: List[Dict[str, Any]] = []
    timeline: List[Dict[str, Any]] = []
    context_switches = 0
    frequency_switches = 0
    busy_energy = 0.0
    idle_energy = 0.0
    busy_ticks = 0
    idle_ticks = 0

    slice_seq = 0
    total_work = sum(p.burst for p in processes)
    atom_budget = int(4 * total_work / ATOM_WORK) + 1000
    atoms_run = 0

    def admit():
        nonlocal next_arrival
        while (next_arrival < len(pending)
               and pending[next_arrival].arrival_tick <= state.now_tick):
            proc = pending[next_arrival]
            next_arrival += 1
            state.ready.append(proc)
            policy.on_admit(proc, state)

    def emit(pid, freq_state, start_tick, ticks, work, slice_id=None):
        """Append a Gantt segment.

        Atoms within one dispatched slice always merge, so the atom
        granularity stays an implementation detail.

        Whether *consecutive slices* merge is the policy's call, via
        `coalesce_slices`. Preemptive policies set it, so an uninterrupted run
        reads as one bar rather than one bar per work unit. Round Robin clears
        it, so each expired quantum stays a separate bar -- the time slicing
        is the thing the chart exists to show.
        """
        if segments:
            prev = segments[-1]
            same_run = (slice_id is not None
                        and (prev.get("_slice") == slice_id
                             or policy.coalesce_slices))
            if (prev["pid"] == pid and prev["freq_state"] == freq_state
                    and prev["end_tick"] == start_tick and same_run):
                prev["end_tick"] = start_tick + ticks
                prev["end"] = to_units(prev["end_tick"], tpu)
                prev["duration"] = to_units(prev["end_tick"] - prev["start_tick"], tpu)
                prev["work"] = round(prev["work"] + work, 6)
                prev["energy"] = round(
                    params.power(freq_state)
                    * (prev["end_tick"] - prev["start_tick"]) / tpu, 6)
                return prev
        proc = by_pid.get(pid)
        seg = {
            "process": "P{0}".format(pid) if pid is not None else IDLE,
            "pid": pid,
            "start": to_units(start_tick, tpu),
            "end": to_units(start_tick + ticks, tpu),
            "start_tick": start_tick,
            "end_tick": start_tick + ticks,
            "duration": to_units(ticks, tpu),
            "freq_state": freq_state,
            "freq_ghz": round(params.ghz(freq_state), 4),
            "f_rel": round(params.f_rel(freq_state), 4),
            "work": round(work, 6),
            "power": round(params.power(freq_state), 4),
            "energy": round(params.power(freq_state) * ticks / tpu, 6),
            "_slice": slice_id,
        }
        if proc is not None and proc.classification:
            seg["classification"] = proc.classification
        segments.append(seg)
        return seg

    def finalize(proc: Process):
        proc.completion_tick = state.now_tick
        proc.completion = to_units(proc.completion_tick, tpu)
        proc.turnaround = to_units(proc.completion_tick - proc.arrival_tick, tpu)
        # Waiting time is turnaround minus the time actually spent executing.
        # Under DVFS that is NOT the burst: a 5-unit burst run at LOW occupies
        # 12.5 time units, so subtracting the burst would report a negative
        # wait. This is the subtlest consequence of coupling frequency to time.
        proc.waiting = to_units(
            proc.completion_tick - proc.arrival_tick - proc.exec_ticks, tpu)
        if proc.deadline is not None:
            proc.deadline_missed = bool(proc.completion > proc.deadline)
        state.completed.append(proc)
        if proc in state.ready:
            state.ready.remove(proc)
        timeline.append({
            "time": proc.completion,
            "process": proc.pid,
            "event": "completion",
            "classification": proc.classification,
        })

    # ---------------------------------------------------------------- loop
    while len(state.completed) < len(processes):
        admit()

        if not state.ready:
            if next_arrival >= len(pending):
                break
            gap_end = pending[next_arrival].arrival_tick
            gap = gap_end - state.now_tick
            if gap > 0:
                emit(None, IDLE, state.now_tick, gap, 0.0)
                governor.observe(False, gap)
                idle_energy += params.power(IDLE) * gap / tpu
                idle_ticks += gap
                state.now_tick = gap_end
            else:
                state.now_tick = gap_end
            continue

        dispatch = policy.select(state)
        if dispatch is None:
            raise SimulationError(
                "policy {0} returned no dispatch with {1} process(es) ready"
                .format(policy.key, len(state.ready)))

        proc = by_pid[dispatch.pid]

        if state.last_pid is not None and state.last_pid != proc.pid:
            context_switches += 1
            prev = by_pid.get(state.last_pid)
            if prev is not None and prev.remaining > 1e-9:
                prev.preemptions += 1

        if proc.first_dispatch_tick < 0:
            proc.first_dispatch_tick = state.now_tick
            proc.start_time = to_units(state.now_tick, tpu)

        slice_seq += 1
        slice_id = slice_seq
        slice_left = min(dispatch.work, proc.remaining)
        finished = False

        while slice_left > 1e-9:
            atoms_run += 1
            if atoms_run > atom_budget:
                raise SimulationError(
                    "simulation did not converge after {0} work atoms "
                    "(policy={1}); this indicates a scheduling bug rather "
                    "than a slow workload".format(atoms_run, policy.key))

            atom = min(ATOM_WORK, slice_left)

            if governor_is_fixed or dispatch.state_hint is None:
                freq_state = governor.select(state, proc)
            else:
                freq_state = dispatch.state_hint

            if state.cur_state is not None and freq_state != state.cur_state:
                frequency_switches += 1
            state.cur_state = freq_state

            ticks = work_to_ticks(atom, params.ticks_per_work_unit(freq_state))
            emit(proc.pid, freq_state, state.now_tick, ticks, atom, slice_id)
            governor.observe(True, ticks)

            power = params.power(freq_state)
            energy = power * ticks / tpu
            busy_energy += energy
            busy_ticks += ticks
            proc.energy += energy
            proc.exec_ticks += ticks
            proc.ticks_by_state[freq_state] += ticks
            proc.work_by_state[freq_state] += atom

            state.now_tick += ticks
            proc.remaining -= atom
            slice_left -= atom

            # New arrivals become visible mid-slice, which is what lets a
            # governor (or EAH's resampling) react to rising pressure.
            admit()

            if proc.remaining <= 1e-9:
                proc.remaining = 0.0
                finished = True
                finalize(proc)
                break

        state.last_pid = proc.pid
        policy.on_slice_end(proc, finished, state)

    for seg in segments:
        seg.pop("_slice", None)

    total_tick = state.now_tick
    result = {
        "algorithm": algorithm_label or policy.label,
        "timeline": timeline,
        "gantt": segments,
        "context_switches": context_switches,
        "frequency_switches": frequency_switches,
        "governor": cfg.governor,
        "quantum_semantics": "work",
        "processes": [_process_dict(p, tpu) for p in state.completed],
        "metrics": _basic_metrics(state.completed, total_tick, tpu),
        "_internal": {
            "busy_energy": busy_energy,
            "idle_energy": idle_energy,
            "busy_ticks": busy_ticks,
            "idle_ticks": idle_ticks,
            "total_tick": total_tick,
            "total_work": total_work,
        },
    }
    result["metrics"].update(policy.extra_metrics(state))
    result.update(policy.extra_result(state))
    return result


def _process_dict(p: Process, tpu: int) -> Dict[str, Any]:
    out = {
        "pid": p.pid,
        "arrival": p.arrival,
        "burst": p.burst,
        "priority": p.priority,
        "completion": p.completion,
        "turnaround": p.turnaround,
        "waiting": p.waiting,
        "start_time": p.start_time,
        "work_done": round(p.burst - p.remaining, 6),
        "exec_time": to_units(p.exec_ticks, tpu),
        "first_dispatch": to_units(p.first_dispatch_tick, tpu)
                          if p.first_dispatch_tick >= 0 else None,
        "response_time": to_units(p.first_dispatch_tick - p.arrival_tick, tpu)
                         if p.first_dispatch_tick >= 0 else None,
        "preemptions": p.preemptions,
        "energy": round(p.energy, 4),
        "freq_residency": _residency(p),
        "classification": p.classification,
    }
    if p.label:
        out["label"] = p.label
    if p.deadline is not None:
        out["deadline"] = p.deadline
        out["deadline_missed"] = p.deadline_missed
    return out


def _residency(p: Process) -> Dict[str, float]:
    total = sum(p.ticks_by_state.values())
    if total <= 0:
        return {s: 0.0 for s in ACTIVE_STATES}
    return {s: round(p.ticks_by_state[s] / total, 4) for s in ACTIVE_STATES}


def _basic_metrics(completed: List[Process], total_tick: int,
                   tpu: int) -> Dict[str, Any]:
    n = len(completed)
    if n == 0:
        return {"avg_turnaround": 0, "avg_waiting": 0, "total_completion": 0}
    total_tat = sum(p.completion_tick - p.arrival_tick for p in completed)
    total_wt = sum(p.completion_tick - p.arrival_tick - p.exec_ticks
                   for p in completed)
    return {
        "avg_turnaround": round(total_tat / n / tpu, 2),
        "avg_waiting": round(total_wt / n / tpu, 2),
        "total_completion": to_units(
            max(p.completion_tick for p in completed), tpu),
    }
