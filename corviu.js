/**
 * CORVIU JavaScript SDK
 * Change Intelligence Platform for AEC
 * Version: 1.0.0
 */

(function(window) {
    'use strict';

    class CORVIU {
        constructor(config = {}) {
            this.apiUrl = config.apiUrl || 'https://corviu.railway.app';
            this.projectId = config.projectId || null;
            this.apiKey = config.apiKey || null;
            this.ws = null;
            this.listeners = new Map();
            this.debugMode = config.debug || false;
        }

        /**
         * Initialize CORVIU SDK
         */
        async init() {
            this.log('Initializing CORVIU SDK...');
            
            // Verify connection
            try {
                const health = await this.checkHealth();
                if (health.status === 'operational') {
                    this.log('✅ CORVIU connected successfully');
                    
                    // Connect WebSocket if project specified
                    if (this.projectId) {
                        this.connectWebSocket();
                    }
                    
                    return true;
                }
            } catch (error) {
                console.error('Failed to initialize CORVIU:', error);
                return false;
            }
        }

        /**
         * Check API health
         */
        async checkHealth() {
            const response = await fetch(`${this.apiUrl}/health`);
            return await response.json();
        }

        /**
         * Create the CORVIU widget
         */
        embedWidget(containerId, options = {}) {
            const container = document.getElementById(containerId);
            if (!container) {
                console.error(`Container ${containerId} not found`);
                return;
            }

            // Create widget iframe
            const iframe = document.createElement('iframe');
            iframe.src = `${this.apiUrl}/widget?project=${this.projectId}`;
            iframe.style.width = options.width || '100%';
            iframe.style.height = options.height || '600px';
            iframe.style.border = 'none';
            iframe.style.borderRadius = '12px';
            iframe.id = 'corviu-widget';
            
            container.appendChild(iframe);
            
            this.log('Widget embedded successfully');
            return iframe;
        }

        /**
         * Create a minimal digest view
         */
        async createDigest(containerId) {
            const container = document.getElementById(containerId);
            if (!container) {
                console.error(`Container ${containerId} not found`);
                return;
            }

            // Create digest element
            const digest = document.createElement('div');
            digest.className = 'corviu-digest';
            digest.innerHTML = `
                <style>
                    .corviu-digest {
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white;
                        padding: 24px;
                        border-radius: 12px;
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.15);
                    }
                    .corviu-header {
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        margin-bottom: 16px;
                    }
                    .corviu-badge {
                        background: rgba(255,255,255,0.2);
                        padding: 4px 12px;
                        border-radius: 20px;
                        font-size: 12px;
                        font-weight: 600;
                    }
                    .corviu-title {
                        font-size: 20px;
                        font-weight: bold;
                        margin: 0 0 8px 0;
                    }
                    .corviu-summary {
                        font-size: 16px;
                        line-height: 1.5;
                        opacity: 0.95;
                        margin: 12px 0;
                    }
                    .corviu-metrics {
                        display: grid;
                        grid-template-columns: repeat(3, 1fr);
                        gap: 16px;
                        margin-top: 20px;
                        padding-top: 20px;
                        border-top: 1px solid rgba(255,255,255,0.2);
                    }
                    .corviu-metric {
                        text-align: center;
                    }
                    .corviu-metric-value {
                        font-size: 24px;
                        font-weight: bold;
                    }
                    .corviu-metric-label {
                        font-size: 11px;
                        opacity: 0.8;
                        text-transform: uppercase;
                        margin-top: 4px;
                    }
                    .corviu-loading {
                        text-align: center;
                        padding: 40px;
                    }
                </style>
                <div class="corviu-loading">Loading CORVIU digest...</div>
            `;
            
            container.appendChild(digest);
            
            // Load actual data
            await this.refreshDigest(digest);
            
            return digest;
        }

        /**
         * Refresh digest with latest data
         */
        async refreshDigest(digestElement) {
            try {
                const data = await this.getChangeSummary();
                
                if (!digestElement) {
                    digestElement = document.querySelector('.corviu-digest');
                }
                
                if (digestElement) {
                    digestElement.innerHTML = `
                        <div class="corviu-header">
                            <span style="font-size: 14px; opacity: 0.9;">⚡ CORVIU Digest</span>
                            <span class="corviu-badge">Live</span>
                        </div>
                        <div class="corviu-title">${data.total_changes} Changes Detected</div>
                        <div class="corviu-summary">${data.ai_summary}</div>
                        <div class="corviu-metrics">
                            <div class="corviu-metric">
                                <div class="corviu-metric-value">${data.total_changes}</div>
                                <div class="corviu-metric-label">Total Changes</div>
                            </div>
                            <div class="corviu-metric">
                                <div class="corviu-metric-value">${data.critical_changes}</div>
                                <div class="corviu-metric-label">Critical</div>
                            </div>
                            <div class="corviu-metric">
                                <div class="corviu-metric-value">${Math.round(data.total_cost_impact).toLocaleString()}</div>
                                <div class="corviu-metric-label">Cost Impact</div>
                            </div>
                        </div>
                    `;
                }
            } catch (error) {
                console.error('Failed to refresh digest:', error);
                if (digestElement) {
                    digestElement.innerHTML = '<div style="padding: 20px; text-align: center;">Unable to load changes</div>';
                }
            }
        }

        /**
         * Get change summary from API
         */
        async getChangeSummary() {
            if (!this.projectId) {
                throw new Error('Project ID not set');
            }
            
            const response = await fetch(`${this.apiUrl}/api/projects/${this.projectId}/changes`);
            if (!response.ok) {
                throw new Error('Failed to fetch changes');
            }
            
            return await response.json();
        }

        /**
         * Get ROI metrics
         */
        async getROIMetrics() {
            if (!this.projectId) {
                throw new Error('Project ID not set');
            }
            
            const response = await fetch(`${this.apiUrl}/api/projects/${this.projectId}/roi`);
            return await response.json();
        }

        /**
         * Connect to Autodesk
         */
        connectAutodesk() {
            window.location.href = `${this.apiUrl}/auth/login`;
        }

        /**
         * Subscribe to real-time events
         */
        on(event, callback) {
            if (!this.listeners.has(event)) {
                this.listeners.set(event, []);
            }
            this.listeners.get(event).push(callback);
        }

        /**
         * Emit event to listeners
         */
        emit(event, data) {
            const callbacks = this.listeners.get(event) || [];
            callbacks.forEach(cb => cb(data));
        }

        /**
         * Connect WebSocket for real-time updates
         */
        connectWebSocket() {
            if (!this.projectId) return;
            
            const wsUrl = this.apiUrl.replace('http', 'ws') + `/ws/${this.projectId}`;
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                this.log('WebSocket connected');
                this.emit('connected', {});
            };
            
            this.ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                this.emit('change', data);
                
                // Auto-refresh digest if exists
                const digest = document.querySelector('.corviu-digest');
                if (digest) {
                    this.refreshDigest(digest);
                }
            };
            
            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.emit('error', error);
            };
            
            this.ws.onclose = () => {
                this.log('WebSocket disconnected, reconnecting...');
                setTimeout(() => this.connectWebSocket(), 5000);
            };
        }

        /**
         * Create a demo project with sample data
         */
        async createDemo() {
            const response = await fetch(`${this.apiUrl}/api/demo/seed`, {
                method: 'POST'
            });
            const data = await response.json();
            
            if (data.success) {
                this.projectId = data.project_id;
                this.log(`Demo project created: ${data.project_id}`);
                return data;
            }
            
            throw new Error('Failed to create demo');
        }

        /**
         * Utility: Log messages in debug mode
         */
        log(message) {
            if (this.debugMode) {
                console.log(`[CORVIU] ${message}`);
            }
        }
    }

    // Auto-initialize from script tag attributes
    function autoInit() {
        const script = document.currentScript || document.querySelector('script[src*="corviu.js"]');
        
        if (script && script.dataset.project) {
            const corviu = new CORVIU({
                projectId: script.dataset.project,
                apiUrl: script.dataset.api || 'https://corviu.railway.app',
                apiKey: script.dataset.key,
                debug: script.dataset.debug === 'true'
            });
            
            // Auto-init on DOM ready
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', () => {
                    corviu.init();
                    
                    // Auto-embed if container specified
                    if (script.dataset.container) {
                        if (script.dataset.widget === 'digest') {
                            corviu.createDigest(script.dataset.container);
                        } else {
                            corviu.embedWidget(script.dataset.container);
                        }
                    }
                });
            } else {
                corviu.init();
            }
            
            // Make available globally
            window.corviu = corviu;
        }
    }

    // Export for different environments
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = CORVIU;
    } else {
        window.CORVIU = CORVIU;
        autoInit();
    }

})(typeof window !== 'undefined' ? window : this);