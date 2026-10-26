# Energy-Efficient CPU Scheduling Algorithm for Mobile & Embedded Systems

## 🎓 Academic Project - Complete & Working Implementation

A comprehensive web-based CPU scheduling simulator demonstrating **6 scheduling algorithms** with a novel **Energy-Aware Hybrid (EAH)** approach integrated with **Adaptive DVFS** (Dynamic Voltage Frequency Scaling) for energy efficiency in mobile and embedded systems.

---

## Key Features

- **Six scheduling policies** -- FCFS, SJF, SRTF, Round Robin, Priority, and
  the custom **Energy-Aware Hybrid (EAH)**.
- **Real DVFS coupling.** Frequency is chosen *during* the simulation and
  determines both power draw and how long work takes. EAH selects a process
  and a clock together, which is the project's central claim.
- **Pluggable governors**, so the effect of frequency choice can be separated
  from the effect of scheduling order.
- **Analysis beyond a single run** -- seeded repeated trials with mean and
  standard deviation, parameter sweeps, energy-delay products, Pareto
  frontiers, and per-process drill-down with starvation detection.
- **Terminal (TUI) interface** -- monospace, keyboard-driven, with both a
  graphical and an ASCII Gantt chart.
- **Runs from a clean checkout.** No database, no build step, one command.

---



## Quick Start

### Prerequisites
- Python 3.11 or newer. **No database and no Node.js are required** -- the
  frontend is plain HTML/CSS/JS with no build step.

### Run it

```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --port 8000 --reload
```

Then open **http://localhost:8000/scheduler-index.html**

The one FastAPI process serves both the REST API and the UI, and the frontend
resolves the API from its own origin -- so there is nothing to configure.

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `1`..`6` | Switch tab (input / results / energy / compare / trials / sweep) |
| `r` | Run the scheduler |
| `c` | Compare all policies |

### Run the tests

```bash
cd backend
python tests/test_regression.py    # pre-DVFS schedules still reproduce at a fixed HIGH clock
python tests/test_dvfs.py          # frequency really does affect time and energy
python test_samples.py             # benchmark the stored workloads (needs the server running)
```

`test_samples.py --csv out.csv` writes the full metric matrix.

---

## 📁 Project Structure

```
EnergiX-Adaptive-Power-Optimized-Scheduler/
├── backend/
│   ├── server.py                 # FastAPI app: REST API + serves the UI
│   ├── schemas.py                # Pydantic request models
│   ├── algorithms.py             # Compatibility facade -> sim.policies
│   ├── energy_aware_scheduler.py # Compatibility facade -> sim.policies / sim.energy
│   ├── multicore_scheduler.py    # Multi-core simulation (fixed HIGH clock)
│   ├── sim/                      # The simulator
│   │   ├── params.py             #   frequency states, power model, EAH weights
│   │   ├── timebase.py           #   integer tick arithmetic
│   │   ├── process.py            #   the single Process class
│   │   ├── governors.py          #   frequency-selection strategies
│   │   ├── engine.py             #   discrete-event dispatch loop
│   │   ├── policies.py           #   the six scheduling policies
│   │   ├── energy.py             #   energy summary, residency, timelines
│   │   └── metrics.py            #   metrics, distributions, starvation
│   ├── analysis/                 # Deeper analysis
│   │   ├── workload_gen.py       #   seeded random workloads
│   │   ├── montecarlo.py         #   repeated trials, paired design
│   │   ├── sweep.py              #   parameter sweeps
│   │   └── pareto.py             #   energy-delay metrics, Pareto frontier
│   ├── tests/
│   │   ├── test_regression.py    #   pre-DVFS behaviour is preserved at fixed HIGH
│   │   ├── test_dvfs.py          #   the DVFS coupling actually works
│   │   └── golden_pre_dvfs.json  #   captured reference output
│   ├── test_samples.py           # Benchmark CLI against a running server
│   ├── sample.json               # Stored sample workloads
│   ├── requirements.txt          # 6 runtime dependencies
│   ├── requirements-dev.txt      # linters and pytest
│   └── Procfile, railway.json, runtime.txt
│
├── frontend/public/              # Plain HTML/CSS/JS -- no build step
│   ├── scheduler-index.html      # The simulator UI
│   ├── index.html                # Redirect to the simulator
│   ├── css/scheduler-style.css   # Terminal (TUI) theme; all colour tokens
│   └── js/
│       ├── theme.js              #   single source of colour, Chart.js defaults
│       ├── scheduler-api.js      #   API client
│       ├── scheduler-gantt.js    #   Gantt chart, frequency ribbon, ASCII view
│       ├── scheduler-charts.js   #   power / frequency / comparison charts
│       ├── scheduler-analysis.js #   trials, sweeps, Pareto, drill-down
│       ├── scheduler-animation.js#   step-through player
│       └── scheduler-main.js     #   UI logic
│
├── utils/process_importer.py     # Import live OS processes (needs psutil)
├── README.md                     # This file
├── USAGE_GUIDE.md                # Walkthrough
├── ENERGY_CALCULATION.md         # The energy model and selection methodology
└── vercel.json                   # Static deployment config
```

