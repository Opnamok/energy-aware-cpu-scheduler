"""
CPU Scheduling Algorithms -- compatibility facade.

The implementations moved into the `sim` package when frequency selection was
coupled into the simulation (see sim/engine.py). This module keeps the import
paths and function signatures that `server.py`, `multicore_scheduler.py` and
`test_samples.py` have always used:

    from algorithms import fcfs, sjf_non_preemptive, sjf_preemptive, \
                           round_robin, priority_scheduling, Process

`Process` is now a single class shared with the EAH scheduler, which used to
carry a near-identical copy of its own.
"""

from sim.metrics import advanced_metrics, calculate_advanced_metrics
from sim.policies import (fcfs, priority_scheduling, round_robin,
                          sjf_non_preemptive, sjf_preemptive)
from sim.process import Process

__all__ = [
    "Process",
    "fcfs",
    "sjf_non_preemptive",
    "sjf_preemptive",
    "round_robin",
    "priority_scheduling",
    "calculate_advanced_metrics",
    "advanced_metrics",
]
