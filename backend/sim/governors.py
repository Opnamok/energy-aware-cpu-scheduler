"""
Frequency governors.

A governor answers one question: *at what frequency should this work run?* It
is consulted inside the dispatch loop, before each work atom executes, so its
answer determines both the power drawn and how long the atom takes.

Making this a pluggable strategy is what allows the interesting experiment:
run FCFS under the EAH governor and you isolate the effect of frequency
*choice* from the effect of process *ordering*. Without that separation, any
energy difference between EAH and the baselines could just be the
context-switch penalty wearing a different hat.
"""

from collections import deque
from typing import Any, Callable, Dict, List, Optional

from sim.params import ACTIVE_STATES, EAHWeights, EnergyParams, HIGH, LOW, MED


class Governor:
    """Base class. Subclasses override `select`."""

    name = "base"
    label = "Base"
    description = ""

    def __init__(self, params: EnergyParams, eah: EAHWeights):
        self.params = params
        self.eah = eah
        self.reset()

    def reset(self) -> None:
        pass

    def observe(self, busy: bool, ticks: int) -> None:
        """Called after every segment, busy or idle, with its tick length."""

    def select(self, state, process) -> str:
        raise NotImplementedError


class FixedGovernor(Governor):
    """Pin the clock to one state. The control for every experiment."""

    def __init__(self, params, eah, fixed_state=HIGH):
        self.fixed_state = fixed_state
        super().__init__(params, eah)

    @property
    def name(self):
        return "fixed:" + self.fixed_state.lower()

    @property
    def label(self):
        return "Fixed " + self.fixed_state

    def select(self, state, process) -> str:
        return self.fixed_state


class UtilizationWindowGovernor(Governor):
    """The project's original heuristic, moved inside the simulation.

    It keeps a sliding window of recent busy/idle ticks and raises the clock
    when utilisation is high, lowers it when idle, with hysteresis to stop it
    thrashing. The thresholds (0.6 / 0.2), window (3 units) and hysteresis (1)
    are unchanged from the post-hoc version -- only the *position* in the
    pipeline has changed, from "after the schedule" to "during it".

    Note what this costs on a saturated workload: with no idle time the window
    reads ~1.0 and the clock pins to HIGH, paying full price for every work
    unit. That is the behaviour EAH is able to beat.
    """

    name = "utilization_window"
    label = "Utilisation window"
    description = ("Sliding-window utilisation with hysteresis -- the original "
                   "EnergiX governor, now applied during the simulation.")

    def reset(self):
        self.window = deque(maxlen=self.params.window_ticks())
        self.current = MED
        self.held = 0

    def observe(self, busy: bool, ticks: int) -> None:
        for _ in range(min(ticks, self.window.maxlen * 2)):
            self.window.append(1.0 if busy else 0.0)

    def select(self, state, process) -> str:
        if self.window:
            util = sum(self.window) / len(self.window)
        else:
            # Nothing observed yet: the queue is about to run, so assume busy.
            util = 1.0

        if util > self.params.util_threshold_high:
            target = HIGH
        elif util < self.params.util_threshold_low:
            target = LOW
        else:
            target = MED

        if target == self.current or self.held >= self.params.hysteresis_samples:
            self.current = target
            self.held = 0
        else:
            self.held += 1
        return self.current


class QueueOndemandGovernor(Governor):
    """Scale with how much work is queued up, not with past utilisation.

    A simple, honest alternative to the window governor: the more pressure in
    the ready queue, the faster we run.
    """

    name = "ondemand_queue"
    label = "On-demand (queue depth)"
    description = "Raise the clock as the ready queue grows."

    def select(self, state, process) -> str:
        depth = state.queue_len()
        if depth >= self.eah.pressure_ref:
            return HIGH
        if depth >= 2:
            return MED
        return LOW


class RaceToIdleGovernor(Governor):
    """Always run flat out, then sleep. The classic alternative strategy.

    Worth having as a baseline because it is what a naive "performance"
    governor does, and because whether it wins depends entirely on the static
    power floor -- which is exactly the point the energy model is making.
    """

    name = "race_to_idle"
    label = "Race to idle"
    description = "Always HIGH while there is work, then idle."

    def select(self, state, process) -> str:
        return HIGH


class EAHScoreGovernor(Governor):
    """The Energy-Aware Hybrid frequency rule, usable on its own.

    Scores urgency from how long the process has waited, its priority, the
    backlog in the ready queue and (when present) its deadline slack, then
    maps that to a frequency state. Used by the EAH policy, and selectable for
    any other policy so that ordering and frequency can be studied separately.
    """

    name = "eah_score"
    label = "EAH urgency score"
    description = ("Weighted urgency from waiting time, priority, queue "
                   "pressure and deadline slack.")

    def select(self, state, process) -> str:
        return eah_frequency(state, process, self.params, self.eah)


