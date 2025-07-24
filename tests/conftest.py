"""
Pytest configuration and fixtures for Telegram Bot System tests
"""

import pytest
import asyncio
import os
import tempfile
import shutil
from unittest.mock import AsyncMock, MagicMock
from typing import Dict, Any

# Test imports
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from database import DatabaseManager, MessagePair
from bot_manager import BotManager
from message_processor import MessageProcessor
from filters import MessageFilter
from image_handler import ImageHandler
from health_monitor import HealthMonitor

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def temp_dir():
    """Create temporary directory for tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.fixture
async def test_config():
    """Create test configuration."""
    config = Config()
    # Override with test values
    config.BOT_TOKENS = ["test_token_1", "test_token_2"]
    config.PRIMARY_BOT_TOKEN = "test_token_1"
    config.API_ID = "12345"
    config.API_HASH = "test_hash"
    config.PHONE_NUMBER = "+1234567890"
    config.DEBUG_MODE = True
    config.MAX_WORKERS = 2
    config.MESSAGE_QUEUE_SIZE = 100
    config.HEALTH_CHECK_INTERVAL = 5
    config.DASHBOARD_PORT = 5001
    config.ADMIN_USER_IDS = [123456789]
    return config

@pytest.fixture
async def test_db(temp_dir):
    """Create test database."""
    db_path = os.path.join(temp_dir, "test.db")
    db_manager = DatabaseManager(db_path)
    await db_manager.initialize()
    yield db_manager
    await db_manager.close()

@pytest.fixture
async def sample_pair(test_db):
    """Create sample message pair for testing."""
    pair_id = await test_db.create_pair(
        source_chat_id=-1001234567890,
        destination_chat_id=-1009876543210,
        name="Test Pair",
        bot_index=0
    )
    pair = await test_db.get_pair(pair_id)
    return pair

@pytest.fixture
def mock_telegram_bot():
    """Create mock Telegram bot."""
    bot = AsyncMock()
    bot.get_me.return_value = MagicMock(username="test_bot", id=123456789)
    bot.send_message.return_value = MagicMock(message_id=12345)
    bot.send_photo.return_value = MagicMock(message_id=12346)
    bot.send_video.return_value = MagicMock(message_id=12347)
    bot.send_document.return_value = MagicMock(message_id=12348)
    bot.edit_message_text.return_value = True
    bot.delete_message.return_value = True
    return bot

@pytest.fixture
def mock_telethon_event():
    """Create mock Telethon event."""
    event = MagicMock()
    event.id = 12345
    event.chat_id = -1001234567890
    event.text = "Test message"
    event.raw_text = "Test message"
    event.media = None
    event.is_reply = False
    event.reply_to_msg_id = None
    event.date = MagicMock()
    event.date.timestamp.return_value = 1640995200.0  # 2022-01-01
    event.entities = []
    event.fwd_from = None
    
    # Mock client and methods
    event.client = AsyncMock()
    event.get_sender = AsyncMock()
    event.download_media = AsyncMock()
    
    return event

@pytest.fixture
def mock_sender():
    """Create mock message sender."""
    sender = MagicMock()
    sender.id = 987654321
    sender.username = "test_user"
    sender.bot = False
    sender.verified = False
    return sender

@pytest.fixture
async def test_message_filter(test_db, test_config):
    """Create test message filter."""
    message_filter = MessageFilter(test_db, test_config)
    await message_filter.initialize()
    return message_filter

@pytest.fixture
async def test_image_handler(test_db, test_config):
    """Create test image handler."""
    image_handler = ImageHandler(test_db, test_config)
    return image_handler

@pytest.fixture
async def test_message_processor(test_db, test_config):
    """Create test message processor."""
    processor = MessageProcessor(test_db, test_config)
    await processor.initialize()
    return processor

@pytest.fixture
async def mock_bot_manager(test_db, test_config):
    """Create mock bot manager."""
    bot_manager = MagicMock()
    bot_manager.config = test_config
    bot_manager.db_manager = test_db
    bot_manager.running = True
    bot_manager.get_queue_size.return_value = 0
    bot_manager.get_metrics.return_value = {}
    bot_manager.reload_pairs = AsyncMock()
    return bot_manager

@pytest.fixture
async def test_health_monitor(mock_bot_manager, test_db):
    """Create test health monitor."""
    health_monitor = HealthMonitor(mock_bot_manager, test_db)
    return health_monitor

# Test data fixtures
@pytest.fixture
def sample_message_data():
    """Sample message data for testing."""
    return {
        'id': 12345,
        'chat_id': -1001234567890,
        'text': 'Test message content',
        'from_user_id': 987654321,
        'timestamp': 1640995200.0,
        'media_type': None,
        'has_media': False
    }

@pytest.fixture
def sample_filter_config():
    """Sample filter configuration."""
    return {
        "blocked_words": ["spam", "bad"],
        "remove_mentions": True,
        "mention_placeholder": "[User]",
        "preserve_replies": True,
        "sync_edits": True,
        "sync_deletes": False,
        "min_message_length": 5,
        "max_message_length": 1000,
        "allowed_media_types": ["photo", "video"],
        "block_forwards": False,
        "block_links": True,
        "custom_regex_filters": [r"test\d+"]
    }

@pytest.fixture
def sample_health_metrics():
    """Sample health metrics for testing."""
    return {
        'memory_mb': 150.5,
        'cpu_percent': 25.3,
        'queue_size': 15,
        'error_rate': 2.1,
        'bot_failures': 0
    }

# Async test utilities
@pytest.fixture
def async_test():
    """Decorator for async test functions."""
    def decorator(func):
        return pytest.mark.asyncio(func)
    return decorator

# Mock external services
@pytest.fixture
def mock_redis():
    """Mock Redis connection."""
    redis_mock = AsyncMock()
    redis_mock.get.return_value = None
    redis_mock.set.return_value = True
    redis_mock.delete.return_value = True
    redis_mock.exists.return_value = False
    return redis_mock

@pytest.fixture
def mock_psutil():
    """Mock psutil for system monitoring."""
    import sys
    from unittest.mock import MagicMock
    
    psutil_mock = MagicMock()
    process_mock = MagicMock()
    
    # Memory info
    memory_info = MagicMock()
    memory_info.rss = 157286400  # ~150MB
    process_mock.memory_info.return_value = memory_info
    
    # CPU percent
    process_mock.cpu_percent.return_value = 25.5
    
    # Disk usage
    disk_usage = MagicMock()
    disk_usage.percent = 45.2
    psutil_mock.disk_usage.return_value = disk_usage
    
    psutil_mock.Process.return_value = process_mock
    
    # Mock the module
    sys.modules['psutil'] = psutil_mock
    return psutil_mock

@pytest.fixture
def mock_pil():
    """Mock PIL for image processing."""
    import sys
    from unittest.mock import MagicMock
    
    pil_mock = MagicMock()
    image_mock = MagicMock()
    
    # Image operations
    image_mock.mode = 'RGB'
    image_mock.convert.return_value = image_mock
    
    pil_mock.Image.open.return_value.__enter__ = lambda x: image_mock
    pil_mock.Image.open.return_value.__exit__ = lambda x, y, z, w: None
    
    sys.modules['PIL'] = MagicMock()
    sys.modules['PIL.Image'] = pil_mock.Image
    return pil_mock

@pytest.fixture
def mock_imagehash():
    """Mock imagehash for image hashing."""
    import sys
    from unittest.mock import MagicMock
    
    imagehash_mock = MagicMock()
    
    # Mock hash object
    hash_obj = MagicMock()
    hash_obj.__str__ = lambda x: "abcdef1234567890"
    hash_obj.__sub__ = lambda x, y: 3  # Hamming distance
    
    imagehash_mock.phash.return_value = hash_obj
    imagehash_mock.hex_to_hash.return_value = hash_obj
    
    sys.modules['imagehash'] = imagehash_mock
    return imagehash_mock

# Cleanup fixtures
@pytest.fixture(autouse=True)
async def cleanup_after_test():
    """Cleanup after each test."""
    yield
    # Cleanup code here if needed
    pass

# Test environment setup
@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment."""
    # Set test environment variables
    os.environ['TESTING'] = 'true'
    os.environ['DEBUG_MODE'] = 'true'
    
    yield
    
    # Cleanup
    if 'TESTING' in os.environ:
        del os.environ['TESTING']
