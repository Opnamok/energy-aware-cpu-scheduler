"""
The six scheduling policies.

Each policy answers only "which process next, and for how much work?" -- the
shared engine handles time, the governor handles frequency. The five classical
baselines are unchanged in behaviour: at a fixed HIGH clock they reproduce the
pre-DVFS schedules exactly, work unit for work unit.

Note on preemption granularity: preemptive policies dispatch one *work atom*
at a time, not one time unit. That is deliberate. SRTF compares remaining
work, and remaining work does not depend on the clock speed, so a process
still yields after the same amount of progress regardless of frequency -- only
the wall-clock cost of that progress changes.
"""

from collections import deque
from typing import Any, Dict, List, Optional

from sim.engine import Dispatch, Policy, SchedState, run_simulation
from sim.governors import eah_frequency, norm01
from sim.params import ATOM_WORK, SimConfig


# --------------------------------------------------------------------------
# Classical baselines
# --------------------------------------------------------------------------

class FCFSPolicy(Policy):
    label = "FCFS"
    key = "fcfs"

    def select(self, state: SchedState) -> Optional[Dispatch]:
        proc = min(state.ready, key=lambda p: (p.arrival_tick, p.pid))
        return Dispatch(proc.pid, proc.remaining)


class SJFPolicy(Policy):
    label = "SJF Non-Preemptive"
    key = "sjf_non_preemptive"

    def select(self, state: SchedState) -> Optional[Dispatch]:
        proc = min(state.ready, key=lambda p: (p.remaining, p.arrival_tick, p.pid))
        return Dispatch(proc.pid, proc.remaining)


class SRTFPolicy(Policy):
    label = "SJF Preemptive (SRTF)"
    key = "sjf_preemptive"

    def select(self, state: SchedState) -> Optional[Dispatch]:
        proc = min(state.ready, key=lambda p: (p.remaining, p.arrival_tick, p.pid))
        return Dispatch(proc.pid, ATOM_WORK)


class RoundRobinPolicy(Policy):
    """Round Robin with a quantum measured in work units.

    The quantum is "how much progress before we re-decide", not a wall-clock
    slice. A wall-clock quantum would complete a frequency-dependent and
    generally fractional amount of work, which would force rational arithmetic
    through the whole simulation. The API reports
    `quantum_semantics: "work"` so this is never silently assumed.
    """

    key = "round_robin"
    # Each expired quantum gets its own Gantt bar: showing the time slicing is
    # the point of charting Round Robin at all.
    coalesce_slices = False

    def __init__(self, quantum: int = 2):
        self.quantum = max(1, int(quantum))
        self.label = "Round Robin (Quantum={0})".format(self.quantum)
        self.queue: deque = deque()

    def on_admit(self, process, state):
        self.queue.append(process.pid)

    def select(self, state: SchedState) -> Optional[Dispatch]:
        ready_pids = {p.pid for p in state.ready}
        while self.queue and self.queue[0] not in ready_pids:
            self.queue.popleft()
        if not self.queue:
            # Fall back to arrival order if the rotation has drained.
            proc = min(state.ready, key=lambda p: (p.arrival_tick, p.pid))
            self.queue.append(proc.pid)
        return Dispatch(self.queue[0], float(self.quantum))

    def on_slice_end(self, process, finished, state):
        if self.queue and self.queue[0] == process.pid:
            self.queue.popleft()
        if not finished:
            self.queue.append(process.pid)

    def extra_result(self, state):
        return {"quantum": self.quantum}


class PriorityPolicy(Policy):
    """Priority scheduling. Lower priority number means higher priority."""

    key = "priority"

    def __init__(self, preemptive: bool = False):
        self.preemptive = preemptive
        self.label = "Priority Scheduling ({0})".format(
            "Preemptive" if preemptive else "Non-Preemptive")

    def select(self, state: SchedState) -> Optional[Dispatch]:
        proc = min(state.ready,
                   key=lambda p: (p.priority, p.arrival_tick, p.pid))
        work = ATOM_WORK if self.preemptive else proc.remaining
        return Dispatch(proc.pid, work)