# --------------------------------------------------------------------------
# The EAH urgency rule, factored out so the policy and the governor share it.
# --------------------------------------------------------------------------

def norm01(value: float, lo: float, hi: float) -> float:
    """Scale `value` into 0..1 across the range lo..hi, clamped."""
    if hi - lo < 1e-9:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def eah_urgency(state, process, params: EnergyParams,
                weights: EAHWeights) -> float:
    """Urgency of running `process` right now, in roughly 0..1.

    Every input is derived from fields the workload already carries -- waiting
    time, priority, queue depth -- so enabling this needs no extra input from
    the user. Deadlines are optional and simply drop out of the formula when
    absent, with the remaining weights renormalised so the scale is stable.
    """
    ready = state.ready
    ticks_per_unit = params.ticks_per_unit

    waits = [state.wait_ticks(p) for p in ready] or [0]
    norm_wait = norm01(state.wait_ticks(process), 0.0, max(waits))

    prios = [p.priority for p in ready] or [0]
    # Lower priority number means more important, so invert.
    norm_prio = 1.0 - norm01(process.priority, min(prios), max(prios))

    pressure = min(1.0, len(ready) / float(max(1, weights.pressure_ref)))

    w_wait, w_prio, w_press, w_dead = (
        weights.u_wait, weights.u_prio, weights.u_pressure, weights.u_deadline)

    have_deadlines = any(p.deadline is not None for p in ready)
    if have_deadlines and process.deadline is not None:
        slacks = []
        for p in ready:
            if p.deadline is None:
                continue
            slacks.append(p.deadline - state.now_units - p.remaining)
        worst = max(slacks) if slacks else 0.0
        own = process.deadline - state.now_units - process.remaining
        norm_dead = 1.0 - norm01(own, min(slacks + [own]), max(worst, own))
    else:
        norm_dead = 0.0
        # Renormalise the remaining three weights so urgency stays on one scale
        # whether or not deadlines are in play.
        total = w_wait + w_prio + w_press
        if total > 1e-9:
            scale = 1.0 / total
            w_wait, w_prio, w_press = w_wait * scale, w_prio * scale, w_press * scale
        w_dead = 0.0

    return (w_wait * norm_wait + w_prio * norm_prio
            + w_press * pressure + w_dead * norm_dead)


def eah_frequency(state, process, params: EnergyParams,
                  weights: EAHWeights) -> str:
    """Map urgency to a frequency state, with a deadline override."""
    # A process about to miss its deadline runs flat out regardless of score.
    if process.deadline is not None:
        slack = process.deadline - state.now_units - process.remaining
        if slack < weights.slack_safety_units:
            return HIGH

    urgency = eah_urgency(state, process, params, weights)
    if urgency >= weights.urgency_high:
        return HIGH
    if urgency >= weights.urgency_med:
        return MED
    return LOW


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

_BUILDERS: Dict[str, Callable[[EnergyParams, EAHWeights], Governor]] = {
    "utilization_window": UtilizationWindowGovernor,
    "ondemand_queue": QueueOndemandGovernor,
    "race_to_idle": RaceToIdleGovernor,
    "eah_score": EAHScoreGovernor,
    "fixed:high": lambda p, e: FixedGovernor(p, e, HIGH),
    "fixed:med": lambda p, e: FixedGovernor(p, e, MED),
    "fixed:medium": lambda p, e: FixedGovernor(p, e, MED),
    "fixed:low": lambda p, e: FixedGovernor(p, e, LOW),
}

DEFAULT_GOVERNOR = "utilization_window"


def make_governor(name: Optional[str], params: EnergyParams,
                  eah: EAHWeights) -> Governor:
    key = (name or DEFAULT_GOVERNOR).strip().lower()
    builder = _BUILDERS.get(key)
    if builder is None:
        raise ValueError(
            "unknown governor '{0}'. Available: {1}".format(
                name, ", ".join(sorted(_BUILDERS))))
    return builder(params, eah)


def is_fixed(name: Optional[str]) -> bool:
    return bool(name) and name.strip().lower().startswith("fixed:")


def list_governors() -> List[Dict[str, Any]]:
    """Describe the governors for the UI."""
    out = []
    seen = set()
    for key in sorted(_BUILDERS):
        gov = _BUILDERS[key](EnergyParams(), EAHWeights())
        label = gov.label if not isinstance(gov, FixedGovernor) else gov.label
        if label in seen:
            continue
        seen.add(label)
        out.append({
            "name": key,
            "label": label,
            "description": getattr(gov, "description", "") or
                           "Pin the clock to {0}.".format(
                               getattr(gov, "fixed_state", "")),
        })
    return out
