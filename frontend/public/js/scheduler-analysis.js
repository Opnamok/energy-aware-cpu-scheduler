/**
 * The deeper analysis views: repeated trials, parameter sweeps, the
 * energy-vs-turnaround Pareto frontier, the normalised radar and the
 * per-process drill-down.
 *
 * Kept separate from scheduler-main.js, which is already 2500 lines.
 */

let sweepChart = null;
let paretoChart = null;
let radarChart = null;
let trialsChart = null;

/* ===================== Repeated trials ================================= */

function renderTrials(data, containerId = 'trialsContent') {
    const container = document.getElementById(containerId);
    if (!container) return;

    const metrics = ['total_energy', 'avg_turnaround', 'avg_waiting',
                     'total_completion', 'context_switches', 'edp'];
    const labels = {
        total_energy: 'energy',
        avg_turnaround: 'turnaround',
        avg_waiting: 'waiting',
        total_completion: 'completion',
        context_switches: 'switches',
        edp: 'EDP'
    };
    const keys = Object.keys(data.results);

    let html = '';

    const summary = data.workload_summary || {};
    html += '<p class="prompt">'
         + `experiment --trials=${data.trials} --seed=${data.seed} `
         + `--governor=${data.governor}</p>`;
    html += '<div class="note">'
         + `${data.trials} random workloads, averaging `
         + `<b>${summary.mean_processes}</b> processes and `
         + `<b>${summary.mean_total_work}</b> units of work each `
         + `(offered load ${summary.mean_offered_load}). `
         + `Completed in ${data.elapsed_ms} ms.</div>`;

    // --- mean +/- sd table --------------------------------------------
    html += '<div class="card"><div class="card-header">'
         + '<h2>mean &plusmn; standard deviation</h2></div><div class="card-body">';
    html += '<div class="table-wrapper"><table class="stat-table"><thead><tr><th>policy</th>';
    metrics.forEach(m => { html += `<th class="num">${labels[m]}</th>`; });
    html += '</tr></thead><tbody>';

    const bests = {};
    metrics.forEach(m => {
        bests[m] = Math.min(...keys.map(k => data.results[k].metrics[m].mean));
    });

    keys.forEach(key => {
        html += `<tr><td>${shortName(key)}</td>`;
        metrics.forEach(m => {
            const st = data.results[key].metrics[m];
            const isBest = Math.abs(st.mean - bests[m]) < 1e-9;
            html += `<td class="num ${isBest ? 'better' : ''}">`
                 + `<span class="mean">${round2(st.mean)}</span>`
                 + `<span class="sd"> &plusmn;${round2(st.std)}</span></td>`;
        });
        html += '</tr>';
    });
    html += '</tbody></table></div>';
    html += '</div></div>';

    // --- paired comparison --------------------------------------------
    const pairwise = data.pairwise_vs || {};
    const comparisons = pairwise.comparisons || {};
    if (Object.keys(comparisons).length) {
        html += '<div class="card"><div class="card-header">'
             + `<h2>paired difference vs ${shortName(pairwise.baseline)}</h2>`
             + '</div><div class="card-body">';
        html += '<div class="note info">Each trial gives every policy the '
             + '<b>same</b> workload, so these differences are not polluted by '
             + 'workload variation. That matters: the per-policy spread above '
             + 'is far larger than the differences between policies, and '
             + 'comparing independent averages would bury a real effect in '
             + 'noise. A 95% confidence interval that excludes zero is a '
             + 'result you can rely on.</div>';
        html += '<div class="table-wrapper"><table class="stat-table"><thead><tr>'
             + '<th>policy</th><th class="num">energy</th><th class="num">95% CI</th>'
             + '<th class="num">wins</th><th class="num">turnaround</th>'
             + '<th class="num">95% CI</th><th></th></tr></thead><tbody>';

        Object.keys(comparisons).forEach(key => {
            const e = comparisons[key].total_energy;
            const t = comparisons[key].avg_turnaround;
            if (!e || !t) return;
            const trials = e.wins + e.losses + e.ties;
            // Significant only when the interval excludes zero outright.
            // Identical policies give [0, 0], which is the opposite of a
            // result and must not be labelled as one.
            const lo = e.ci95_delta_pct[0];
            const hi = e.ci95_delta_pct[1];
            const solid = (lo > 0 && hi > 0) || (lo < 0 && hi < 0);
            const identical = lo === 0 && hi === 0;
            html += `<tr><td>${shortName(key)}</td>`
                 + `<td class="num ${e.mean_delta_pct < 0 ? 'better' : 'worse'}">`
                 + `${signed(round2(e.mean_delta_pct))}%</td>`
                 + `<td class="num sd">[${round2(lo)}, ${round2(hi)}]</td>`
                 + `<td class="num">${e.wins}/${trials}</td>`
                 + `<td class="num ${t.mean_delta_pct < 0 ? 'better' : 'worse'}">`
                 + `${signed(round2(t.mean_delta_pct))}%</td>`
                 + `<td class="num sd">[${round2(t.ci95_delta_pct[0])}, `
                 + `${round2(t.ci95_delta_pct[1])}]</td>`
                 + '<td>' + (identical
                        ? '<span class="badge idle">no difference</span>'
                        : solid ? '<span class="badge ok">significant</span>'
                                : '<span class="badge warn">inconclusive</span>')
                 + '</td>'
                 + '</tr>';
        });
        html += '</tbody></table></div></div></div>';
    }

    html += '<div class="chart-container tall">'
         + '<h3><i class="fas fa-chart-column"></i> energy, mean with '
         + 'standard deviation</h3><canvas id="trialsCanvas"></canvas></div>';

    container.innerHTML = html;

    setTimeout(() => renderTrialsChart(data, keys), 60);
}