## 🔬 Algorithms Implemented

### 1. FCFS (First Come First Serve)
- **Type**: Non-preemptive
- **Complexity**: O(n)
- **Pros**: Simple, no starvation
- **Cons**: High average waiting time

### 2. SJF Non-Preemptive
- **Type**: Non-preemptive
- **Complexity**: O(n²)
- **Pros**: Minimum average waiting time
- **Cons**: Potential starvation of long processes

### 3. SJF Preemptive (SRTF)
- **Type**: Preemptive
- **Complexity**: O(n²)
- **Pros**: Better average waiting time
- **Cons**: High context switches, starvation risk

### 4. Round Robin
- **Type**: Preemptive
- **Complexity**: O(n)
- **Pros**: Fair CPU allocation, good response time
- **Cons**: Higher context switches

### 5. Priority Scheduling
- **Type**: Preemptive / Non-preemptive
- **Complexity**: O(n²)
- **Pros**: Important tasks execute first
- **Cons**: Starvation of low-priority tasks

### 6. Energy-Aware Hybrid (EAH) -- the custom policy
- **Type**: Non-preemptive, scored
- **Decides two things at once**: which process runs next, *and* at what clock.

**Stage 1 -- which process.** A weighted score over how long a process has
waited, how short it is, and how important it is:

```
score(p) = 0.35*norm_wait + 0.40*norm_short + 0.25*norm_prio
```

The shortness term keeps SJF's turnaround advantage; the waiting term provides
aging. That is a deliberate change from the original "drain the whole short
queue, then the long queue" rule, under which a steady stream of short
arrivals could starve a long job indefinitely. Ties break on waiting time,
then remaining work, then priority, then arrival, then pid -- so the policy is
fully deterministic, which the seeded trial statistics depend on.

**Stage 2 -- which clock.** An urgency score drives the frequency:

```
urgency(p) = 0.30*norm_wait + 0.25*norm_prio + 0.25*queue_pressure
             (+ 0.20*deadline_slack when deadlines are given)

urgency >= 0.70 -> HIGH    >= 0.30 -> MED    otherwise -> LOW
```

Frequency is **resampled every work unit**, so a long job dispatched at LOW
into an empty queue escalates as pressure builds -- adapting the clock without
paying a single extra context switch. The utilisation-window governor
structurally cannot do this: on a saturated stretch it sees utilisation near
1.0 and pins HIGH.

**Why this saves energy:** it defaults to MED, which is the energy-optimal
state (see the energy model below), and spends HIGH only on work that is
genuinely urgent. It stays non-preemptive, so context-switch energy stays low.

**What it costs:** turnaround time. EAH finishes later than SRTF. That is the
trade-off the project exists to study, and it is why the comparison view
reports a Pareto frontier rather than a single winner.

- **Complexity**: O(n^2) over dispatches; weights in `backend/sim/params.py`

---

## Energy Model (DVFS)

Power follows the report's `P proportional to f * V^2` relationship, with a
static leakage floor:

```
P(state) = c_eff * f_GHz * V^2 + p_static        c_eff = 1.35, p_static = 0.95
```

| State | Frequency | Voltage | Power | Time per work unit | Energy per work unit |
|-------|-----------|---------|-------|--------------------|----------------------|
| HIGH  | 3.0 GHz   | 1.00 V  | 5.000 W | 1.0x             | 5.0000 |
| MED   | 2.0 GHz   | 0.85 V  | 2.901 W | 1.5x             | **4.3511** |
| LOW   | 1.2 GHz   | 0.75 V  | 1.861 W | 2.5x             | 4.6531 |
| IDLE  | gated     | -       | 0.200 W | -                | - |

