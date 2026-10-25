"""
Energy-Aware Hybrid (EAH) scheduling -- compatibility facade.

The implementation moved into `sim.policies.EAHPolicy` and the energy model
into `sim.energy` when DVFS was coupled into the simulation. The important
change in behaviour: EAH now chooses a frequency state as well as a process,
and the frequency it picks determines how long the work takes. Previously
`calculate_dvfs_energy` ran a governor over a finished Gantt chart, so the
frequency could not affect anything and every policy got identical treatment.

This module keeps the original import paths:

    from energy_aware_scheduler import energy_aware_hybrid, calculate_dvfs_energy
"""

from sim.energy import calculate_dvfs_energy, summarize_energy
from sim.policies import EAHPolicy, energy_aware_hybrid
from sim.process import Process

__all__ = [
    "energy_aware_hybrid",
    "calculate_dvfs_energy",
    "summarize_energy",
    "EAHPolicy",
    "Process",
]
