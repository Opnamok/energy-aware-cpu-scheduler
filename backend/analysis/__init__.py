"""
Deeper analysis on top of the simulator.

    workload_gen  seeded random workload generation
    montecarlo    repeated trials with paired (common random number) design
    sweep         one-parameter-at-a-time sweeps
    pareto        energy-delay metrics and Pareto frontiers
"""

from analysis.montecarlo import monte_carlo, run_once
from analysis.pareto import normalized_radar, pareto_analysis
from analysis.sweep import sweep, sweepable
from analysis.workload_gen import generate_workload, summarize_workloads

__all__ = [
    "generate_workload",
    "monte_carlo",
    "normalized_radar",
    "pareto_analysis",
    "run_once",
    "summarize_workloads",
    "sweep",
    "sweepable",
]
