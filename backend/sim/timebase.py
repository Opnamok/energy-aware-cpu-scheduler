"""
The simulation time base.

All internal time is an integer number of *ticks*. One unit of work at the
reference frequency takes `ticks_per_unit` ticks (2 by default), so a tick is
half a display time unit. Keeping time integral is what makes completion times
exact and reproducible: running a 5-unit burst entirely at LOW takes 25 ticks,
i.e. 12.5 display units, with no floating-point drift anywhere.

Display values are only produced at the boundary, when a result is serialised.
"""

from typing import Union

Number = Union[int, float]


def to_units(ticks: int, ticks_per_unit: int) -> float:
    """Convert ticks to display time units."""
    units = ticks / ticks_per_unit
    # Present whole numbers as ints so that unscaled runs look exactly as they
    # did before DVFS was coupled in (0 and 5, not 0.0 and 5.0).
    if units == int(units):
        return int(units)
    return round(units, 6)


def to_ticks(units: Number, ticks_per_unit: int) -> int:
    """Convert display time units to ticks, insisting the result is whole."""
    exact = units * ticks_per_unit
    ticks = int(round(exact))
    if abs(exact - ticks) > 1e-9:
        raise ValueError(
            "{0} time units is not a whole number of ticks at "
            "ticks_per_unit={1}".format(units, ticks_per_unit))
    return ticks


def work_to_ticks(work: Number, ticks_per_work_unit: int) -> int:
    """Ticks consumed by `work` units of work at a given state."""
    exact = work * ticks_per_work_unit
    ticks = int(round(exact))
    if abs(exact - ticks) > 1e-9:
        raise ValueError(
            "{0} units of work does not map to a whole number of ticks at "
            "{1} ticks per work unit".format(work, ticks_per_work_unit))
    return ticks
