/**
 * Gantt chart, frequency ribbon, process table and metric cards.
 *
 * All colour comes from Theme (js/theme.js), which reads the CSS custom
 * properties -- so retheming means editing :root, not hunting hex literals
 * through here.
 */

/** Format a number without trailing zeros: 4 not 4.0, while 4.5 stays 4.5. */
function fmt(value) {
    if (value === null || value === undefined) return '';
    const n = Number(value);
    if (Number.isNaN(n)) return String(value);
    return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function renderGanttChart(gantt, containerId = 'ganttChart') {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!gantt || !gantt.length) {
        container.innerHTML = '<div class="empty-state"><p>no schedule to draw</p></div>';
        return;
    }

    const totalTime = Math.max(...gantt.map(seg => seg.end));

    let html = '<div class="gantt-container">';
    html += '<h3><i class="fas fa-chart-gantt"></i> execution timeline</h3>';
    html += '<div class="gantt-chart">';

    // --- the schedule itself ------------------------------------------
    html += '<div class="gantt-timeline">';
    gantt.forEach(segment => {
        const duration = segment.end - segment.start;
        const widthPercent = (duration / totalTime) * 100;
        const idle = segment.process === 'IDLE';
        const color = Theme.processColor(segment.process);
        const state = segment.freq_state || '';
        const ghz = segment.freq_ghz ? segment.freq_ghz.toFixed(1) + ' GHz' : '';
        const detail = state
            ? `  (${fmt(duration)} time units for ${fmt(segment.work)} work at ${state} / ${ghz})`
            : '';
        const title = idle
            ? `idle: ${fmt(segment.start)} - ${fmt(segment.end)}`
            : `${segment.process}  ${fmt(segment.start)} - ${fmt(segment.end)}${detail}`;

        html += `
            <div class="gantt-segment${idle ? ' idle' : ''}"
                 style="width: ${widthPercent}%; background: ${idle ? 'transparent' : color};"
                 title="${title}">
                <div>${idle ? '~' : segment.process}</div>
                <div style="font-size: 0.62rem; opacity: 0.75;">${fmt(duration)}</div>
            </div>
        `;
    });
    html += '</div>';

    // --- the frequency ribbon -----------------------------------------
    // This is the frequency timeline the report asks for, drawn directly
    // under the schedule so a clock change lines up with the slice that
    // caused it. A wider block means the same work took longer.
    if (gantt.some(seg => seg.freq_state)) {
        html += '<div class="freq-ribbon">';
        gantt.forEach(segment => {
            const widthPercent = ((segment.end - segment.start) / totalTime) * 100;
            const segState = segment.freq_state || 'IDLE';
            const ghz = segment.freq_ghz
                ? ' / ' + segment.freq_ghz.toFixed(1) + ' GHz' : '';
            html += `<div class="freq-ribbon-seg"`
                 + ` style="width:${widthPercent}%;background:${Theme.stateColor(segState)};"`
                 + ` title="${segState}${ghz}"></div>`;
        });
        html += '</div>';

        html += '<div class="ribbon-legend">';
        ['HIGH', 'MED', 'LOW', 'IDLE'].forEach(name => {
            html += `<span><i style="background:${Theme.stateColor(name)}"></i>${name}</span>`;
        });
        html += '</div>';
    }

    // --- time axis ----------------------------------------------------
    html += '<div class="gantt-labels">';
    gantt.forEach(segment => {
        const widthPercent = ((segment.end - segment.start) / totalTime) * 100;
        html += `<div class="gantt-label" style="width: ${widthPercent}%;">${fmt(segment.start)}</div>`;
    });
    html += `<div class="gantt-label" style="width: 0; position: absolute; right: 0;">${fmt(totalTime)}</div>`;
    html += '</div>';

    html += renderGanttAscii(gantt);
    html += '</div></div>';

    container.innerHTML = html;
}

/**
 * A character-cell rendering of the same schedule.
 *
 * Worth having next to the graphical chart: it pastes straight into a report,
 * it survives any screenshot scale, and one row per process makes preemption
 * and time slicing far easier to read than a single stacked bar. The fill
 * character also encodes the clock, so time dilation is visible as a wider
 * run of the same symbol.
 */
function renderGanttAscii(gantt, width = 72) {
    const busy = gantt.filter(seg => seg.process !== 'IDLE');
    if (!busy.length) return '';

    const totalTime = Math.max(...gantt.map(seg => seg.end));
    if (!totalTime) return '';

    const pids = [];
    busy.forEach(seg => {
        if (pids.indexOf(seg.process) === -1) pids.push(seg.process);
    });
    pids.sort((a, b) => parseInt(a.replace('P', ''), 10)
                        - parseInt(b.replace('P', ''), 10));

    const cell = totalTime / width;
    const stateChar = { HIGH: '#', MED: '=', LOW: '-' };
    const rule = '.'.repeat(width);

    let out = '<div class="gantt-ascii"><pre>';
    out += '    t=0' + ' '.repeat(Math.max(1, width - 9))
         + 't=' + fmt(totalTime) + '\n';
    out += '    ' + rule + '\n';

    pids.forEach(pid => {
        let row = '';
        for (let i = 0; i < width; i++) {
            const t = i * cell + cell / 2;
            const seg = gantt.find(x => x.process === pid
                                        && x.start <= t && t < x.end);
            row += seg ? (stateChar[seg.freq_state] || '#') : ' ';
        }
        out += '<span class="row-label">' + (pid + '   ').slice(0, 3)
             + '</span>|' + row + '|\n';
    });

    out += '    ' + rule + '\n';
    out += '\n    # HIGH 3.0GHz     = MED 2.0GHz     - LOW 1.2GHz';
    out += '</pre></div>';
    return out;
}

