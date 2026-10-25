/**
 * Chart.js visualisations.
 *
 * Axis, grid, tooltip and legend styling comes from Theme.applyChartDefaults,
 * so none of it is repeated here. Series colours come from Theme.series and
 * Theme.stateColor.
 */

let powerChart = null;
let frequencyChart = null;
let energyComparisonChart = null;
let residencyChart = null;

function destroyChart(chart) {
    if (chart) {
        chart.destroy();
    }
    return null;
}

/* ====================== Energy analysis view ========================== */

function renderEnergyCharts(energyData, containerId = 'energyCharts') {
    const container = document.getElementById(containerId);
    if (!container) return;

    const params = energyData.parameters || {};
    const residency = energyData.frequency_residency || {};

    let html = '';

    // --- headline figures ---------------------------------------------
    html += '<div class="metrics-grid">';
    const cards = [
        ['fa-bolt', 'total energy', energyData.total_energy, 'energy units',
         Theme.series.energy],
        ['fa-fire', 'busy energy', energyData.busy_energy, 'executing',
         Theme.palette.red],
        ['fa-moon', 'idle energy', energyData.idle_energy, 'clock-gated',
         Theme.palette.grey],
        ['fa-right-left', 'switch energy', energyData.context_switch_energy,
         'context switches', Theme.palette.magenta],
        ['fa-gauge-high', 'clock-change energy', energyData.freq_switch_energy,
         energyData.frequency_switches + ' transitions', Theme.palette.yellow],
        ['fa-tachometer-alt', 'avg power', energyData.avg_power,
         'watts (model)', Theme.palette.green]
    ];
    cards.forEach(([icon, label, value, unit, color]) => {
        html += `
            <div class="metric-card">
                <div class="metric-label"><i class="fas ${icon}"></i> ${label}</div>
                <div class="metric-value" style="color:${color}">${fmt(value)}</div>
                <div class="metric-unit">${unit}</div>
            </div>
        `;
    });
    html += '</div>';

    // --- energy-delay -------------------------------------------------
    if (energyData.edp !== undefined) {
        html += '<div class="note">';
        html += '<b>energy-delay:</b> EDP ' + fmt(energyData.edp)
             + ' &middot; ED&sup2;P ' + fmt(energyData.ed2p)
             + ' &middot; ' + fmt(energyData.energy_per_process)
             + ' energy units per process. ';
        html += 'EDP weights energy and delay equally; ED&sup2;P penalises '
             + 'delay harder, so it favours finishing sooner even at some '
             + 'energy cost.';
        html += '</div>';
    }

    // --- where the time went ------------------------------------------
    html += '<div class="card"><div class="card-header"><h2>clock residency</h2></div>';
    html += '<div class="card-body">';
    html += '<p class="prompt">share of <b>busy</b> time spent in each frequency state</p>';
    html += '<div class="table-wrapper"><table><thead><tr>'
         + '<th>state</th><th class="num">GHz</th><th class="num">power</th>'
         + '<th class="num">by busy time</th><th class="num">by work done</th>'
         + '<th class="num">energy</th><th></th></tr></thead><tbody>';

    ['HIGH', 'MED', 'LOW'].forEach(state => {
        const share = residency[state] || 0;
        const byWork = (energyData.residency_by_work || {})[state] || 0;
        const energy = (energyData.energy_by_state || {})[state] || 0;
        const ghzKey = 'freq_' + state.toLowerCase() + '_ghz';
        const powerKey = 'power_' + state.toLowerCase();
        const bars = Math.round(share * 30);
        html += '<tr>'
             + `<td><span class="badge ${state}">${state}</span></td>`
             + `<td class="num">${fmt(params[ghzKey])}</td>`
             + `<td class="num">${fmt(params[powerKey])} W</td>`
             + `<td class="num">${(share * 100).toFixed(1)}%</td>`
             + `<td class="num">${(byWork * 100).toFixed(1)}%</td>`
             + `<td class="num">${fmt(energy)}</td>`
             + `<td class="text-bar" style="color:${Theme.stateColor(state)}">`
             + '█'.repeat(bars) + '</td>'
             + '</tr>';
    });
    html += '</tbody></table></div>';

    // The two denominators diverge by exactly the time-dilation factors, so
    // stating both makes the stretch visible as a number rather than only as
    // a wider bar on a chart.
    html += '<div class="note">Residency <b>by busy time</b> and <b>by work '
         + 'done</b> differ because slower states take longer to do the same '
         + 'work: 1.5&times; at MED, 2.5&times; at LOW. A state with a bigger '
         + 'share of time than of work is one the CPU was crawling in.</div>';
    html += '</div></div>';

    // --- the model itself ---------------------------------------------
    html += '<div class="energy-params">';
    html += '<h3>dvfs model parameters</h3>';
    const rows = [
        ['power formula', params.power_formula],
        ['reference clock', fmt(params.f_ref_ghz) + ' GHz'],
        ['HIGH', fmt(params.freq_high_ghz) + ' GHz @ ' + fmt(params.volts_high)
                 + ' V = ' + fmt(params.power_high) + ' W'],
        ['MED', fmt(params.freq_med_ghz) + ' GHz @ ' + fmt(params.volts_med)
                + ' V = ' + fmt(params.power_med) + ' W'],
        ['LOW', fmt(params.freq_low_ghz) + ' GHz @ ' + fmt(params.volts_low)
                + ' V = ' + fmt(params.power_low) + ' W'],
        ['idle power', fmt(params.power_idle) + ' W'],
        ['c_eff', fmt(params.c_eff) + ' W per GHz·V²'],
        ['p_static (leakage)', fmt(params.p_static) + ' W'],
        ['context-switch penalty', fmt(params.context_switch_penalty)],
        ['clock-change penalty', fmt(params.freq_switch_penalty)],
        ['governor', energyData.governor || '-'],
        ['util thresholds', fmt(params.util_threshold_high) + ' / '
                            + fmt(params.util_threshold_low)],
        ['window / hysteresis', fmt(params.window_size) + ' / '
                                + fmt(params.hysteresis)]
    ];
    rows.forEach(([label, value]) => {
        html += `<div class="param-item"><span class="param-label">${label}</span>`
             + `<span class="param-value">${value === undefined ? '-' : value}</span></div>`;
    });

    if (params.energy_per_work_unit) {
        html += '<h3 style="margin-top:0.85rem">energy per unit of work</h3>';
        ['HIGH', 'MED', 'LOW'].forEach(state => {
            const dilation = (params.time_dilation || {})[state];
            html += `<div class="param-item"><span class="param-label">${state}`
                 + ` (${fmt(dilation)}× time)</span>`
                 + `<span class="param-value">`
                 + `${fmt(params.energy_per_work_unit[state])}</span></div>`;
        });
    }
    html += '</div>';

    // The interior optimum is the whole reason there is a decision to make,
    // so say it out loud rather than leaving it in a table.
    if (params.energy_per_work_unit) {
        const e = params.energy_per_work_unit;
        const best = ['HIGH', 'MED', 'LOW']
            .reduce((a, b) => (e[a] <= e[b] ? a : b));
        html += '<div class="note warn">Dynamic energy per unit of work falls '
             + 'as V&sup2; when the clock drops, but static energy rises as '
             + '1/f. With this leakage floor the cheapest state is <b>' + best
             + '</b> &mdash; so running as slowly as possible is not the '
             + 'energy-optimal strategy. Sweep <code>p_static</code> to see '
             + 'that optimum move.</div>';
    }

    // --- charts --------------------------------------------------------
    html += '<div class="chart-container"><h3><i class="fas fa-chart-line"></i>'
         + ' power and utilisation over time</h3>'
         + '<canvas id="powerChart"></canvas></div>';
    html += '<div class="chart-container"><h3><i class="fas fa-chart-area"></i>'
         + ' frequency state over time</h3>'
         + '<canvas id="frequencyChart"></canvas></div>';

    container.innerHTML = html;

    setTimeout(() => {
        renderPowerChart(energyData.power_timeline);
        renderFrequencyChart(energyData.frequency_timeline, params);
    }, 60);
}