# --------------------------------------------------------------------------
# Energy-Aware Hybrid
# --------------------------------------------------------------------------

class EAHPolicy(Policy):
    """The project's custom policy: choose a process *and* a frequency.

    Process selection is a weighted score over how long a process has waited,
    how short it is and how important it is. That keeps the short-job bias the
    original design had -- so the turnaround advantage survives -- while the
    waiting term provides aging, which the original could not do: its "drain
    the short queue completely, then the long queue" rule let a steady stream
    of short arrivals starve a long job indefinitely.

    Frequency selection is the urgency rule in `governors.eah_frequency`, and
    it is resampled every `resample_work` units of work. So a long job
    dispatched at LOW into an empty queue escalates as pressure builds, which
    adapts the clock without paying a single extra context switch. That is the
    behaviour the utilisation-window governor structurally cannot produce: on
    a saturated stretch it sees utilisation near 1.0 and pins HIGH.
    """

    label = "Energy-Aware Hybrid (EAH)"
    key = "eah"

    def __init__(self, threshold: Optional[float] = None):
        self.requested_threshold = threshold
        self.threshold = threshold

    def on_admit(self, process, state):
        if self.threshold is None:
            bursts = [p.burst for p in state.all_processes]
            self.threshold = sum(bursts) / float(len(bursts))
        self._classify(process)

    def _classify(self, process):
        process.classification = (
            "short" if process.burst <= self.threshold else "long")

    def select(self, state: SchedState) -> Optional[Dispatch]:
        weights = state.eah
        ready = state.ready

        waits = [state.wait_ticks(p) for p in ready] or [0]
        max_wait = max(waits)
        w_lo, w_hi = state.work_bounds()
        p_lo, p_hi = state.priority_bounds()

        have_deadlines = any(p.deadline is not None for p in ready)
        slacks = [p.deadline - state.now_units - p.remaining
                  for p in ready if p.deadline is not None]
        s_lo = min(slacks) if slacks else 0.0
        s_hi = max(slacks) if slacks else 0.0

        def score(p):
            norm_wait = norm01(state.wait_ticks(p), 0.0, max_wait)
            # 1.0 for the shortest remaining work.
            norm_short = 1.0 - norm01(p.remaining, w_lo, w_hi)
            # 1.0 for the lowest priority number.
            norm_prio = 1.0 - norm01(p.priority, p_lo, p_hi)
            if have_deadlines and p.deadline is not None:
                own = p.deadline - state.now_units - p.remaining
                norm_dead = 1.0 - norm01(own, s_lo, s_hi)
            else:
                norm_dead = 0.0
            return (weights.w_wait * norm_wait
                    + weights.w_short * norm_short
                    + weights.w_prio * norm_prio
                    + weights.w_deadline * norm_dead)

        # Highest score wins. The tie-break chain terminates on pid, which
        # makes the policy fully deterministic -- required for the repeated
        # trial statistics to be reproducible from a seed.
        chosen = max(ready, key=lambda p: (
            score(p), state.wait_ticks(p), -p.remaining, -p.priority,
            -p.arrival_tick, -p.pid))

        freq = eah_frequency(state, chosen, state.params, weights)
        work = min(chosen.remaining, max(ATOM_WORK, weights.resample_work))
        return Dispatch(chosen.pid, work, state_hint=freq)

    def extra_metrics(self, state):
        completed = state.completed
        shorts = [p for p in completed if p.classification == "short"]
        longs = [p for p in completed if p.classification == "long"]
        return {
            "threshold": round(self.threshold or 0.0, 2),
            "short_tasks_count": len(shorts),
            "long_tasks_count": len(longs),
        }

    def extra_result(self, state):
        return {"classification_threshold": round(self.threshold or 0.0, 2)}


