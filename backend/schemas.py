"""
Request models for the API.

Kept out of `server.py` so the endpoint bodies stay readable. Every new field
is optional with a default that reproduces the previous behaviour, so existing
clients are unaffected.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProcessInput(BaseModel):
    pid: int
    arrival: int
    burst: int = Field(description="Work required, at the reference frequency")
    priority: Optional[int] = 0
    # Optional. When present, EAH will raise the clock for a process whose
    # slack is running out.
    deadline: Optional[int] = None
    label: Optional[str] = None


class SimOptions(BaseModel):
    """Options shared by every simulating endpoint."""

    governor: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    eah_weights: Optional[Dict[str, Any]] = None
    include_timelines: bool = True


class SchedulerRequest(SimOptions):
    algorithm: str
    processes: List[ProcessInput]
    quantum: Optional[int] = 2
    threshold: Optional[float] = None
    preemptive: Optional[bool] = False


class EnergyRequest(BaseModel):
    gantt: List[Dict[str, Any]]
    context_switches: int = 0
    frequency_switches: Optional[int] = None
    params: Optional[Dict[str, Any]] = None


class CompareRequest(SimOptions):
    processes: List[ProcessInput]
    quantum: Optional[int] = 2
    task_threshold: Optional[float] = None
    algorithms: Optional[List[str]] = None


class MulticoreRequest(BaseModel):
    processes: List[ProcessInput]
    num_cores: int = Field(ge=2, le=8)
    algorithm: str = "fcfs"
    quantum: Optional[int] = 2
    threshold: Optional[float] = None


class ExperimentRequest(SimOptions):
    """Repeated trials over seeded random workloads."""

    trials: int = Field(default=200, ge=1, le=2000)
    seed: int = 42
    workload: Optional[Dict[str, Any]] = None
    algorithms: Optional[List[str]] = None
    metrics: Optional[List[str]] = None
    quantum: Optional[int] = 2
    threshold: Optional[float] = None
    baseline: str = "fcfs"


class SweepRequest(SimOptions):
    """Sweep one or more parameters, one axis at a time."""

    sweeps: List[Dict[str, Any]]
    processes: Optional[List[ProcessInput]] = None
    workload: Optional[Dict[str, Any]] = None
    seed: int = 7
    trials_per_point: int = Field(default=10, ge=1, le=200)
    algorithms: Optional[List[str]] = None
    metrics: Optional[List[str]] = None
    quantum: Optional[int] = 2
    threshold: Optional[float] = None
    include_unaffected: bool = True


class EnergyDelayRequest(SimOptions):
    """Energy-delay products and the Pareto frontier for one workload."""

    processes: List[ProcessInput]
    quantum: Optional[int] = 2
    threshold: Optional[float] = None
    algorithms: Optional[List[str]] = None
    objectives: Optional[List[str]] = None


class DrilldownRequest(SimOptions):
    """Per-process detail for a single algorithm run."""

    algorithm: str = "eah"
    processes: List[ProcessInput]
    quantum: Optional[int] = 2
    threshold: Optional[float] = None
    preemptive: Optional[bool] = False
    bins: int = Field(default=5, ge=2, le=20)