function renderPowerChart(powerTimeline) {
    const canvas = document.getElementById('powerChart');
    if (!canvas || !powerTimeline || !powerTimeline.length) return;

    powerChart = destroyChart(powerChart);
    powerChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels: powerTimeline.map(p => p.time),
            datasets: [
                {
                    label: 'power (W)',
                    data: powerTimeline.map(p => p.power),
                    borderColor: Theme.series.power,
                    backgroundColor: Theme.alpha(Theme.series.power, 0.12),
                    fill: true,
                    stepped: true,
                    yAxisID: 'y'
                },
                {
                    label: 'utilisation',
                    data: powerTimeline.map(p => p.utilization),
                    borderColor: Theme.series.utilization,
                    backgroundColor: Theme.alpha(Theme.series.utilization, 0.08),
                    fill: true,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: Theme.axis('simulated time'),
                y: Theme.axis('power (W)', {
                    type: 'linear', position: 'left', beginAtZero: true
                }),
                y1: Theme.axis('utilisation', {
                    type: 'linear', position: 'right', min: 0, max: 1.05,
                    grid: { drawOnChartArea: false }
                })
            }
        }
    });
}

function renderFrequencyChart(frequencyTimeline, params) {
    const canvas = document.getElementById('frequencyChart');
    if (!canvas || !frequencyTimeline || !frequencyTimeline.length) return;

    frequencyChart = destroyChart(frequencyChart);

    const states = frequencyTimeline.map(f => f.state);
    const colors = states.map(s => Theme.alpha(Theme.stateColor(s), 0.75));
    const ghz = frequencyTimeline.map(f => f.frequency_ghz);
    const maxGhz = (params && params.freq_high_ghz) || 3.0;

    frequencyChart = new Chart(canvas.getContext('2d'), {
        type: 'bar',
        data: {
            labels: frequencyTimeline.map(f => f.time),
            datasets: [{
                label: 'clock (GHz)',
                // Plotted in GHz rather than the normalised 0..1 ratio, with
                // the axis scaled to the top operating point so nothing clips.
                data: ghz,
                backgroundColor: colors,
                borderColor: states.map(s => Theme.stateColor(s)),
                borderWidth: 1,
                barPercentage: 1,
                categoryPercentage: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    callbacks: {
                        afterLabel: ctx => 'state: ' + states[ctx.dataIndex]
                                    + '  power: '
                                    + frequencyTimeline[ctx.dataIndex].power + ' W'
                    }
                }
            },
            scales: {
                x: Theme.axis('simulated time'),
                y: Theme.axis('clock (GHz)', {
                    beginAtZero: true, max: maxGhz * 1.1
                })
            }
        }
    });
}

