"""
Telegram Message Copying Bot - Production Ready
Complete multi-bot message copying system with advanced filtering
"""

import asyncio
import logging
import signal
import sys
import os
import time
from typing import Dict, List, Optional
from datetime import datetime

from config import Config, validate_environment
from database import DatabaseManager
from bot_manager import BotManager
from health_monitor import HealthMonitor
from web_dashboard import DashboardServer

# Configure logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class TelegramBotSystem:
    """Main system coordinator for the Telegram bot network"""
    
    def __init__(self):
        self.config = Config()
        self.db_manager = None
        self.bot_manager = None
        self.health_monitor = None
        self.dashboard_server = None
        self.running = False
        self._shutdown_event = asyncio.Event()
        self._start_time = time.time()
        
    async def initialize(self):
        """Initialize all system components"""
        try:
            logger.info("Starting Telegram Bot System initialization...")
            
            # Validate environment
            validate_environment()
            
            # Create logs directory
            os.makedirs('logs', exist_ok=True)
            
            # Initialize database
            self.db_manager = DatabaseManager()
            await self.db_manager.initialize()
            
            # Initialize bot manager
            self.bot_manager = BotManager(self.db_manager, self.config)
            await self.bot_manager.initialize()
            
            # Initialize health monitor
            self.health_monitor = HealthMonitor(self.bot_manager, self.db_manager)
            
            # Initialize dashboard server
            self.dashboard_server = DashboardServer(
                self.bot_manager, 
                self.db_manager, 
                self.health_monitor
            )
            
            logger.info("System initialization completed successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize system: {e}", exc_info=True)
            raise
    
    async def start(self):
        """Start all system components"""
        try:
            self.running = True
            
            # Start components
            await self.bot_manager.start()
            await self.health_monitor.start()
            await self.dashboard_server.start()
            
            logger.info("=== Telegram Bot System Started ===")
            logger.info(f"Active bot tokens: {len(self.config.BOT_TOKENS)}")
            logger.info(f"Dashboard available at: http://{self.config.DASHBOARD_HOST}:{self.config.DASHBOARD_PORT}")
            logger.info(f"Debug mode: {self.config.DEBUG_MODE}")
            
            # Wait for shutdown signal
            await self._shutdown_event.wait()
            
        except Exception as e:
            logger.error(f"Error during system operation: {e}", exc_info=True)
            raise
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Gracefully shutdown all components"""
        if not self.running:
            return
            
        logger.info("Initiating system shutdown...")
        self.running = False
        
        try:
            # Stop components in reverse order
            if self.dashboard_server:
                await self.dashboard_server.stop()
                
            if self.health_monitor:
                await self.health_monitor.stop()
                
            if self.bot_manager:
                await self.bot_manager.stop()
                
            if self.db_manager:
                await self.db_manager.close()
                
            logger.info("System shutdown completed")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}", exc_info=True)
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        self._shutdown_event.set()
    
    def get_uptime(self) -> int:
        """Get system uptime in seconds"""
        return int(time.time() - self._start_time)

async def main():
    """Main entry point"""
    system = None
    
    try:
        # Create and initialize system
        system = TelegramBotSystem()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, system.signal_handler)
        signal.signal(signal.SIGTERM, system.signal_handler)
        
        # Initialize and start
        await system.initialize()
        await system.start()
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1
    finally:
        if system:
            await system.shutdown()
    
    return 0

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except Exception as e:
        logger.error(f"Failed to start system: {e}", exc_info=True)
        sys.exit(1)
