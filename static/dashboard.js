/**
 * Telegram Bot Dashboard - Interactive JavaScript
 */

class TelegramBotDashboard {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000;
        this.isConnected = false;
        this.lastUpdate = null;
        
        // Chart instances
        this.charts = {};
        
        // Initialize dashboard
        this.init();
    }
    
    async init() {
        console.log('Initializing Telegram Bot Dashboard...');
        
        // Setup event listeners
        this.setupEventListeners();
        
        // Connect WebSocket
        this.connectWebSocket();
        
        // Load initial data
        await this.loadInitialData();
        
        // Setup periodic updates
        this.setupPeriodicUpdates();
        
        // Setup notifications
        this.setupNotifications();
        
        console.log('Dashboard initialized successfully');
    }
    
    setupEventListeners() {
        // Control buttons
        document.getElementById('pauseBtn')?.addEventListener('click', () => this.pauseSystem());
        document.getElementById('resumeBtn')?.addEventListener('click', () => this.resumeSystem());
        document.getElementById('refreshBtn')?.addEventListener('click', () => this.refreshData());
        
        // Add pair form
        document.getElementById('addPairForm')?.addEventListener('submit', (e) => this.handleAddPair(e));
        
        // Delete pair buttons
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('delete-pair-btn')) {
                this.deletePair(e.target.dataset.pairId);
            }
        });
        
        // Theme toggle
        document.getElementById('themeToggle')?.addEventListener('click', () => this.toggleTheme());
        
        // Auto-refresh toggle
        document.getElementById('autoRefreshToggle')?.addEventListener('change', (e) => {
            this.autoRefresh = e.target.checked;
            if (this.autoRefresh) {
                this.setupPeriodicUpdates();
            } else {
                clearInterval(this.refreshInterval);
            }
        });
        
        // Window events
        window.addEventListener('beforeunload', () => this.cleanup());
        window.addEventListener('focus', () => this.handleWindowFocus());
        window.addEventListener('blur', () => this.handleWindowBlur());
    }
    
    connectWebSocket() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            return;
        }
        
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        console.log(`Connecting to WebSocket: ${wsUrl}`);
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.isConnected = true;
            this.reconnectAttempts = 0;
            this.updateConnectionStatus(true);
            
            // Subscribe to updates
            this.sendWebSocketMessage({
                type: 'subscribe',
                subscription: 'all'
            });
        };
        
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleWebSocketMessage(data);
            } catch (error) {
                console.error('Error parsing WebSocket message:', error);
            }
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.isConnected = false;
            this.updateConnectionStatus(false);
            this.attemptReconnect();
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }
    
    attemptReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('Max reconnection attempts reached');
            this.showNotification('Connection lost. Please refresh the page.', 'error');
            return;
        }
        
        this.reconnectAttempts++;
        console.log(`Attempting to reconnect... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
        
        setTimeout(() => {
            this.connectWebSocket();
        }, this.reconnectDelay * this.reconnectAttempts);
    }
    
    sendWebSocketMessage(message) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        }
    }
    
    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'status_update':
                this.updateDashboard(data.data);
                break;
            case 'pong':
                // Heartbeat response
                break;
            case 'error':
                console.error('WebSocket error:', data.message);
                this.showNotification(data.message, 'error');
                break;
            default:
                console.log('Unknown WebSocket message type:', data.type);
        }
    }
    
    updateConnectionStatus(connected) {
        const indicator = document.getElementById('connectionStatus');
        if (indicator) {
            indicator.className = `real-time-indicator ${connected ? 'connected' : 'disconnected'}`;
            indicator.innerHTML = `
                <div class="pulse ${connected ? '' : 'error'}"></div>
                ${connected ? 'Connected' : 'Disconnected'}
            `;
        }
    }
    
    async loadInitialData() {
        try {
            // Load system status
            const status = await this.fetchAPI('/api/status');
            this.updateSystemStatus(status);
            
            // Load statistics
            const stats = await this.fetchAPI('/api/stats');
            this.updateStatistics(stats);
            
            // Load health data
            const health = await this.fetchAPI('/api/health');
            this.updateHealthStatus(health);
            
            // Load pairs
            const pairs = await this.fetchAPI('/api/pairs');
            this.updatePairsTable(pairs);
            
            // Load recent logs
            const logs = await this.fetchAPI('/api/logs?limit=20');
            this.updateLogViewer(logs);
            
        } catch (error) {
            console.error('Error loading initial data:', error);
            this.showNotification('Failed to load dashboard data', 'error');
        }
    }
    
    async fetchAPI(endpoint) {
        const response = await fetch(endpoint);
        if (!response.ok) {
            throw new Error(`API request failed: ${response.status}`);
        }
        return await response.json();
    }
    
    async postAPI(endpoint, data) {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            throw new Error(`API request failed: ${response.status}`);
        }
        
        return await response.json();
    }
    
    async deleteAPI(endpoint) {
        const response = await fetch(endpoint, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            throw new Error(`API request failed: ${response.status}`);
        }
        
        return await response.json();
    }
    
    updateDashboard(data) {
        this.lastUpdate = new Date();
        
        if (data.running !== undefined) {
            this.updateSystemStatus(data);
        }
        
        if (data.health) {
            this.updateHealthStatus(data.health);
        }
        
        if (data.bot_metrics) {
            this.updateBotMetrics(data.bot_metrics);
        }
        
        if (data.queue_size !== undefined) {
            this.updateQueueStatus(data.queue_size);
        }
        
        // Update last update time
        this.updateLastUpdateTime();
    }
    
    updateSystemStatus(status) {
        // Update system status indicator
        const statusElement = document.querySelector('.system-status .status-indicator');
        if (statusElement) {
            statusElement.className = 'status-indicator';
            if (status.paused) {
                statusElement.classList.add('paused');
                statusElement.innerHTML = '<i data-feather="pause"></i> Paused';
            } else if (status.running) {
                statusElement.classList.add('running');
                statusElement.innerHTML = '<i data-feather="play"></i> Running';
            } else {
                statusElement.classList.add('error');
                statusElement.innerHTML = '<i data-feather="alert-circle"></i> Stopped';
            }
        }
        
        // Update control buttons
        const pauseBtn = document.getElementById('pauseBtn');
        const resumeBtn = document.getElementById('resumeBtn');
        
        if (pauseBtn && resumeBtn) {
            if (status.paused) {
                pauseBtn.style.display = 'none';
                resumeBtn.style.display = 'inline-flex';
            } else {
                pauseBtn.style.display = 'inline-flex';
                resumeBtn.style.display = 'none';
            }
        }
    }
    
    updateStatistics(stats) {
        // Update metric cards
        this.updateMetricCard('totalMessages', stats.total_messages || 0);
        this.updateMetricCard('messages24h', stats.messages_24h || 0);
        this.updateMetricCard('totalPairs', stats.total_pairs || 0);
        this.updateMetricCard('activePairs', stats.active_pairs || 0);
        this.updateMetricCard('errors24h', stats.errors_24h || 0);
        this.updateMetricCard('databaseSize', `${stats.database_size_mb || 0} MB`);
    }
    
    updateMetricCard(id, value) {
        const element = document.getElementById(id);
        if (element) {
            const valueElement = element.querySelector('.metric-value');
            if (valueElement) {
                const oldValue = parseInt(valueElement.textContent) || 0;
                valueElement.textContent = typeof value === 'number' ? value.toLocaleString() : value;
                
                // Add change indicator for numeric values
                if (typeof value === 'number' && oldValue !== value) {
                    const changeElement = element.querySelector('.metric-change');
                    if (changeElement) {
                        const change = value - oldValue;
                        changeElement.textContent = change > 0 ? `+${change}` : change.toString();
                        changeElement.className = `metric-change ${change > 0 ? 'positive' : 'negative'}`;
                    }
                }
            }
        }
    }
    
    updateHealthStatus(health) {
        // Update overall health status
        const healthStatusElement = document.querySelector('.health-status');
        if (healthStatusElement) {
            const iconElement = healthStatusElement.querySelector('.health-icon');
            const textElement = healthStatusElement.querySelector('.health-text');
            
            if (iconElement && textElement) {
                iconElement.className = `health-icon ${health.status}`;
                iconElement.innerHTML = this.getHealthIcon(health.status);
                textElement.textContent = health.status.charAt(0).toUpperCase() + health.status.slice(1);
            }
        }
        
        // Update health metrics
        if (health.metrics) {
            Object.entries(health.metrics).forEach(([key, metric]) => {
                this.updateHealthMetric(key, metric);
            });
        }
        
        // Update alerts
        this.updateAlerts(health.alerts || []);
        
        // Update uptime
        if (health.uptime_formatted) {
            const uptimeElement = document.getElementById('uptime');
            if (uptimeElement) {
                uptimeElement.textContent = health.uptime_formatted;
            }
        }
    }
    
    updateHealthMetric(key, metric) {
        const element = document.getElementById(`metric-${key}`);
        if (element) {
            const valueElement = element.querySelector('.health-metric-value');
            const labelElement = element.querySelector('.health-metric-label');
            
            if (valueElement) {
                valueElement.textContent = `${metric.value}${metric.unit || ''}`;
                valueElement.className = `health-metric-value ${metric.status}`;
            }
            
            if (labelElement) {
                labelElement.textContent = metric.name;
            }
        }
    }
    
    updateBotMetrics(botMetrics) {
        const botListElement = document.querySelector('.bot-list');
        if (!botListElement) return;
        
        botListElement.innerHTML = '';
        
        Object.entries(botMetrics).forEach(([botIndex, metrics]) => {
            const botItem = document.createElement('div');
            botItem.className = 'bot-item';
            
            const statusClass = metrics.consecutive_failures > 0 ? 'error' : 'success';
            
            botItem.innerHTML = `
                <div class="bot-info">
                    <div class="bot-status-dot ${statusClass}"></div>
                    <span>Bot ${botIndex}</span>
                </div>
                <div class="bot-metrics">
                    <span>Processed: ${metrics.messages_processed.toLocaleString()}</span>
                    <span>Success: ${(metrics.success_rate * 100).toFixed(1)}%</span>
                    <span>Load: ${metrics.current_load}</span>
                    <span>Failures: ${metrics.consecutive_failures}</span>
                </div>
            `;
            
            botListElement.appendChild(botItem);
        });
    }
    
    updateQueueStatus(queueSize) {
        const queueElement = document.getElementById('queueSize');
        if (queueElement) {
            queueElement.textContent = queueSize.toLocaleString();
        }
        
        // Update queue progress bar
        const progressBar = document.getElementById('queueProgress');
        if (progressBar) {
            const maxQueue = 1000; // This should come from config
            const percentage = Math.min((queueSize / maxQueue) * 100, 100);
            progressBar.style.width = `${percentage}%`;
            
            // Change color based on queue size
            progressBar.className = 'progress-bar';
            if (percentage > 80) {
                progressBar.classList.add('danger');
            } else if (percentage > 60) {
                progressBar.classList.add('warning');
            } else {
                progressBar.classList.add('success');
            }
        }
    }
    
    updatePairsTable(pairs) {
        const tableBody = document.querySelector('.pairs-table tbody');
        if (!tableBody) return;
        
        tableBody.innerHTML = '';
        
        pairs.forEach(pair => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${pair.id}</td>
                <td>${pair.name}</td>
                <td>${pair.source_chat_id}</td>
                <td>${pair.destination_chat_id}</td>
                <td>
                    <span class="pair-status ${pair.status}">
                        ${pair.status.charAt(0).toUpperCase() + pair.status.slice(1)}
                    </span>
                </td>
                <td>Bot ${pair.assigned_bot_index}</td>
                <td>${(pair.stats?.messages_copied || 0).toLocaleString()}</td>
                <td>
                    <button class="btn btn-danger btn-sm delete-pair-btn" 
                            data-pair-id="${pair.id}" 
                            title="Delete Pair">
                        <i data-feather="trash-2"></i>
                    </button>
                </td>
            `;
            tableBody.appendChild(row);
        });
        
        // Update Feather icons
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    }
    
    updateLogViewer(logs) {
        const logViewer = document.getElementById('logViewer');
        if (!logViewer) return;
        
        logViewer.innerHTML = '';
        
        logs.forEach(log => {
            const logEntry = document.createElement('div');
            logEntry.className = 'log-entry';
            
            const timestamp = new Date(log.created_at).toLocaleTimeString();
            
            logEntry.innerHTML = `
                <span class="log-timestamp">${timestamp}</span>
                <span class="log-level ${log.error_type}">${log.error_type.toUpperCase()}</span>
                <span class="log-message">${this.escapeHtml(log.error_message)}</span>
            `;
            
            logViewer.appendChild(logEntry);
        });
        
        // Auto-scroll to bottom
        logViewer.scrollTop = logViewer.scrollHeight;
    }
    
    updateAlerts(alerts) {
        const alertsContainer = document.getElementById('alertsContainer');
        if (!alertsContainer) return;
        
        alertsContainer.innerHTML = '';
        
        alerts.forEach(alert => {
            const alertElement = document.createElement('div');
            
            let alertClass = 'alert-info';
            if (alert.includes('CRITICAL')) {
                alertClass = 'alert-danger';
            } else if (alert.includes('WARNING')) {
                alertClass = 'alert-warning';
            }
            
            alertElement.className = `alert ${alertClass}`;
            alertElement.innerHTML = `
                <i data-feather="alert-triangle"></i>
                ${this.escapeHtml(alert)}
            `;
            
            alertsContainer.appendChild(alertElement);
        });
        
        // Update Feather icons
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    }
    
    updateLastUpdateTime() {
        const lastUpdateElement = document.getElementById('lastUpdate');
        if (lastUpdateElement && this.lastUpdate) {
            lastUpdateElement.textContent = this.lastUpdate.toLocaleTimeString();
        }
    }
    
    async pauseSystem() {
        try {
            await this.postAPI('/api/pause', {});
            this.showNotification('System paused successfully', 'success');
        } catch (error) {
            console.error('Error pausing system:', error);
            this.showNotification('Failed to pause system', 'error');
        }
    }
    
    async resumeSystem() {
        try {
            await this.postAPI('/api/resume', {});
            this.showNotification('System resumed successfully', 'success');
        } catch (error) {
            console.error('Error resuming system:', error);
            this.showNotification('Failed to resume system', 'error');
        }
    }
    
    async refreshData() {
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.disabled = true;
            refreshBtn.innerHTML = '<div class="loading"></div> Refreshing...';
        }
        
        try {
            await this.loadInitialData();
            this.showNotification('Data refreshed successfully', 'success');
        } catch (error) {
            console.error('Error refreshing data:', error);
            this.showNotification('Failed to refresh data', 'error');
        } finally {
            if (refreshBtn) {
                refreshBtn.disabled = false;
                refreshBtn.innerHTML = '<i data-feather="refresh-cw"></i> Refresh';
                if (typeof feather !== 'undefined') {
                    feather.replace();
                }
            }
        }
    }
    
    async handleAddPair(event) {
        event.preventDefault();
        
        const formData = new FormData(event.target);
        const pairData = {
            source_chat_id: parseInt(formData.get('source_chat_id')),
            destination_chat_id: parseInt(formData.get('destination_chat_id')),
            name: formData.get('name'),
            bot_index: parseInt(formData.get('bot_index') || '0')
        };
        
        try {
            await this.postAPI('/api/pairs', pairData);
            this.showNotification('Pair created successfully', 'success');
            
            // Reset form
            event.target.reset();
            
            // Refresh pairs table
            const pairs = await this.fetchAPI('/api/pairs');
            this.updatePairsTable(pairs);
            
        } catch (error) {
            console.error('Error creating pair:', error);
            this.showNotification('Failed to create pair', 'error');
        }
    }
    
    async deletePair(pairId) {
        if (!confirm('Are you sure you want to delete this pair?')) {
            return;
        }
        
        try {
            await this.deleteAPI(`/api/pairs/${pairId}`);
            this.showNotification('Pair deleted successfully', 'success');
            
            // Refresh pairs table
            const pairs = await this.fetchAPI('/api/pairs');
            this.updatePairsTable(pairs);
            
        } catch (error) {
            console.error('Error deleting pair:', error);
            this.showNotification('Failed to delete pair', 'error');
        }
    }
    
    setupPeriodicUpdates() {
        // Clear existing interval
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
        
        // Set up new interval (every 30 seconds)
        this.refreshInterval = setInterval(() => {
            if (!this.isConnected) {
                this.loadInitialData();
            }
        }, 30000);
    }
    
    setupNotifications() {
        // Request notification permission
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission();
        }
    }
    
    showNotification(message, type = 'info') {
        // Show in-page notification
        const notification = document.createElement('div');
        notification.className = `alert alert-${type === 'error' ? 'danger' : type}`;
        notification.innerHTML = `
            <i data-feather="${this.getNotificationIcon(type)}"></i>
            ${this.escapeHtml(message)}
        `;
        
        // Add to notifications container
        let container = document.getElementById('notificationsContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'notificationsContainer';
            container.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 9999;
                max-width: 400px;
            `;
            document.body.appendChild(container);
        }
        
        container.appendChild(notification);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 5000);
        
        // Update Feather icons
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
        
        // Show browser notification for important messages
        if (type === 'error' && 'Notification' in window && Notification.permission === 'granted') {
            new Notification('Telegram Bot Dashboard', {
                body: message,
                icon: '/static/favicon.ico'
            });
        }
    }
    
    toggleTheme() {
        document.body.classList.toggle('dark-theme');
        localStorage.setItem('theme', document.body.classList.contains('dark-theme') ? 'dark' : 'light');
    }
    
    handleWindowFocus() {
        // Reconnect WebSocket if needed
        if (!this.isConnected) {
            this.connectWebSocket();
        }
        
        // Refresh data
        this.loadInitialData();
    }
    
    handleWindowBlur() {
        // Could pause some operations when window is not visible
    }
    
    cleanup() {
        if (this.ws) {
            this.ws.close();
        }
        
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
    }
    
    // Utility methods
    getHealthIcon(status) {
        const icons = {
            healthy: '<i data-feather="check"></i>',
            warning: '<i data-feather="alert-triangle"></i>',
            critical: '<i data-feather="alert-circle"></i>',
            unknown: '<i data-feather="help-circle"></i>'
        };
        return icons[status] || icons.unknown;
    }
    
    getNotificationIcon(type) {
        const icons = {
            success: 'check-circle',
            warning: 'alert-triangle',
            error: 'alert-circle',
            info: 'info'
        };
        return icons[type] || icons.info;
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Load theme from localStorage
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.body.classList.add('dark-theme');
    }
    
    // Initialize Feather icons
    if (typeof feather !== 'undefined') {
        feather.replace();
    }
    
    // Initialize dashboard
    window.dashboard = new TelegramBotDashboard();
});

// WebSocket heartbeat
setInterval(() => {
    if (window.dashboard && window.dashboard.isConnected) {
        window.dashboard.sendWebSocketMessage({ type: 'ping' });
    }
}, 30000);