**Frequency changes how long work takes.** A process's `burst` is the work it
needs at the reference clock (3.0 GHz). Running at 2.0 GHz stretches that work
to 1.5x the wall-clock time; at 1.2 GHz, 2.5x. The simulator runs on integer
ticks (one work unit costs 2 / 3 / 5 ticks), so every segment boundary is
exact and completion times never drift.

```
Total Energy = SUM(P_state * duration)
             + context_switches   * 0.5
             + frequency_changes  * 0.1
```

### The energy-optimal clock is MED, not LOW

Dynamic energy per unit of work falls as `V^2` when the clock drops, but
static energy rises as `1/f` because leakage is paid for longer. The sum has an
interior minimum at MED -- so **LOW is both slower and less efficient**. This
is the well-documented critical-frequency effect, and it is why real
processors do not simply run as slowly as possible.

`p_static` is the knob that moves that optimum. Sweeping it (tab 6) shows the
energy-optimal state migrate LOW -> MED -> HIGH as leakage rises.

### Governors

Frequency selection is pluggable, so the effect of *frequency choice* can be
separated from the effect of *process ordering*:

| Governor | Behaviour |
|----------|-----------|
| `utilization_window` | Default. Sliding-window utilisation with hysteresis (thresholds 0.6 / 0.2, window 3, hysteresis 1). |
| `eah_score` | The EAH urgency rule, usable by any policy. |
| `ondemand_queue` | Scale with ready-queue depth. |
| `race_to_idle` | Always HIGH, then idle. |
| `fixed:high` / `fixed:med` / `fixed:low` | Pin the clock -- the experimental control. |

Running **FCFS under `eah_score`** isolates frequency choice from scheduling
order. Without that ablation, any energy difference between EAH and the
baselines could just be the context-switch penalty under another name.

See [ENERGY_CALCULATION.md](ENERGY_CALCULATION.md) for the full model, the
EAH scoring rule with its weights, and a worked example.

---

## API

Base URL `http://localhost:8000/api`. Every simulating endpoint accepts
optional `governor`, `params` (energy-model overrides) and `eah_weights`.

### Information

| Endpoint | Returns |
|----------|---------|
| `GET /health` | Service status |
| `GET /parameters` | The energy model and EAH weights with their defaults |
| `GET /governors` | Available frequency governors |
| `GET /sweepable` | Which parameters can be swept |

### Simulation

| Endpoint | Purpose |
|----------|---------|
| `POST /run` | One algorithm, without the energy block |
| `POST /all` | One algorithm plus energy -- what the UI calls |
| `POST /energy` | Energy for a supplied Gantt chart |
| `POST /compare` | Every policy on one workload, plus the Pareto analysis |
| `POST /multicore` | Multi-core simulation (fixed HIGH clock; `dvfs: false`) |

### Analysis

| Endpoint | Purpose |
|----------|---------|
| `POST /experiment` | N seeded random workloads; mean, standard deviation, 95% CI, and paired differences against a baseline |
| `POST /sweep` | Sweep a parameter and report a metric per policy |
| `POST /energy_delay` | EDP, ED2P and the Pareto frontier |
| `POST /drilldown` | Per-process detail, distributions, starvation, clock residency |

### Examples

```bash
# Run EAH and get its energy
curl -X POST http://localhost:8000/api/all \
  -H "Content-Type: application/json" \
  -d '{"algorithm":"eah",
       "processes":[{"pid":1,"arrival":0,"burst":5,"priority":2},
                    {"pid":2,"arrival":1,"burst":3,"priority":1}],
       "quantum":2}'

# Pin the clock low and watch completion time stretch
curl -X POST http://localhost:8000/api/all \
  -H "Content-Type: application/json" \
  -d '{"algorithm":"fcfs","governor":"fixed:low",
       "processes":[{"pid":1,"arrival":0,"burst":4,"priority":1}]}'

# 200 seeded trials, reproducible
curl -X POST http://localhost:8000/api/experiment \
  -H "Content-Type: application/json" \
  -d '{"trials":200,"seed":42,"baseline":"fcfs"}'

# Sweep the leakage floor and watch the energy-optimal clock move
curl -X POST http://localhost:8000/api/sweep \
  -H "Content-Type: application/json" \
  -d '{"sweeps":[{"param":"p_static","values":[0.2,0.95,2.5]}],
       "trials_per_point":10,"metrics":["total_energy"]}'
```

