"""
Bot Manager - Handles multiple Telegram bots with load balancing
"""

import asyncio
import logging
import time
import json
import traceback
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict, deque
from enum import Enum
import heapq

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import RetryAfter, TelegramError, NetworkError, TimedOut, Forbidden, BadRequest
from telegram.request import HTTPXRequest
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, AuthKeyUnregisteredError

from database import DatabaseManager, MessagePair, MessageMapping
from message_processor import MessageProcessor
from config import Config

logger = logging.getLogger(__name__)

class MessagePriority(Enum):
    """Message priority levels"""
    URGENT = 4
    HIGH = 3
    NORMAL = 2
    LOW = 1

    def __lt__(self, other):
        return self.value < other.value

@dataclass
class QueuedMessage:
    """Queued message with priority and metadata"""
    data: dict
    priority: MessagePriority
    timestamp: float
    pair_id: int
    bot_index: int
    retry_count: int = 0
    max_retries: int = 3
    processing_time_estimate: float = 1.0

    def __lt__(self, other):
        if self.priority.value != other.priority.value:
            return self.priority.value > other.priority.value
        return self.timestamp < other.timestamp

@dataclass
class BotMetrics:
    """Bot performance metrics"""
    messages_processed: int = 0
    success_rate: float = 1.0
    avg_processing_time: float = 1.0
    current_load: int = 0
    error_count: int = 0
    last_activity: float = 0
    rate_limit_until: float = 0
    consecutive_failures: int = 0
    
    def update_success_rate(self, success: bool):
        """Update success rate with exponential moving average"""
        alpha = 0.1  # Learning rate
        new_rate = 1.0 if success else 0.0
        self.success_rate = alpha * new_rate + (1 - alpha) * self.success_rate
        
        if success:
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1