# --------------------------------------------------------------------------
# Public functions -- signatures preserved from the original module
# --------------------------------------------------------------------------

def _cfg(cfg: Optional[SimConfig]) -> SimConfig:
    return cfg or SimConfig()


def fcfs(processes_input: List[Dict], cfg: Optional[SimConfig] = None) -> Dict[str, Any]:
    """First Come First Serve scheduling."""
    return run_simulation(processes_input, FCFSPolicy(), _cfg(cfg))


def sjf_non_preemptive(processes_input: List[Dict],
                       cfg: Optional[SimConfig] = None) -> Dict[str, Any]:
    """Shortest Job First (non-preemptive) scheduling."""
    return run_simulation(processes_input, SJFPolicy(), _cfg(cfg))


def sjf_preemptive(processes_input: List[Dict],
                   cfg: Optional[SimConfig] = None) -> Dict[str, Any]:
    """Shortest Remaining Time First (preemptive SJF) scheduling."""
    return run_simulation(processes_input, SRTFPolicy(), _cfg(cfg))


def round_robin(processes_input: List[Dict], quantum: int = 2,
                cfg: Optional[SimConfig] = None) -> Dict[str, Any]:
    """Round Robin scheduling with a work-denominated quantum."""
    conf = _cfg(cfg)
    q = quantum if quantum else conf.quantum
    return run_simulation(processes_input, RoundRobinPolicy(q), conf)


def priority_scheduling(processes_input: List[Dict], preemptive: bool = False,
                        cfg: Optional[SimConfig] = None) -> Dict[str, Any]:
    """Priority scheduling (lower number = higher priority)."""
    return run_simulation(processes_input, PriorityPolicy(preemptive), _cfg(cfg))


def energy_aware_hybrid(processes_input: List[Dict],
                        threshold: Optional[float] = None,
                        cfg: Optional[SimConfig] = None) -> Dict[str, Any]:
    """Energy-Aware Hybrid: joint process and frequency selection."""
    conf = _cfg(cfg)
    thr = threshold if threshold is not None else conf.threshold
    return run_simulation(processes_input, EAHPolicy(thr), conf)


# Registry used by /api/run, /api/compare and the analysis endpoints.
ALGORITHMS = {
    "fcfs": lambda procs, cfg: fcfs(procs, cfg),
    "sjf": lambda procs, cfg: sjf_non_preemptive(procs, cfg),
    "sjf_non_preemptive": lambda procs, cfg: sjf_non_preemptive(procs, cfg),
    "sjf_preemptive": lambda procs, cfg: sjf_preemptive(procs, cfg),
    "srtf": lambda procs, cfg: sjf_preemptive(procs, cfg),
    "round_robin": lambda procs, cfg: round_robin(procs, cfg.quantum, cfg),
    "rr": lambda procs, cfg: round_robin(procs, cfg.quantum, cfg),
    "priority": lambda procs, cfg: priority_scheduling(procs, cfg.preemptive, cfg),
    "priority_preemptive": lambda procs, cfg: priority_scheduling(procs, True, cfg),
    "eah": lambda procs, cfg: energy_aware_hybrid(procs, cfg.threshold, cfg),
    "energy_aware_hybrid": lambda procs, cfg: energy_aware_hybrid(
        procs, cfg.threshold, cfg),
}

# The canonical six, in the order the comparison view presents them.
COMPARE_ORDER = ("fcfs", "sjf_non_preemptive", "sjf_preemptive",
                 "round_robin", "priority", "eah")


def run_algorithm(name: str, processes_input: List[Dict],
                  cfg: Optional[SimConfig] = None) -> Dict[str, Any]:
    """Dispatch by algorithm name, as the API receives it."""
    key = (name or "").strip().lower()
    runner = ALGORITHMS.get(key)
    if runner is None:
        raise ValueError("unknown algorithm '{0}'. Available: {1}".format(
            name, ", ".join(sorted(set(ALGORITHMS)))))
    return runner(processes_input, _cfg(cfg))
