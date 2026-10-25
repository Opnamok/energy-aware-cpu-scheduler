"""
Simulation parameters: frequency states, the power model and the EAH weights.

Everything the energy model depends on lives here as a single frozen block so
that it can be inspected, surfaced through the API and swept over, rather than
being buried as literals inside the schedulers.
"""

from dataclasses import dataclass, replace
from typing import Any, Dict, Optional


# Frequency-state names. These strings travel over the API and appear in the
# Gantt chart, so they are part of the contract. "MED" (not "MEDIUM") is what
# the frontend's state-to-colour mapping already expects.
HIGH = "HIGH"
MED = "MED"
LOW = "LOW"
IDLE = "IDLE"

ACTIVE_STATES = (HIGH, MED, LOW)
ALL_STATES = (HIGH, MED, LOW, IDLE)

# One unit of work is the scheduler's decision granularity: the amount of
# progress a process makes before the policy and the governor are consulted
# again. Preemptive policies advance exactly one atom per iteration, which is
# what keeps them identical to the pre-DVFS one-time-unit loop at HIGH.
ATOM_WORK = 1.0


@dataclass(frozen=True)
class EnergyParams:
    """The DVFS and energy model.

    Power follows the relationship the project report states, P proportional
    to f * V^2, with a static (leakage) floor added on top:

        P(state) = c_eff * f_GHz * V^2 + p_static

    The defaults are chosen so that HIGH comes out at exactly 5.00 W, which is
    the figure the report quotes, while MED and LOW are derived from the model
    rather than asserted independently.
    """

    # --- time base -------------------------------------------------------
    f_ref_ghz: float = 3.0
    ticks_per_unit: int = 2

    # --- operating points (GHz, Volts) -----------------------------------
    freq_high_ghz: float = 3.0
    freq_med_ghz: float = 2.0
    freq_low_ghz: float = 1.2
    volts_high: float = 1.00
    volts_med: float = 0.85
    volts_low: float = 0.75

    # --- power model -----------------------------------------------------
    c_eff: float = 1.35       # watts per (GHz * V^2)
    p_static: float = 0.95    # leakage floor while a core is active
    power_idle: float = 0.20  # clock-gated / sleep state

    # --- overheads (energy units) ----------------------------------------
    context_switch_penalty: float = 0.50
    freq_switch_penalty: float = 0.10

    # --- utilisation-window governor -------------------------------------
    util_threshold_high: float = 0.6
    util_threshold_low: float = 0.2
    window_units: float = 3.0
    hysteresis_samples: int = 1

    # --- starvation reporting --------------------------------------------
    starvation_wait_factor: float = 4.0
    starvation_ntat_factor: float = 5.0

    # -- derived ----------------------------------------------------------

    def ghz(self, state: str) -> float:
        if state == HIGH:
            return self.freq_high_ghz
        if state == MED:
            return self.freq_med_ghz
        if state == LOW:
            return self.freq_low_ghz
        return 0.0

    def volts(self, state: str) -> float:
        if state == HIGH:
            return self.volts_high
        if state == MED:
            return self.volts_med
        if state == LOW:
            return self.volts_low
        return 0.0

    def f_rel(self, state: str) -> float:
        """Frequency relative to the reference (HIGH), in the range 0..1."""
        if state == IDLE:
            return 0.0
        return self.ghz(state) / self.f_ref_ghz

    def power(self, state: str) -> float:
        """Modelled power draw, in watts."""
        if state == IDLE:
            return self.power_idle
        return self.c_eff * self.ghz(state) * (self.volts(state) ** 2) + self.p_static

    def ticks_per_work_unit(self, state: str) -> int:
        """Wall-clock ticks consumed by one unit of work at this state.

        The whole simulation runs on integers, which means a state is only
        admissible when this division comes out whole. With the defaults the
        report's three frequencies give 2 / 3 / 5 ticks exactly.
        """
        if state == IDLE:
            raise ValueError("IDLE performs no work")
        numerator = self.ticks_per_unit * self.f_ref_ghz
        exact = numerator / self.ghz(state)
        ticks = int(round(exact))
        if abs(exact - ticks) > 1e-9 or ticks <= 0:
            admissible = ", ".join(
                "{0:.4g}".format(numerator / k) for k in range(1, 9))
            raise ValueError(
                "frequency {0} GHz is not admissible: one work unit would take "
                "{1:.4f} ticks, which is not a whole number. With f_ref_ghz={2} "
                "and ticks_per_unit={3} the admissible frequencies are {4} GHz. "
                "Raise ticks_per_unit to make finer states exact.".format(
                    self.ghz(state), exact, self.f_ref_ghz,
                    self.ticks_per_unit, admissible))
        return ticks

    def energy_per_work_unit(self, state: str) -> float:
        """Energy to complete one unit of work at this state.

        This is where the trade-off lives. Dynamic energy per unit of work
        scales as V^2 (so slower is cheaper), while static energy scales as
        1/f (so slower is dearer). With the default p_static the sum has an
        interior minimum at MED: LOW is both slower and less efficient.
        """
        ticks = self.ticks_per_work_unit(state)
        return self.power(state) * ticks / self.ticks_per_unit

    def window_ticks(self) -> int:
        return max(1, int(round(self.window_units * self.ticks_per_unit)))

    def with_overrides(self, overrides: Optional[Dict[str, Any]]) -> "EnergyParams":
        if not overrides:
            return self
        known = set(self.__dataclass_fields__)
        unknown = sorted(set(overrides) - known)
        if unknown:
            raise ValueError("unknown energy parameter(s): " + ", ".join(unknown))
        return replace(self, **overrides)

    def to_api_dict(self) -> Dict[str, Any]:
        """Flat dict for the API.

        The legacy keys (freq_high, power_med, window_size, ...) keep both
        their names and their original meaning: freq_* stay relative
        frequencies in 0..1, because the frontend's frequency chart pins its
        y-axis at 1.2 and would silently clip absolute GHz values.
        """
        return {
            # --- legacy keys, unchanged meaning --------------------------
            "freq_high": round(self.f_rel(HIGH), 4),
            "freq_med": round(self.f_rel(MED), 4),
            "freq_low": round(self.f_rel(LOW), 4),
            "power_high": round(self.power(HIGH), 4),
            "power_med": round(self.power(MED), 4),
            "power_low": round(self.power(LOW), 4),
            "power_idle": round(self.power_idle, 4),
            "context_switch_penalty": self.context_switch_penalty,
            "util_threshold_high": self.util_threshold_high,
            "util_threshold_low": self.util_threshold_low,
            "window_size": self.window_units,
            "hysteresis": self.hysteresis_samples,
            # --- the DVFS model, made explicit --------------------------
            "f_ref_ghz": self.f_ref_ghz,
            "ticks_per_unit": self.ticks_per_unit,
            "freq_high_ghz": self.freq_high_ghz,
            "freq_med_ghz": self.freq_med_ghz,
            "freq_low_ghz": self.freq_low_ghz,
            "volts_high": self.volts_high,
            "volts_med": self.volts_med,
            "volts_low": self.volts_low,
            "c_eff": self.c_eff,
            "p_static": self.p_static,
            "freq_switch_penalty": self.freq_switch_penalty,
            "power_formula": "P = c_eff * f_GHz * V^2 + p_static",
            "ticks_per_work_unit": {
                s: self.ticks_per_work_unit(s) for s in ACTIVE_STATES},
            "time_dilation": {
                s: round(self.ticks_per_work_unit(s) / self.ticks_per_unit, 4)
                for s in ACTIVE_STATES},
            "energy_per_work_unit": {
                s: round(self.energy_per_work_unit(s), 4) for s in ACTIVE_STATES},
            "starvation_wait_factor": self.starvation_wait_factor,
            "starvation_ntat_factor": self.starvation_ntat_factor,
        }


