#!/usr/bin/env python3
"""
Simple demo server to showcase the Telegram bot dashboard
without requiring Telegram API credentials
"""

import asyncio
import logging
import os
from aiohttp import web
from aiohttp_jinja2 import setup as jinja2_setup
import aiohttp_jinja2
import jinja2
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DemoDashboard:
    """Simple demo dashboard for showcasing the UI"""
    
    def __init__(self):
        self.app = web.Application()
        self.setup_routes()
        self.setup_templates()
    
    def setup_templates(self):
        """Setup Jinja2 templates"""
        templates_path = Path(__file__).parent / 'templates'
        jinja2_setup(self.app, loader=jinja2.FileSystemLoader(str(templates_path)))
    
    def setup_routes(self):
        """Setup web routes"""
        # Static files
        static_path = Path(__file__).parent / 'static'
        self.app.router.add_static('/static/', static_path, name='static')
        
        # Dashboard routes
        self.app.router.add_get('/', self.dashboard_view)
        self.app.router.add_get('/dashboard', self.dashboard_view)
        
        # API routes (demo data)
        self.app.router.add_get('/api/status', self.api_status)
        self.app.router.add_get('/api/stats', self.api_stats)
        self.app.router.add_get('/api/health', self.api_health)
        self.app.router.add_get('/api/pairs', self.api_pairs)
        self.app.router.add_get('/api/logs', self.api_logs)
    
    async def dashboard_view(self, request):
        """Main dashboard view"""
        context = {
            'title': 'Telegram Bot Dashboard - Demo',
            'bot_count': 3,
            'debug_mode': True,
            'error': None,
            'health': {
                'status': 'healthy',
                'uptime_formatted': '2h 34m',
                'metrics': {
                    'memory_mb': {'value': 125.6, 'unit': 'MB'},
                    'cpu_percent': {'value': 15.2, 'unit': '%'},
                    'queue_size': {'value': 42, 'unit': ''},
                    'error_rate': {'value': 0.5, 'unit': '%'}
                }
            },
            'stats': {
                'total_messages': 15847,
                'messages_24h': 2341,
                'total_pairs': 8,
                'active_pairs': 6
            }
        }
        return aiohttp_jinja2.render_template('dashboard.html', request, context)
    
    async def api_status(self, request):
        """API endpoint for system status"""
        return web.json_response({
            'running': True,
            'paused': False,
            'bot_count': 3,
            'uptime': 9240,  # seconds
            'version': '1.0.0'
        })
    
    async def api_stats(self, request):
        """API endpoint for statistics"""
        return web.json_response({
            'total_messages': 15847,
            'messages_24h': 2341,
            'total_pairs': 8,
            'active_pairs': 6,
            'errors_24h': 12,
            'database_size_mb': 45.2,
            'success_rate': 98.7
        })
    
    async def api_health(self, request):
        """API endpoint for health metrics"""
        return web.json_response({
            'status': 'healthy',
            'uptime': 9240,
            'uptime_formatted': '2h 34m',
            'metrics': {
                'memory_mb': {
                    'value': 125.6,
                    'unit': 'MB',
                    'status': 'normal',
                    'name': 'Memory Usage'
                },
                'cpu_percent': {
                    'value': 15.2,
                    'unit': '%',
                    'status': 'normal',
                    'name': 'CPU Usage'
                },
                'queue_size': {
                    'value': 42,
                    'unit': '',
                    'status': 'normal',
                    'name': 'Queue Size'
                },
                'error_rate': {
                    'value': 0.5,
                    'unit': '%',
                    'status': 'normal',
                    'name': 'Error Rate'
                }
            },
            'alerts': []
        })
    
    async def api_pairs(self, request):
        """API endpoint for message pairs"""
        return web.json_response([
            {
                'id': 1,
                'name': 'News Channel → Community',
                'source_chat_id': -1001234567890,
                'destination_chat_id': -1009876543210,
                'status': 'active',
                'assigned_bot_index': 0,
                'stats': {'messages_copied': 1247}
            },
            {
                'id': 2,
                'name': 'Updates → Notifications',
                'source_chat_id': -1001111111111,
                'destination_chat_id': -1002222222222,
                'status': 'active',
                'assigned_bot_index': 1,
                'stats': {'messages_copied': 856}
            },
            {
                'id': 3,
                'name': 'Announcements → Archive',
                'source_chat_id': -1003333333333,
                'destination_chat_id': -1004444444444,
                'status': 'inactive',
                'assigned_bot_index': 2,
                'stats': {'messages_copied': 423}
            }
        ])
    
    async def api_logs(self, request):
        """API endpoint for recent logs"""
        return web.json_response([
            {
                'timestamp': '2025-01-24 15:30:45',
                'level': 'INFO',
                'message': 'Message copied successfully from News Channel to Community'
            },
            {
                'timestamp': '2025-01-24 15:30:23',
                'level': 'INFO',
                'message': 'Bot 1 processed 15 messages in last minute'
            },
            {
                'timestamp': '2025-01-24 15:29:12',
                'level': 'WARNING',
                'message': 'Rate limit approaching for Bot 2, switching to Bot 0'
            },
            {
                'timestamp': '2025-01-24 15:28:45',
                'level': 'INFO',
                'message': 'Image duplicate detected and filtered'
            },
            {
                'timestamp': '2025-01-24 15:27:33',
                'level': 'ERROR',
                'message': 'Failed to send message: Chat not found'
            }
        ])

async def create_app():
    """Create and configure the application"""
    dashboard = DemoDashboard()
    return dashboard.app

async def main():
    """Main application entry point"""
    logger.info("Starting Telegram Bot Dashboard Demo...")
    
    # Create application
    app = await create_app()
    
    # Start server
    host = os.getenv('DASHBOARD_HOST', '0.0.0.0')
    port = int(os.getenv('DASHBOARD_PORT', 5000))
    
    logger.info(f"Starting web server on {host}:{port}")
    logger.info("Dashboard will be available at: http://localhost:5000")
    
    # Start the web server
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, host, port)
    await site.start()
    
    logger.info("Demo dashboard is now running!")
    logger.info("Visit http://localhost:5000 to see the dashboard")
    
    # Keep the server running
    try:
        while True:
            await asyncio.sleep(3600)  # Sleep for 1 hour
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())