function renderTrialsChart(data, keys) {
    const canvas = document.getElementById('trialsCanvas');
    if (!canvas) return;

    trialsChart = destroyChart(trialsChart);
    const means = keys.map(k => data.results[k].metrics.total_energy.mean);
    const sds = keys.map(k => data.results[k].metrics.total_energy.std);

    trialsChart = new Chart(canvas.getContext('2d'), {
        type: 'bar',
        data: {
            labels: keys.map(shortName),
            datasets: [
                {
                    label: 'mean energy',
                    data: means,
                    backgroundColor: Theme.alpha(Theme.series.energy, 0.7),
                    borderColor: Theme.series.energy
                },
                {
                    label: 'mean + 1 sd',
                    type: 'line',
                    data: means.map((m, i) => m + sds[i]),
                    borderColor: Theme.alpha(Theme.palette.fgFaint, 0.9),
                    borderDash: [3, 3],
                    pointStyle: 'line',
                    fill: false
                },
                {
                    label: 'mean - 1 sd',
                    type: 'line',
                    data: means.map((m, i) => m - sds[i]),
                    borderColor: Theme.alpha(Theme.palette.fgFaint, 0.9),
                    borderDash: [3, 3],
                    pointStyle: 'line',
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: Theme.axis(null),
                y: Theme.axis('energy units', { beginAtZero: false })
            }
        }
    });
}

/* ===================== Parameter sweep ================================ */

function renderSweep(data, metric, containerId = 'sweepContent') {
    const container = document.getElementById(containerId);
    if (!container) return;

    const series = data.series[0];
    if (!series) {
        container.innerHTML = '<div class="empty-state"><p>nothing swept</p></div>';
        return;
    }

    let html = '';
    html += `<p class="prompt">sweep --param=${series.param} `
         + `--metric=${metric} --workloads=${data.trials_per_point} `
         + `--seed=${data.seed}</p>`;
    html += `<div class="note">${series.label}. `
         + (series.global
            ? 'This parameter affects every policy.'
            : 'Only <b>' + series.affects.map(shortName).join(', ')
              + '</b> responds to it; the other lines are flat on purpose, '
              + 'as a reference.')
         + ` Each point averages ${data.trials_per_point} random workloads `
         + `(${data.elapsed_ms} ms).</div>`;

    html += '<div class="chart-container tall">'
         + `<h3><i class="fas fa-chart-line"></i> ${metric} vs ${series.param}</h3>`
         + '<canvas id="sweepCanvas"></canvas></div>';

    // The numbers as well as the picture: a sweep is usually read for its
    // shape, but the values are what end up quoted in a report.
    const algos = Object.keys(series.points[0].algorithms || {});
    html += '<div class="card"><div class="card-header"><h2>sweep values</h2></div>';
    html += '<div class="card-body"><div class="table-wrapper"><table><thead><tr>';
    html += `<th>${series.param}</th>`;
    algos.forEach(a => { html += `<th class="num">${shortName(a)}</th>`; });
    html += '</tr></thead><tbody>';
    series.points.forEach(point => {
        html += `<tr><td>${point.value}</td>`;
        algos.forEach(a => {
            const st = (point.algorithms[a] || {})[metric];
            html += `<td class="num">${st ? round2(st.mean) : '-'}`
                 + (st && st.std ? `<span class="sd"> &plusmn;${round2(st.std)}</span>` : '')
                 + '</td>';
        });
        html += '</tr>';
    });
    html += '</tbody></table></div></div></div>';

    container.innerHTML = html;

    setTimeout(() => renderSweepChart(series, metric, algos), 60);
}

function renderSweepChart(series, metric, algos) {
    const canvas = document.getElementById('sweepCanvas');
    if (!canvas) return;

    sweepChart = destroyChart(sweepChart);

    const colors = [Theme.palette.green, Theme.palette.cyan,
                    Theme.palette.magenta, Theme.palette.amber,
                    Theme.palette.blue, Theme.palette.red];

    sweepChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels: series.points.map(p => p.value),
            datasets: algos.map((algo, i) => {
                const affected = series.global
                                 || series.affects.indexOf(algo) !== -1;
                return {
                    label: shortName(algo) + (affected ? '' : ' (flat)'),
                    data: series.points.map(p => {
                        const st = (p.algorithms[algo] || {})[metric];
                        return st ? st.mean : null;
                    }),
                    borderColor: affected ? colors[i % colors.length]
                                          : Theme.alpha(Theme.palette.fgFaint, 0.5),
                    backgroundColor: 'transparent',
                    borderWidth: affected ? 2 : 1,
                    borderDash: affected ? [] : [2, 3],
                    pointRadius: affected ? 3 : 0
                };
            })
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: Theme.axis(series.label),
                y: Theme.axis(metric, { beginAtZero: false })
            }
        }
    });
}