/* ====================== Comparison chart ============================== */

function renderComparisonChart(comparisonData, containerId = 'comparisonChart') {
    const container = document.getElementById(containerId);
    if (!container) return;

    const keys = Object.keys(comparisonData)
        .filter(k => k !== '_analysis' && !comparisonData[k].error);

    container.innerHTML = '<div class="chart-container tall">'
        + '<h3><i class="fas fa-chart-column"></i> policy comparison</h3>'
        + '<canvas id="comparisonCanvas"></canvas></div>';

    setTimeout(() => {
        const canvas = document.getElementById('comparisonCanvas');
        if (!canvas) return;

        energyComparisonChart = destroyChart(energyComparisonChart);
        energyComparisonChart = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: keys.map(shortName),
                datasets: [
                    {
                        label: 'total energy',
                        data: keys.map(k => comparisonData[k].total_energy),
                        backgroundColor: Theme.alpha(Theme.series.energy, 0.7),
                        borderColor: Theme.series.energy,
                        yAxisID: 'y'
                    },
                    {
                        label: 'avg turnaround',
                        data: keys.map(k => comparisonData[k].avg_turnaround),
                        backgroundColor: Theme.alpha(Theme.series.turnaround, 0.7),
                        borderColor: Theme.series.turnaround,
                        yAxisID: 'y1'
                    },
                    {
                        label: 'context switches',
                        data: keys.map(k => comparisonData[k].context_switches),
                        backgroundColor: Theme.alpha(Theme.series.switches, 0.7),
                        borderColor: Theme.series.switches,
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: Theme.axis(null),
                    y: Theme.axis('energy units', {
                        type: 'linear', position: 'left', beginAtZero: true
                    }),
                    y1: Theme.axis('time / count', {
                        type: 'linear', position: 'right', beginAtZero: true,
                        grid: { drawOnChartArea: false }
                    })
                }
            }
        });
    }, 60);
}

/** Short labels, so the axis stays legible. */
function shortName(key) {
    const names = {
        fcfs: 'FCFS',
        sjf: 'SJF',
        sjf_non_preemptive: 'SJF',
        sjf_preemptive: 'SRTF',
        srtf: 'SRTF',
        round_robin: 'RR',
        priority: 'PRIO',
        priority_preemptive: 'PRIO-P',
        eah: 'EAH'
    };
    return names[key] || key.toUpperCase().replace(/_/g, ' ');
}
