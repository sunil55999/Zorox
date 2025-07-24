"""
Tests for Bot Manager functionality
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from bot_manager import BotManager, MessagePriority, QueuedMessage, BotMetrics
from database import MessagePair


class TestBotManager:
    """Test suite for BotManager"""
    
    @pytest.mark.asyncio
    async def test_initialization(self, test_db, test_config):
        """Test bot manager initialization"""
        with patch('bot_manager.TelegramClient'), \
             patch('bot_manager.Bot'), \
             patch('bot_manager.Application'):
            
            bot_manager = BotManager(test_db, test_config)
            
            # Test initial state
            assert bot_manager.db_manager == test_db
            assert bot_manager.config == test_config
            assert not bot_manager.running
            assert len(bot_manager.worker_tasks) == 0
            assert len(bot_manager.pairs) == 0
    
    @pytest.mark.asyncio
    async def test_bot_metrics_update(self):
        """Test bot metrics updating"""
        metrics = BotMetrics()
        
        # Test success rate updates
        initial_rate = metrics.success_rate
        
        # Success should improve rate
        metrics.update_success_rate(True)
        assert metrics.consecutive_failures == 0
        
        # Failure should worsen rate and increase failures
        metrics.update_success_rate(False)
        assert metrics.consecutive_failures == 1
        assert metrics.success_rate < initial_rate
    
    @pytest.mark.asyncio
    async def test_message_priority_ordering(self):
        """Test message priority ordering"""
        import time
        
        # Create messages with different priorities
        urgent_msg = QueuedMessage(
            data={'test': 'urgent'},
            priority=MessagePriority.URGENT,
            timestamp=time.time(),
            pair_id=1,
            bot_index=0
        )
        
        normal_msg = QueuedMessage(
            data={'test': 'normal'},
            priority=MessagePriority.NORMAL,
            timestamp=time.time(),
            pair_id=1,
            bot_index=0
        )
        
        # Urgent should have higher priority
        assert urgent_msg < normal_msg
        
        # Test timestamp ordering for same priority
        older_msg = QueuedMessage(
            data={'test': 'older'},
            priority=MessagePriority.NORMAL,
            timestamp=time.time() - 100,
            pair_id=1,
            bot_index=0
        )
        
        newer_msg = QueuedMessage(
            data={'test': 'newer'},
            priority=MessagePriority.NORMAL,
            timestamp=time.time(),
            pair_id=1,
            bot_index=0
        )
        
        # Older message should be processed first
        assert older_msg < newer_msg
    
    @pytest.mark.asyncio
    async def test_load_pairs(self, test_db, test_config, sample_pair):
        """Test loading pairs from database"""
        with patch('bot_manager.TelegramClient'), \
             patch('bot_manager.Bot'), \
             patch('bot_manager.Application'):
            
            bot_manager = BotManager(test_db, test_config)
            await bot_manager._load_pairs()
            
            # Should have loaded the sample pair
            assert len(bot_manager.pairs) == 1
            assert sample_pair.id in bot_manager.pairs
            assert sample_pair.source_chat_id in bot_manager.source_to_pairs
    
    @pytest.mark.asyncio
    async def test_queue_message(self, test_db, test_config):
        """Test message queueing"""
        with patch('bot_manager.TelegramClient'), \
             patch('bot_manager.Bot'), \
             patch('bot_manager.Application'):
            
            bot_manager = BotManager(test_db, test_config)
            
            # Queue a test message
            message_data = {'type': 'new_message', 'content': 'test'}
            await bot_manager._queue_message(
                message_data, 
                MessagePriority.NORMAL, 
                1, 
                0
            )
            
            # Should have one message in queue
            assert bot_manager.message_queue.qsize() == 1
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, test_db, test_config):
        """Test rate limiting functionality"""
        with patch('bot_manager.TelegramClient'), \
             patch('bot_manager.Bot'), \
             patch('bot_manager.Application'):
            
            bot_manager = BotManager(test_db, test_config)
            bot_index = 0
            
            # Initially should allow messages
            assert bot_manager._check_rate_limit(bot_index)
            
            # Fill up rate limit
            for _ in range(test_config.RATE_LIMIT_MESSAGES):
                bot_manager._check_rate_limit(bot_index)
            
            # Should now be rate limited
            assert not bot_manager._check_rate_limit(bot_index)
    
    @pytest.mark.asyncio
    async def test_handle_new_message(self, test_db, test_config, sample_pair, mock_telethon_event):
        """Test handling new message events"""
        with patch('bot_manager.TelegramClient'), \
             patch('bot_manager.Bot'), \
             patch('bot_manager.Application'):
            
            bot_manager = BotManager(test_db, test_config)
            await bot_manager._load_pairs()
            
            # Set up event for our test pair
            mock_telethon_event.chat_id = sample_pair.source_chat_id
            
            # Handle the message
            await bot_manager._handle_new_message(mock_telethon_event)
            
            # Should have queued the message
            assert bot_manager.message_queue.qsize() == 1
    
    @pytest.mark.asyncio
    async def test_handle_message_edit(self, test_db, test_config, sample_pair, mock_telethon_event):
        """Test handling message edit events"""
        with patch('bot_manager.TelegramClient'), \
             patch('bot_manager.Bot'), \
             patch('bot_manager.Application'):
            
            bot_manager = BotManager(test_db, test_config)
            await bot_manager._load_pairs()
            
            # Enable edit sync
            sample_pair.filters['sync_edits'] = True
            await test_db.update_pair(sample_pair)
            await bot_manager._load_pairs()
            
            # Set up event
            mock_telethon_event.chat_id = sample_pair.source_chat_id
            
            # Handle the edit
            await bot_manager._handle_message_edited(mock_telethon_event)
            
            # Should have queued the edit
            assert bot_manager.message_queue.qsize() == 1
    
    @pytest.mark.asyncio
    async def test_handle_message_delete(self, test_db, test_config, sample_pair, mock_telethon_event):
        """Test handling message delete events"""
        with patch('bot_manager.TelegramClient'), \
             patch('bot_manager.Bot'), \
             patch('bot_manager.Application'):
            
            bot_manager = BotManager(test_db, test_config)
            await bot_manager._load_pairs()
            
            # Enable delete sync
            sample_pair.filters['sync_deletes'] = True
            await test_db.update_pair(sample_pair)
            await bot_manager._load_pairs()
            
            # Set up event
            mock_telethon_event.chat_id = sample_pair.source_chat_id
            mock_telethon_event.deleted_ids = [12345]
            
            # Handle the deletion
            await bot_manager._handle_message_deleted(mock_telethon_event)
            
            # Should have queued the deletion
            assert bot_manager.message_queue.qsize() == 1
    
    @pytest.mark.asyncio
    async def test_process_queued_message_success(self, test_db, test_config, sample_pair, mock_telegram_bot):
        """Test successful message processing"""
        with patch('bot_manager.TelegramClient'), \
             patch('bot_manager.Bot'), \
             patch('bot_manager.Application'):
            
            bot_manager = BotManager(test_db, test_config)
            bot_manager.telegram_bots = [mock_telegram_bot]
            bot_manager.bot_metrics[0] = BotMetrics()
            await bot_manager._load_pairs()
            
            # Mock message processor
            mock_processor = AsyncMock()
            mock_processor.process_new_message.return_value = True
            bot_manager.message_processor = mock_processor
            
            # Create queued message
            queued_msg = QueuedMessage(
                data={
                    'type': 'new_message',
                    'event': MagicMock(),
                    'pair_id': sample_pair.id
                },
                priority=MessagePriority.NORMAL,
                timestamp=1640995200.0,
                pair_id=sample_pair.id,
                bot_index=0
            )
            
            # Process the message
            result = await bot_manager._process_queued_message(queued_msg)
            
            # Should succeed
            assert result is True
            assert mock_processor.process_new_message.called
    
    @pytest.mark.asyncio
    async def test_message_worker_paused_system(self, test_db, test_config):
        """Test message worker behavior when system is paused"""
        with patch('bot_manager.TelegramClient'), \
             patch('bot_manager.Bot'), \
             patch('bot_manager.Application'):
            
            bot_manager = BotManager(test_db, test_config)
            bot_manager.running = True
            
            # Set system as paused
            await test_db.set_setting("system_paused", "true")
            
            # Add a message to queue
            await bot_manager.message_queue.put(
                QueuedMessage(
                    data={'test': 'data'},
                    priority=MessagePriority.NORMAL,
                    timestamp=1640995200.0,
                    pair_id=1,
                    bot_index=0
                )
            )
            
            initial_queue_size = bot_manager.message_queue.qsize()
            
            # Start worker briefly
            worker_task = asyncio.create_task(bot_manager._message_worker(0))
            await asyncio.sleep(0.1)  # Let it process
            worker_task.cancel()
            
            # Queue should still have the message (not processed due to pause)
            assert bot_manager.message_queue.qsize() == initial_queue_size
    
    @pytest.mark.asyncio
    async def test_get_message_priority(self, test_db, test_config, sample_pair):
        """Test message priority determination"""
        with patch('bot_manager.TelegramClient'), \
             patch('bot_manager.Bot'), \
             patch('bot_manager.Application'):
            
            bot_manager = BotManager(test_db, test_config)
            
            # Test reply message with preserve_replies enabled
            reply_event = MagicMock()
            reply_event.is_reply = True
            reply_event.media = None
            sample_pair.filters['preserve_replies'] = True
            
            priority = bot_manager._get_message_priority(reply_event, sample_pair)
            assert priority == MessagePriority.HIGH
            
            # Test media message
            media_event = MagicMock()
            media_event.is_reply = False
            media_event.media = MagicMock()
            
            priority = bot_manager._get_message_priority(media_event, sample_pair)
            assert priority == MessagePriority.HIGH
            
            # Test normal message
            normal_event = MagicMock()
            normal_event.is_reply = False
            normal_event.media = None
            
            priority = bot_manager._get_message_priority(normal_event, sample_pair)
            assert priority == MessagePriority.NORMAL
    
    @pytest.mark.asyncio
    async def test_reload_pairs(self, test_db, test_config, sample_pair):
        """Test reloading pairs from database"""
        with patch('bot_manager.TelegramClient'), \
             patch('bot_manager.Bot'), \
             patch('bot_manager.Application'):
            
            bot_manager = BotManager(test_db, test_config)
            
            # Initially no pairs loaded
            assert len(bot_manager.pairs) == 0
            
            # Reload pairs
            await bot_manager.reload_pairs()
            
            # Should now have the sample pair
            assert len(bot_manager.pairs) == 1
            assert sample_pair.id in bot_manager.pairs
    
    @pytest.mark.asyncio
    async def test_bot_health_check(self, test_db, test_config, mock_telegram_bot):
        """Test bot health checking"""
        with patch('bot_manager.TelegramClient'), \
             patch('bot_manager.Bot'), \
             patch('bot_manager.Application'):
            
            bot_manager = BotManager(test_db, test_config)
            bot_manager.telegram_bots = [mock_telegram_bot]
            bot_manager.bot_metrics[0] = BotMetrics()
            bot_manager.running = True
            
            # Mock successful health check
            mock_telegram_bot.get_me.return_value = MagicMock(username="test_bot")
            
            # Run health monitor once
            health_task = asyncio.create_task(bot_manager._health_monitor())
            await asyncio.sleep(0.1)
            health_task.cancel()
            
            # Should have no consecutive failures
            assert bot_manager.bot_metrics[0].consecutive_failures == 0
    
    @pytest.mark.asyncio
    async def test_error_logging(self, test_db, test_config):
        """Test error logging functionality"""
        with patch('bot_manager.TelegramClient'), \
             patch('bot_manager.Bot'), \
             patch('bot_manager.Application'):
            
            bot_manager = BotManager(test_db, test_config)
            
            # Log an error
            await bot_manager._log_error(
                "test_error",
                "Test error message",
                "Stack trace here",
                pair_id=1,
                bot_index=0
            )
            
            # Verify error was logged to database
            async with test_db.get_connection() as conn:
                cursor = await conn.execute(
                    'SELECT * FROM error_logs WHERE error_type = ?',
                    ("test_error",)
                )
                row = await cursor.fetchone()
                
                assert row is not None
                assert row[2] == "Test error message"  # error_message column