/* ===================== Pareto frontier ================================ */

function renderPareto(analysis, containerId = 'paretoContent') {
    const container = document.getElementById(containerId);
    if (!container || !analysis) return;

    const points = analysis.points || [];
    const frontier = analysis.pareto_frontier || [];

    let html = '';
    html += '<div class="card"><div class="card-header">'
         + '<h2>energy vs turnaround &mdash; pareto frontier</h2>'
         + '</div><div class="card-body">';

    html += '<div class="note info">A policy is on the <b>frontier</b> when '
         + 'nothing else beats it on both energy and turnaround at once. '
         + 'Several policies can share it, and that is the point: choosing '
         + 'between them is the trade-off, not a tie to be broken. A single '
         + 'weighted score would hide that choice inside its weights.</div>';

    if (frontier.length) {
        html += `<p class="prompt">frontier: <b>`
             + frontier.map(shortName).join(', ') + '</b>'
             + (analysis.knee ? ` &middot; most balanced: <b>${shortName(analysis.knee)}</b>` : '')
             + '</p>';
    }

    html += '<div class="chart-container tall">'
         + '<canvas id="paretoCanvas"></canvas></div>';

    html += '<div class="table-wrapper"><table><thead><tr>'
         + '<th>policy</th><th class="num">energy</th><th class="num">turnaround</th>'
         + '<th class="num">EDP</th><th class="num">ED&sup2;P</th>'
         + '<th class="num">rank</th><th>status</th></tr></thead><tbody>';

    points.filter(p => !p.error).forEach(p => {
        const onFrontier = p.non_dominated;
        html += `<tr><td style="color:${onFrontier ? Theme.palette.accent : 'inherit'}">`
             + `${shortName(p.key)}</td>`
             + `<td class="num">${p.total_energy}</td>`
             + `<td class="num">${p.avg_turnaround}</td>`
             + `<td class="num">${p.edp}</td>`
             + `<td class="num">${p.ed2p}</td>`
             + `<td class="num">${p.pareto_rank}</td>`
             + '<td>' + (onFrontier
                ? '<span class="badge ok">frontier</span>'
                : `<span class="badge warn">beaten by `
                  + p.dominated_by.map(shortName).join(', ') + '</span>')
             + '</td></tr>';
    });
    html += '</tbody></table></div>';
    html += '</div></div>';

    html += '<div class="chart-container tall">'
         + '<h3><i class="fas fa-radar"></i> normalised profile '
         + '(1.0 = best observed)</h3>'
         + '<canvas id="radarCanvas"></canvas></div>';

    container.innerHTML = html;

    setTimeout(() => {
        renderParetoChart(points, frontier, analysis.knee);
        if (analysis.radar) renderRadarChart(analysis.radar);
    }, 60);
}