Interactive API docs are at `http://localhost:8000/docs`.

---

## 🎮 Using the Simulator

### Step 1: Configure Simulation
1. Select an algorithm from the dropdown
2. Set parameters (quantum for Round Robin, threshold for EAH)
3. Add/modify processes in the table

### Step 2: Add Processes
- **Default**: 4 processes pre-loaded
- **Add Process**: Click "Add Process" button
- **Load Sample**: Click "Load Sample" for 6-process workload
- **Remove**: Click trash icon next to any process

### Step 3: Run Simulation
- **Single Algorithm**: Click "Run Scheduler"
- **Compare All**: Click "Compare All Algorithms"

### Step 4: View Results
- **Results Tab**: View Gantt chart, metrics, and process details
- **Energy Analysis Tab**: View power timeline, frequency states, and energy breakdown
- **Compare Tab**: Side-by-side algorithm comparison with charts

### Step 5: Export Data
- Click "Export JSON" to download complete results for further analysis

---

## 🧪 Testing

### Backend API Testing
```bash
# Test health endpoint
curl http://localhost:8000/api/health

# Test EAH algorithm
curl -X POST http://localhost:8000/api/all \
  -H "Content-Type: application/json" \
  -d '{
    "algorithm": "eah",
    "processes": [
      {"pid": 1, "arrival": 0, "burst": 5, "priority": 2},
      {"pid": 2, "arrival": 1, "burst": 3, "priority": 1}
    ]
  }'

# Compare all algorithms
curl -X POST http://localhost:8000/api/compare \
  -H "Content-Type: application/json" \
  -d '{
    "processes": [
      {"pid": 1, "arrival": 0, "burst": 5, "priority": 2}
    ],
    "quantum": 2
  }'
```

### Frontend Testing
1. Open http://localhost:8000/scheduler-index.html
2. Use default processes or load sample data
3. Test each algorithm individually
4. Use "Compare All Algorithms" to verify all work
5. Check Results, Energy Analysis, and Compare tabs
6. Verify all charts render correctly

---

## 📊 Sample Test Cases

Note that `burst` is **work at the reference clock (3.0 GHz)**, not a
duration -- the clock the scheduler picks decides how long that work takes.

### Test Case 1: Basic Workload (Default)
```json
{
  "processes": [
    {"pid": 1, "arrival": 0, "burst": 5, "priority": 2},
    {"pid": 2, "arrival": 1, "burst": 3, "priority": 1},
    {"pid": 3, "arrival": 2, "burst": 8, "priority": 3},
    {"pid": 4, "arrival": 3, "burst": 6, "priority": 2}
  ],
  "quantum": 2
}
```

### Test Case 2: Energy-Aware Scenario (Sample Data)
```json
{
  "processes": [
    {"pid": 1, "arrival": 0, "burst": 3, "priority": 1},
    {"pid": 2, "arrival": 0, "burst": 9, "priority": 2},
    {"pid": 3, "arrival": 1, "burst": 2, "priority": 1},
    {"pid": 4, "arrival": 2, "burst": 12, "priority": 3},
    {"pid": 5, "arrival": 3, "burst": 4, "priority": 2},
    {"pid": 6, "arrival": 4, "burst": 1, "priority": 1}
  ],
  "threshold": 5
}
```

---

## 🔧 Troubleshooting

