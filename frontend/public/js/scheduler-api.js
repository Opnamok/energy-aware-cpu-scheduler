/**
 * API Communication Module
 * Handles all backend API calls
 */

/**
 * Backend URL resolution.
 *
 * The FastAPI server mounts this frontend as static files, so in the normal
 * case (`uvicorn server:app --port 8000`) the API lives on the same origin and
 * an empty base is exactly right. A split deployment -- static frontend on one
 * host, API on another -- sets `window.ENERGIX_API_BASE` in the page instead.
 */
const API_BASE_URL = (function resolveApiBase() {
    if (typeof window !== 'undefined' && window.ENERGIX_API_BASE) {
        return String(window.ENERGIX_API_BASE).replace(/\/+$/, '');
    }
    return '';
})();

const API = {
    /**
     * Run scheduling algorithm
     */
    async runScheduler(algorithm, processes, quantum = 2, threshold = null,
                       options = {}) {
        try {
            const response = await fetch(`${API_BASE_URL}/api/all`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(Object.assign({
                    algorithm,
                    processes,
                    quantum: parseInt(quantum),
                    threshold: threshold ? parseFloat(threshold) : null
                }, options))
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || error.error || 'API request failed');
            }

            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    },

    /**
     * Compare all algorithms
     */
    async compareAlgorithms(processes, quantum = 2, taskThreshold = null,
                            options = {}) {
        try {
            const payload = Object.assign({
                processes,
                quantum: parseInt(quantum)
            }, options);
            
            if (taskThreshold !== null && taskThreshold !== '') {
                payload.task_threshold = parseFloat(taskThreshold);
            }
            
            const response = await fetch(`${API_BASE_URL}/api/compare`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || error.error || 'API request failed');
            }

            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    },

    /**
     * Health check
     */
    async healthCheck() {
        try {
            const response = await fetch(`${API_BASE_URL}/api/health`);
            return await response.json();
        } catch (error) {
            console.error('Health check failed:', error);
            return { status: 'error' };
        }
    },

    /**
     * Run multi-core simulation
     */
    async runMulticore(config) {
        try {
            const response = await fetch(`${API_BASE_URL}/api/multicore`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(config)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Multi-core simulation failed');
            }

            return await response.json();
        } catch (error) {
            console.error('Multi-core API Error:', error);
            throw error;
        }
    },

    /**
     * Shared helper for the analysis endpoints.
     */
    async _post(path, payload) {
        const response = await fetch(`${API_BASE_URL}${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || error.error || `${path} failed`);
        }
        return response.json();
    },

    async _get(path) {
        const response = await fetch(`${API_BASE_URL}${path}`);
        if (!response.ok) {
            throw new Error(`${path} failed (${response.status})`);
        }
        return response.json();
    },

    /** The energy model and EAH weights, with their defaults. */
    getParameters() {
        return this._get('/api/parameters');
    },

    /** Available frequency governors. */
    getGovernors() {
        return this._get('/api/governors');
    },

    /** Repeated seeded trials: mean +/- standard deviation per metric. */
    runExperiment(payload) {
        return this._post('/api/experiment', payload);
    },

    /** Sweep one or more parameters. */
    runSweep(payload) {
        return this._post('/api/sweep', payload);
    },

    /** Energy-delay products and the Pareto frontier. */
    runEnergyDelay(payload) {
        return this._post('/api/energy_delay', payload);
    },

    /** Per-process detail, distributions and residency. */
    runDrilldown(payload) {
        return this._post('/api/drilldown', payload);
    }
};