function renderParetoChart(points, frontier, knee) {
    const canvas = document.getElementById('paretoCanvas');
    if (!canvas) return;

    paretoChart = destroyChart(paretoChart);
    const valid = points.filter(p => !p.error);

    // Two datasets so the frontier reads differently from the dominated set.
    const onFrontier = valid.filter(p => p.non_dominated);
    const dominated = valid.filter(p => !p.non_dominated);

    const toXY = p => ({ x: p.avg_turnaround, y: p.total_energy, label: p.key });

    paretoChart = new Chart(canvas.getContext('2d'), {
        type: 'scatter',
        data: {
            datasets: [
                {
                    label: 'on the frontier',
                    data: onFrontier.map(toXY),
                    backgroundColor: Theme.palette.accent,
                    borderColor: Theme.palette.accent,
                    pointRadius: 7,
                    pointStyle: 'rectRot',
                    showLine: true,
                    borderWidth: 1,
                    borderDash: [4, 4],
                    fill: false
                },
                {
                    label: 'dominated',
                    data: dominated.map(toXY),
                    backgroundColor: Theme.alpha(Theme.palette.fgFaint, 0.8),
                    borderColor: Theme.palette.fgFaint,
                    pointRadius: 5,
                    pointStyle: 'crossRot'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const p = ctx.raw;
                            return `${shortName(p.label)}: turnaround ${p.x}, `
                                 + `energy ${p.y}`
                                 + (p.label === knee ? '  (most balanced)' : '');
                        }
                    }
                }
            },
            scales: {
                x: Theme.axis('avg turnaround (lower is better)'),
                y: Theme.axis('total energy (lower is better)')
            }
        }
    });
}

function renderRadarChart(radar) {
    const canvas = document.getElementById('radarCanvas');
    if (!canvas) return;

    radarChart = destroyChart(radarChart);
    const colors = [Theme.palette.green, Theme.palette.cyan,
                    Theme.palette.magenta, Theme.palette.amber,
                    Theme.palette.blue, Theme.palette.red];

    radarChart = new Chart(canvas.getContext('2d'), {
        type: 'radar',
        data: {
            labels: radar.metrics.map(m => m.replace(/_/g, ' ')),
            datasets: radar.series.map((s, i) => ({
                label: shortName(s.key),
                data: s.scores,
                borderColor: colors[i % colors.length],
                backgroundColor: Theme.alpha(colors[i % colors.length], 0.08),
                borderWidth: 1.5,
                pointRadius: 2
            }))
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                r: {
                    min: 0,
                    max: 1,
                    angleLines: { color: Theme.palette.border },
                    grid: { color: Theme.palette.border },
                    pointLabels: {
                        color: Theme.palette.fgDim,
                        font: { family: Theme.mono, size: 10 }
                    },
                    ticks: {
                        color: Theme.palette.fgFaint,
                        backdropColor: 'transparent',
                        font: { family: Theme.mono, size: 9 }
                    }
                }
            }
        }
    });
}

/* ===================== Drill-down ===================================== */

