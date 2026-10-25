/**
 * The single source of truth for colour.
 *
 * Previously the same hex values were written out in roughly a hundred places
 * across the chart, Gantt and main modules, so the CSS custom properties were
 * not actually authoritative and a retheme meant hunting literals. Everything
 * now reads from here, and here reads from the stylesheet -- so changing a
 * token in :root changes the charts too.
 *
 * Must load before every other script.
 */

const Theme = (function () {
    'use strict';

    function token(name, fallback) {
        try {
            const value = getComputedStyle(document.documentElement)
                .getPropertyValue(name).trim();
            return value || fallback;
        } catch (err) {
            return fallback;
        }
    }

    // Fallbacks match :root in scheduler-style.css, so the charts still render
    // sensibly if the stylesheet has not parsed yet.
    const palette = {
        bg: token('--bg-primary', '#06090a'),
        bgAlt: token('--bg-secondary', '#0a1012'),
        panel: token('--bg-card', '#0b1113'),
        panelHover: token('--bg-card-hover', '#121b1d'),
        border: token('--border', '#1d2b2b'),
        borderBright: token('--border-bright', '#2f4a44'),
        fg: token('--text-primary', '#c8e6d0'),
        fgDim: token('--text-secondary', '#7c9a88'),
        fgFaint: token('--text-faint', '#4e6358'),
        accent: token('--accent', '#5ef08a'),
        accentDim: token('--accent-dim', '#2f8a52'),

        green: token('--ansi-green', '#5ef08a'),
        cyan: token('--ansi-cyan', '#4dd4e8'),
        blue: token('--ansi-blue', '#6ba8ff'),
        yellow: token('--ansi-yellow', '#f4e04d'),
        amber: token('--ansi-amber', '#ffb347'),
        red: token('--ansi-red', '#ff6b6b'),
        magenta: token('--ansi-magenta', '#d78bff'),
        grey: token('--ansi-grey', '#5c7068')
    };

    const mono = token('--font-mono',
        "'JetBrains Mono', 'Fira Code', ui-monospace, Consolas, monospace");

    /**
     * Process colours. Deliberately ordered so adjacent PIDs are easy to tell
     * apart, and so none of them is the same hue as a DVFS state badge.
     */
    const processColors = [
        palette.green, palette.cyan, palette.magenta, palette.yellow,
        palette.blue, palette.amber, '#8ef0c8', '#b8a6ff'
    ];

    /**
     * DVFS state colours, keyed by power: hot states read warm, the slow
     * state reads cool, idle recedes. The frequency timeline is the main
     * place this matters.
     */
    const stateColors = {
        HIGH: palette.red,
        MED: palette.amber,
        MEDIUM: palette.amber,
        LOW: palette.cyan,
        IDLE: palette.grey
    };

    /** Series colours for the comparison and analysis charts. */
    const series = {
        energy: palette.amber,
        turnaround: palette.cyan,
        waiting: palette.blue,
        completion: palette.green,
        switches: palette.magenta,
        power: palette.amber,
        utilization: palette.cyan,
        frequency: palette.green,
        edp: palette.yellow
    };

    function processColor(label) {
        if (!label || label === 'IDLE') {
            return palette.grey;
        }
        const digits = String(label).replace(/[^0-9]/g, '');
        const index = digits ? parseInt(digits, 10) : 0;
        return processColors[index % processColors.length];
    }

    function stateColor(state) {
        return stateColors[state] || palette.accent;
    }

    /** Add transparency to a hex colour, for chart fills. */
    function alpha(hex, amount) {
        const clean = String(hex).replace('#', '');
        if (clean.length !== 6) {
            return hex;
        }
        const r = parseInt(clean.slice(0, 2), 16);
        const g = parseInt(clean.slice(2, 4), 16);
        const b = parseInt(clean.slice(4, 6), 16);
        return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + amount + ')';
    }

    /**
     * Teach Chart.js the terminal look once, so no chart has to repeat axis,
     * grid, tooltip and legend styling.
     */
    function applyChartDefaults() {
        if (typeof Chart === 'undefined') {
            return false;
        }
        const d = Chart.defaults;
        d.color = palette.fgDim;
        d.borderColor = palette.border;
        d.font.family = mono;
        d.font.size = 11;

        d.plugins.legend.labels.color = palette.fgDim;
        d.plugins.legend.labels.boxWidth = 10;
        d.plugins.legend.labels.boxHeight = 10;
        d.plugins.legend.labels.font = { family: mono, size: 11 };

        d.plugins.tooltip.backgroundColor = palette.bgAlt;
        d.plugins.tooltip.titleColor = palette.accent;
        d.plugins.tooltip.bodyColor = palette.fg;
        d.plugins.tooltip.borderColor = palette.borderBright;
        d.plugins.tooltip.borderWidth = 1;
        d.plugins.tooltip.cornerRadius = 0;
        d.plugins.tooltip.displayColors = true;
        d.plugins.tooltip.titleFont = { family: mono, size: 11, weight: '600' };
        d.plugins.tooltip.bodyFont = { family: mono, size: 11 };
        d.plugins.tooltip.padding = 8;

        if (d.plugins.title) {
            d.plugins.title.color = palette.fg;
            d.plugins.title.font = { family: mono, size: 13, weight: '600' };
        }

        // Square everything off -- rounded bars and curvy lines fight the
        // character-grid feel.
        if (d.elements) {
            if (d.elements.bar) {
                d.elements.bar.borderRadius = 0;
                d.elements.bar.borderWidth = 1;
            }
            if (d.elements.line) {
                d.elements.line.tension = 0;
                d.elements.line.borderWidth = 1.5;
            }
            if (d.elements.point) {
                d.elements.point.radius = 2;
                d.elements.point.hoverRadius = 4;
                d.elements.point.pointStyle = 'rect';
            }
        }
        return true;
    }

    /** Standard axis styling, so charts stay consistent. */
    function axis(title, extra) {
        const base = {
            title: title ? {
                display: true,
                text: title,
                color: palette.fgDim,
                font: { family: mono, size: 11 }
            } : { display: false },
            ticks: { color: palette.fgFaint, font: { family: mono, size: 10 } },
            grid: {
                color: alpha(palette.border, 0.85),
                tickColor: palette.border,
                drawTicks: true
            },
            border: { color: palette.border }
        };
        return Object.assign(base, extra || {});
    }

    return {
        palette: palette,
        mono: mono,
        processColors: processColors,
        stateColors: stateColors,
        series: series,
        processColor: processColor,
        stateColor: stateColor,
        alpha: alpha,
        axis: axis,
        applyChartDefaults: applyChartDefaults
    };
})();

// Chart.js loads before this file, so defaults can be applied immediately;
// retry on DOM ready in case the CDN was slow.
if (!Theme.applyChartDefaults()) {
    document.addEventListener('DOMContentLoaded', Theme.applyChartDefaults);
}