@dataclass(frozen=True)
class EAHWeights:
    """Weights for the Energy-Aware Hybrid policy.

    Stage 1 (w_*) decides which process runs next; stage 2 (u_*) decides the
    frequency it runs at. Both are written down here rather than inlined so
    that the policy is auditable and tunable.
    """

    # stage 1 - process selection
    w_wait: float = 0.35
    w_short: float = 0.40
    w_prio: float = 0.25
    w_deadline: float = 0.00

    # stage 2 - frequency selection
    u_wait: float = 0.30
    u_prio: float = 0.25
    u_pressure: float = 0.25
    u_deadline: float = 0.20

    pressure_ref: int = 4
    # Queue pressure alone reaches ~0.31 of the urgency scale, so a threshold
    # of 0.60 let a merely-busy queue force the top clock. At 0.70 a full
    # queue settles on MED -- the energy-optimal state -- and HIGH is reserved
    # for work that is genuinely urgent (waited long, or high priority, or
    # near a deadline). Raising it further trades more turnaround for more
    # energy saving; the sweep endpoint plots that curve.
    urgency_high: float = 0.70
    urgency_med: float = 0.30

    # How much work may elapse before the frequency is reconsidered. EAH stays
    # non-preemptive, but a long run can still escalate as the queue fills.
    resample_work: float = 1.0
    slack_safety_units: float = 1.0

    def with_overrides(self, overrides: Optional[Dict[str, Any]]) -> "EAHWeights":
        if not overrides:
            return self
        known = set(self.__dataclass_fields__)
        unknown = sorted(set(overrides) - known)
        if unknown:
            raise ValueError("unknown EAH weight(s): " + ", ".join(unknown))
        return replace(self, **overrides)

    def to_api_dict(self) -> Dict[str, Any]:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


@dataclass
class SimConfig:
    """Everything one simulation run needs besides the workload itself."""

    params: Optional[EnergyParams] = None
    eah: Optional[EAHWeights] = None
    governor: str = "utilization_window"
    include_timelines: bool = True
    quantum: int = 2
    threshold: Optional[float] = None
    preemptive: bool = False

    def __post_init__(self):
        if self.params is None:
            self.params = EnergyParams()
        if self.eah is None:
            self.eah = EAHWeights()


DEFAULT_PARAMS = EnergyParams()
DEFAULT_EAH = EAHWeights()