function renderDrilldown(data, containerId = 'drilldownContent') {
    const container = document.getElementById(containerId);
    if (!container) return;

    const starve = data.starvation || {};
    const residency = data.frequency_residency || {};
    const breakdown = data.energy_breakdown || {};

    let html = '';
    html += '<div class="card"><div class="card-header">'
         + '<h2>drill-down</h2></div><div class="card-body">';
    html += `<p class="prompt">drilldown <b>"${data.algorithm}"</b> `
         + `--governor=${data.governor}</p>`;

    // --- starvation ----------------------------------------------------
    html += '<div class="note ' + (starve.any_starved ? 'warn' : 'good') + '">';
    if (starve.any_starved) {
        html += `<b>starvation detected:</b> P${starve.starved_pids.join(', P')}. `;
    } else {
        html += '<b>no starvation.</b> ';
    }
    html += `Longest wait ${starve.max_wait} time units (P${starve.max_wait_pid}); `
         + `worst slowdown ${starve.max_normalized_turnaround}&times; `
         + `(P${starve.max_normalized_turnaround_pid}). `
         + `Flagged above ${starve.wait_factor}&times; own execution time or `
         + `${starve.ntat_factor}&times; slowdown.`;
    html += '</div>';

    // --- distributions -------------------------------------------------
    html += '<div class="table-wrapper"><table><thead><tr><th>distribution</th>'
         + '<th class="num">min</th><th class="num">p25</th>'
         + '<th class="num">median</th><th class="num">p75</th>'
         + '<th class="num">max</th><th class="num">mean</th>'
         + '<th class="num">sd</th><th>shape</th></tr></thead><tbody>';
    [['waiting', data.waiting_distribution],
     ['response', data.response_distribution],
     ['turnaround', data.turnaround_distribution]].forEach(([label, dist]) => {
        if (!dist) return;
        html += `<tr><td>${label}</td>`
             + `<td class="num">${dist.min}</td><td class="num">${dist.p25}</td>`
             + `<td class="num">${dist.median}</td><td class="num">${dist.p75}</td>`
             + `<td class="num">${dist.max}</td><td class="num">${dist.mean}</td>`
             + `<td class="num sd">${dist.std}</td>`
             + `<td>${histogram(dist.histogram)}</td></tr>`;
    });
    html += '</tbody></table></div>';

    // --- energy breakdown ---------------------------------------------
    html += '<h4 style="margin-top:1rem;font-size:0.78rem;color:var(--text-primary)">'
         + 'where the energy went</h4>';
    html += '<div class="table-wrapper"><table><thead><tr><th>source</th>'
         + '<th class="num">energy</th><th class="num">share</th>'
         + '<th></th></tr></thead><tbody>';
    const total = breakdown.total || 1;
    [['executing', breakdown.busy], ['idle', breakdown.idle],
     ['context switches', breakdown.context_switch],
     ['clock changes', breakdown.frequency_switch]].forEach(([label, value]) => {
        const share = (value || 0) / total;
        html += `<tr><td>${label}</td><td class="num">${fmt(value)}</td>`
             + `<td class="num">${(share * 100).toFixed(1)}%</td>`
             + `<td class="text-bar">${'█'.repeat(Math.round(share * 30))}</td>`
             + '</tr>';
    });
    html += `<tr><td><b>total</b></td><td class="num"><b>${fmt(breakdown.total)}</b></td>`
         + '<td class="num">100%</td><td></td></tr>';
    html += '</tbody></table></div>';

    // --- residency, three ways ----------------------------------------
    html += '<h4 style="margin-top:1rem;font-size:0.78rem;color:var(--text-primary)">'
         + 'clock residency</h4>';
    html += '<div class="table-wrapper"><table><thead><tr><th>state</th>'
         + '<th class="num">by busy time</th><th class="num">by work done</th>'
         + '<th class="num">by wall time</th></tr></thead><tbody>';
    ['HIGH', 'MED', 'LOW'].forEach(state => {
        html += `<tr><td><span class="badge ${state}">${state}</span></td>`
             + `<td class="num">${pct((residency.by_busy_time || {})[state])}</td>`
             + `<td class="num">${pct((residency.by_work || {})[state])}</td>`
             + `<td class="num">${pct((residency.by_wall_time || {})[state])}</td>`
             + '</tr>';
    });
    html += `<tr><td><span class="badge idle">IDLE</span></td>`
         + '<td class="num">-</td><td class="num">-</td>'
         + `<td class="num">${pct((residency.by_wall_time || {}).IDLE)}</td></tr>`;
    html += '</tbody></table></div>';
    html += `<div class="note">${residency.switches} clock change(s). `
         + 'A state whose share of <b>time</b> exceeds its share of <b>work</b> '
         + 'is one the CPU spent longer in than it accomplished in &mdash; '
         + 'that gap is the time dilation from running slower.</div>';

    html += '</div></div>';
    container.innerHTML = html;
}

/* ===================== helpers ======================================== */

function pct(value) {
    if (value === undefined || value === null) return '-';
    return (value * 100).toFixed(1) + '%';
}

/** Two decimals is as much precision as any of these numbers carry. */
function round2(value) {
    if (value === null || value === undefined) return '-';
    const n = Number(value);
    if (Number.isNaN(n)) return String(value);
    return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

function signed(value) {
    return (value > 0 ? '+' : '') + value;
}

/** A sparkline-ish histogram drawn with block characters. */
function histogram(hist) {
    if (!hist || !hist.counts || !hist.counts.length) return '';
    const max = Math.max(...hist.counts) || 1;
    const blocks = ['▁', '▂', '▃', '▅', '▆', '█'];
    return '<span class="text-bar">' + hist.counts.map(c => {
        if (!c) return '·';
        return blocks[Math.min(blocks.length - 1,
                               Math.round((c / max) * (blocks.length - 1)))];
    }).join('') + '</span>';
}
