"""
FastAPI backend for the Energy-Aware CPU Scheduler Simulator.

One process serves both the REST API under /api and the simulator UI from
frontend/public, so `uvicorn server:app --port 8000` is all you need. No
database is required.

Endpoints
    GET  /api/health          service check
    GET  /api/parameters      the energy model and EAH weights
    GET  /api/governors       available frequency governors
    GET  /api/sweepable       which parameters can be swept
    POST /api/run             one algorithm
    POST /api/all             one algorithm plus energy (what the UI calls)
    POST /api/energy          energy for a supplied Gantt chart
    POST /api/compare         every algorithm on one workload
    POST /api/multicore       multi-core simulation (fixed HIGH clock)
    POST /api/experiment      repeated seeded trials, mean +/- std dev
    POST /api/sweep           parameter sweeps
    POST /api/energy_delay    EDP / ED2P and the Pareto frontier
    POST /api/drilldown       per-process detail and distributions
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from analysis.montecarlo import monte_carlo, run_once
from analysis.pareto import normalized_radar, pareto_analysis
from analysis.sweep import sweep as run_sweep, sweepable
from multicore_scheduler import multicore_schedule
from schemas import (CompareRequest, DrilldownRequest, EnergyDelayRequest,
                     EnergyRequest, ExperimentRequest, MulticoreRequest,
                     SchedulerRequest, SweepRequest)
from sim.energy import calculate_dvfs_energy, energy_delay, summarize_energy
from sim.governors import DEFAULT_GOVERNOR, list_governors
from sim.metrics import (advanced_metrics, distribution, per_process_detail,
                         starvation_report)
from sim.params import EAHWeights, EnergyParams, SimConfig
from sim.policies import COMPARE_ORDER, run_algorithm

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Optional MongoDB. Nothing in the simulator needs it; it exists only so a
# deployment can persist runs if it wants to. Unset means no database, which
# is what lets a fresh checkout run with nothing but `pip install`.
mongo_url = os.environ.get("MONGO_URL")
client = None
db = None
if mongo_url:
    from motor.motor_asyncio import AsyncIOMotorClient  # imported lazily

    client = AsyncIOMotorClient(mongo_url)
    db = client[os.environ.get("DB_NAME", "energix")]

app = FastAPI(title="Energy-Aware CPU Scheduler Simulator API")

# CORS is registered before the router and the static mount so that it wraps
# them. Credentials stay off: a wildcard origin combined with credentials is
# something browsers refuse, and nothing here uses cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

@app.middleware("http")
async def no_cache_static(request, call_next):
    """Stop browsers caching the UI.

    The frontend is plain files with no build step and no content hashing, so
    an edited stylesheet or script would otherwise keep serving stale until a
    hard reload -- which is exactly the wrong failure mode when you are
    demonstrating a change.
    """
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


api_router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _processes(request) -> List[Dict[str, Any]]:
    procs = [p.model_dump() for p in (request.processes or [])]
    if not procs:
        raise HTTPException(status_code=400, detail="No processes provided")
    return procs


def _config(request, quantum=None, threshold=None, preemptive=False) -> SimConfig:
    """Build a SimConfig from the shared request options."""
    try:
        params = EnergyParams().with_overrides(getattr(request, "params", None))
        weights = EAHWeights().with_overrides(
            getattr(request, "eah_weights", None))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return SimConfig(
        params=params,
        eah=weights,
        governor=getattr(request, "governor", None) or DEFAULT_GOVERNOR,
        include_timelines=getattr(request, "include_timelines", True),
        quantum=quantum if quantum is not None else 2,
        threshold=threshold,
        preemptive=bool(preemptive),
    )


def _simulate(algorithm: str, procs: List[Dict[str, Any]],
              cfg: SimConfig) -> Dict[str, Any]:
    """Run one algorithm and attach its energy and advanced metrics."""
    try:
        result = run_algorithm(algorithm, procs, cfg)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    energy = summarize_energy(
        result["gantt"], result["context_switches"],
        result["frequency_switches"], cfg.params,
        include_timelines=cfg.include_timelines)
    energy.update(energy_delay(energy["total_energy"],
                               result["metrics"]["avg_turnaround"],
                               len(result["processes"])))
    energy["governor"] = cfg.governor

    result["energy"] = energy
    result["advanced_metrics"] = advanced_metrics(result, procs)
    result.pop("_internal", None)
    return result


def _handle(exc: Exception, where: str):
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc))
    logger.error("Error in %s: %s", where, exc, exc_info=True)
    raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Information
# ---------------------------------------------------------------------------

@api_router.get("/")
async def root():
    return {"message": "Energy-Aware CPU Scheduler Simulator API - Ready"}


@api_router.get("/health")
async def health():
    return {"status": "healthy",
            "service": "Energy-Aware CPU Scheduler Simulator",
            "database": "connected" if db is not None else "none (not required)"}


@api_router.get("/parameters")
async def parameters():
    """The energy model and EAH weights, with their defaults."""
    return {
        "parameters": EnergyParams().to_api_dict(),
        "eah_weights": EAHWeights().to_api_dict(),
        "default_governor": DEFAULT_GOVERNOR,
        "algorithms": list(COMPARE_ORDER),
    }


@api_router.get("/governors")
async def governors():
    return {"governors": list_governors(), "default": DEFAULT_GOVERNOR}


@api_router.get("/sweepable")
async def sweepable_params():
    return sweepable()


# ---------------------------------------------------------------------------
# Single runs
# ---------------------------------------------------------------------------

@api_router.post("/run")
async def run_scheduler(request: SchedulerRequest):
    """Run one scheduling algorithm (without the energy block)."""
    try:
        procs = _processes(request)
        cfg = _config(request, request.quantum, request.threshold,
                      request.preemptive)
        result = run_algorithm(request.algorithm, procs, cfg)
        result.pop("_internal", None)
        return JSONResponse(content=result)
    except Exception as exc:
        _handle(exc, "run_scheduler")


@api_router.post("/all")
async def run_all(request: SchedulerRequest):
    """Run one algorithm and compute its energy. This is what the UI calls."""
    try:
        procs = _processes(request)
        cfg = _config(request, request.quantum, request.threshold,
                      request.preemptive)
        return JSONResponse(content=_simulate(request.algorithm, procs, cfg))
    except Exception as exc:
        _handle(exc, "run_all")


@api_router.post("/energy")
async def calculate_energy(request: EnergyRequest):
    """Energy for a supplied Gantt chart.

    Segments produced by this engine carry their frequency state and are
    summarised faithfully. Segments without one cannot be DVFS-aware -- there
    is no way to know what clock the work ran at -- so HIGH is assumed and the
    response says so, rather than passing a guess off as a measurement.
    """
    try:
        params = EnergyParams().with_overrides(request.params)
        return JSONResponse(content=calculate_dvfs_energy(
            request.gantt, request.context_switches, params))
    except Exception as exc:
        _handle(exc, "calculate_energy")


@api_router.post("/compare")
async def compare_algorithms(request: CompareRequest):
    """Run every algorithm on the same workload."""
    try:
        procs = _processes(request)
        cfg = _config(request, request.quantum, request.task_threshold)
        algorithms = list(request.algorithms or COMPARE_ORDER)

        results: Dict[str, Any] = {}
        points = []
        for name in algorithms:
            try:
                result = _simulate(name, procs, cfg)
            except HTTPException as exc:
                results[name] = {"error": exc.detail}
                continue
            except Exception as exc:                      # noqa: BLE001
                results[name] = {"error": str(exc)}
                continue

            energy = result["energy"]
            results[name] = {
                "algorithm": result["algorithm"],
                "avg_turnaround": result["metrics"]["avg_turnaround"],
                "avg_waiting": result["metrics"]["avg_waiting"],
                "context_switches": result["context_switches"],
                "frequency_switches": result["frequency_switches"],
                "total_energy": energy["total_energy"],
                "completion_time": result["metrics"]["total_completion"],
                "edp": energy["edp"],
                "ed2p": energy["ed2p"],
                "energy_per_process": energy["energy_per_process"],
                "frequency_residency": energy["frequency_residency"],
                "energy_breakdown": {
                    "busy": energy["busy_energy"],
                    "idle": energy["idle_energy"],
                    "context_switch": energy["context_switch_energy"],
                    "frequency_switch": energy["freq_switch_energy"],
                },
                "gantt": result["gantt"],
                "processes": result["processes"],
                "metrics": result["metrics"],
                "advanced_metrics": result["advanced_metrics"],
            }
            points.append({
                "key": name,
                "algorithm": result["algorithm"],
                "total_energy": energy["total_energy"],
                "avg_turnaround": result["metrics"]["avg_turnaround"],
                "avg_waiting": result["metrics"]["avg_waiting"],
                "total_completion": result["metrics"]["total_completion"],
                "context_switches": result["context_switches"],
                "edp": energy["edp"],
                "ed2p": energy["ed2p"],
                "energy_per_process": energy["energy_per_process"],
            })

        # The Pareto analysis travels with the comparison so the UI can show
        # which policies are genuinely not beaten on both axes, instead of
        # only naming a single weighted "winner".
        pareto = pareto_analysis(points, ("total_energy", "avg_turnaround"))
        radar = normalized_radar(
            points, ("total_energy", "avg_turnaround", "avg_waiting",
                     "total_completion", "context_switches"))

        payload = dict(results)
        payload["_analysis"] = {
            # The per-point ranks are kept: the comparison table shows which
            # policy dominates which, not just the frontier membership.
            "pareto": pareto,
            "radar": radar,
            "governor": cfg.governor,
            "parameters": cfg.params.to_api_dict(),
        }
        return JSONResponse(content=payload)
    except Exception as exc:
        _handle(exc, "compare_algorithms")


@api_router.post("/multicore")
async def run_multicore(request: MulticoreRequest):
    """Multi-core simulation.

    This path runs at a fixed HIGH clock: DVFS is modelled for the single-core
    engine only, and pretending otherwise here would be misleading. The
    response says so explicitly via `dvfs: false`.
    """
    try:
        procs = _processes(request)
        result = multicore_schedule(procs, request.num_cores,
                                    request.algorithm.lower(),
                                    request.quantum or 2, request.threshold)
        params = EnergyParams()
        energy = summarize_energy(result["gantt"], result["context_switches"],
                                  0, params, include_timelines=True)
        energy["governor"] = "fixed:high"
        result["energy"] = energy
        result["advanced_metrics"] = advanced_metrics(result, procs)
        result["dvfs"] = False
        result["governor"] = "fixed:high"
        result["note"] = ("Multi-core runs at a fixed HIGH clock; DVFS is "
                          "modelled for single-core scheduling only.")
        result.pop("_internal", None)
        return JSONResponse(content=result)
    except Exception as exc:
        _handle(exc, "run_multicore")


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@api_router.post("/experiment")
async def experiment(request: ExperimentRequest):
    """Repeated trials over seeded random workloads.

    Within each trial every algorithm gets the identical workload, so the
    pairwise differences are far less noisy than the per-algorithm standard
    deviations. The same seed always gives the same numbers.
    """
    try:
        payload = await run_in_threadpool(
            monte_carlo,
            trials=request.trials,
            seed=request.seed,
            workload=request.workload,
            algorithms=request.algorithms,
            metrics=request.metrics,
            governor=request.governor or DEFAULT_GOVERNOR,
            quantum=request.quantum or 2,
            threshold=request.threshold,
            params=request.params,
            eah_weights=request.eah_weights,
            baseline=request.baseline)
        return JSONResponse(content=payload)
    except Exception as exc:
        _handle(exc, "experiment")


@api_router.post("/sweep")
async def sweep_parameters(request: SweepRequest):
    """Sweep parameters one axis at a time."""
    try:
        procs = ([p.model_dump() for p in request.processes]
                 if request.processes else None)
        payload = await run_in_threadpool(
            run_sweep,
            sweeps=request.sweeps,
            processes=procs,
            workload=request.workload,
            seed=request.seed,
            trials_per_point=request.trials_per_point,
            algorithms=request.algorithms,
            metrics=request.metrics,
            governor=request.governor or DEFAULT_GOVERNOR,
            quantum=request.quantum or 2,
            threshold=request.threshold,
            params=request.params,
            eah_weights=request.eah_weights,
            include_unaffected=request.include_unaffected)
        return JSONResponse(content=payload)
    except Exception as exc:
        _handle(exc, "sweep_parameters")


@api_router.post("/energy_delay")
async def energy_delay_analysis(request: EnergyDelayRequest):
    """Energy-delay products and the Pareto frontier."""
    try:
        procs = _processes(request)
        cfg = _config(request, request.quantum, request.threshold)
        cfg.include_timelines = False
        algorithms = list(request.algorithms or COMPARE_ORDER)

        points = []
        for name in algorithms:
            try:
                flat = run_once(name, procs, cfg)
            except Exception as exc:                      # noqa: BLE001
                points.append({"key": name, "error": str(exc)})
                continue
            points.append({
                "key": name,
                "algorithm": flat["algorithm"],
                "total_energy": flat["total_energy"],
                "avg_turnaround": flat["avg_turnaround"],
                "avg_waiting": flat["avg_waiting"],
                "total_completion": flat["total_completion"],
                "context_switches": flat["context_switches"],
                "edp": flat["edp"],
                "ed2p": flat["ed2p"],
                "energy_per_process": flat["energy_per_process"],
                "residency": {
                    "HIGH": flat["residency_high"],
                    "MED": flat["residency_med"],
                    "LOW": flat["residency_low"],
                },
            })

        analysis = pareto_analysis(points, request.objectives
                                   or ("total_energy", "avg_turnaround"))
        analysis["radar"] = normalized_radar(
            points, ("total_energy", "avg_turnaround", "avg_waiting",
                     "total_completion", "context_switches"))
        analysis["governor"] = cfg.governor
        analysis["parameters"] = cfg.params.to_api_dict()
        return JSONResponse(content=analysis)
    except Exception as exc:
        _handle(exc, "energy_delay_analysis")


@api_router.post("/drilldown")
async def drilldown(request: DrilldownRequest):
    """Per-process detail, distributions, residency and energy breakdown."""
    try:
        procs = _processes(request)
        cfg = _config(request, request.quantum, request.threshold,
                      request.preemptive)
        result = _simulate(request.algorithm, procs, cfg)
        energy = result["energy"]
        rows = per_process_detail(result)

        return JSONResponse(content={
            "algorithm": result["algorithm"],
            "governor": cfg.governor,
            "metrics": result["metrics"],
            "advanced_metrics": result["advanced_metrics"],
            "per_process": rows,
            "waiting_distribution": distribution(
                [r.get("waiting", 0) for r in rows], request.bins),
            "response_distribution": distribution(
                [r.get("response_time") or 0 for r in rows], request.bins),
            "turnaround_distribution": distribution(
                [r.get("turnaround", 0) for r in rows], request.bins),
            "starvation": starvation_report(result, cfg.params),
            "frequency_residency": {
                "by_busy_time": energy["frequency_residency"],
                "by_work": energy["residency_by_work"],
                "by_wall_time": energy["residency_by_wall_time"],
                "switches": energy["frequency_switches"],
            },
            "energy_breakdown": {
                "busy": energy["busy_energy"],
                "idle": energy["idle_energy"],
                "context_switch": energy["context_switch_energy"],
                "frequency_switch": energy["freq_switch_energy"],
                "total": energy["total_energy"],
                "by_state": energy["energy_by_state"],
            },
            "gantt": result["gantt"],
            "parameters": cfg.params.to_api_dict(),
        })
    except Exception as exc:
        _handle(exc, "drilldown")


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

app.include_router(api_router)

# The static mount must come last: a mount at "/" swallows everything that did
# not match a route registered above it.
frontend_path = Path(__file__).parent.parent / "frontend" / "public"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True),
              name="static")


@app.on_event("startup")
async def startup_event():
    logger.info("Energy-Aware CPU Scheduler Simulator API started")
    if db is None:
        logger.info("No database configured (MONGO_URL unset) - not required")
    if frontend_path.exists():
        logger.info("Serving the UI from %s", frontend_path)


@app.on_event("shutdown")
async def shutdown_event():
    if client is not None:
        client.close()