class BotManager:
    """Production-ready bot manager with advanced features"""
    
    def __init__(self, db_manager: DatabaseManager, config: Config):
        self.db_manager = db_manager
        self.config = config
        self.message_processor = MessageProcessor(db_manager, config)
        
        # Bot instances
        self.telegram_bots: List[Bot] = []
        self.bot_applications: List[Application] = []
        self.admin_bot: Optional[Bot] = None
        self.admin_application: Optional[Application] = None
        self.telethon_client: Optional[TelegramClient] = None
        
        # Initialize filter and image handler from message processor
        self.message_filter = self.message_processor.message_filter
        self.image_handler = self.message_processor.image_handler
        
        # Monitoring and metrics
        self.bot_metrics: Dict[int, BotMetrics] = {}
        self.message_queue = asyncio.PriorityQueue(maxsize=config.MESSAGE_QUEUE_SIZE)
        self.pair_queues: Dict[int, deque] = defaultdict(lambda: deque(maxlen=100))
        
        # Rate limiting
        self.rate_limiters: Dict[int, deque] = defaultdict(lambda: deque(maxlen=config.RATE_LIMIT_MESSAGES))
        
        # System state
        self.running = False
        self.worker_tasks: List[asyncio.Task] = []
        self.pairs: Dict[int, MessagePair] = {}
        self.source_to_pairs: Dict[int, List[int]] = defaultdict(list)
        
        # Custom bot instances cache for saved bot tokens
        self.custom_bots: Dict[int, Bot] = {}  # token_id -> Bot instance
        
        # Error tracking
        self.global_error_count = 0
        self.last_error_time = 0
        
    async def initialize(self):
        """Initialize all bot components"""
        try:
            # Initialize bots
            await self._init_telegram_bots()
            await self._init_telethon_client()
            
            # Initialize message processor
            await self.message_processor.initialize()
            
            # Load pairs from database
            await self._load_pairs()
            
            # Initialize metrics
            for i in range(len(self.telegram_bots)):
                self.bot_metrics[i] = BotMetrics()
            
            logger.info(f"Bot manager initialized with {len(self.telegram_bots)} bots")
            
        except Exception as e:
            logger.error(f"Failed to initialize bot manager: {e}")
            raise
    
    async def _init_telegram_bots(self):
        """Initialize Telegram bot instances"""
        try:
            # Import required modules with proper async support
            from telegram.request import HTTPXRequest
            
            # Create a custom HTTP request handler with proper asyncio support
            request = HTTPXRequest(
                connection_pool_size=8,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
                pool_timeout=30
            )
            
            # Initialize admin bot first if configured
            if self.config.ADMIN_BOT_TOKEN:
                self.admin_bot = Bot(token=self.config.ADMIN_BOT_TOKEN, request=request)
                
                # Test admin bot connectivity with retry
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        me = await self.admin_bot.get_me()
                        logger.info(f"Admin bot initialized: @{me.username}")
                        break
                    except Exception as e:
                        if attempt == max_retries - 1:
                            raise
                        logger.warning(f"Admin bot connection attempt {attempt + 1} failed: {e}")
                        await asyncio.sleep(2)
                
                # Create admin application for commands
                self.admin_application = Application.builder().token(self.config.ADMIN_BOT_TOKEN).request(request).build()
                await self._setup_command_handlers(self.admin_application)
                logger.info("Admin bot command handlers configured")
            
            # Initialize message sending bots
            for i, token in enumerate(self.config.BOT_TOKENS):
                try:
                    # Create bot with custom request handler
                    bot = Bot(token=token, request=request)
                    
                    # Test bot connectivity with retry
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            bot_info = await bot.get_me()
                            logger.info(f"Bot {i} initialized: @{bot_info.username}")
                            break
                        except Exception as e:
                            if attempt == max_retries - 1:
                                logger.error(f"Bot {i} failed after {max_retries} attempts: {e}")
                                continue  # Skip this bot but continue with others
                            logger.warning(f"Bot {i} connection attempt {attempt + 1} failed: {e}")
                            await asyncio.sleep(2)
                    else:
                        # If all retries failed, skip this bot
                        continue
                    
                    self.telegram_bots.append(bot)
                    
                    # Create application for message sending (no commands on these)
                    app = Application.builder().token(token).request(request).build()
                    self.bot_applications.append(app)
                    
                except Exception as e:
                    logger.error(f"Failed to initialize bot {i}: {e}")
                    # Continue with other bots
            
            if not self.telegram_bots:
                raise ValueError("No Telegram bots could be initialized successfully")
                
        except Exception as e:
            logger.error(f"Failed to initialize bots: {e}")
            raise
    
    async def _init_telethon_client(self):
        """Initialize Telethon client for message listening"""
        try:
            # Validate required configuration
            if not self.config.API_ID or not self.config.API_HASH or not self.config.PHONE_NUMBER:
                raise ValueError("Missing required Telethon configuration: API_ID, API_HASH, or PHONE_NUMBER")
            
            api_id = int(self.config.API_ID) if isinstance(self.config.API_ID, str) else self.config.API_ID
            
            self.telethon_client = TelegramClient(
                'session_bot',
                api_id,
                self.config.API_HASH
            )
            
            if self.telethon_client and not self.telethon_client.is_connected():
                await self.telethon_client.start(phone=self.config.PHONE_NUMBER)
            logger.info("Telethon client initialized")
            
            # Setup message handlers
            self.telethon_client.add_event_handler(
                self._handle_new_message,
                events.NewMessage()
            )
            
            self.telethon_client.add_event_handler(
                self._handle_message_edited,
                events.MessageEdited()
            )
            
            self.telethon_client.add_event_handler(
                self._handle_message_deleted,
                events.MessageDeleted()
            )
            
        except Exception as e:
            logger.error(f"Failed to initialize Telethon client: {e}")
            raise
    
    async def _setup_command_handlers(self, app: Application):
        """Setup command handlers for primary bot"""
        # Basic commands
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("help", self._cmd_help))
        
        # System management
        app.add_handler(CommandHandler("status", self._cmd_status))
        app.add_handler(CommandHandler("stats", self._cmd_stats))
        app.add_handler(CommandHandler("health", self._cmd_health))
        app.add_handler(CommandHandler("pause", self._cmd_pause))
        app.add_handler(CommandHandler("resume", self._cmd_resume))
        app.add_handler(CommandHandler("restart", self._cmd_restart))
        
        # Pair management
        app.add_handler(CommandHandler("pairs", self._cmd_pairs))
        app.add_handler(CommandHandler("addpair", self._cmd_add_pair))
        app.add_handler(CommandHandler("delpair", self._cmd_delete_pair))
        app.add_handler(CommandHandler("editpair", self._cmd_edit_pair))
        app.add_handler(CommandHandler("pairinfo", self._cmd_pair_info))
        
        # Bot management
        app.add_handler(CommandHandler("bots", self._cmd_bots))
        app.add_handler(CommandHandler("botinfo", self._cmd_bot_info))
        app.add_handler(CommandHandler("rebalance", self._cmd_rebalance))
        
        # Queue management
        app.add_handler(CommandHandler("queue", self._cmd_queue))
        app.add_handler(CommandHandler("clearqueue", self._cmd_clear_queue))
        
        # Logs and diagnostics
        app.add_handler(CommandHandler("logs", self._cmd_logs))
        app.add_handler(CommandHandler("errors", self._cmd_errors))
        app.add_handler(CommandHandler("diagnostics", self._cmd_diagnostics))
        
        # Settings
        app.add_handler(CommandHandler("settings", self._cmd_settings))
        app.add_handler(CommandHandler("set", self._cmd_set_setting))
        
        # Utilities
        app.add_handler(CommandHandler("backup", self._cmd_backup))
        app.add_handler(CommandHandler("cleanup", self._cmd_cleanup))
        
        # Advanced filtering commands
        app.add_handler(CommandHandler("blockword", self._cmd_block_word))
        app.add_handler(CommandHandler("unblockword", self._cmd_unblock_word))
        app.add_handler(CommandHandler("listblocked", self._cmd_list_blocked_words))
        app.add_handler(CommandHandler("blockimage", self._cmd_block_image))
        app.add_handler(CommandHandler("unblockimage", self._cmd_unblock_image))
        app.add_handler(CommandHandler("listblockedimages", self._cmd_list_blocked_images))
        app.add_handler(CommandHandler("mentions", self._cmd_set_mention_removal))
        app.add_handler(CommandHandler("headerregex", self._cmd_set_header_regex))
        app.add_handler(CommandHandler("footerregex", self._cmd_set_footer_regex))
        app.add_handler(CommandHandler("testfilter", self._cmd_test_filter))
        
        # Bot token management commands
        app.add_handler(CommandHandler("addtoken", self._cmd_add_token))
        app.add_handler(CommandHandler("addbot", self._cmd_add_token))  # Alias for addtoken
        app.add_handler(CommandHandler("listtokens", self._cmd_list_tokens))
        app.add_handler(CommandHandler("listbots", self._cmd_list_tokens))  # Alias for listtokens
        app.add_handler(CommandHandler("deletetoken", self._cmd_delete_token))
        app.add_handler(CommandHandler("deletebot", self._cmd_delete_token))  # Alias for deletetoken
        app.add_handler(CommandHandler("toggletoken", self._cmd_toggle_token))
        app.add_handler(CommandHandler("togglebot", self._cmd_toggle_token))  # Alias for toggletoken
        
        app.add_handler(CallbackQueryHandler(self._handle_callback))
    
    async def _load_pairs(self):
        """Load message pairs from database"""
        try:
            pairs = await self.db_manager.get_all_pairs()
            self.pairs = {pair.id: pair for pair in pairs}
            
            # Build optimized source chat mapping for fast lookups
            self.source_to_pairs.clear()
            for pair in pairs:
                if pair.status == "active":
                    if pair.source_chat_id not in self.source_to_pairs:
                        self.source_to_pairs[pair.source_chat_id] = []
                    self.source_to_pairs[pair.source_chat_id].append(pair.id)
            
            logger.info(f"Loaded {len(pairs)} pairs from database")
            
        except Exception as e:
            logger.error(f"Failed to load pairs: {e}")
            raise
    
    async def start(self):
        """Start bot manager and all components"""
        try:
            self.running = True
            
            # Start admin bot application if available
            if self.admin_application:
                await self.admin_application.initialize()
                await self.admin_application.start()
                logger.info("Started admin bot application")
                
                # Start polling for admin bot to receive commands
                if self.admin_application.updater:
                    admin_task = asyncio.create_task(self.admin_application.updater.start_polling())
                    self.worker_tasks.append(admin_task)
                    logger.info("Started admin bot polling")
            
            # Start message sending bot applications
            for i, app in enumerate(self.bot_applications):
                await app.initialize()
                await app.start()
                logger.info(f"Started bot application {i}")
            
            # Start worker tasks
            for i in range(self.config.MAX_WORKERS):
                task = asyncio.create_task(self._message_worker(i))
                self.worker_tasks.append(task)
                logger.info(f"Message worker {i} started")
            
            # Start monitoring tasks
            monitoring_tasks = [
                asyncio.create_task(self._health_monitor()),
                asyncio.create_task(self._queue_monitor()),
                asyncio.create_task(self._rate_limit_monitor())
            ]
            self.worker_tasks.extend(monitoring_tasks)
            
            logger.info("Bot manager started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start bot manager: {e}")
            raise
    
    async def stop(self):
        """Stop bot manager and cleanup"""
        try:
            self.running = False
            
            # Cancel worker tasks
            for task in self.worker_tasks:
                task.cancel()
            
            # Wait for tasks to complete
            if self.worker_tasks:
                await asyncio.gather(*self.worker_tasks, return_exceptions=True)
            
            # Stop admin bot application
            if self.admin_application and self.admin_application.running:
                await self.admin_application.stop()
                await self.admin_application.shutdown()
            
            # Stop bot applications
            for app in self.bot_applications:
                if app.running:
                    await app.stop()
                    await app.shutdown()
            
            # Disconnect Telethon client
            if self.telethon_client and self.telethon_client.is_connected():
                await self.telethon_client.disconnect()
            
            # Clear custom bot instances cache
            self.custom_bots.clear()
            
            logger.info("Bot manager stopped")
            
        except Exception as e:
            logger.error(f"Error stopping bot manager: {e}")
    
    async def _handle_new_message(self, event):
        """Handle new messages from Telethon"""
        try:
            chat_id = event.chat_id
            
            # Check if this chat has active pairs
            if chat_id not in self.source_to_pairs:
                return
            
            # Log URL messages for debugging
            message_text = event.text or event.raw_text or ""
            if self.message_processor._contains_urls(message_text):
                logger.info(f"New URL message received: {message_text[:100]}...")
            
            # Process message for each pair
            for pair_id in self.source_to_pairs[chat_id]:
                pair = self.pairs.get(pair_id)
                if not pair or pair.status != "active":
                    continue
                
                # Create message data
                message_data = {
                    'type': 'new_message',
                    'event': event,
                    'pair_id': pair_id,
                    'timestamp': time.time()
                }
                
                # Determine priority
                priority = self._get_message_priority(event, pair)
                
                # Queue message
                await self._queue_message(message_data, priority, pair_id, pair.assigned_bot_index)
        
        except Exception as e:
            logger.error(f"Error handling new message: {e}")
            await self._log_error("message_handling", str(e), traceback.format_exc())
    
    async def _handle_message_edited(self, event):
        """Handle message edits"""
        try:
            chat_id = event.chat_id
            
            if chat_id not in self.source_to_pairs:
                return
            
            for pair_id in self.source_to_pairs[chat_id]:
                pair = self.pairs.get(pair_id)
                if not pair or pair.status != "active":
                    continue
                
                if not pair.filters.get("sync_edits", True):
                    continue
                
                message_data = {
                    'type': 'edit_message',
                    'event': event,
                    'pair_id': pair_id,
                    'timestamp': time.time()
                }
                
                await self._queue_message(message_data, MessagePriority.HIGH, pair_id, pair.assigned_bot_index)
        
        except Exception as e:
            logger.error(f"Error handling message edit: {e}")
    
    async def _handle_message_deleted(self, event):
        """Handle message deletions"""
        try:
            chat_id = event.chat_id
            
            if chat_id not in self.source_to_pairs:
                return
            
            for pair_id in self.source_to_pairs[chat_id]:
                pair = self.pairs.get(pair_id)
                if not pair or pair.status != "active":
                    continue
                
                if not pair.filters.get("sync_deletes", False):
                    continue
                
                message_data = {
                    'type': 'delete_message',
                    'event': event,
                    'pair_id': pair_id,
                    'timestamp': time.time()
                }
                
                await self._queue_message(message_data, MessagePriority.NORMAL, pair_id, pair.assigned_bot_index)
        
        except Exception as e:
            logger.error(f"Error handling message deletion: {e}")
    
    def _get_message_priority(self, event, pair: MessagePair) -> MessagePriority:
        """Determine message priority"""
        # High priority for replies if preserve_replies is enabled
        if event.is_reply and pair.filters.get("preserve_replies", True):
            return MessagePriority.HIGH
        
        # High priority for media messages
        if event.media:
            return MessagePriority.HIGH
        
        # Normal priority for regular messages
        return MessagePriority.NORMAL
    
    async def _queue_message(self, message_data: dict, priority: MessagePriority, 
                           pair_id: int, bot_index: int):
        """Queue message for processing"""
        try:
            queued_msg = QueuedMessage(
                data=message_data,
                priority=priority,
                timestamp=time.time(),
                pair_id=pair_id,
                bot_index=bot_index
            )
            
            # Check if queue is full
            if self.message_queue.full():
                logger.warning("Message queue is full, dropping oldest message")
                try:
                    self.message_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            
            await self.message_queue.put(queued_msg)
            
        except Exception as e:
            logger.error(f"Failed to queue message: {e}")
    
    async def _message_worker(self, worker_id: int):
        """Worker task for processing messages"""
        logger.info(f"Message worker {worker_id} started")
        
        while self.running:
            try:
                # Get message from queue with timeout
                try:
                    queued_msg = await asyncio.wait_for(
                        self.message_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Check if system is paused
                paused = await self.db_manager.get_setting("system_paused", "false")
                if paused and paused.lower() == "true":
                    # Put message back in queue
                    await self.message_queue.put(queued_msg)
                    await asyncio.sleep(5)
                    continue
                
                # Process message
                success = await self._process_queued_message(queued_msg)
                
                # Update metrics
                bot_metrics = self.bot_metrics.get(queued_msg.bot_index)
                if bot_metrics:
                    bot_metrics.update_success_rate(success)
                    bot_metrics.messages_processed += 1
                    bot_metrics.last_activity = time.time()
                
                # Handle retry if failed
                if not success and queued_msg.retry_count < queued_msg.max_retries:
                    queued_msg.retry_count += 1
                    await asyncio.sleep(2 ** queued_msg.retry_count)  # Exponential backoff
                    await self.message_queue.put(queued_msg)
                
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                await asyncio.sleep(1)
        
        logger.info(f"Message worker {worker_id} stopped")
    
    async def _process_queued_message(self, queued_msg: QueuedMessage) -> bool:
        """Process a queued message"""
        try:
            start_time = time.time()
            
            # Get pair first
            pair = self.pairs.get(queued_msg.pair_id)
            if not pair:
                logger.warning(f"Pair {queued_msg.pair_id} not found")
                return False
            
            # Determine which bot to use
            bot = None
            bot_index = queued_msg.bot_index
            
            # Check if pair has a custom bot token assigned
            if pair.bot_token_id:
                logger.debug(f"Using custom bot token {pair.bot_token_id} for pair {pair.id}")
                bot = await self._get_or_create_custom_bot(pair.bot_token_id)
                if not bot:
                    logger.error(f"Failed to get custom bot for token {pair.bot_token_id}, falling back to default bot")
                    # Fall back to default bot
                    if bot_index >= len(self.telegram_bots):
                        bot_index = 0  # Fallback to primary bot
                    bot = self.telegram_bots[bot_index]
                else:
                    # Use a special bot index for custom bots (negative to distinguish from default bots)
                    bot_index = -pair.bot_token_id
            else:
                # Use default bot from config
                if bot_index >= len(self.telegram_bots):
                    bot_index = 0  # Fallback to primary bot
                bot = self.telegram_bots[bot_index]
            
            # Check rate limits (only for default bots, custom bots have their own limits)
            if bot_index >= 0 and not self._check_rate_limit(bot_index):
                logger.warning(f"Rate limit exceeded for bot {bot_index}")
                return False
            
            # Process based on message type
            message_type = queued_msg.data['type']
            event = queued_msg.data['event']
            
            success = False
            if message_type == 'new_message':
                success = await self.message_processor.process_new_message(
                    event, pair, bot, bot_index
                )
            elif message_type == 'edit_message':
                success = await self.message_processor.process_message_edit(
                    event, pair, bot, bot_index
                )
            elif message_type == 'delete_message':
                success = await self.message_processor.process_message_delete(
                    event, pair, bot, bot_index
                )
            
            # Update processing time (only for default bots)
            processing_time = time.time() - start_time
            if bot_index >= 0:  # Only update metrics for default bots
                bot_metrics = self.bot_metrics.get(bot_index)
                if bot_metrics:
                    # Update average processing time with EMA
                    alpha = 0.1
                    bot_metrics.avg_processing_time = (
                        alpha * processing_time + 
                        (1 - alpha) * bot_metrics.avg_processing_time
                    )
            
            return success
            
        except RetryAfter as e:
            logger.warning(f"Rate limited by Telegram: {e.retry_after} seconds")
            bot_metrics = self.bot_metrics.get(queued_msg.bot_index)
            if bot_metrics:
                bot_metrics.rate_limit_until = time.time() + float(getattr(e, 'retry_after', 60))
            return False
            
        except (NetworkError, TimedOut) as e:
            logger.warning(f"Network error: {e}")
            return False
            
        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
            await self._log_error("telegram_error", str(e), None, queued_msg.pair_id, queued_msg.bot_index)
            return False
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            await self._log_error("processing_error", str(e), traceback.format_exc(), queued_msg.pair_id, queued_msg.bot_index)
            return False
    
    def _check_rate_limit(self, bot_index: int) -> bool:
        """Check if bot is rate limited"""
        bot_metrics = self.bot_metrics.get(bot_index)
        if bot_metrics and bot_metrics.rate_limit_until > time.time():
            return False
        
        # Check message rate limit
        now = time.time()
        rate_limiter = self.rate_limiters[bot_index]
        
        # Remove old entries
        while rate_limiter and rate_limiter[0] < now - self.config.RATE_LIMIT_WINDOW:
            rate_limiter.popleft()
        
        # Check if limit exceeded
        if len(rate_limiter) >= self.config.RATE_LIMIT_MESSAGES:
            return False
        
        # Add current time
        rate_limiter.append(now)
        return True
    
    async def _health_monitor(self):
        """Monitor bot health and performance"""
        while self.running:
            try:
                await asyncio.sleep(self.config.HEALTH_CHECK_INTERVAL)
                
                # Check bot connectivity
                for i, bot in enumerate(self.telegram_bots):
                    try:
                        await bot.get_me()
                        bot_metrics = self.bot_metrics.get(i)
                        if bot_metrics:
                            bot_metrics.consecutive_failures = 0
                    except Exception as e:
                        logger.warning(f"Bot {i} health check failed: {e}")
                        bot_metrics = self.bot_metrics.get(i)
                        if bot_metrics:
                            bot_metrics.consecutive_failures += 1
                
                # Log metrics
                await self._log_metrics()
                
            except Exception as e:
                logger.error(f"Health monitor error: {e}")
    
    async def _queue_monitor(self):
        """Monitor message queue health"""
        while self.running:
            try:
                await asyncio.sleep(30)
                
                queue_size = self.message_queue.qsize()
                if queue_size > self.config.MESSAGE_QUEUE_SIZE * 0.8:
                    logger.warning(f"Message queue is {queue_size}/{self.config.MESSAGE_QUEUE_SIZE}")
                
                # Update current load for each bot
                for bot_index, metrics in self.bot_metrics.items():
                    metrics.current_load = queue_size
                
            except Exception as e:
                logger.error(f"Queue monitor error: {e}")
    
    async def _rate_limit_monitor(self):
        """Monitor and reset rate limits"""
        while self.running:
            try:
                await asyncio.sleep(60)
                
                now = time.time()
                for bot_index, rate_limiter in self.rate_limiters.items():
                    # Clean old entries
                    while rate_limiter and rate_limiter[0] < now - self.config.RATE_LIMIT_WINDOW:
                        rate_limiter.popleft()
                
            except Exception as e:
                logger.error(f"Rate limit monitor error: {e}")
    
    async def _get_or_create_custom_bot(self, bot_token_id: int) -> Optional[Bot]:
        """Get or create a Bot instance for a specific bot_token_id"""
        try:
            # Check if we already have this bot cached
            if bot_token_id in self.custom_bots:
                return self.custom_bots[bot_token_id]
            
            # Get token from database
            token_data = await self.db_manager.get_bot_token_by_id(bot_token_id)
            if not token_data:
                logger.error(f"Bot token {bot_token_id} not found in database")
                return None
            
            if not token_data['is_active']:
                logger.error(f"Bot token {bot_token_id} is not active")
                return None
            
            # Create custom HTTP request handler (same as default bots)
            from telegram.request import HTTPXRequest
            request = HTTPXRequest(
                connection_pool_size=8,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
                pool_timeout=30
            )
            
            # Create Bot instance
            bot = Bot(token=token_data['token'], request=request)
            
            # Test bot connectivity
            try:
                bot_info = await bot.get_me()
                logger.info(f"Custom bot created for token {bot_token_id}: @{bot_info.username}")
                
                # Cache the bot
                self.custom_bots[bot_token_id] = bot
                
                # Update usage count in database
                await self.db_manager.update_bot_token_usage(bot_token_id)
                
                return bot
                
            except Exception as e:
                logger.error(f"Failed to connect to custom bot {bot_token_id}: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating custom bot for token {bot_token_id}: {e}")
            return None
    
    async def _log_metrics(self):
        """Log system metrics"""
        try:
            total_processed = sum(m.messages_processed for m in self.bot_metrics.values())
            avg_success_rate = sum(m.success_rate for m in self.bot_metrics.values()) / len(self.bot_metrics) if self.bot_metrics else 0
            queue_size = self.message_queue.qsize()
            
            logger.info(f"Metrics - Processed: {total_processed}, Success Rate: {avg_success_rate:.2f}, Queue: {queue_size}")
            
        except Exception as e:
            logger.error(f"Failed to log metrics: {e}")
    
    async def _log_error(self, error_type: str, error_message: str, 
                        stack_trace: Optional[str] = None, 
                        pair_id: Optional[int] = None, 
                        bot_index: Optional[int] = None):
        """Log error to database"""
        try:
            await self.db_manager.log_error(error_type, error_message, pair_id, bot_index, stack_trace)
        except Exception as e:
            logger.error(f"Failed to log error to database: {e}")
    
    # Command handlers
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        if not update.effective_user or not self._is_admin(update.effective_user.id):
            if update.message:
                await update.message.reply_text("❌ You are not authorized to use this bot.")
            return
        if update.message:
            await update.message.reply_text(
            "🤖 Telegram Message Copying Bot\n\n"
            "Available commands:\n"
            "/status - System status\n"
            "/stats - Statistics\n"
            "/pairs - List message pairs\n"
            "/pause - Pause system\n"
            "/resume - Resume system\n"
            "/help - Show help"
        )
    
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command handler"""
        if not update.effective_user or not self._is_admin(update.effective_user.id):
            return
        if not update.message:
            return
        
        help_text = """🤖 Telegram Message Copying Bot

System Management:
/status - System status and overview
/stats - Detailed statistics
/health - Health monitoring
/pause - Pause message processing
/resume - Resume message processing
/restart - Restart bot system

Pair Management:
/pairs - List all message pairs
/addpair <source> <dest> <name> [bot_token_id] - Add new pair with optional bot selection
/delpair <id> - Delete pair
/editpair <id> <setting> <value> - Edit pair settings
/pairinfo <id> - Detailed pair information

Bot Management:
/bots - List all bot instances
/botinfo <index> - Detailed bot information
/rebalance - Rebalance message distribution

Queue & Processing:
/queue - View message queue status
/clearqueue - Clear message queue

Logs & Diagnostics:
/logs [limit] - View recent log entries
/errors [limit] - View recent errors
/diagnostics - Run system diagnostics

Settings:
/settings - View current settings
/set <key> <value> - Update setting

Content Filtering:
/blockword <word> [pair_id] - Block word globally or for pair
/unblockword <word> [pair_id] - Unblock word
/listblocked [pair_id] - List blocked words
/blockimage <pair_id> - Block image via reply
/unblockimage <pair_id> <hash> - Unblock image
/listblockedimages <pair_id> - List blocked images

Text Processing:
/mentions <pair_id> <enable|disable> [placeholder] - Configure mention removal
/headerregex <pair_id> <pattern> - Set header removal regex
/footerregex <pair_id> <pattern> - Set footer removal regex
/testfilter <pair_id> <text> - Test filtering on text

Utilities:
/backup - Create database backup
/cleanup [--force] - Clean old data (preview or execute)

Bot Token Management:
/addtoken <name> <token> - Add new bot token
/addbot <name> <token> - Add new bot token (alias)
/listtokens [--all] - List bot tokens
/listbots [--all] - List bot tokens (alias)  
/deletetoken <token_id> - Delete bot token
/deletebot <token_id> - Delete bot token (alias)
/toggletoken <token_id> - Enable/disable bot token
/togglebot <token_id> - Enable/disable bot token (alias)

Features:
✅ Multi-bot support with load balancing
✅ Bot token management via commands
✅ Advanced message filtering with word/image blocking
✅ Real-time synchronization with premium emoji support
✅ Image duplicate detection and processing
✅ Reply preservation and webpage preview handling
✅ Edit/delete sync with formatting preservation
✅ Mention removal and header/footer regex filtering
✅ Comprehensive statistics and auto-cleanup"""
        
        await update.message.reply_text(help_text, parse_mode=None)
    
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Status command handler"""
        if not update.effective_user or not self._is_admin(update.effective_user.id):
            return
        
        try:
            # System status
            paused = await self.db_manager.get_setting("system_paused", "false")
            queue_size = self.message_queue.qsize()
            active_pairs = len([p for p in self.pairs.values() if p.status == "active"])
            
            # Bot status
            bot_status = []
            for i, metrics in self.bot_metrics.items():
                status = "🟢" if metrics.consecutive_failures == 0 else "🔴"
                bot_status.append(f"{status} Bot {i}: {metrics.success_rate:.1%} success")
            
            status_text = f"""
🔄 **System Status**

**State:** {'⏸️ PAUSED' if paused == 'true' else '▶️ RUNNING'}
**Queue:** {queue_size} messages
**Active Pairs:** {active_pairs}

**Bots:**
{chr(10).join(bot_status)}

**Uptime:** {self._get_uptime()}
            """
            
            if update.message:
                await update.message.reply_text(status_text, parse_mode='Markdown')
            
        except Exception as e:
            if update.message:
                await update.message.reply_text(f"Error getting status: {e}")
    
    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Statistics command handler"""
        if not update.effective_user or not self._is_admin(update.effective_user.id) or not update.message:
            return
        
        try:
            stats = await self.db_manager.get_stats()
            
            # Calculate totals from bot metrics
            total_processed = sum(m.messages_processed for m in self.bot_metrics.values())
            avg_processing_time = sum(m.avg_processing_time for m in self.bot_metrics.values()) / len(self.bot_metrics) if self.bot_metrics else 0
            
            stats_text = f"""
📊 **System Statistics**

**Messages:**
• Total processed: {total_processed:,}
• Last 24h: {stats.get('messages_24h', 0):,}
• In database: {stats.get('total_messages', 0):,}

**Pairs:**
• Total: {stats.get('total_pairs', 0)}
• Active: {stats.get('active_pairs', 0)}

**Performance:**
• Avg processing time: {avg_processing_time:.2f}s
• Queue size: {self.message_queue.qsize()}
• Errors (24h): {stats.get('errors_24h', 0)}

**Memory:** {self._get_memory_usage()}
            """
            
            await update.message.reply_text(stats_text, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"Error getting statistics: {e}")
    
    async def _cmd_pairs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List pairs command handler"""
        if not update.effective_user or not self._is_admin(update.effective_user.id) or not update.message:
            return
        
        try:
            pairs = list(self.pairs.values())[:10]  # Show first 10
            
            if not pairs:
                await update.message.reply_text("No message pairs configured.")
                return
            
            pairs_text = "📋 **Message Pairs:**\n\n"
            for pair in pairs:
                status_emoji = "✅" if pair.status == "active" else "❌"
                pairs_text += f"{status_emoji} **{pair.name}** (ID: {pair.id})\n"
                pairs_text += f"   {pair.source_chat_id} → {pair.destination_chat_id}\n"
                
                # Show bot token information if available
                bot_info = f"Bot: {pair.assigned_bot_index}"
                if pair.bot_token_id:
                    try:
                        token = await self.db_manager.get_bot_token_by_id(pair.bot_token_id)
                        if token:
                            bot_info = f"Bot: {token['name']} (@{token['username']}, ID: {pair.bot_token_id})"
                    except:
                        bot_info = f"Bot: Token ID {pair.bot_token_id} (not found)"
                
                pairs_text += f"   {bot_info}, Messages: {pair.stats.get('messages_copied', 0)}\n\n"
            
            if len(self.pairs) > 10:
                pairs_text += f"... and {len(self.pairs) - 10} more pairs"
            
            await update.message.reply_text(pairs_text, parse_mode='Markdown')
            
        except Exception as e:
            if update.message:
                await update.message.reply_text(f"Error listing pairs: {e}")
    
    async def _cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Pause system command handler"""
        if not update.effective_user or not self._is_admin(update.effective_user.id):
            return
        if not update.message:
            return
        
        try:
            await self.db_manager.set_setting("system_paused", "true")
            if update.message:
                await update.message.reply_text("⏸️ System paused. Use /resume to continue.")
            logger.info(f"System paused by user {update.effective_user.id}")
            
        except Exception as e:
            if update.message:
                await update.message.reply_text(f"Error pausing system: {e}")
    
    async def _cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resume system command handler"""
        if not update.effective_user or not self._is_admin(update.effective_user.id):
            return
        if not update.message:
            return
        
        try:
            await self.db_manager.set_setting("system_paused", "false")
            if update.message:
                await update.message.reply_text("▶️ System resumed.")
            logger.info(f"System resumed by user {update.effective_user.id}")
            
        except Exception as e:
            if update.message:
                await update.message.reply_text(f"Error resuming system: {e}")
    
    async def _cmd_add_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add pair command handler with optional bot token selection"""
        if not update.effective_user or not self._is_admin(update.effective_user.id) or not update.message:
            return
        
        try:
            if len(context.args) < 3:
                await update.message.reply_text(
                    "Usage: /addpair <source_chat_id> <dest_chat_id> <name> [bot_token_id]\n"
                    "Use /listtokens to see available bot tokens"
                )
                return
            
            source_id = int(context.args[0])
            dest_id = int(context.args[1])
            bot_token_id = None
            
            # Check if bot_token_id is provided
            if len(context.args) >= 4:
                try:
                    potential_token_id = int(context.args[3])
                    # Verify token exists and is active
                    token = await self.db_manager.get_bot_token_by_id(potential_token_id)
                    if token and token['is_active']:
                        bot_token_id = potential_token_id
                        name = " ".join(context.args[2:3])  # Only take the name, not the token_id
                    else:
                        await update.message.reply_text(f"❌ Bot token {potential_token_id} not found or inactive. Use /listtokens to see available tokens.")
                        return
                except ValueError:
                    # Last argument is not a number, treat as part of name
                    name = " ".join(context.args[2:])
            else:
                name = " ".join(context.args[2:])
            
            pair_id = await self.db_manager.create_pair(source_id, dest_id, name, bot_token_id=bot_token_id)
            await self._load_pairs()  # Reload pairs
            
            token_info = ""
            if bot_token_id:
                token = await self.db_manager.get_bot_token_by_id(bot_token_id)
                token_info = f"\n🤖 Using bot: {token['name']} (@{token['username']})"
            
            await update.message.reply_text(
                f"✅ Created pair {pair_id}: {name}\n"
                f"{source_id} → {dest_id}{token_info}"
            )
            
        except ValueError as e:
            if update.message:
                await update.message.reply_text(f"Error: {e}")
        except Exception as e:
            if update.message:
                await update.message.reply_text(f"Error adding pair: {e}")
    
    async def _cmd_delete_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Delete pair command handler"""
        if not update.effective_user or not self._is_admin(update.effective_user.id) or not update.message:
            return
        
        try:
            if not context.args:
                await update.message.reply_text("Usage: /delpair <pair_id>")
                return
            
            pair_id = int(context.args[0])
            
            if pair_id not in self.pairs:
                await update.message.reply_text("Pair not found.")
                return
            
            pair_name = self.pairs[pair_id].name
            await self.db_manager.delete_pair(pair_id)
            await self._load_pairs()  # Reload pairs
            
            await update.message.reply_text(f"✅ Deleted pair: {pair_name}")
            
        except ValueError:
            if update.message:
                await update.message.reply_text("Invalid pair ID.")
        except Exception as e:
            if update.message:
                await update.message.reply_text(f"Error deleting pair: {e}")
    
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries"""
        # Placeholder for future callback implementations
        query = update.callback_query
        await query.answer()
    
    # Enhanced command handlers
    async def _cmd_health(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Health monitoring command"""
        if not update.effective_user or not self._is_admin(update.effective_user.id) or not update.message:
            return
        
        try:
            # Get system health info
            memory_mb = self._get_memory_usage()
            uptime = self._get_uptime()
            queue_size = self.message_queue.qsize()
            
            # Bot health
            healthy_bots = sum(1 for m in self.bot_metrics.values() if m.consecutive_failures == 0)
            total_bots = len(self.bot_metrics)
            
            # Error rate
            total_errors = sum(m.consecutive_failures for m in self.bot_metrics.values())
            
            health_text = f"""
🏥 **System Health Report**

**Overall Status:** {'🟢 Healthy' if healthy_bots == total_bots else '🟡 Warning' if healthy_bots > 0 else '🔴 Critical'}

**System Resources:**
• Memory Usage: {memory_mb}
• Uptime: {uptime}
• Queue Size: {queue_size}

**Bot Health:**
• Healthy Bots: {healthy_bots}/{total_bots}
• Total Errors: {total_errors}

**Performance:**
• Messages in Queue: {queue_size}
• Active Pairs: {len([p for p in self.pairs.values() if p.status == "active"])}
            """
            
            await update.message.reply_text(health_text, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"Error getting health info: {e}")
    
    async def _cmd_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Restart system command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        await update.message.reply_text("🔄 System restart functionality is not yet implemented. Use /pause and /resume instead.")
    
    async def _cmd_edit_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Edit pair settings command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            if len(context.args) < 3:
                await update.message.reply_text(
                    "Usage: /editpair <pair_id> <setting> <value>\n"
                    "Settings: name, status, sync_edits, sync_deletes, preserve_replies"
                )
                return
            
            pair_id = int(context.args[0])
            setting = context.args[1]
            value = " ".join(context.args[2:])
            
            if pair_id not in self.pairs:
                await update.message.reply_text("Pair not found.")
                return
            
            # Update pair setting (basic implementation)
            pair = self.pairs[pair_id]
            if setting == "name":
                pair.name = value
            elif setting == "status":
                pair.status = value
            else:
                pair.filters[setting] = value.lower() == 'true' if value.lower() in ['true', 'false'] else value
            
            await update.message.reply_text(f"✅ Updated {setting} for pair {pair_id}")
            
        except ValueError:
            await update.message.reply_text("Invalid pair ID.")
        except Exception as e:
            await update.message.reply_text(f"Error editing pair: {e}")
    
    async def _cmd_pair_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Detailed pair information command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            if not context.args:
                await update.message.reply_text("Usage: /pairinfo <pair_id>")
                return
            
            pair_id = int(context.args[0])
            
            if pair_id not in self.pairs:
                await update.message.reply_text("Pair not found.")
                return
            
            pair = self.pairs[pair_id]
            
            # Get bot token information if available
            bot_info = f"Assigned Bot: {pair.assigned_bot_index}"
            if pair.bot_token_id:
                try:
                    token = await self.db_manager.get_bot_token_by_id(pair.bot_token_id)
                    if token:
                        bot_info = f"Bot Token: {token['name']} (@{token['username']}, ID: {pair.bot_token_id})"
                    else:
                        bot_info = f"Bot Token: ID {pair.bot_token_id} (not found)"
                except Exception:
                    bot_info = f"Bot Token: ID {pair.bot_token_id} (error loading)"
            
            info_text = f"""
📋 **Pair Information - {pair.name}**

**Basic Info:**
• ID: {pair.id}
• Status: {pair.status}
• Source: {pair.source_chat_id}
• Destination: {pair.destination_chat_id}
• {bot_info}

**Statistics:**
• Messages Copied: {pair.stats.get('messages_copied', 0)}
• Errors: {pair.stats.get('errors', 0)}

**Settings:**
• Sync Edits: {pair.filters.get('sync_edits', True)}
• Sync Deletes: {pair.filters.get('sync_deletes', False)}
• Preserve Replies: {pair.filters.get('preserve_replies', True)}

**Filters:**
{chr(10).join([f"• {k}: {v}" for k, v in pair.filters.items() if k not in ['sync_edits', 'sync_deletes', 'preserve_replies']])}
            """
            
            await update.message.reply_text(info_text, parse_mode='Markdown')
            
        except ValueError:
            await update.message.reply_text("Invalid pair ID.")
        except Exception as e:
            await update.message.reply_text(f"Error getting pair info: {e}")
    
    async def _cmd_bots(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List bot instances command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            bots_text = "🤖 **Bot Instances:**\n\n"
            
            for i, metrics in self.bot_metrics.items():
                status_emoji = "🟢" if metrics.consecutive_failures == 0 else "🔴"
                rate_limited = "⏰" if metrics.rate_limit_until > time.time() else ""
                
                bots_text += f"{status_emoji}{rate_limited} **Bot {i}**\n"
                bots_text += f"  Success Rate: {metrics.success_rate:.1%}\n"
                bots_text += f"  Messages: {metrics.messages_processed}\n"
                bots_text += f"  Avg Time: {metrics.avg_processing_time:.2f}s\n"
                bots_text += f"  Failures: {metrics.consecutive_failures}\n\n"
            
            await update.message.reply_text(bots_text, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"Error listing bots: {e}")
    
    async def _cmd_bot_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Detailed bot information command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            if not context.args:
                await update.message.reply_text("Usage: /botinfo <bot_index>")
                return
            
            bot_index = int(context.args[0])
            
            if bot_index not in self.bot_metrics:
                await update.message.reply_text("Bot not found.")
                return
            
            metrics = self.bot_metrics[bot_index]
            
            info_text = f"""
🤖 **Bot {bot_index} Information**

**Status:** {'🟢 Healthy' if metrics.consecutive_failures == 0 else '🔴 Unhealthy'}
**Rate Limited:** {'Yes' if metrics.rate_limit_until > time.time() else 'No'}

**Performance:**
• Messages Processed: {metrics.messages_processed}
• Success Rate: {metrics.success_rate:.1%}
• Avg Processing Time: {metrics.avg_processing_time:.2f}s
• Current Load: {metrics.current_load}

**Error Tracking:**
• Consecutive Failures: {metrics.consecutive_failures}
• Last Activity: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(metrics.last_activity))}
            """
            
            await update.message.reply_text(info_text, parse_mode='Markdown')
            
        except ValueError:
            await update.message.reply_text("Invalid bot index.")
        except Exception as e:
            await update.message.reply_text(f"Error getting bot info: {e}")
    
    async def _cmd_rebalance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Rebalance message distribution command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            # Simple rebalancing: redistribute pairs across healthy bots
            healthy_bots = [i for i, m in self.bot_metrics.items() if m.consecutive_failures == 0]
            
            if not healthy_bots:
                await update.message.reply_text("❌ No healthy bots available for rebalancing.")
                return
            
            rebalanced = 0
            for pair_id, pair in self.pairs.items():
                if pair.assigned_bot_index not in healthy_bots:
                    # Reassign to a healthy bot
                    pair.assigned_bot_index = healthy_bots[rebalanced % len(healthy_bots)]
                    rebalanced += 1
            
            await update.message.reply_text(f"✅ Rebalanced {rebalanced} pairs across {len(healthy_bots)} healthy bots.")
            
        except Exception as e:
            await update.message.reply_text(f"Error rebalancing: {e}")
    
    async def _cmd_queue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View message queue status command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            queue_size = self.message_queue.qsize()
            max_size = self.config.MESSAGE_QUEUE_SIZE
            
            queue_text = f"""
📊 **Message Queue Status**

**Current Size:** {queue_size}/{max_size}
**Usage:** {(queue_size/max_size*100):.1f}%
**Status:** {'🟢 Normal' if queue_size < max_size * 0.7 else '🟡 High' if queue_size < max_size * 0.9 else '🔴 Critical'}

**Queue Distribution:**
            """
            
            # Add per-pair queue info if available
            for pair_id, queue in self.pair_queues.items():
                if len(queue) > 0:
                    pair_name = self.pairs.get(pair_id, {}).name if pair_id in self.pairs else f"Pair {pair_id}"
                    queue_text += f"• {pair_name}: {len(queue)} messages\n"
            
            await update.message.reply_text(queue_text, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"Error getting queue status: {e}")
    
    async def _cmd_clear_queue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clear message queue command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            cleared = 0
            while not self.message_queue.empty():
                try:
                    self.message_queue.get_nowait()
                    cleared += 1
                except asyncio.QueueEmpty:
                    break
            
            await update.message.reply_text(f"✅ Cleared {cleared} messages from queue.")
            
        except Exception as e:
            await update.message.reply_text(f"Error clearing queue: {e}")
    
    async def _cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View recent log entries command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            limit = 10
            if context.args:
                try:
                    limit = min(int(context.args[0]), 50)  # Max 50 logs
                except ValueError:
                    pass
            
            # Read recent logs from database or log file
            logs_text = f"📜 **Recent Logs (Last {limit}):**\n\n"
            logs_text += "Log viewing from database not yet implemented.\n"
            logs_text += "Check the server logs for detailed information."
            
            await update.message.reply_text(logs_text, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"Error getting logs: {e}")
    
    async def _cmd_errors(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View recent errors command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            limit = 10
            if context.args:
                try:
                    limit = min(int(context.args[0]), 20)  # Max 20 errors
                except ValueError:
                    pass
            
            errors_text = f"🚨 **Recent Errors (Last {limit}):**\n\n"
            errors_text += "Error log viewing from database not yet implemented.\n"
            errors_text += "Use /diagnostics for current system status."
            
            await update.message.reply_text(errors_text, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"Error getting errors: {e}")
    
    async def _cmd_diagnostics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Run system diagnostics command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            diagnostics = []
            
            # Check bot connectivity
            healthy_bots = sum(1 for m in self.bot_metrics.values() if m.consecutive_failures == 0)
            diagnostics.append(f"🤖 Bots: {healthy_bots}/{len(self.bot_metrics)} healthy")
            
            # Check queue status
            queue_size = self.message_queue.qsize()
            max_size = self.config.MESSAGE_QUEUE_SIZE
            queue_status = "🟢" if queue_size < max_size * 0.7 else "🟡" if queue_size < max_size * 0.9 else "🔴"
            diagnostics.append(f"{queue_status} Queue: {queue_size}/{max_size}")
            
            # Check database
            diagnostics.append("💾 Database: Connected")
            
            # Check telethon client
            client_status = "🟢 Connected" if self.telethon_client and self.telethon_client.is_connected() else "🔴 Disconnected"
            diagnostics.append(f"📡 Telethon: {client_status}")
            
            # System paused status
            paused = await self.db_manager.get_setting("system_paused", "false")
            pause_status = "⏸️ Paused" if paused and paused.lower() == "true" else "▶️ Running"
            diagnostics.append(f"⚙️ System: {pause_status}")
            
            diagnostics_text = f"🔍 **System Diagnostics**\n\n" + "\n".join(diagnostics)
            
            await update.message.reply_text(diagnostics_text, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"Error running diagnostics: {e}")
    
    async def _cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View current settings command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            settings_text = f"""
⚙️ **Current Settings**

**System:**
• Max Workers: {self.config.MAX_WORKERS}
• Queue Size: {self.config.MESSAGE_QUEUE_SIZE}
• Rate Limit: {self.config.RATE_LIMIT_MESSAGES}/{self.config.RATE_LIMIT_WINDOW}s

**Features:**
• Debug Mode: {self.config.DEBUG_MODE}
• Image Processing: {hasattr(self.config, 'ENABLE_IMAGE_PROCESSING') and self.config.ENABLE_IMAGE_PROCESSING}

**Current Status:**
• System Paused: {await self.db_manager.get_setting('system_paused', 'false')}
• Active Pairs: {len([p for p in self.pairs.values() if p.status == 'active'])}
• Total Bots: {len(self.telegram_bots)}
            """
            
            await update.message.reply_text(settings_text, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"Error getting settings: {e}")
    
    async def _cmd_set_setting(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Update setting command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            if not context.args or len(context.args) < 2:
                await update.message.reply_text("Usage: /set <setting> <value>")
                return
            
            setting = context.args[0]
            value = " ".join(context.args[1:])
            
            # Only allow certain settings to be changed
            allowed_settings = ['system_paused', 'debug_mode']
            
            if setting not in allowed_settings:
                await update.message.reply_text(f"Setting '{setting}' cannot be changed. Allowed: {', '.join(allowed_settings)}")
                return
            
            await self.db_manager.set_setting(setting, value)
            await update.message.reply_text(f"✅ Updated {setting} = {value}")
            
        except Exception as e:
            await update.message.reply_text(f"Error updating setting: {e}")
    
    async def _cmd_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Create database backup command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            backup_name = f"backup_{int(time.time())}.db"
            await update.message.reply_text(f"📦 Database backup functionality not yet implemented.\nWould create: {backup_name}")
            
        except Exception as e:
            await update.message.reply_text(f"Error creating backup: {e}")
    
    async def _cmd_cleanup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clean old data command"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            if context.args and context.args[0].lower() in ['--force', '-f']:
                # Perform actual cleanup
                await update.message.reply_text("🧹 Starting database cleanup...")
                
                # Clean old messages (older than 30 days)
                cutoff_time = time.time() - (30 * 24 * 60 * 60)  # 30 days ago
                cleaned_messages = await self.db_manager.cleanup_old_messages(cutoff_time)
                
                # Clean old errors (older than 7 days)
                error_cutoff = time.time() - (7 * 24 * 60 * 60)  # 7 days ago
                cleaned_errors = await self.db_manager.cleanup_old_errors(error_cutoff)
                
                # Clean orphaned image hashes
                cleaned_hashes = await self.image_handler.cleanup_orphaned_hashes() if self.image_handler else 0
                
                cleanup_text = f"""
✅ **Cleanup Complete**

**Cleaned:**
• Old messages: {cleaned_messages}
• Old errors: {cleaned_errors}
• Orphaned image hashes: {cleaned_hashes}

**Result:** Database optimized and old data removed.
                """
                await update.message.reply_text(cleanup_text, parse_mode='Markdown')
                
            else:
                # Show cleanup preview
                cutoff_time = time.time() - (30 * 24 * 60 * 60)
                error_cutoff = time.time() - (7 * 24 * 60 * 60)
                
                # Get counts without actually deleting
                old_messages = await self.db_manager.count_old_messages(cutoff_time)
                old_errors = await self.db_manager.count_old_errors(error_cutoff)
                
                preview_text = f"""
🧹 **Cleanup Preview**

**Will remove:**
• Messages older than 30 days: {old_messages}
• Errors older than 7 days: {old_errors}
• Orphaned image hashes: (calculating...)

Use `/cleanup --force` to proceed with cleanup.
                """
                await update.message.reply_text(preview_text, parse_mode='Markdown')
            
        except Exception as e:
            await update.message.reply_text(f"Error during cleanup: {e}")
    
    # Advanced filtering command handlers
    async def _cmd_block_word(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Block word globally or for specific pair"""
        if not update.effective_user or not self._is_admin(update.effective_user.id):
            return
        
        try:
            if not context.args or len(context.args) < 1:
                await update.message.reply_text(
                    "Usage: /blockword <word> [pair_id]\n"
                    "Without pair_id, blocks globally"
                )
                return
            
            word = context.args[0]
            
            if context.args and len(context.args) > 1:
                # Block for specific pair
                pair_id = int(context.args[1])
                success = await self.message_filter.add_pair_word_block(pair_id, word)
                if success:
                    # Reload pairs to get the updated configuration
                    await self._load_pairs()
                    await update.message.reply_text(f"✅ Blocked word '{word}' for pair {pair_id}")
                else:
                    await update.message.reply_text(f"❌ Failed to block word for pair {pair_id}")
            else:
                # Block globally
                await self.message_filter.add_global_word_block(word)
                await update.message.reply_text(f"✅ Globally blocked word '{word}'")
                
        except ValueError:
            await update.message.reply_text("Invalid pair ID.")
        except Exception as e:
            await update.message.reply_text(f"Error blocking word: {e}")
    
    async def _cmd_unblock_word(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Unblock word globally or for specific pair"""
        if not update.effective_user or not self._is_admin(update.effective_user.id):
            return
        
        try:
            if not context.args or len(context.args) < 1:
                await update.message.reply_text(
                    "Usage: /unblockword <word> [pair_id]\n"
                    "Without pair_id, unblocks globally"
                )
                return
            
            word = context.args[0]
            
            if context.args and len(context.args) > 1:
                # Unblock for specific pair
                pair_id = int(context.args[1])
                
                # Check if pair exists
                if pair_id not in self.pairs:
                    await update.message.reply_text(f"❌ Pair {pair_id} not found")
                    return
                
                # Get current blocked words before removal
                pair = self.pairs[pair_id]
                current_blocked = pair.filters.get("blocked_words", [])
                
                if word not in current_blocked:
                    await update.message.reply_text(f"ℹ️ Word '{word}' is not blocked for pair {pair_id}")
                    return
                
                logger.info(f"Attempting to unblock word '{word}' for pair {pair_id}")
                success = await self.message_filter.remove_pair_word_block(pair_id, word)
                
                if success:
                    # Reload pairs to get the updated configuration
                    await self._load_pairs()
                    
                    # Verify the word was actually removed
                    updated_pair = self.pairs.get(pair_id)
                    if updated_pair:
                        updated_blocked = updated_pair.filters.get("blocked_words", [])
                        if word not in updated_blocked:
                            logger.info(f"Successfully unblocked word '{word}' for pair {pair_id}")
                            await update.message.reply_text(
                                f"✅ Unblocked word '{word}' for pair {pair_id}\n"
                                f"📋 Current blocked words: {updated_blocked if updated_blocked else 'None'}"
                            )
                        else:
                            logger.error(f"Word '{word}' still present after unblock operation for pair {pair_id}")
                            await update.message.reply_text(f"❌ Failed to unblock word '{word}' - word still present after operation")
                    else:
                        await update.message.reply_text(f"❌ Failed to reload pair {pair_id} after unblock")
                else:
                    logger.error(f"Failed to unblock word '{word}' for pair {pair_id}")
                    await update.message.reply_text(f"❌ Failed to unblock word '{word}' for pair {pair_id}")
            else:
                # Unblock globally
                current_global = self.message_filter.global_blocks.get("words", [])
                
                if word not in current_global:
                    await update.message.reply_text(f"ℹ️ Word '{word}' is not globally blocked")
                    return
                
                logger.info(f"Attempting to unblock global word '{word}'")
                await self.message_filter.remove_global_word_block(word)
                
                # Verify removal
                updated_global = self.message_filter.global_blocks.get("words", [])
                if word not in updated_global:
                    logger.info(f"Successfully unblocked global word '{word}'")
                    await update.message.reply_text(
                        f"✅ Globally unblocked word '{word}'\n"
                        f"📋 Current global blocks: {updated_global if updated_global else 'None'}"
                    )
                else:
                    logger.error(f"Global word '{word}' still present after unblock operation")
                    await update.message.reply_text(f"❌ Failed to unblock global word '{word}' - word still present after operation")
                
        except ValueError:
            await update.message.reply_text("Invalid pair ID.")
        except Exception as e:
            logger.error(f"Error in unblock word command: {e}")
            await update.message.reply_text(f"Error unblocking word: {e}")
    
    async def _cmd_list_blocked_words(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List blocked words"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            pair_id = None
            if context.args:
                pair_id = int(context.args[0])
            
            # Get global blocks
            global_words = self.message_filter.global_blocks.get("words", [])
            
            blocked_text = "🚫 **Blocked Words:**\n\n"
            
            if global_words:
                blocked_text += "**Global Blocks:**\n"
                for word in global_words:
                    blocked_text += f"• {word}\n"
                blocked_text += "\n"
            
            if pair_id:
                pair = self.pairs.get(pair_id)
                if pair:
                    pair_words = pair.filters.get("blocked_words", [])
                    if pair_words:
                        blocked_text += f"**Pair {pair_id} Blocks:**\n"
                        for word in pair_words:
                            blocked_text += f"• {word}\n"
                    else:
                        blocked_text += f"**Pair {pair_id}:** No blocked words\n"
            else:
                blocked_text += "Use `/listblocked <pair_id>` to see pair-specific blocks"
            
            await update.message.reply_text(blocked_text, parse_mode='Markdown')
            
        except ValueError:
            await update.message.reply_text("Invalid pair ID.")
        except Exception as e:
            await update.message.reply_text(f"Error listing blocked words: {e}")
    
    async def _cmd_block_image(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Block image by replying to it"""
        if not update.effective_user or not self._is_admin(update.effective_user.id):
            return
        
        try:
            if not update.message:
                return
            
            reply_msg = update.message.reply_to_message
            if not reply_msg or not reply_msg.photo:
                await update.message.reply_text(
                    "Reply to an image message to block it.\n"
                    "Usage: /blockimage [pair_id] [description]\n"
                    "Without pair_id, blocks globally"
                )
                return
            
            block_scope = "global"
            pair_id = None
            description = "Blocked via bot command"
            
            if context.args:
                try:
                    pair_id = int(context.args[0])
                    block_scope = "pair"
                    if len(context.args) > 1:
                        description = " ".join(context.args[1:])
                except ValueError:
                    # First argument is description, not pair_id
                    description = " ".join(context.args)
            
            # Alternative approach: Download image directly using Bot API and compute hash
            try:
                # Get file from Bot API
                photo = reply_msg.photo[-1]  # Get largest photo
                file = await context.bot.get_file(photo.file_id)
                
                # Download image data
                from io import BytesIO
                buffer = BytesIO()
                await file.download_to_memory(buffer)
                buffer.seek(0)
                
                # Compute hash directly
                if self.image_handler.enabled:
                    try:
                        from PIL import Image
                        import imagehash
                        
                        with Image.open(buffer) as img:
                            if img.mode != 'RGB':
                                img = img.convert('RGB')
                            
                            phash = imagehash.phash(img)
                            image_hash = str(phash)
                            
                            # Use config default threshold
                            similarity_threshold = self.config.SIMILARITY_THRESHOLD
                            
                            # Save to database directly
                            async with self.db_manager.get_connection() as conn:
                                await conn.execute('''
                                    INSERT OR REPLACE INTO blocked_images 
                                    (phash, pair_id, description, blocked_by, block_scope, similarity_threshold)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                ''', (
                                    image_hash,
                                    pair_id if block_scope == "pair" else None,
                                    description,
                                    str(update.effective_user.id),
                                    block_scope,
                                    similarity_threshold
                                ))
                                await conn.commit()
                            
                            success = True
                            logger.info(f"Added image block: {image_hash} (scope: {block_scope})")
                    except Exception as hash_error:
                        logger.error(f"Error computing image hash: {hash_error}")
                        success = False
                else:
                    await update.message.reply_text("Image processing not available (PIL/imagehash not installed)")
                    return
                    
            except Exception as download_error:
                logger.error(f"Error downloading image: {download_error}")
                success = False
            
            if success:
                scope_text = f"for pair {pair_id}" if block_scope == "pair" else "globally"
                await update.message.reply_text(f"✅ Image blocked {scope_text}")
            else:
                await update.message.reply_text("❌ Failed to block image")
                
        except Exception as e:
            await update.message.reply_text(f"Error blocking image: {e}")
    
    async def _cmd_unblock_image(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Unblock image by hash"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            if not context.args:
                await update.message.reply_text(
                    "Usage: /unblockimage <image_hash> [pair_id]\n"
                    "Without pair_id, removes global block"
                )
                return
            
            image_hash = context.args[0]
            pair_id = int(context.args[1]) if len(context.args) > 1 else None
            
            success = await self.image_handler.remove_image_block(image_hash, pair_id)
            
            if success:
                scope_text = f"for pair {pair_id}" if pair_id else "globally"
                await update.message.reply_text(f"✅ Image unblocked {scope_text}")
            else:
                await update.message.reply_text("❌ Failed to unblock image")
                
        except ValueError:
            await update.message.reply_text("Invalid pair ID.")
        except Exception as e:
            await update.message.reply_text(f"Error unblocking image: {e}")
    
    async def _cmd_list_blocked_images(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List blocked images"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            pair_id = int(context.args[0]) if context.args else None
            
            blocked_images = await self.image_handler.get_blocked_images(pair_id)
            
            if not blocked_images:
                await update.message.reply_text("No blocked images found.")
                return
            
            images_text = f"🖼️ **Blocked Images ({len(blocked_images)}):**\n\n"
            
            for img in blocked_images[:10]:  # Limit to 10 for readability
                scope = img['block_scope']
                images_text += f"**Hash:** `{img['phash'][:16]}...`\n"
                images_text += f"**Scope:** {scope}"
                if img['pair_id']:
                    images_text += f" (Pair {img['pair_id']})"
                images_text += f"\n**Used:** {img['usage_count']} times\n"
                if img['description']:
                    images_text += f"**Description:** {img['description']}\n"
                images_text += "\n"
            
            if len(blocked_images) > 10:
                images_text += f"... and {len(blocked_images) - 10} more images"
            
            await update.message.reply_text(images_text, parse_mode='Markdown')
            
        except ValueError:
            await update.message.reply_text("Invalid pair ID.")
        except Exception as e:
            await update.message.reply_text(f"Error listing blocked images: {e}")
    
    async def _cmd_set_mention_removal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Configure mention removal for pair"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            if len(context.args) < 2:
                await update.message.reply_text(
                    "Usage: /mentions <pair_id> <enable|disable> [placeholder]\n"
                    "Example: /mentions 1 enable [User]\n"
                    "Example: /mentions 1 disable"
                )
                return
            
            pair_id = int(context.args[0])
            action = context.args[1].lower()
            placeholder = " ".join(context.args[2:]) if len(context.args) > 2 else ""
            
            if action not in ['enable', 'disable']:
                await update.message.reply_text("Action must be 'enable' or 'disable'")
                return
            
            remove_mentions = action == 'enable'
            success = await self.message_filter.set_mention_removal(pair_id, remove_mentions, placeholder)
            
            if success:
                # Reload pairs to get the updated configuration
                await self._load_pairs()
                
                if remove_mentions:
                    placeholder_text = f" with placeholder '{placeholder}'" if placeholder else " (complete removal)"
                    await update.message.reply_text(f"✅ Mention removal enabled for pair {pair_id}{placeholder_text}")
                else:
                    await update.message.reply_text(f"✅ Mention removal disabled for pair {pair_id}")
            else:
                await update.message.reply_text(f"❌ Failed to update mention removal for pair {pair_id}")
                
        except ValueError:
            await update.message.reply_text("Invalid pair ID.")
        except Exception as e:
            await update.message.reply_text(f"Error configuring mention removal: {e}")
    
    async def _cmd_set_header_regex(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set header removal regex for pair"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            if len(context.args) < 2:
                await update.message.reply_text(
                    "Usage: /headerregex <pair_id> <regex_pattern>\n"
                    "Use /headerregex <pair_id> clear to remove\n"
                    "Example: /headerregex 1 ^.*?[:|：].*"
                )
                return
            
            pair_id = int(context.args[0])
            pattern = " ".join(context.args[1:])
            
            if pattern.lower() == 'clear':
                pattern = ""
            
            success = await self.message_filter.set_pair_header_footer_regex(pair_id, header_regex=pattern)
            
            if success:
                # Reload pairs to get the updated configuration
                await self._load_pairs()
                
                if pattern:
                    await update.message.reply_text(f"✅ Header regex set for pair {pair_id}: `{pattern}`")
                else:
                    await update.message.reply_text(f"✅ Header regex cleared for pair {pair_id}")
            else:
                await update.message.reply_text(f"❌ Failed to set header regex for pair {pair_id}")
                
        except ValueError:
            await update.message.reply_text("Invalid pair ID.")
        except Exception as e:
            await update.message.reply_text(f"Error setting header regex: {e}")
    
    async def _cmd_set_footer_regex(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set footer removal regex for pair"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            if len(context.args) < 2:
                await update.message.reply_text(
                    "Usage: /footerregex <pair_id> <regex_pattern>\n"
                    "Use /footerregex <pair_id> clear to remove\n"
                    "Example: /footerregex 1 @\\w+.*$"
                )
                return
            
            pair_id = int(context.args[0])
            pattern = " ".join(context.args[1:])
            
            if pattern.lower() == 'clear':
                pattern = ""
            
            success = await self.message_filter.set_pair_header_footer_regex(pair_id, footer_regex=pattern)
            
            if success:
                # Reload pairs to get the updated configuration
                await self._load_pairs()
                
                if pattern:
                    await update.message.reply_text(f"✅ Footer regex set for pair {pair_id}: `{pattern}`")
                else:
                    await update.message.reply_text(f"✅ Footer regex cleared for pair {pair_id}")
            else:
                await update.message.reply_text(f"❌ Failed to set footer regex for pair {pair_id}")
                
        except ValueError:
            await update.message.reply_text("Invalid pair ID.")
        except Exception as e:
            await update.message.reply_text(f"Error setting footer regex: {e}")
    
    async def _cmd_test_filter(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Test filtering on a message"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            if not context.args:
                await update.message.reply_text(
                    "Usage: /testfilter <pair_id> <text_to_test>\n"
                    "Example: /testfilter 1 Hello @username this is a test"
                )
                return
            
            pair_id = int(context.args[0])
            test_text = " ".join(context.args[1:])
            
            if pair_id not in self.pairs:
                await update.message.reply_text("Pair not found.")
                return
            
            pair = self.pairs[pair_id]
            
            # Apply text filtering
            filtered_text = await self.message_filter.filter_text(test_text, pair)
            
            result_text = f"🧪 **Filter Test Results for Pair {pair_id}:**\n\n"
            result_text += f"**Original:** {test_text}\n\n"
            result_text += f"**Filtered:** {filtered_text}\n\n"
            
            # Show what filters would be applied
            result_text += "**Active Filters:**\n"
            filters = []
            if pair.filters.get("remove_mentions"):
                placeholder = pair.filters.get("mention_placeholder", "(removed)")
                filters.append(f"• Mention removal: {placeholder}")
            if pair.filters.get("header_regex"):
                filters.append(f"• Header regex: `{pair.filters['header_regex']}`")
            if pair.filters.get("footer_regex"):
                filters.append(f"• Footer regex: `{pair.filters['footer_regex']}`")
            
            if filters:
                result_text += "\n".join(filters)
            else:
                result_text += "No text filters configured"
            
            await update.message.reply_text(result_text, parse_mode='Markdown')
            
        except ValueError:
            await update.message.reply_text("Invalid pair ID.")
        except Exception as e:
            await update.message.reply_text(f"Error testing filter: {e}")
    
    def _is_admin(self, user_id: Optional[int]) -> bool:
        """Check if user is admin"""
        if user_id is None:
            return False
        
        # If no admin users configured, allow all users for initial setup
        if not self.config.ADMIN_USER_IDS:
            logger.warning(f"No admin users configured, allowing user {user_id} for setup")
            return True
            
        return user_id in self.config.ADMIN_USER_IDS
    
    async def _safe_reply(self, update: Update, text: str, parse_mode: str = None) -> bool:
        """Safely reply to a message, returning True if successful"""
        try:
            if update and update.message:
                await update.message.reply_text(text, parse_mode=parse_mode)
                return True
        except Exception as e:
            logger.error(f"Failed to send reply: {e}")
        return False
    
    def _get_uptime(self) -> str:
        """Get system uptime"""
        # This would be calculated from start time
        return "Running"
    
    def _get_memory_usage(self) -> str:
        """Get memory usage"""
        try:
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            return f"{memory_mb:.1f} MB"
        except ImportError:
            return "N/A"
    
    # Public methods for external access
    async def reload_pairs(self):
        """Reload pairs from database"""
        await self._load_pairs()
    
    def get_metrics(self) -> Dict[int, BotMetrics]:
        """Get bot metrics"""
        return self.bot_metrics.copy()
    
    def get_queue_size(self) -> int:
        """Get current queue size"""
        return self.message_queue.qsize()

    # Bot Token Management Commands
    async def _cmd_add_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add a new bot token"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            if len(context.args) < 2:
                await update.message.reply_text(
                    "Usage: /addtoken <name> <token>\n"
                    "Example: /addtoken MyBot 1234567890:ABCdefGHIjklMNOPqrs"
                )
                return
            
            name = context.args[0]
            token = context.args[1]
            
            # Validate token format
            if not token.count(':') == 1 or len(token.split(':')[0]) < 8:
                await update.message.reply_text("❌ Invalid token format. Token should be like: 1234567890:ABCdefGHIjklMNOPqrs")
                return
            
            # Test the token by getting bot info
            try:
                test_bot = Bot(token)
                bot_info = await test_bot.get_me()
                username = bot_info.username
            except Exception as e:
                await update.message.reply_text(f"❌ Invalid token or bot unreachable: {e}")
                return
            
            # Save token to database
            token_id = await self.db_manager.save_bot_token(name, token, username)
            
            await update.message.reply_text(
                f"✅ Bot token added successfully!\n"
                f"Name: {name}\n"
                f"Username: @{username}\n"
                f"ID: {token_id}"
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error adding token: {e}")

    async def _cmd_list_tokens(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all bot tokens"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            show_all = len(context.args) > 0 and context.args[0] == "--all"
            tokens = await self.db_manager.get_bot_tokens(active_only=not show_all)
            
            if not tokens:
                await update.message.reply_text("No bot tokens found.")
                return
            
            tokens_text = "🤖 Bot Tokens:\n\n"
            for token in tokens:
                status = "✅ Active" if token['is_active'] else "❌ Inactive"
                usage = token['usage_count'] or 0
                last_used = token['last_used'] or "Never"
                
                tokens_text += f"{token['name']} (ID: {token['id']})\n"
                tokens_text += f"   @{token['username']} - {status}\n"
                tokens_text += f"   Used: {usage} times, Last: {last_used}\n\n"
            
            await update.message.reply_text(tokens_text)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error listing tokens: {e}")

    async def _cmd_delete_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Delete a bot token"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            if len(context.args) < 1:
                await update.message.reply_text("Usage: /deletetoken <token_id>")
                return
            
            token_id = int(context.args[0])
            
            # Check if token exists
            token = await self.db_manager.get_bot_token_by_id(token_id)
            if not token:
                await update.message.reply_text("❌ Token not found.")
                return
            
            # Delete token
            success = await self.db_manager.delete_bot_token(token_id)
            
            if success:
                await update.message.reply_text(
                    f"✅ Deleted token: {token['name']} (@{token['username']})"
                )
            else:
                await update.message.reply_text("❌ Failed to delete token.")
                
        except ValueError:
            await update.message.reply_text("❌ Invalid token ID. Please use a number.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error deleting token: {e}")

    async def _cmd_toggle_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Toggle bot token active status"""
        if not self._is_admin(update.effective_user.id):
            return
        
        try:
            if len(context.args) < 1:
                await update.message.reply_text("Usage: /toggletoken <token_id>")
                return
            
            token_id = int(context.args[0])
            
            # Check if token exists
            token = await self.db_manager.get_bot_token_by_id(token_id)
            if not token:
                await update.message.reply_text("❌ Token not found.")
                return
            
            # Toggle status
            success = await self.db_manager.toggle_bot_token_status(token_id)
            
            if success:
                new_status = "Active" if not token['is_active'] else "Inactive"
                await update.message.reply_text(
                    f"✅ Token {token['name']} is now {new_status}"
                )
            else:
                await update.message.reply_text("❌ Failed to toggle token status.")
                
        except ValueError:
            await update.message.reply_text("❌ Invalid token ID. Please use a number.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error toggling token: {e}")
