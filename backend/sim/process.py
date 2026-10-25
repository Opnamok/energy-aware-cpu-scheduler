"""
The process model -- one class, used by every policy.

This replaces the two near-identical `Process` classes that used to live in
`algorithms.py` and `energy_aware_scheduler.py`. The positional signature
`(pid, arrival, burst, priority=0)` and the attribute names `remaining`,
`completion`, `turnaround`, `waiting` and `start_time` are kept exactly as
they were, because `multicore_scheduler.py` constructs and reads them directly.

Under DVFS, `burst` is no longer a duration. It is the amount of *work* a
process needs, measured at the reference frequency. How long that work takes
depends on the frequency it runs at, which is why execution time is tracked
separately in `exec_ticks`.
"""

from typing import Any, Dict, List, Optional

from sim.params import ACTIVE_STATES


class Process:
    """A single schedulable process."""

    def __init__(self, pid: int, arrival: int, burst: int,
                 priority: int = 0, deadline: Optional[int] = None,
                 label: Optional[str] = None):
        self.pid = pid
        self.arrival = arrival
        self.burst = burst            # work required, at the reference frequency
        self.priority = priority
        self.deadline = deadline
        self.label = label

        self.remaining = float(burst)  # work still to do
        self.completion = 0
        self.turnaround = 0
        self.waiting = 0
        self.start_time = -1

        # tick-domain bookkeeping
        self.arrival_tick = 0
        self.completion_tick = -1
        self.first_dispatch_tick = -1
        self.exec_ticks = 0
        self.preemptions = 0
        self.energy = 0.0
        self.ticks_by_state: Dict[str, int] = {s: 0 for s in ACTIVE_STATES}
        self.work_by_state: Dict[str, float] = {s: 0.0 for s in ACTIVE_STATES}

        self.classification = "short"
        self.deadline_missed: Optional[bool] = None

    def __repr__(self):
        return "P{0}(A:{1}, W:{2}, P:{3})".format(
            self.pid, self.arrival, self.burst, self.priority)


def build_processes(processes_input: List[Dict[str, Any]]) -> List[Process]:
    """Turn the API's list of dicts into Process objects, validating as we go."""
    if not processes_input:
        raise ValueError("no processes provided")

    built = []
    seen = set()
    for raw in processes_input:
        for field in ("pid", "arrival", "burst"):
            if raw.get(field) is None:
                raise ValueError(
                    "process is missing required field '{0}': {1}".format(field, raw))
        pid = int(raw["pid"])
        if pid in seen:
            raise ValueError("duplicate pid {0}".format(pid))
        seen.add(pid)

        arrival = int(raw["arrival"])
        burst = int(raw["burst"])
        if arrival < 0:
            raise ValueError("P{0}: arrival time cannot be negative".format(pid))
        if burst <= 0:
            raise ValueError(
                "P{0}: burst must be at least 1 work unit (got {1})".format(pid, burst))

        deadline = raw.get("deadline")
        built.append(Process(
            pid=pid,
            arrival=arrival,
            burst=burst,
            priority=int(raw.get("priority") or 0),
            deadline=int(deadline) if deadline is not None else None,
            label=raw.get("label") or raw.get("name"),
        ))
    return built
