"""
Web dashboard for Telegram Bot System monitoring and management
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import os

from aiohttp import web, WSMsgType
from aiohttp.web import Application, Request, Response, WebSocketResponse
import aiohttp_jinja2
import jinja2

from database import DatabaseManager
from config import Config

logger = logging.getLogger(__name__)

class DashboardServer:
    """Production web dashboard server"""
    
    def __init__(self, bot_manager, db_manager: DatabaseManager, health_monitor):
        self.bot_manager = bot_manager
        self.db_manager = db_manager
        self.health_monitor = health_monitor
        self.config = bot_manager.config if hasattr(bot_manager, 'config') else Config()
        
        # Web server components
        self.app: Optional[Application] = None
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        
        # WebSocket connections
        self.websockets: List[WebSocketResponse] = []
        
        # Background tasks
        self.broadcast_task: Optional[asyncio.Task] = None
        self.running = False
    
    async def start(self):
        """Start dashboard server"""
        try:
            # Create aiohttp application
            self.app = web.Application()
            
            # Setup Jinja2 templating
            aiohttp_jinja2.setup(
                self.app,
                loader=jinja2.FileSystemLoader('templates')
            )
            
            # Setup routes
            self._setup_routes()
            
            # Create runner and start server
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            
            self.site = web.TCPSite(
                self.runner,
                self.config.DASHBOARD_HOST,
                self.config.DASHBOARD_PORT
            )
            await self.site.start()
            
            # Start background tasks
            self.running = True
            self.broadcast_task = asyncio.create_task(self._broadcast_loop())
            
            logger.info(f"Dashboard server started on {self.config.DASHBOARD_HOST}:{self.config.DASHBOARD_PORT}")
            
        except Exception as e:
            logger.error(f"Failed to start dashboard server: {e}")
            raise
    
    async def stop(self):
        """Stop dashboard server"""
        try:
            self.running = False
            
            # Cancel background tasks
            if self.broadcast_task:
                self.broadcast_task.cancel()
            
            # Close WebSocket connections
            for ws in self.websockets[:]:
                await ws.close()
            
            # Stop server
            if self.site:
                await self.site.stop()
            if self.runner:
                await self.runner.cleanup()
            
            logger.info("Dashboard server stopped")
            
        except Exception as e:
            logger.error(f"Error stopping dashboard server: {e}")
    
    def _setup_routes(self):
        """Setup web routes"""
        # Static files
        self.app.router.add_static('/static', 'static', name='static')
        
        # Dashboard routes
        self.app.router.add_get('/', self._dashboard_handler)
        self.app.router.add_get('/dashboard', self._dashboard_handler)
        
        # API routes
        self.app.router.add_get('/api/status', self._api_status)
        self.app.router.add_get('/api/stats', self._api_stats)
        self.app.router.add_get('/api/health', self._api_health)
        self.app.router.add_get('/api/pairs', self._api_pairs)
        self.app.router.add_get('/api/logs', self._api_logs)
        
        # Control API routes
        self.app.router.add_post('/api/pause', self._api_pause)
        self.app.router.add_post('/api/resume', self._api_resume)
        self.app.router.add_post('/api/pairs', self._api_create_pair)
        self.app.router.add_delete('/api/pairs/{pair_id}', self._api_delete_pair)
        
        # WebSocket
        self.app.router.add_get('/ws', self._websocket_handler)
    
    @aiohttp_jinja2.template('dashboard.html')
    async def _dashboard_handler(self, request: Request) -> Dict[str, Any]:
        """Main dashboard page"""
        try:
            # Get system overview data
            health = self.health_monitor.get_health_summary() if self.health_monitor else {}
            stats = await self.db_manager.get_stats()
            
            # Get recent pairs
            pairs = await self.db_manager.get_all_pairs()
            recent_pairs = sorted(pairs, key=lambda p: p.created_at or "", reverse=True)[:5]
            
            return {
                'title': 'Telegram Bot Dashboard',
                'health': health,
                'stats': stats,
                'recent_pairs': recent_pairs,
                'bot_count': len(self.config.BOT_TOKENS),
                'debug_mode': self.config.DEBUG_MODE
            }
            
        except Exception as e:
            logger.error(f"Error rendering dashboard: {e}")
            return {
                'title': 'Telegram Bot Dashboard',
                'error': str(e),
                'health': {},
                'stats': {},
                'recent_pairs': [],
                'bot_count': 0,
                'debug_mode': False
            }
    
    async def _api_status(self, request: Request) -> Response:
        """API endpoint for system status"""
        try:
            # Get system status
            paused = await self.db_manager.get_setting("system_paused", "false")
            queue_size = self.bot_manager.get_queue_size() if hasattr(self.bot_manager, 'get_queue_size') else 0
            
            # Get bot metrics
            bot_metrics = {}
            if hasattr(self.bot_manager, 'get_metrics'):
                metrics = self.bot_manager.get_metrics()
                for bot_index, metric in metrics.items():
                    bot_metrics[bot_index] = {
                        'messages_processed': metric.messages_processed,
                        'success_rate': metric.success_rate,
                        'current_load': metric.current_load,
                        'consecutive_failures': metric.consecutive_failures,
                        'last_activity': metric.last_activity
                    }
            
            status_data = {
                'running': self.bot_manager.running if hasattr(self.bot_manager, 'running') else False,
                'paused': paused.lower() == 'true',
                'queue_size': queue_size,
                'bot_metrics': bot_metrics,
                'timestamp': datetime.now().isoformat()
            }
            
            return web.json_response(status_data)
            
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def _api_stats(self, request: Request) -> Response:
        """API endpoint for system statistics"""
        try:
            stats = await self.db_manager.get_stats()
            
            # Add processing stats if available
            if hasattr(self.bot_manager, 'message_processor'):
                processor_stats = self.bot_manager.message_processor.get_stats()
                stats.update(processor_stats)
            
            return web.json_response(stats)
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def _api_health(self, request: Request) -> Response:
        """API endpoint for health status"""
        try:
            if self.health_monitor:
                health = self.health_monitor.get_health_summary()
            else:
                health = {'status': 'unknown', 'message': 'Health monitor not available'}
            
            return web.json_response(health)
            
        except Exception as e:
            logger.error(f"Error getting health: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def _api_pairs(self, request: Request) -> Response:
        """API endpoint for message pairs"""
        try:
            pairs = await self.db_manager.get_all_pairs()
            
            pairs_data = []
            for pair in pairs:
                pairs_data.append({
                    'id': pair.id,
                    'name': pair.name,
                    'source_chat_id': pair.source_chat_id,
                    'destination_chat_id': pair.destination_chat_id,
                    'status': pair.status,
                    'assigned_bot_index': pair.assigned_bot_index,
                    'stats': pair.stats,
                    'created_at': pair.created_at
                })
            
            return web.json_response(pairs_data)
            
        except Exception as e:
            logger.error(f"Error getting pairs: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def _api_logs(self, request: Request) -> Response:
        """API endpoint for error logs"""
        try:
            limit = int(request.query.get('limit', 50))
            
            # Get recent errors from database
            async with self.db_manager.get_connection() as conn:
                cursor = await conn.execute('''
                    SELECT * FROM error_logs 
                    ORDER BY created_at DESC 
                    LIMIT ?
                ''', (limit,))
                
                logs = []
                async for row in cursor:
                    logs.append({
                        'id': row[0],
                        'error_type': row[1],
                        'error_message': row[2],
                        'pair_id': row[3],
                        'bot_index': row[4],
                        'created_at': row[6]
                    })
            
            return web.json_response(logs)
            
        except Exception as e:
            logger.error(f"Error getting logs: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def _api_pause(self, request: Request) -> Response:
        """API endpoint to pause system"""
        try:
            await self.db_manager.set_setting("system_paused", "true")
            logger.info("System paused via API")
            return web.json_response({'success': True, 'message': 'System paused'})
            
        except Exception as e:
            logger.error(f"Error pausing system: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def _api_resume(self, request: Request) -> Response:
        """API endpoint to resume system"""
        try:
            await self.db_manager.set_setting("system_paused", "false")
            logger.info("System resumed via API")
            return web.json_response({'success': True, 'message': 'System resumed'})
            
        except Exception as e:
            logger.error(f"Error resuming system: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def _api_create_pair(self, request: Request) -> Response:
        """API endpoint to create new pair"""
        try:
            data = await request.json()
            
            source_id = int(data['source_chat_id'])
            dest_id = int(data['destination_chat_id'])
            name = data['name']
            bot_index = int(data.get('bot_index', 0))
            
            pair_id = await self.db_manager.create_pair(source_id, dest_id, name, bot_index)
            
            # Reload pairs in bot manager
            if hasattr(self.bot_manager, 'reload_pairs'):
                await self.bot_manager.reload_pairs()
            
            return web.json_response({
                'success': True,
                'pair_id': pair_id,
                'message': f'Created pair: {name}'
            })
            
        except ValueError as e:
            return web.json_response({'error': str(e)}, status=400)
        except Exception as e:
            logger.error(f"Error creating pair: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def _api_delete_pair(self, request: Request) -> Response:
        """API endpoint to delete pair"""
        try:
            pair_id = int(request.match_info['pair_id'])
            
            await self.db_manager.delete_pair(pair_id)
            
            # Reload pairs in bot manager
            if hasattr(self.bot_manager, 'reload_pairs'):
                await self.bot_manager.reload_pairs()
            
            return web.json_response({
                'success': True,
                'message': f'Deleted pair {pair_id}'
            })
            
        except Exception as e:
            logger.error(f"Error deleting pair: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def _websocket_handler(self, request: Request) -> WebSocketResponse:
        """WebSocket handler for real-time updates"""
        ws = WebSocketResponse()
        await ws.prepare(request)
        
        self.websockets.append(ws)
        logger.debug("WebSocket connection established")
        
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_websocket_message(ws, data)
                    except json.JSONDecodeError:
                        await ws.send_str(json.dumps({
                            'error': 'Invalid JSON message'
                        }))
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f'WebSocket error: {ws.exception()}')
                    break
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            if ws in self.websockets:
                self.websockets.remove(ws)
            logger.debug("WebSocket connection closed")
        
        return ws
    
    async def _handle_websocket_message(self, ws: WebSocketResponse, data: Dict[str, Any]):
        """Handle incoming WebSocket messages"""
        try:
            message_type = data.get('type')
            
            if message_type == 'ping':
                await ws.send_str(json.dumps({'type': 'pong'}))
            
            elif message_type == 'get_status':
                # Send current status
                status_response = await self._get_realtime_status()
                await ws.send_str(json.dumps({
                    'type': 'status_update',
                    'data': status_response
                }))
            
            elif message_type == 'subscribe':
                # Subscribe to specific updates
                subscription = data.get('subscription', 'all')
                # Store subscription preference (could be expanded)
                logger.debug(f"WebSocket subscribed to: {subscription}")
            
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")
            await ws.send_str(json.dumps({
                'type': 'error',
                'message': str(e)
            }))
    
    async def _broadcast_loop(self):
        """Background task to broadcast updates to WebSocket clients"""
        while self.running:
            try:
                if self.websockets:
                    # Get current status
                    status_data = await self._get_realtime_status()
                    
                    # Broadcast to all connected clients
                    message = json.dumps({
                        'type': 'status_update',
                        'data': status_data
                    })
                    
                    # Remove closed connections
                    active_websockets = []
                    for ws in self.websockets:
                        if not ws.closed:
                            try:
                                await ws.send_str(message)
                                active_websockets.append(ws)
                            except Exception as e:
                                logger.debug(f"Failed to send to WebSocket: {e}")
                    
                    self.websockets = active_websockets
                
                await asyncio.sleep(5)  # Broadcast every 5 seconds
                
            except Exception as e:
                logger.error(f"Error in broadcast loop: {e}")
                await asyncio.sleep(5)
    
    async def _get_realtime_status(self) -> Dict[str, Any]:
        """Get real-time status data for broadcasting"""
        try:
            # Get basic status
            paused = await self.db_manager.get_setting("system_paused", "false")
            queue_size = self.bot_manager.get_queue_size() if hasattr(self.bot_manager, 'get_queue_size') else 0
            
            # Get health status
            health = {}
            if self.health_monitor:
                health = self.health_monitor.get_health_summary()
            
            # Get bot metrics
            bot_metrics = {}
            if hasattr(self.bot_manager, 'get_metrics'):
                metrics = self.bot_manager.get_metrics()
                for bot_index, metric in metrics.items():
                    bot_metrics[bot_index] = {
                        'messages_processed': metric.messages_processed,
                        'success_rate': round(metric.success_rate * 100, 1),
                        'current_load': metric.current_load,
                        'consecutive_failures': metric.consecutive_failures
                    }
            
            return {
                'timestamp': datetime.now().isoformat(),
                'running': self.bot_manager.running if hasattr(self.bot_manager, 'running') else False,
                'paused': paused.lower() == 'true',
                'queue_size': queue_size,
                'health': health,
                'bot_metrics': bot_metrics
            }
            
        except Exception as e:
            logger.error(f"Error getting realtime status: {e}")
            return {
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            }