function renderProcessTable(processes, containerId = 'processDetailsTable') {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!processes || !processes.length) {
        container.innerHTML = '';
        return;
    }

    const first = processes[0];
    const hasPriority = first.priority !== undefined;
    const hasClass = Boolean(first.classification);
    const hasExec = first.exec_time !== undefined;
    const hasResponse = first.response_time !== undefined
                        && first.response_time !== null;

    let html = '<div class="process-detail-table">';
    html += '<h3><i class="fas fa-table"></i> per-process detail</h3>';
    html += '<div class="table-wrapper"><table><thead><tr>';
    html += '<th>pid</th><th class="num">arrival</th><th class="num">work</th>';
    if (hasExec) html += '<th class="num">exec time</th>';
    html += '<th class="num">completion</th><th class="num">turnaround</th>';
    html += '<th class="num">waiting</th>';
    if (hasResponse) html += '<th class="num">response</th>';
    if (hasPriority) html += '<th class="num">priority</th>';
    if (hasClass) html += '<th>class</th>';
    if (hasExec) html += '<th>clock</th>';
    html += '</tr></thead><tbody>';

    processes.forEach(p => {
        html += '<tr>';
        html += `<td style="color:${Theme.processColor('P' + p.pid)}">P${p.pid}</td>`;
        html += `<td class="num">${fmt(p.arrival)}</td>`;
        html += `<td class="num">${fmt(p.burst)}</td>`;
        if (hasExec) html += `<td class="num">${fmt(p.exec_time)}</td>`;
        html += `<td class="num">${fmt(p.completion)}</td>`;
        html += `<td class="num">${fmt(p.turnaround)}</td>`;
        html += `<td class="num">${fmt(p.waiting)}</td>`;
        if (hasResponse) html += `<td class="num">${fmt(p.response_time)}</td>`;
        if (hasPriority) html += `<td class="num">${fmt(p.priority)}</td>`;
        if (hasClass) {
            html += `<td><span class="badge ${p.classification}">${p.classification}</span></td>`;
        }
        if (hasExec) html += `<td>${renderResidency(p.freq_residency)}</td>`;
        html += '</tr>';
    });

    html += '</tbody></table></div></div>';
    container.innerHTML = html;
}

/** Which clocks a process actually ran at, as inline badges. */
function renderResidency(residency) {
    if (!residency) return '';
    return ['HIGH', 'MED', 'LOW']
        .filter(state => residency[state] > 0)
        .map(state => `<span class="badge ${state}">${state} `
                      + `${Math.round(residency[state] * 100)}%</span>`)
        .join(' ') || '<span class="badge idle">-</span>';
}

function renderMetrics(metrics, contextSwitches, containerId = 'metricsDisplay',
                       advanced = null, extra = null) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const cards = [
        ['fa-clock', 'avg turnaround', metrics.avg_turnaround, 'time units'],
        ['fa-hourglass-half', 'avg waiting', metrics.avg_waiting, 'time units'],
        ['fa-flag-checkered', 'completion', metrics.total_completion, 'time units'],
        ['fa-right-left', 'context switches', contextSwitches, 'count']
    ];

    if (extra && extra.frequency_switches !== undefined) {
        cards.push(['fa-gauge-high', 'clock changes', extra.frequency_switches,
                    'count']);
    }
    if (advanced) {
        if (advanced.avg_response_time !== undefined) {
            cards.push(['fa-stopwatch', 'avg response', advanced.avg_response_time,
                        'arrival to first run']);
        }
        if (advanced.cpu_utilization !== undefined) {
            cards.push(['fa-microchip', 'cpu busy', advanced.cpu_utilization + '%',
                        'of wall-clock time']);
        }
        if (advanced.throughput !== undefined) {
            cards.push(['fa-gauge', 'throughput', advanced.throughput,
                        'processes / time unit']);
        }
        if (advanced.fairness_slowdown !== undefined) {
            cards.push(['fa-scale-balanced', 'fairness', advanced.fairness_slowdown,
                        'Jain index over slowdown']);
        }
    }
    if (metrics.threshold) {
        cards.push(['fa-ruler', 'eah threshold', metrics.threshold,
                    'short / long split']);
    }
    if (metrics.short_tasks_count !== undefined) {
        cards.push(['fa-layer-group', 'short / long',
                    metrics.short_tasks_count + ' / ' + metrics.long_tasks_count,
                    'classified tasks']);
    }

    let html = '<div class="metrics-grid">';
    cards.forEach(([icon, label, value, unit]) => {
        html += `
            <div class="metric-card">
                <div class="metric-label"><i class="fas ${icon}"></i> ${label}</div>
                <div class="metric-value">${fmt(value)}</div>
                <div class="metric-unit">${unit}</div>
            </div>
        `;
    });
    html += '</div>';

    container.innerHTML = html;
}