### Issue: Backend not responding
```bash
# Check if backend is running
curl http://localhost:8000/api/health

# If not running, start it manually
cd backend
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

### Issue: Frontend not loading
- Frontend is served automatically by the backend
- Just restart the backend server (Ctrl+C, then uvicorn command again)
- Access at http://localhost:8000/scheduler-index.html

### Issue: Charts not displaying
- Ensure Chart.js CDN is accessible
- Check browser console for JavaScript errors
- Clear browser cache and reload

---

## Results

Measured on the default workload -- P1(arrival 0, work 5), P2(1, 3), P3(2, 8),
P4(3, 6) -- with the `utilization_window` governor and quantum 2:

| Algorithm | Completion | Avg TAT | Avg WT | Switches | Energy | EDP |
|-----------|-----------|---------|--------|----------|--------|-----|
| FCFS | 22.5 | 11.75 | 6.12 | 3 | 110.95 | 1303.7 |
| SJF Non-Preemptive | 22.5 | 11.25 | 5.62 | 3 | 110.95 | 1248.2 |
| SJF Preemptive (SRTF) | 22.5 | 11.00 | 5.38 | 4 | 111.45 | 1226.0 |
| Round Robin (Q=2) | 22.5 | 15.75 | 10.12 | 11 | 114.95 | 1810.5 |
| Priority | 22.5 | 11.25 | 5.62 | 3 | 110.95 | 1248.2 |
| **EAH** | 24.0 | 11.75 | 5.75 | 4 | **109.70** | 1289.0 |

Over **200 randomised workloads** (seed 42, paired design -- every policy sees
the identical workload within each trial), EAH versus FCFS:

| Metric | Mean difference | 95% CI | Trials won |
|--------|-----------------|--------|------------|
| Total energy | **-3.15%** | [-3.45, -2.85] | 190 / 200 |
| Avg turnaround | +3.88% | [1.20, 6.57] | - |

### What this actually shows

1. **EAH consistently uses the least energy**, and the paired design resolves
   that effect cleanly -- the confidence interval excludes zero, even though
   the per-policy standard deviation is roughly 38% of the mean. Comparing
   independent averages would have buried it in noise.
2. **It pays for that with turnaround time.** EAH finishes later than SRTF.
   That is the trade-off, not a defect.
3. **No single policy wins outright.** The comparison view reports a **Pareto
   frontier** -- the set of policies nothing beats on both energy and
   turnaround at once. Across the nine stored benchmark workloads, SRTF is on
   the frontier 9 times and EAH 8, usually for opposite reasons.
4. **The ranking depends on the hardware.** At a low leakage floor
   (`p_static = 0.2`) EAH wins on energy by a wide margin; at a high one
   (`p_static = 2.5`) it *loses*, because slowing down stops paying when
   leakage dominates.

Reproduce any of this with `python test_samples.py` against a running server,
or from tab 5 (trials) and tab 6 (sweep) in the UI. Every result is seeded.

> Energy figures are **model estimates**, not measurements from physical
> hardware. See the Assumptions section of
> [ENERGY_CALCULATION.md](ENERGY_CALCULATION.md).

---

## 🎓 Academic Value

This project demonstrates:
- Novel energy-aware scheduling approach
- Practical DVFS integration
- Complete working implementation
- Comprehensive documentation
- Visual analytics for understanding

Suitable for Operating Systems coursework, energy-efficient computing research, and embedded systems projects.

---

## 📚 References

1. Silberschatz, A., Galvin, P. B., & Gagne, G. (2018). *Operating System Concepts* (10th ed.).
2. Tanenbaum, A. S., & Bos, H. (2014). *Modern Operating Systems* (4th ed.).
3. Pillai, P., & Shin, K. G. (2001). Real-time dynamic voltage scaling for low-power embedded operating systems.

---

## ✅ Final Status

### ✅ Backend - WORKING
- All 6 algorithms implemented and tested
- DVFS energy model functional
- All API endpoints working
- CORS configured correctly

### ✅ Frontend - WORKING
- Landing page functional
- Simulator interface operational
- API communication successful
- Gantt charts and energy graphs rendering
- Comparison feature working

### ✅ Integration - COMPLETE
- Frontend-backend communication verified
- JSON schema matching correctly
- Real-time visualization working
- Export functionality operational

---

## 🎉 Project Status

**FULLY FUNCTIONAL and READY for:**
- ✅ Local development and testing
- ✅ Academic submission and demonstration  
- ✅ Presentation and viva
- ✅ Production deployment

---

**Project Completion Date**: November 2025  
**Status**: ✅ Fully Functional & Tested  
**Version**: 1.0 - Production Ready

---

For detailed documentation, see:
- **README_PROJECT.md** - Complete project documentation
- **USAGE_GUIDE.md** - Step-by-step usage instructions
