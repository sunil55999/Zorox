"""
Telegram Message Copying Bot - Production Ready
Complete multi-bot message copying system with advanced filtering
"""

import asyncio
import logging
import sqlite3
import json
import re
import os
import sys
import time
import tempfile
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from telegram import Bot, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
from telethon import TelegramClient, events
from dataclasses import dataclass, field
from queue import Queue, Empty, Full
from collections import defaultdict, deque
from enum import Enum
import heapq
import statistics
import contextlib

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Core imports with proper error handling
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    import imagehash
    from PIL import Image
    IMAGE_PROCESSING_AVAILABLE = True
except ImportError:
    IMAGE_PROCESSING_AVAILABLE = False

try:
    from telethon import TelegramClient, events
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

try:
    from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
    TELEGRAM_BOT_AVAILABLE = True
except ImportError:
    TELEGRAM_BOT_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# Configuration
API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE_NUMBER = os.getenv('TELEGRAM_PHONE')

BOT_TOKENS = [
    os.getenv('TELEGRAM_BOT_TOKEN_1'),
    os.getenv('TELEGRAM_BOT_TOKEN_2'),
    os.getenv('TELEGRAM_BOT_TOKEN_3')
]

# Filter valid tokens
BOT_TOKENS = [token for token in BOT_TOKENS if token and len(token) > 10]
if not BOT_TOKENS:
    raise ValueError("No valid bot tokens found")

PRIMARY_BOT_TOKEN = BOT_TOKENS[0]

# Validate required configs
if not all([API_ID, API_HASH, PHONE_NUMBER, PRIMARY_BOT_TOKEN]):
    raise ValueError("Missing required configuration")

# Optional settings
REDIS_URL = os.getenv('REDIS_URL', "redis://localhost:6379")
MAX_WORKERS = int(os.getenv('MAX_WORKERS', '10'))
DEBUG_MODE = os.getenv('DEBUG_MODE', 'False').lower() == 'true'
SIMILARITY_THRESHOLD = int(os.getenv('SIMILARITY_THRESHOLD', '5'))

# Setup logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MessagePriority(Enum):
    """Message priority levels"""
    URGENT = 4
    HIGH = 3
    NORMAL = 2
    LOW = 1

    def __lt__(self, other):
        if not isinstance(other, MessagePriority):
            return NotImplemented
        return self.value < other.value

@dataclass
class QueuedMessage:
    """Enhanced message data structure with metadata"""
    data: dict
    priority: MessagePriority
    timestamp: float
    pair_id: int
    bot_index: int
    retry_count: int = 0
    max_retries: int = 3
    processing_time_estimate: float = 1.0

    def __lt__(self, other):
        # Higher priority first, then older messages first
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

@dataclass
class MessagePair:
    """Data class for message copying pairs with enhanced features"""
    id: int
    source_chat_id: int
    destination_chat_id: int
    name: str
    status: str = "active"
    assigned_bot_index: int = 0
    filters: Dict[str, Any] = field(default_factory=dict)
    stats: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if not self.filters:
            self.filters = {
                "blocked_words": [],
                "remove_mentions": False,
                "mention_placeholder": "[User]",
                "preserve_replies": True,
                "sync_edits": True,
                "sync_deletes": False,
                "remove_headers": False,
                "header_patterns": [],
                "remove_footers": False,
                "footer_patterns": []
            }

        if not self.stats:
            self.stats = {
                "messages_copied": 0,
                "messages_filtered": 0,
                "errors": 0,
                "replies_preserved": 0,
                "edits_synced": 0,
                "deletes_synced": 0,
                "mentions_removed": 0,
                "headers_removed": 0,
                "footers_removed": 0
            }

class DatabaseManager:
    """Enhanced database manager with all features"""
    
    def __init__(self, db_path: str = "bot.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Initialize complete database schema"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Pairs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pairs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_chat_id INTEGER NOT NULL,
                    destination_chat_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    assigned_bot_index INTEGER DEFAULT 0,
                    filters TEXT DEFAULT '{}',
                    stats TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Message mapping table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_mapping (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_message_id INTEGER NOT NULL,
                    destination_message_id INTEGER NOT NULL,
                    pair_id INTEGER NOT NULL,
                    bot_index INTEGER NOT NULL,
                    source_chat_id INTEGER NOT NULL,
                    destination_chat_id INTEGER NOT NULL,
                    message_type TEXT DEFAULT 'text',
                    has_media BOOLEAN DEFAULT FALSE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                    is_reply BOOLEAN DEFAULT FALSE,
                    reply_to_source_id INTEGER,
                    reply_to_dest_id INTEGER,
                    UNIQUE(source_message_id, pair_id),
                    FOREIGN KEY(pair_id) REFERENCES pairs(id) ON DELETE CASCADE
                )
            ''')

            # Check if blocked_images table exists and has the right schema
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='blocked_images'")
            table_exists = cursor.fetchone()

            if table_exists:
                # Check if block_scope column exists
                cursor.execute("PRAGMA table_info(blocked_images)")
                columns = [row[1] for row in cursor.fetchall()]
                
                if 'block_scope' not in columns:
                    # Add missing columns to existing table
                    cursor.execute('ALTER TABLE blocked_images ADD COLUMN block_scope TEXT DEFAULT "pair"')
                    cursor.execute('ALTER TABLE blocked_images ADD COLUMN similarity_threshold INTEGER DEFAULT 5')
            else:
                # Create new table with complete schema
                cursor.execute('''
                    CREATE TABLE blocked_images (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        phash TEXT NOT NULL,
                        pair_id INTEGER,
                        description TEXT DEFAULT '',
                        blocked_by TEXT DEFAULT '',
                        usage_count INTEGER DEFAULT 0,
                        block_scope TEXT DEFAULT 'pair',
                        similarity_threshold INTEGER DEFAULT 5,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(phash, pair_id)
                    )
                ''')

            # Add indexes for fast global lookups
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_blocked_images_global ON blocked_images(phash, block_scope)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_blocked_images_scope ON blocked_images(block_scope)')

            # Global settings table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Create indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_message_mapping_source ON message_mapping(source_message_id, pair_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_message_mapping_dest ON message_mapping(destination_message_id, pair_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_message_mapping_reply ON message_mapping(reply_to_source_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_message_mapping_pair ON message_mapping(pair_id)')

            # Initialize default settings
            cursor.execute('''
                INSERT OR IGNORE INTO settings (key, value)
                VALUES ('system_paused', 'false')
            ''')
            cursor.execute('''
                INSERT OR IGNORE INTO settings (key, value)
                VALUES ('global_blocks', '{"words": []}')
            ''')

            conn.commit()
            logger.info("Complete database initialized")

    def create_pair(self, source_chat_id: int, destination_chat_id: int,
                   name: str, bot_index: int = 0) -> int:
        """Create new pair"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pairs (source_chat_id, destination_chat_id, name, assigned_bot_index, filters, stats)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (source_chat_id, destination_chat_id, name, bot_index,
                  json.dumps(MessagePair(0, 0, 0, "").filters),
                  json.dumps(MessagePair(0, 0, 0, "").stats)))
            pair_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Created pair {pair_id}: {name}")
            return pair_id

    def get_pair(self, pair_id: int) -> Optional[MessagePair]:
        """Get pair by ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM pairs WHERE id = ?', (pair_id,))
            row = cursor.fetchone()
            
            if row:
                return MessagePair(
                    id=row[0],
                    source_chat_id=row[1],
                    destination_chat_id=row[2],
                    name=row[3],
                    status=row[4],
                    assigned_bot_index=row[5],
                    filters=json.loads(row[6]),
                    stats=json.loads(row[7])
                )
        return None

    def get_all_pairs(self) -> List[MessagePair]:
        """Get all pairs"""
        pairs = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM pairs ORDER BY id')
            for row in cursor.fetchall():
                pairs.append(MessagePair(
                    id=row[0],
                    source_chat_id=row[1],
                    destination_chat_id=row[2],
                    name=row[3],
                    status=row[4],
                    assigned_bot_index=row[5],
                    filters=json.loads(row[6]),
                    stats=json.loads(row[7])
                ))
        return pairs

    def update_pair(self, pair: MessagePair):
        """Update pair"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE pairs SET status = ?, filters = ?, stats = ? WHERE id = ?
            ''', (pair.status, json.dumps(pair.filters), json.dumps(pair.stats), pair.id))
            conn.commit()

    def delete_pair(self, pair_id: int):
        """Delete pair and related data"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM pairs WHERE id = ?', (pair_id,))
            cursor.execute('DELETE FROM blocked_images WHERE pair_id = ?', (pair_id,))
            cursor.execute('DELETE FROM message_mapping WHERE pair_id = ?', (pair_id,))
            conn.commit()
            logger.info(f"Deleted pair {pair_id}")

    def get_setting(self, key: str, default: str = "") -> str:
        """Get setting value"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
            row = cursor.fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: str):
        """Set setting value"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (key, value))
            conn.commit()

    def add_blocked_image(self, phash: str, pair_id: Optional[int] = None,
                         description: str = "", blocked_by: str = "") -> bool:
        """Add blocked image hash"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO blocked_images (phash, pair_id, description, blocked_by)
                    VALUES (?, ?, ?, ?)
                ''', (phash, pair_id, description, blocked_by))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_blocked_images(self, pair_id: Optional[int] = None) -> List[str]:
        """Get blocked image hashes"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if pair_id is None:
                cursor.execute('SELECT phash FROM blocked_images WHERE pair_id IS NULL')
            else:
                cursor.execute('SELECT DISTINCT phash FROM blocked_images WHERE pair_id IS NULL OR pair_id = ?', (pair_id,))
            return [row[0] for row in cursor.fetchall()]

class EnhancedMessageMapper:
    """Complete message mapping for reply preservation and sync operations"""
    
    def __init__(self, db_manager):
        self.db = db_manager

    def store_message_mapping(self, source_msg_id: int, dest_msg_id: int, pair_id: int,
                            bot_index: int, source_chat_id: int, dest_chat_id: int,
                            message_type: str = 'text', has_media: bool = False,
                            is_reply: bool = False, reply_to_source_id: int = None,
                            reply_to_dest_id: int = None):
        """Store comprehensive message mapping"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO message_mapping
                (source_message_id, destination_message_id, pair_id, bot_index,
                 source_chat_id, destination_chat_id, message_type, has_media,
                 is_reply, reply_to_source_id, reply_to_dest_id, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (source_msg_id, dest_msg_id, pair_id, bot_index, source_chat_id,
                  dest_chat_id, message_type, has_media, is_reply,
                  reply_to_source_id, reply_to_dest_id))
            conn.commit()

    def get_destination_message_id(self, source_msg_id: int, pair_id: int) -> Optional[int]:
        """Get destination message ID for a source message"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT destination_message_id FROM message_mapping
                WHERE source_message_id = ? AND pair_id = ?
            ''', (source_msg_id, pair_id))
            result = cursor.fetchone()
            return result[0] if result else None

    def get_reply_destination_id(self, reply_to_source_id: int, pair_id: int) -> Optional[int]:
        """Get destination message ID for a reply target"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT destination_message_id FROM message_mapping
                WHERE source_message_id = ? AND pair_id = ?
            ''', (reply_to_source_id, pair_id))
            result = cursor.fetchone()
            return result[0] if result else None

    def get_mapping_info(self, source_msg_id: int, pair_id: int) -> Optional[Dict]:
        """Get complete mapping information"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM message_mapping
                WHERE source_message_id = ? AND pair_id = ?
            ''', (source_msg_id, pair_id))
            result = cursor.fetchone()
            
            if result:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, result))
        return None

class ImageHashCalculator:
    """Complete image hash calculator"""
    
    def __init__(self):
        self.enabled = IMAGE_PROCESSING_AVAILABLE

    def calculate_phash(self, image_path: str) -> str:
        """Calculate perceptual hash"""
        if not self.enabled:
            return ""
        
        try:
            with Image.open(image_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                phash = imagehash.phash(img)
                return str(phash)
        except Exception as e:
            logger.error(f"Hash calculation error: {e}")
            return ""

    def hash_similarity(self, hash1: str, hash2: str) -> int:
        """Calculate similarity between hashes"""
        if len(hash1) != len(hash2):
            return 100
        return sum(c1 != c2 for c1, c2 in zip(hash1, hash2))

class ImageBlocker:
    """Enhanced image blocking system with global support"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.calculator = ImageHashCalculator()
        self.global_cache = {}
        self.cache_update_time = 0

    def block_image_from_file(self, image_path: str, pair_id: Optional[int] = None,
                            description: str = "", blocked_by: str = "") -> Tuple[bool, str]:
        """Block image from file"""
        if not os.path.exists(image_path):
            return False, "File not found"

        phash = self.calculator.calculate_phash(image_path)
        if not phash:
            return False, "Failed to calculate hash"

        success = self.db.add_blocked_image(phash, pair_id, description, blocked_by)
        return success, phash

    def block_image_globally(self, image_path: str, description: str = "",
                           blocked_by: str = "", similarity_threshold: int = 5) -> Tuple[bool, str]:
        """Block image globally across all pairs"""
        if not os.path.exists(image_path):
            return False, "File not found"

        phash = self.calculator.calculate_phash(image_path)
        if not phash:
            return False, "Failed to calculate hash"

        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO blocked_images
                    (phash, pair_id, description, blocked_by, block_scope, similarity_threshold)
                    VALUES (?, NULL, ?, ?, 'global', ?)
                ''', (phash, description, blocked_by, similarity_threshold))
                conn.commit()
                
                # Clear cache to force refresh
                self.global_cache.clear()
                return True, phash
            except sqlite3.IntegrityError:
                return False, "Image already blocked globally"

    def is_image_blocked(self, image_path: str, pair_id: int) -> Tuple[bool, str]:
        """Check if image is blocked (pair-specific or globally)"""
        if not os.path.exists(image_path):
            return False, ""

        phash = self.calculator.calculate_phash(image_path)
        if not phash:
            return False, ""

        # Check global blocks first
        is_global_blocked, global_reason, _ = self.is_image_blocked_globally(image_path)
        if is_global_blocked:
            return True, global_reason

        # Check pair-specific blocks
        blocked_hashes = self.db.get_blocked_images(pair_id)

        # Direct match
        if phash in blocked_hashes:
            return True, f"Exact match: {phash}"

        # Similarity match
        for blocked_hash in blocked_hashes:
            similarity = self.calculator.hash_similarity(phash, blocked_hash)
            if similarity <= SIMILARITY_THRESHOLD:
                return True, f"Similar match: {blocked_hash} (distance: {similarity})"

        return False, ""

    def is_image_blocked_globally(self, image_path: str) -> Tuple[bool, str, Dict]:
        """Check if image is blocked globally with detailed info"""
        if not os.path.exists(image_path):
            return False, "", {}

        phash = self.calculator.calculate_phash(image_path)
        if not phash:
            return False, "", {}

        # Check cache first
        if phash in self.global_cache:
            cached_result = self.global_cache[phash]
            return cached_result['blocked'], cached_result['reason'], cached_result['info']

        # Get global blocked hashes
        global_hashes = self.get_global_blocked_images()

        # Direct match check
        for blocked_info in global_hashes:
            blocked_hash = blocked_info['phash']
            threshold = blocked_info.get('similarity_threshold', 5)

            if phash == blocked_hash:
                result = {
                    'blocked': True,
                    'reason': f"Exact global match: {blocked_hash}",
                    'info': blocked_info
                }
                self.global_cache[phash] = result
                return True, result['reason'], blocked_info

            # Similarity check
            similarity = self.calculator.hash_similarity(phash, blocked_hash)
            if similarity <= threshold:
                result = {
                    'blocked': True,
                    'reason': f"Similar global match: {blocked_hash} (distance: {similarity})",
                    'info': blocked_info
                }
                self.global_cache[phash] = result
                return True, result['reason'], blocked_info

        # Cache negative result
        result = {'blocked': False, 'reason': "", 'info': {}}
        self.global_cache[phash] = result
        return False, "", {}

    def get_global_blocked_images(self) -> List[Dict]:
        """Get all globally blocked images with metadata"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT phash, description, blocked_by, usage_count, similarity_threshold, created_at
                FROM blocked_images
                WHERE block_scope = 'global'
                ORDER BY created_at DESC
            ''')
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'phash': row[0],
                    'description': row[1],
                    'blocked_by': row[2],
                    'usage_count': row[3],
                    'similarity_threshold': row[4],
                    'created_at': row[5]
                })
            return results

    def update_usage_count(self, phash: str):
        """Update usage statistics for blocked image"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE blocked_images
                SET usage_count = usage_count + 1
                WHERE phash = ?
            ''', (phash,))
            conn.commit()

    def remove_global_block(self, phash: str) -> bool:
        """Remove global image block"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM blocked_images
                WHERE phash = ? AND block_scope = 'global'
            ''', (phash,))
            affected = cursor.rowcount
            conn.commit()

            # Clear cache
            if phash in self.global_cache:
                del self.global_cache[phash]

            return affected > 0

class FilterManager:
    """Complete message filtering system with enhanced features"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.image_blocker = ImageBlocker(db)
        self.mention_patterns = [
            (r'@[a-zA-Z0-9_]{1,32}\b', '@'),
            (r'(?<!\w)@[a-zA-Z0-9_]{1,32}(?!\w)', '@'),
            (r'https?://(?:www\.)?t\.me/[a-zA-Z0-9_]{1,32}(?:/\d+)?', 'tme_link'),
            (r'https?://(?:www\.)?telegram\.me/[a-zA-Z0-9_]{1,32}(?:/\d+)?', 'telegram_link'),
        ]

    def should_filter_message(self, text: str, pair: MessagePair) -> Tuple[bool, str]:
        """Check if message should be filtered"""
        if not text:
            return False, ""

        # Global blocked words
        global_blocks = json.loads(self.db.get_setting('global_blocks', '{"words": []}'))
        global_words = global_blocks.get('words', [])

        # Pair-specific blocked words
        pair_words = pair.filters.get('blocked_words', [])

        # Check all blocked words
        all_blocked_words = global_words + pair_words

        for word in all_blocked_words:
            if re.search(r'\b' + re.escape(word.lower()) + r'\b', text.lower()):
                return True, f"Blocked word: {word}"

        return False, ""

    def process_mentions(self, text: str, pair: MessagePair) -> Tuple[str, int]:
        """Remove mentions and related links, and clean up leftover placeholders."""
        if not pair.filters.get('remove_mentions', False):
            return text, 0

        # Remove @mentions
        text, n1 = re.subn(r'@[a-zA-Z0-9_]{1,32}\b', '', text)

        # Remove t.me/ links
        text, n2 = re.subn(r'(https?://)?t\.me/[a-zA-Z0-9_]{1,32}(/\d+)?', '', text, flags=re.IGNORECASE)

        # Remove telegram.me/ links
        text, n3 = re.subn(r'(https?://)?telegram\.me/[a-zA-Z0-9_]{1,32}(/\d+)?', '', text, flags=re.IGNORECASE)

        # Remove tg:// links
        text, n4 = re.subn(r'tg://[^\s]+', '', text, flags=re.IGNORECASE)

        mentions_removed = n1 + n2 + n3 + n4

        # Remove leftover [User] and extra whitespace
        text = re.sub(r'\[User\]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()

        # Remove empty lines
        text = '\n'.join([line for line in text.split('\n') if line.strip()])

        return text, mentions_removed

    def remove_headers(self, text: str, pair: MessagePair) -> Tuple[str, int]:
        """Remove headers using regex patterns from the start of the message."""
        if not pair.filters.get('remove_headers', False):
            return text, 0

        headers_removed = 0
        header_patterns = pair.filters.get('header_patterns', [])

        for pattern in header_patterns:
            try:
                regex = pattern if pattern.startswith('^') else f'^{pattern}'
                text, n = re.subn(regex, '', text, flags=re.MULTILINE | re.IGNORECASE)
                headers_removed += n
            except re.error as e:
                logger.warning(f"Invalid header pattern '{pattern}': {e}")

        text = text.lstrip('\n\r\t ')
        return text, headers_removed

    def remove_footers(self, text: str, pair: MessagePair) -> Tuple[str, int]:
        """Remove footers using regex patterns from the end of the message."""
        if not pair.filters.get('remove_footers', False):
            return text, 0

        footers_removed = 0
        footer_patterns = pair.filters.get('footer_patterns', [])

        for pattern in footer_patterns:
            try:
                regex = pattern if pattern.endswith('$') else f'{pattern}$'
                text, n = re.subn(regex, '', text, flags=re.MULTILINE | re.IGNORECASE)
                footers_removed += n
            except re.error as e:
                logger.warning(f"Invalid footer pattern '{pattern}': {e}")

        text = text.rstrip('\n\r\t ')
        return text, footers_removed

    def process_message_text(self, text: str, pair: MessagePair) -> Tuple[str, Dict[str, int], list]:
        """Comprehensive text processing with statistics"""
        if not text:
            return text, {'mentions_removed': 0, 'headers_removed': 0, 'footers_removed': 0}, []

        stats = {'mentions_removed': 0, 'headers_removed': 0, 'footers_removed': 0}
        preserved_entities = []

        # Process in order: headers -> mentions -> footers
        text, headers_removed = self.remove_headers(text, pair)
        stats['headers_removed'] = headers_removed

        text, mentions_removed = self.process_mentions(text, pair)
        stats['mentions_removed'] = mentions_removed

        text, footers_removed = self.remove_footers(text, pair)
        stats['footers_removed'] = footers_removed

        # Final cleanup while preserving formatting
        text = re.sub(r'\n\s*\n', '\n\n', text)  # Remove excessive empty lines
        text = text.strip()

        return text, stats, preserved_entities

    def process_message_text_preserve_format(self, text: str, pair: MessagePair, entities: List[Dict]) -> Tuple[str, Dict[str, int], List[Dict]]:
        """Enhanced text processing that preserves formatting, links and entities"""
        if not text:
            return text, {'mentions_removed': 0, 'headers_removed': 0, 'footers_removed': 0}, []

        stats = {'mentions_removed': 0, 'headers_removed': 0, 'footers_removed': 0}

        if not entities:
            entities = []

        # Create a copy of entities to avoid modifying the original
        preserved_entities = [dict(e) for e in entities]

        # Process in order: headers -> mentions -> footers
        text, headers_removed = self.remove_headers(text, pair)
        stats['headers_removed'] = headers_removed

        text, mentions_removed = self.process_mentions(text, pair)
        stats['mentions_removed'] = mentions_removed

        text, footers_removed = self.remove_footers(text, pair)
        stats['footers_removed'] = footers_removed

        # Final cleanup while preserving formatting
        text = re.sub(r'\n\s*\n', '\n\n', text)  # Remove excessive empty lines
        text = text.strip()

        # Adjust entity positions after final cleanup
        self.adjust_entity_positions(text, preserved_entities)

        return text, stats, preserved_entities

    def adjust_entity_positions(self, text: str, entities: List[Dict]):
        """Adjust entity positions after text modifications"""
        if not entities:
            return

        text_length = len(text)
        valid_entities = []

        for entity in sorted(entities, key=lambda e: e.get('offset', 0)):
            offset = entity.get('offset', 0)
            length = entity.get('length', 0)

            # Skip entities that are now completely outside text bounds
            if offset >= text_length:
                continue

            # Adjust entity length if it extends beyond text
            if offset + length > text_length:
                entity['length'] = text_length - offset

            valid_entities.append(entity)

        entities.clear()
        entities.extend(valid_entities)

class BotLoadBalancer:
    """Complete bot load balancer"""
    
    def __init__(self, bot_tokens: List[str]):
        self.bot_tokens = bot_tokens
        self.bots = [Bot(token=token) for token in bot_tokens]
        self.current_index = 0

    def get_next_bot(self) -> Tuple[Bot, int]:
        """Get next bot in round-robin"""
        bot_index = self.current_index
        bot = self.bots[bot_index]
        self.current_index = (self.current_index + 1) % len(self.bots)
        return bot, bot_index

    def get_bot_by_index(self, index: int) -> Optional[Bot]:
        """Get bot by index"""
        if 0 <= index < len(self.bots):
            return self.bots[index]
        return None

class SmartQueueManager:
    """Advanced queue manager with intelligent load balancing"""
    
    def __init__(self, bot_tokens: List[str], max_queue_size: int = 50000):
        self.bot_tokens = bot_tokens
        self.num_bots = len(bot_tokens)
        self.max_queue_size = max_queue_size

        # Optimized queue structure with separate priority levels
        self.priority_queues = {
            i: {
                priority: [] for priority in MessagePriority
            } for i in range(self.num_bots)
        }

        # Use asyncio locks for better async performance
        self.queue_locks = {
            i: asyncio.Lock() for i in range(self.num_bots)
        }

        # Enhanced bot performance tracking
        self.bot_metrics = {
            i: BotMetrics(
                messages_processed=0,
                success_rate=1.0,
                avg_processing_time=1.0,
                current_load=0,
                error_count=0,
                last_activity=time.time(),
                rate_limit_until=0,
                consecutive_failures=0
            ) for i in range(self.num_bots)
        }

        # Adaptive load balancing
        self.round_robin_index = 0
        self.processing_history = {
            i: deque(maxlen=100) for i in range(self.num_bots)
        }

        # Enhanced rate limiting with burst control
        self.rate_limits = {
            i: {
                'messages_per_second': 20,
                'burst_limit': 40,
                'recovery_time': 5,
                'adaptive_limit': True
            } for i in range(self.num_bots)
        }

        # Optimized rate tracking with millisecond precision
        self.rate_trackers = {
            i: {
                'times': deque(maxlen=60),
                'counts': deque(maxlen=60),
                'last_reset': time.time()
            } for i in range(self.num_bots)
        }

        # Queue monitoring
        self.total_enqueued = 0
        self.total_processed = 0
        self.total_failed = 0
        self.queue_start_time = time.time()

        # Adaptive settings
        self.adaptive_enabled = True
        self.load_balance_algorithm = "smart"

        # Background monitoring
        self.monitoring_task = None
        self.cleanup_task = None

        logger.info(f"Smart Queue Manager initialized with {self.num_bots} bots")

    def start_background_tasks(self):
        """Start background monitoring and cleanup tasks"""
        if self.monitoring_task is None:
            self.monitoring_task = asyncio.create_task(self._monitor_queues())
        if self.cleanup_task is None:
            self.cleanup_task = asyncio.create_task(self._cleanup_stale_messages())

    async def _monitor_queues(self):
        """Enhanced background task to monitor queue health and optimize performance"""
        while True:
            try:
                start_time = time.time()
                tasks = [
                    self._update_bot_metrics(),
                    self._adjust_rate_limits(),
                    self._rebalance_queues(),
                    self._update_performance_stats()
                ]

                # Run monitoring tasks concurrently
                await asyncio.gather(*tasks)

                # Log detailed stats periodically
                elapsed = time.time() - start_time
                if elapsed > 1.0:
                    logger.warning(f"Queue monitoring took {elapsed:.2f}s")

                await asyncio.sleep(max(0.1, 10 - elapsed))

            except Exception as e:
                logger.error(f"Queue monitoring error: {str(e)}", exc_info=True)
                await asyncio.sleep(30)

    async def _update_performance_stats(self):
        """Update detailed performance statistics"""
        current_time = time.time()
        total_messages = sum(metrics.messages_processed for metrics in self.bot_metrics.values())
        uptime = current_time - self.queue_start_time

        if uptime > 0:
            messages_per_second = total_messages / uptime
            success_rate = ((self.total_processed - self.total_failed) / max(1, self.total_processed) * 100)
            logger.info(f"Performance stats: {messages_per_second:.1f} msg/s, Success: {success_rate:.1f}%")

    async def _cleanup_stale_messages(self):
        """Enhanced cleanup of old messages with smart throttling"""
        while True:
            try:
                start_time = time.time()
                current_time = start_time
                cleaned_total = 0

                # Clean one bot's queues at a time to spread load
                bot_index = int(current_time) % self.num_bots

                async with self.queue_locks[bot_index]:
                    for priority in MessagePriority:
                        queue = self.priority_queues[bot_index][priority]
                        if not queue:
                            continue

                        # Remove expired messages
                        valid_messages = []
                        for msg in queue:
                            if (current_time - msg.timestamp <= 300 or msg.retry_count < msg.max_retries):
                                valid_messages.append(msg)
                            else:
                                cleaned_total += 1

                        if len(valid_messages) != len(queue):
                            self.priority_queues[bot_index][priority] = valid_messages
                            if valid_messages:
                                heapq.heapify(valid_messages)

                if cleaned_total > 0:
                    logger.info(f"Cleaned {cleaned_total} stale messages from bot {bot_index}")

                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"Queue cleanup error: {e}")
                await asyncio.sleep(60)

    def determine_message_priority(self, message_data: dict) -> MessagePriority:
        """Intelligently determine message priority based on content and context"""
        # High priority for replies to preserve conversation flow
        if message_data.get('is_reply', False):
            return MessagePriority.HIGH

        # Urgent priority for media messages (time-sensitive)
        if message_data.get('has_media', False):
            return MessagePriority.HIGH

        # High priority for short text messages (quick to process)
        text = message_data.get('text', '')
        if text and len(text) < 100:
            return MessagePriority.NORMAL

        # Lower priority for long messages
        if text and len(text) > 1000:
            return MessagePriority.LOW

        return MessagePriority.NORMAL

    async def select_optimal_bot(self, message: QueuedMessage) -> int:
        """Select the best bot for processing based on multiple factors"""
        if self.load_balance_algorithm == "round_robin":
            return self._round_robin_selection()
        elif self.load_balance_algorithm == "least_loaded":
            return self._least_loaded_selection()
        else:  # smart
            return await self._smart_selection_with_exclusions(message, set())

    def _round_robin_selection(self) -> int:
        """Simple round-robin bot selection"""
        bot_index = self.round_robin_index
        self.round_robin_index = (self.round_robin_index + 1) % self.num_bots
        return bot_index

    def _least_loaded_selection(self) -> int:
        """Select bot with least current load"""
        min_load = float('inf')
        best_bot = 0

        for bot_index in range(self.num_bots):
            metrics = self.bot_metrics[bot_index]
            current_load = sum(len(q) for q in self.priority_queues[bot_index].values()) + metrics.current_load

            # Skip rate-limited bots
            if time.time() < metrics.rate_limit_until:
                continue

            if current_load < min_load:
                min_load = current_load
                best_bot = bot_index

        return best_bot

    async def _smart_selection_with_exclusions(self, message: QueuedMessage, excluded_bots: set) -> int:
        """Enhanced intelligent bot selection with exclusion support"""
        current_time = time.time()
        bot_scores = []

        for bot_index in range(self.num_bots):
            if bot_index in excluded_bots:
                continue

            metrics = self.bot_metrics[bot_index]
            score = 0.0

            # Skip problematic bots
            if current_time < metrics.rate_limit_until:
                continue
            if metrics.consecutive_failures >= 3:
                continue

            # Factor 1: Queue load (40% weight)
            total_queue_size = sum(len(q) for q in self.priority_queues[bot_index].values())
            load_score = max(0, 100 - (total_queue_size * 2))
            score += load_score * 0.4

            # Factor 2: Bot health (30% weight)
            health_score = (metrics.success_rate * 50) + (min(50, 1000 / (metrics.error_count + 10)))
            score += health_score * 0.3

            # Factor 3: Performance (20% weight)
            if metrics.avg_processing_time > 0:
                speed_score = min(50, 5 / metrics.avg_processing_time)
                score += speed_score * 0.2

            # Factor 4: Rate limit headroom (10% weight)
            tracker = self.rate_trackers[bot_index]
            recent_count = sum(tracker['counts'])
            limit = self.rate_limits[bot_index]['messages_per_second']
            headroom = max(0, (limit - recent_count) / limit * 100)
            score += headroom * 0.1

            bot_scores.append((score, bot_index))

        if not bot_scores:
            # Fallback to least loaded non-excluded bot
            available_bots = set(range(self.num_bots)) - excluded_bots
            if not available_bots:
                return 0
            return min(available_bots, key=lambda b: sum(len(q) for q in self.priority_queues[b].values()))

        # Return bot with highest score
        bot_scores.sort(reverse=True)
        return bot_scores[0][1]

    async def enqueue_message(self, message_data: dict, preferred_bot: Optional[int] = None) -> bool:
        """Enhanced message enqueueing with intelligent routing"""
        try:
            current_time = time.time()

            # Create enhanced message object
            priority = self.determine_message_priority(message_data)
            estimated_time = self._estimate_processing_time(message_data)

            message = QueuedMessage(
                data=message_data,
                priority=priority,
                timestamp=current_time,
                pair_id=message_data.get('pair_id', 0),
                bot_index=preferred_bot or -1,
                processing_time_estimate=estimated_time
            )

            # Select optimal bot if not specified
            if preferred_bot is None:
                bot_index = await self.select_optimal_bot(message)
            else:
                bot_index = preferred_bot

            # Validate preferred bot is available
            if (time.time() < self.bot_metrics[bot_index].rate_limit_until or
                self.bot_metrics[bot_index].consecutive_failures > 5):
                bot_index = await self.select_optimal_bot(message)

            message.bot_index = bot_index

            # Check if bot's queue is full
            async with self.queue_locks[bot_index]:
                total_queue_size = sum(len(q) for q in self.priority_queues[bot_index].values())
                if total_queue_size >= self.max_queue_size // self.num_bots:
                    alternative_bot = self._least_loaded_selection()
                    if alternative_bot != bot_index:
                        bot_index = alternative_bot
                        message.bot_index = bot_index
                    else:
                        logger.warning("All queues are full, dropping message")
                        return False

                # Add to priority queue
                heapq.heappush(self.priority_queues[bot_index][message.priority], message)
                self.total_enqueued += 1

                # Update rate tracking
                self.rate_trackers[bot_index]['times'].append(current_time)
                self.rate_trackers[bot_index]['counts'].append(1)

                logger.debug(f"Enqueued message to bot {bot_index} with priority {priority.name}")
                return True

        except Exception as e:
            logger.error(f"Failed to enqueue message: {e}")
            return False

    async def dequeue_message(self, bot_index: int, timeout: float = 30.0) -> Optional[QueuedMessage]:
        """Enhanced message dequeuing with priority handling"""
        try:
            start_time = time.time()
            metrics = self.bot_metrics[bot_index]

            # Check rate limits first
            if time.time() < metrics.rate_limit_until:
                await asyncio.sleep(0.5)
                return None

            while time.time() - start_time < timeout:
                async with self.queue_locks[bot_index]:
                    # Check each priority queue in order
                    for priority in sorted(MessagePriority, reverse=True):
                        queue = self.priority_queues[bot_index][priority]
                        if queue:
                            message = heapq.heappop(queue)
                            current_time = time.time()

                            # Skip expired or over-retried messages
                            if current_time - message.timestamp > 300:
                                continue
                            if message.retry_count >= message.max_retries:
                                self.total_failed += 1
                                continue

                            # Check rate limits
                            tracker = self.rate_trackers[bot_index]
                            recent_count = sum(tracker['counts'])
                            if recent_count >= self.rate_limits[bot_index]['burst_limit']:
                                heapq.heappush(queue, message)
                                recovery_time = self.rate_limits[bot_index]['recovery_time']
                                metrics.rate_limit_until = current_time + recovery_time
                                return None

                            # Update metrics
                            metrics.last_activity = current_time
                            metrics.current_load += 1

                            # Update rate tracking
                            tracker['times'].append(current_time)
                            tracker['counts'].append(1)

                            # Prune old tracking entries
                            while tracker['times'] and tracker['times'][0] < current_time - 60:
                                tracker['times'].popleft()
                                tracker['counts'].popleft()

                            return message

                await asyncio.sleep(0.1)

            return None

        except Exception as e:
            logger.error(f"Failed to dequeue message for bot {bot_index}: {e}", exc_info=True)
            return None

    async def requeue_failed_message(self, message: QueuedMessage, error: str = "", backoff_factor: int = 2):
        """Requeue failed message with enhanced retry logic"""
        message.retry_count += 1
        current_time = time.time()
        message.timestamp = current_time

        if message.retry_count < message.max_retries:
            # Calculate backoff delay
            delay = min(30, backoff_factor ** (message.retry_count - 1))
            message.timestamp += delay

            # Adjust priority based on retry count
            if "rate limit" not in error.lower():
                message.priority = MessagePriority(max(1, message.priority.value - 1))

            # Select optimal bot for retry
            original_bot = message.bot_index
            excluded_bots = {original_bot}

            if message.retry_count > 2:
                excluded_bots.update(
                    bot_id for bot_id, metrics in self.bot_metrics.items()
                    if metrics.consecutive_failures > 0 or current_time < metrics.rate_limit_until
                )

            new_bot = await self._smart_selection_with_exclusions(message, excluded_bots)
            message.bot_index = new_bot

            # Update bot metrics
            self.bot_metrics[original_bot].error_count += 1
            self.bot_metrics[original_bot].consecutive_failures += 1
            self.bot_metrics[original_bot].success_rate = max(
                0.5,
                self.bot_metrics[original_bot].success_rate * 0.9
            )

            # Queue message with new priority
            async with self.queue_locks[new_bot]:
                heapq.heappush(self.priority_queues[new_bot][message.priority], message)

            logger.info(f"Requeued failed message (attempt {message.retry_count}/{message.max_retries}) from bot {original_bot} to {new_bot}")
        else:
            self.total_failed += 1
            logger.error(f"Message failed permanently after {message.retry_count} attempts. Error: {error}")

    def mark_message_processed(self, message: QueuedMessage, success: bool, processing_time: float):
        """Update metrics after message processing"""
        bot_index = message.bot_index
        metrics = self.bot_metrics[bot_index]

        # Update processing metrics
        metrics.current_load = max(0, metrics.current_load - 1)
        metrics.messages_processed += 1

        if success:
            self.total_processed += 1
            metrics.consecutive_failures = 0

            # Update processing time moving average
            self.processing_history[bot_index].append(processing_time)
            if self.processing_history[bot_index]:
                metrics.avg_processing_time = statistics.mean(self.processing_history[bot_index])

            # Update success rate
            total_attempts = metrics.messages_processed
            if total_attempts > 0:
                success_count = total_attempts - metrics.error_count
                metrics.success_rate = success_count / total_attempts
        else:
            metrics.error_count += 1
            metrics.consecutive_failures += 1

    def _estimate_processing_time(self, message_data: dict) -> float:
        """Estimate processing time based on message content"""
        base_time = 0.5

        # Text length factor
        text = message_data.get('text', '')
        if text:
            base_time += len(text) / 10000

        # Media factor
        if message_data.get('has_media', False):
            base_time += 2.0

        # Reply factor
        if message_data.get('is_reply', False):
            base_time += 0.5

        return min(base_time, 10.0)

    async def _update_bot_metrics(self):
        """Update bot performance metrics"""
        current_time = time.time()
        for bot_index in range(self.num_bots):
            metrics = self.bot_metrics[bot_index]
            
            # Check for rate limit recovery
            if current_time > metrics.rate_limit_until:
                metrics.consecutive_failures = max(0, metrics.consecutive_failures - 1)

    async def _adjust_rate_limits(self):
        """Dynamically adjust rate limits based on bot performance"""
        if not self.adaptive_enabled:
            return

        current_time = time.time()
        for bot_index in range(self.num_bots):
            metrics = self.bot_metrics[bot_index]
            rate_limit = self.rate_limits[bot_index]

            if metrics.success_rate > 0.95 and metrics.consecutive_failures == 0:
                # Performing well - consider increasing limits
                rate_limit['messages_per_second'] = min(30, rate_limit['messages_per_second'] * 1.1)
                rate_limit['burst_limit'] = min(60, int(rate_limit['messages_per_second'] * 2))
                rate_limit['recovery_time'] = max(2, rate_limit['recovery_time'] - 1)
            elif metrics.success_rate < 0.8 or metrics.consecutive_failures > 2:
                # Having issues - reduce limits
                rate_limit['messages_per_second'] = max(5, rate_limit['messages_per_second'] * 0.8)
                rate_limit['burst_limit'] = max(10, int(rate_limit['messages_per_second'] * 1.5))
                rate_limit['recovery_time'] = min(30, rate_limit['recovery_time'] + 5)

    async def _rebalance_queues(self):
        """Intelligently redistribute messages between bots"""
        if not self.adaptive_enabled:
            return

        current_time = time.time()
        bot_loads = []

        for bot_index in range(self.num_bots):
            metrics = self.bot_metrics[bot_index]
            
            # Skip bots that are rate limited or having issues
            if current_time < metrics.rate_limit_until or metrics.consecutive_failures > 2:
                continue

            # Calculate total queue size across all priorities
            total_queue_size = sum(len(q) for q in self.priority_queues[bot_index].values())

            effective_load = {
                'size': total_queue_size,
                'processing_load': metrics.current_load,
                'success_rate': metrics.success_rate,
                'processing_time': metrics.avg_processing_time,
                'bot_index': bot_index
            }
            bot_loads.append(effective_load)

        if len(bot_loads) < 2:
            return

        # Sort bots by effective load
        bot_loads.sort(key=lambda x: (
            x['size'] / max(0.1, x['success_rate']),
            x['processing_time']
        ))

        # Get most and least loaded bots
        least_loaded = bot_loads[0]
        most_loaded = bot_loads[-1]

        load_difference = most_loaded['size'] - least_loaded['size']
        if load_difference < 10:
            return

        # Calculate number of messages to move
        messages_to_move = min(load_difference // 2, 20)
        source_bot = most_loaded['bot_index']
        target_bot = least_loaded['bot_index']

        try:
            async with self.queue_locks[source_bot], self.queue_locks[target_bot]:
                moved_count = 0
                
                # Move messages priority by priority
                for priority in sorted(MessagePriority, reverse=True):
                    source_queue = self.priority_queues[source_bot][priority]
                    if not source_queue:
                        continue

                    while moved_count < messages_to_move and source_queue:
                        message = heapq.heappop(source_queue)
                        message.bot_index = target_bot
                        message.timestamp = current_time
                        
                        heapq.heappush(self.priority_queues[target_bot][priority], message)
                        moved_count += 1

                if moved_count > 0:
                    logger.info(f"Rebalanced {moved_count} messages from bot {source_bot} to bot {target_bot}")

        except Exception as e:
            logger.error(f"Error during queue rebalancing: {str(e)}", exc_info=True)

    def get_queue_stats(self) -> Dict[str, Any]:
        """Get comprehensive queue statistics"""
        current_time = time.time()
        uptime = current_time - self.queue_start_time

        bot_stats = {}
        for bot_index in range(self.num_bots):
            metrics = self.bot_metrics[bot_index]
            total_queue_size = sum(len(q) for q in self.priority_queues[bot_index].values())
            
            bot_stats[f'bot_{bot_index}'] = {
                'queue_size': total_queue_size,
                'messages_processed': metrics.messages_processed,
                'success_rate': round(metrics.success_rate * 100, 2),
                'avg_processing_time': round(metrics.avg_processing_time, 2),
                'current_load': metrics.current_load,
                'consecutive_failures': metrics.consecutive_failures,
                'rate_limited': current_time < metrics.rate_limit_until
            }

        return {
            'total_enqueued': self.total_enqueued,
            'total_processed': self.total_processed,
            'total_failed': self.total_failed,
            'total_pending': sum(sum(len(q) for q in queues.values()) for queues in self.priority_queues.values()),
            'processing_rate': round(self.total_processed / max(uptime, 1), 2),
            'success_rate': round((self.total_processed / max(self.total_enqueued, 1)) * 100, 2),
            'uptime_seconds': round(uptime, 2),
            'load_balance_algorithm': self.load_balance_algorithm,
            'adaptive_enabled': self.adaptive_enabled,
            'bot_stats': bot_stats
        }

    def update_settings(self, settings: Dict[str, Any]):
        """Update queue manager settings dynamically"""
        if 'load_balance_algorithm' in settings:
            algorithm = settings['load_balance_algorithm']
            if algorithm in ['round_robin', 'least_loaded', 'smart']:
                self.load_balance_algorithm = algorithm
                logger.info(f"Updated load balance algorithm to: {algorithm}")

        if 'adaptive_enabled' in settings:
            self.adaptive_enabled = bool(settings['adaptive_enabled'])
            logger.info(f"Adaptive queue management: {'enabled' if self.adaptive_enabled else 'disabled'}")

    async def stop(self):
        """Gracefully stop the queue manager"""
        if self.monitoring_task:
            self.monitoring_task.cancel()
        if self.cleanup_task:
            self.cleanup_task.cancel()
        logger.info("Smart Queue Manager stopped")

    # Legacy compatibility methods
    async def enqueue(self, message_data: dict, bot_index: int = 0) -> bool:
        """Legacy compatibility method"""
        return await self.enqueue_message(message_data, bot_index)

    async def dequeue(self, bot_index: int = 0, timeout: int = 1) -> Optional[dict]:
        """Legacy compatibility method"""
        try:
            message = await self.dequeue_message(bot_index, timeout)
            return message.data if message else None
        except Exception as e:
            logger.error(f"Legacy dequeue error: {e}", exc_info=True)
            return None

    def get_size(self, bot_index: int = None) -> int:
        """Legacy compatibility method"""
        if bot_index is not None:
            return sum(len(q) for q in self.priority_queues.get(bot_index, {}).values())
        return sum(sum(len(q) for q in queues.values()) for queues in self.priority_queues.values())

class EnhancedMessageWorker:
    """Enhanced message worker with smart queue integration"""
    
    def __init__(self, bot_index: int, bot: Bot, queue_manager: SmartQueueManager, parent_bot):
        self.bot_index = bot_index
        self.bot = bot
        self.queue_manager = queue_manager
        self.parent_bot = parent_bot
        self.running = False
        self.last_activity = time.time()
        self.messages_processed = 0
        self.consecutive_errors = 0
        self.processing_timeout = 300
        self.health_check_interval = 60
        self.last_health_check = time.time()
        self.stuck_threshold = 180
        self.error_threshold = 5

    async def start(self):
        """Start the enhanced worker with health monitoring"""
        self.running = True
        logger.info(f"Enhanced worker {self.bot_index} started")

        while self.running:
            try:
                # Health check
                await self.check_health()

                # Get message from smart queue with timeout
                try:
                    message = await asyncio.wait_for(
                        self.queue_manager.dequeue_message(self.bot_index),
                        timeout=30.0
                    )
                except asyncio.TimeoutError:
                    logger.debug(f"Worker {self.bot_index}: No messages for 30s")
                    self.update_activity()
                    continue

                if not message:
                    await asyncio.sleep(0.1)
                    continue

                # Process message with timing and timeout protection
                async with self.timeout_guard():
                    start_time = time.time()
                    success = await self.process_message(message)
                    processing_time = time.time() - start_time

                    # Update metrics
                    self.queue_manager.mark_message_processed(message, success, processing_time)
                    self.update_activity(success)

                    if not success:
                        self.consecutive_errors += 1
                        if self.consecutive_errors >= self.error_threshold:
                            logger.warning(f"Worker {self.bot_index}: Too many consecutive errors, restarting...")
                            await self.restart()
                            continue

                        # Requeue failed message with backoff
                        await self.queue_manager.requeue_failed_message(
                            message,
                            f"Processing failed (attempt {message.retry_count + 1})",
                            backoff_factor=2
                        )
                    else:
                        self.consecutive_errors = 0

            except asyncio.TimeoutError:
                logger.error(f"Worker {self.bot_index}: Message processing timed out")
                self.consecutive_errors += 1
                await self.handle_timeout()
            except Exception as e:
                logger.error(f"Worker {self.bot_index} error: {str(e)}", exc_info=True)
                self.consecutive_errors += 1
                if self.consecutive_errors >= self.error_threshold:
                    await self.restart()
                await asyncio.sleep(min(2 ** self.consecutive_errors, 30))

    async def process_message(self, message: QueuedMessage) -> bool:
        """Process message with enhanced error handling"""
        try:
            message_data = message.data
            pair_id = message_data.get('pair_id')
            source_message_id = message_data.get('source_message_id')

            logger.info(f"Worker {self.bot_index} processing message for pair {pair_id}")

            # Check for existing media forward
            if message_data.get('has_media', False) and source_message_id:
                existing_dest_id = self.parent_bot.message_mapper.get_destination_message_id(source_message_id, pair_id)
                if existing_dest_id:
                    logger.info(f"Skipping duplicate media forward for message {source_message_id} in pair {pair_id}")
                    return True

            # Use existing send_message_complete method
            success = await self.send_message_with_retries(message_data)

            if success:
                logger.info(f"Worker {self.bot_index} successfully sent message for pair {pair_id}")
            else:
                logger.warning(f"Worker {self.bot_index} failed to send message for pair {pair_id}")

            return success

        except Exception as e:
            logger.error(f"Worker {self.bot_index} message processing error: {e}")
            return False

    async def send_message_with_retries(self, message_data: dict) -> bool:
        """Send message with built-in retry logic"""
        for attempt in range(3):
            try:
                success = await self.parent_bot.send_message_complete(message_data, self.bot)
                if success:
                    return True
            except Exception as e:
                logger.warning(f"Send attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)

        return False

    async def check_health(self):
        """Check worker health and perform maintenance if needed"""
        now = time.time()
        if now - self.last_health_check < self.health_check_interval:
            return

        self.last_health_check = now
        inactivity_time = now - self.last_activity

        # Log health status
        logger.info(
            f"Worker {self.bot_index} health check: "
            f"Messages processed: {self.messages_processed}, "
            f"Last activity: {inactivity_time:.1f}s ago, "
            f"Consecutive errors: {self.consecutive_errors}"
        )

        # Check for stuck worker
        if inactivity_time > self.stuck_threshold:
            logger.warning(f"Worker {self.bot_index} appears stuck, restarting...")
            await self.restart()

    async def restart(self):
        """Restart the worker gracefully"""
        logger.info(f"Worker {self.bot_index} restarting...")
        self.running = False

        # Reset metrics
        self.consecutive_errors = 0
        self.messages_processed = 0
        self.last_activity = time.time()

        # Small delay before restarting
        await asyncio.sleep(1)

        # Restart
        self.running = True
        logger.info(f"Worker {self.bot_index} restarted")

    async def handle_timeout(self):
        """Handle message processing timeout"""
        logger.error(f"Worker {self.bot_index}: Processing timeout detected")
        await self.restart()

    @contextlib.asynccontextmanager
    async def timeout_guard(self):
        """Context manager to guard against processing timeouts"""
        try:
            yield
        except asyncio.TimeoutError:
            logger.error(f"Worker {self.bot_index}: Operation timed out")
            raise
        except Exception as e:
            logger.error(f"Worker {self.bot_index}: Error in guarded operation: {e}")
            raise

    def update_activity(self, success=True):
        """Update worker activity timestamps and metrics"""
        self.last_activity = time.time()
        if success:
            self.messages_processed += 1

    def stop(self):
        """Stop the worker gracefully"""
        self.running = False
        logger.info(f"Enhanced worker {self.bot_index} stopped")

class TelegramCopyBot:
    """Complete main bot class with all features"""
    
    def __init__(self):
        # Initialize core components
        self.db = DatabaseManager()
        self.filter_manager = FilterManager(self.db)
        self.load_balancer = BotLoadBalancer(BOT_TOKENS)
        self.queue_manager = SmartQueueManager(BOT_TOKENS, max_queue_size=100000)
        self.message_mapper = EnhancedMessageMapper(self.db)

        # Runtime state
        self.system_paused = False
        self.active_pairs = {}
        self.enhanced_workers = []

        # Media processing optimizations
        self.media_cache = {}
        self.download_semaphore = asyncio.Semaphore(20)
        self.upload_semaphore = asyncio.Semaphore(10)

        # Create optimized temp directory
        self.temp_dir = "temp_media"
        os.makedirs(self.temp_dir, exist_ok=True)

        # Initialize Telegram components
        self.userbot = TelegramClient(
            "userbot_session",
            API_ID,
            API_HASH,
            connection_retries=3,
            retry_delay=1,
            timeout=30,
            request_retries=3
        )
        self.app = Application.builder().token(PRIMARY_BOT_TOKEN).build()

        # Bind all command handlers
        self.setup_handlers()

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show enhanced system statistics"""
        try:
            pairs = self.db.get_all_pairs()
            active_pairs = [p for p in pairs if p.status == "active"]
            
            total_copied = sum(p.stats.get('messages_copied', 0) for p in pairs)
            total_filtered = sum(p.stats.get('messages_filtered', 0) for p in pairs)
            total_replies = sum(p.stats.get('replies_preserved', 0) for p in pairs)
            total_edits = sum(p.stats.get('edits_synced', 0) for p in pairs)
            total_deletes = sum(p.stats.get('deletes_synced', 0) for p in pairs)
            total_mentions = sum(p.stats.get('mentions_removed', 0) for p in pairs)
            total_headers = sum(p.stats.get('headers_removed', 0) for p in pairs)
            total_footers = sum(p.stats.get('footers_removed', 0) for p in pairs)

            queue_stats = self.queue_manager.get_queue_stats()
            total_pending = queue_stats.get('total_pending', 0)

            text = (
                f"📊 **Enhanced System Statistics**\n\n"
                f"**📋 Pairs:**\n"
                f"• Total: {len(pairs)}\n"
                f"• Active: {len(active_pairs)}\n"
                f"• Paused: {len(pairs) - len(active_pairs)}\n\n"
                f"**📨 Messages:**\n"
                f"• Copied: {total_copied:,}\n"
                f"• Filtered: {total_filtered:,}\n"
                f"• Pending: {total_pending:,}\n\n"
                f"**🔄 Sync Features:**\n"
                f"• Replies Preserved: {total_replies:,}\n"
                f"• Edits Synced: {total_edits:,}\n"
                f"• Deletes Synced: {total_deletes:,}\n\n"
                f"**🎯 Content Processing:**\n"
                f"• Mentions Removed: {total_mentions:,}\n"
                f"• Headers Removed: {total_headers:,}\n"
                f"• Footers Removed: {total_footers:,}\n\n"
                f"**🤖 System:**\n"
                f"• Bot Tokens: {len(BOT_TOKENS)}\n"
                f"• Processing Rate: {queue_stats.get('processing_rate', 0):.1f}/sec\n"
                f"• Success Rate: {queue_stats.get('success_rate', 0):.1f}%\n"
                f"• Status: {'🔴 Paused' if self.system_paused else '🟢 Active'}"
            )

            await update.message.reply_text(text, parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ Error retrieving stats: {str(e)}")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show complete help"""
        help_text = (
            "🤖 **Complete Telegram Message Copying Bot**\n\n"
            "**📋 Pair Management:**\n"
            "• `/create_pair <source> <dest> <name>` - Create pair\n"
            "• `/list_pairs` - List all pairs\n"
            "• `/pause_pair <id>` - Pause pair\n"
            "• `/resume_pair <id>` - Resume pair\n"
            "• `/delete_pair <id>` - Delete pair\n\n"
            "**🌐 Global Controls:**\n"
            "• `/pause_all` - Pause all pairs\n"
            "• `/resume_all` - Resume all pairs\n\n"
            "**🚫 Word Filtering:**\n"
            "• `/block_word <word> <scope>` - Block word\n"
            "• `/unblock_word <word> <scope>` - Unblock word\n"
            "• `/list_blocks [scope]` - List blocked words\n\n"
            "**🎯 Enhanced Filtering:**\n"
            "• `/set_mention_removal <scope> <on/off> [placeholder]` - Configure mentions\n"
            "• `/add_header_pattern <pair_id> <pattern>` - Add header pattern\n"
            "• `/add_footer_pattern <pair_id> <pattern>` - Add footer pattern\n"
            "• `/list_patterns <pair_id>` - List all patterns\n"
            "• `/remove_pattern <pair_id> <type> <index>` - Remove pattern\n\n"
        )

        if IMAGE_PROCESSING_AVAILABLE:
            help_text += (
                "**🖼️ Image Blocking:**\n"
                "• `/block_image <scope>` - Block image (reply to image)\n"
                "• `/list_blocked_images [scope]` - List blocked images\n"
                "• `/block_image_global [description]` - Block image globally (reply to image)\n"
                "• `/list_global_blocks` - List globally blocked images\n"
                "• `/remove_global_block <hash>` - Remove global block\n"
                "• `/check_image_status` - Check image blocking status (reply to image)\n\n"
            )

        help_text += (
            "**⚙️ Sync Settings:**\n"
            "• `/sync_settings <scope> <setting> <on/off>` - Configure sync\n\n"
            "**📊 Utilities:**\n"
            "• `/stats` - Enhanced statistics\n"
            "• `/queue_stats` - Smart queue statistics\n"
            "• `/queue_settings <setting> <value>` - Configure queue\n"
            "• `/get_chat_id` - Get chat ID\n"
            "• `/help` - This help\n\n"
            "**🚀 Smart Queue Features:**\n"
            "• Intelligent load balancing across multiple bots\n"
            "• Priority processing (URGENT → HIGH → NORMAL → LOW)\n"
            "• Adaptive rate limiting and auto-optimization\n"
            "• Real-time performance monitoring\n\n"
            "**💡 Notes:**\n"
            "• Use 'all' for global scope or pair ID for specific\n"
            "• Sync settings: sync_edits, sync_deletes, preserve_replies\n"
            "• Patterns support regex expressions\n"
            "• Smart queue automatically balances load across bots"
        )

        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def get_chat_id_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get chat ID"""
        if update.message.forward_from_chat:
            chat = update.message.forward_from_chat
            await update.message.reply_text(
                f"📋 **Chat Information**\n\n"
                f"**Name:** {chat.title}\n"
                f"**ID:** `{chat.id}`\n"
                f"**Type:** {chat.type}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "Forward a message from the target chat to get its ID"
            )
            
    async def sync_settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Configure sync settings for pairs"""
        if len(context.args) < 3:
            await update.message.reply_text(
                "⚙️ **Sync Settings Configuration**\n\n"
                "Usage: `/sync_settings <scope> <setting> <action>`\n\n"
                "**Available Settings:**\n"
                "• `sync_edits` - Synchronize message edits\n"
                "• `sync_deletes` - Synchronize message deletions\n"
                "• `preserve_replies` - Maintain reply chains\n\n"
                "**Examples:**\n"
                "• `/sync_settings 1 sync_edits on`\n"
                "• `/sync_settings all sync_deletes off`\n"
                "• `/sync_settings 2 preserve_replies on`",
                parse_mode='Markdown'
            )
            return

        scope = context.args[0]
        setting = context.args[1]
        action = context.args[2].lower()

        if action not in ['on', 'off']:
            await update.message.reply_text("❌ Action must be 'on' or 'off'")
            return

        enable = action == 'on'

        try:
            if scope == "all":
                pairs = self.db.get_all_pairs()
                updated_count = 0
                for pair in pairs:
                    pair.filters[setting] = enable
                    self.db.update_pair(pair)
                    updated_count += 1

                await update.message.reply_text(
                    f"✅ **Global Sync Setting Updated**\n\n"
                    f"⚙️ **Setting:** {setting}\n"
                    f"🔄 **Status:** {'Enabled' if enable else 'Disabled'}\n"
                    f"📊 **Affected Pairs:** {updated_count}",
                    parse_mode='Markdown'
                )
            else:
                pair_id = int(scope)
                pair = self.db.get_pair(pair_id)
                if not pair:
                    await update.message.reply_text("❌ Invalid pair ID")
                    return

                pair.filters[setting] = enable
                self.db.update_pair(pair)

                await update.message.reply_text(
                    f"✅ **Sync Setting Updated**\n\n"
                    f"🎯 **Pair:** #{pair_id} - {pair.name}\n"
                    f"⚙️ **Setting:** {setting}\n"
                    f"🔄 **Status:** {'Enabled' if enable else 'Disabled'}",
                    parse_mode='Markdown'
                )

        except ValueError:
            await update.message.reply_text("❌ Invalid pair ID")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
            
    async def queue_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed queue statistics"""
        stats = self.queue_manager.get_queue_stats()
        
        text = f"📊 **Smart Queue Statistics**\n\n"
        text += f"**📈 Overall Performance:**\n"
        text += f"• Total Processed: {stats['total_processed']:,}\n"
        text += f"• Total Pending: {stats['total_pending']:,}\n"
        text += f"• Processing Rate: {stats['processing_rate']:.1f}/sec\n"
        text += f"• Success Rate: {stats['success_rate']:.1f}%\n"
        text += f"• Uptime: {stats['uptime_seconds']:.1f}s\n\n"
        text += f"**⚙️ Configuration:**\n"
        text += f"• Algorithm: {stats['load_balance_algorithm']}\n"
        text += f"• Adaptive: {'✅' if stats['adaptive_enabled'] else '❌'}\n\n"
        text += f"**🤖 Bot Performance:**\n"

        for bot_name, bot_stats in stats['bot_stats'].items():
            bot_num = bot_name.split('_')[1]
            status = "🚫" if bot_stats['rate_limited'] else "✅"
            text += f"{status} **Bot #{bot_num}:**\n"
            text += f"  Queue: {bot_stats['queue_size']}\n"
            text += f"  Success: {bot_stats['success_rate']:.1f}%\n"
            text += f"  Speed: {bot_stats['avg_processing_time']:.2f}s\n\n"

        await update.message.reply_text(text, parse_mode='Markdown')
        self.userbot = TelegramClient(
            'userbot_session',
            int(API_ID),
            API_HASH,
            connection_retries=3,
            retry_delay=1,
            timeout=30,
            request_retries=3
        )

        self.app = Application.builder().token(PRIMARY_BOT_TOKEN).build()

        # Runtime state
        self.active_pairs = {}
        self.workers = []
        self.enhanced_workers = []
        self.system_paused = False

        self.setup_handlers()
        logger.info(f"Complete bot initialized with {len(BOT_TOKENS)} tokens")

    def setup_handlers(self):
        """Setup complete command handlers"""
        handlers = [
            # Basic handlers
            CommandHandler("create_pair", self.create_pair_command),
            CommandHandler("list_pairs", self.list_pairs_command),
            CommandHandler("pause_pair", self.pause_pair_command),
            CommandHandler("resume_pair", self.resume_pair_command),
            CommandHandler("delete_pair", self.delete_pair_command),
            CommandHandler("pause_all", self.pause_all_command),
            CommandHandler("resume_all", self.resume_all_command),
            
            # Word filtering handlers
            CommandHandler("block_word", self.block_word_command),
            CommandHandler("unblock_word", self.unblock_word_command),
            CommandHandler("list_blocks", self.list_blocks_command),
            
            # Utility handlers
            CommandHandler("stats", self.stats_command),
            CommandHandler("help", self.help_command),
            CommandHandler("get_chat_id", self.get_chat_id_command),
            
            # Settings handlers
            CommandHandler("sync_settings", self.sync_settings_command),
            CommandHandler("queue_settings", self.queue_settings_command),
            
            # Pattern handlers
            CommandHandler("set_mention_removal", self.set_mention_removal_command),
            CommandHandler("add_header_pattern", self.add_header_pattern_command),
            CommandHandler("add_footer_pattern", self.add_footer_pattern_command),
            CommandHandler("list_patterns", self.list_patterns_command),
            CommandHandler("remove_pattern", self.remove_pattern_command),
            
            # Queue handlers
            CommandHandler("queue_stats", self.queue_stats_command),
        ]
        
        # Register all basic handlers
        for handler in handlers:
            self.app.add_handler(handler)

        # Add image handlers if available
        if IMAGE_PROCESSING_AVAILABLE:
            # Image handlers
            self.app.add_handler(CommandHandler("block_image", self.block_image_command))
            self.app.add_handler(CommandHandler("list_blocked_images", self.list_blocked_images_command))
            self.app.add_handler(CommandHandler("block_image_global", self.block_image_global_command))
            self.app.add_handler(CommandHandler("list_global_blocks", self.list_global_blocks_command))
            self.app.add_handler(CommandHandler("remove_global_block", self.remove_global_block_command))
            self.app.add_handler(CommandHandler("check_image_status", self.check_image_status_command))


    # PAIR MANAGEMENT COMMANDS
    async def create_pair_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Create new pair"""
        if len(context.args) < 3:
            await update.message.reply_text(
                "Usage: `/create_pair <source_chat_id> <dest_chat_id> <name>`\n\n"
                "Example: `/create_pair -1001234567 -1001234568 'News Copy'`",
                parse_mode='Markdown'
            )
            return

        try:
            source_id = int(context.args[0])
            dest_id = int(context.args[1])
            name = " ".join(context.args[2:])

            # Get next available bot
            bot, bot_index = self.load_balancer.get_next_bot()

            # Test bot access
            try:
                await bot.get_chat(dest_id)
            except Exception as e:
                await update.message.reply_text(f"❌ Bot cannot access destination: {e}")
                return

            pair_id = self.db.create_pair(source_id, dest_id, name, bot_index)

            await update.message.reply_text(
                f"✅ **Pair Created**\n\n"
                f"ID: #{pair_id}\n"
                f"Name: {name}\n"
                f"Source: `{source_id}`\n"
                f"Destination: `{dest_id}`\n"
                f"Bot: #{bot_index + 1}\n\n"
                f"Starting monitoring...",
                parse_mode='Markdown'
            )

            await self.start_pair_monitoring(pair_id)

        except ValueError:
            await update.message.reply_text("❌ Invalid chat ID format")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def list_pairs_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all pairs with enhanced statistics"""
        pairs = self.db.get_all_pairs()
        if not pairs:
            await update.message.reply_text("📭 No pairs found. Create one with `/create_pair`")
            return

        text = "📋 **All Message Copying Pairs**\n\n"
        for pair in pairs:
            status_emoji = "✅" if pair.status == "active" else "⏸️"
            text += (
                f"{status_emoji} **#{pair.id} - {pair.name}**\n"
                f"🤖 Bot: #{pair.assigned_bot_index + 1}\n"
                f"📊 Copied: {pair.stats.get('messages_copied', 0)} | "
                f"Filtered: {pair.stats.get('messages_filtered', 0)}\n"
                f"🔄 Replies: {pair.stats.get('replies_preserved', 0)} | "
                f"Edits: {pair.stats.get('edits_synced', 0)} | "
                f"Deletes: {pair.stats.get('deletes_synced', 0)}\n"
                f"🎯 Mentions: {pair.stats.get('mentions_removed', 0)} | "
                f"Headers: {pair.stats.get('headers_removed', 0)} | "
                f"Footers: {pair.stats.get('footers_removed', 0)}\n\n"
            )

        await update.message.reply_text(text, parse_mode='Markdown')

    async def pause_pair_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Pause specific pair"""
        if not context.args:
            await update.message.reply_text("Usage: `/pause_pair <pair_id>`")
            return

        try:
            pair_id = int(context.args[0])
            pair = self.db.get_pair(pair_id)
            if not pair:
                await update.message.reply_text(f"❌ Pair #{pair_id} not found")
                return

            pair.status = "paused"
            self.db.update_pair(pair)

            # Stop monitoring
            if pair_id in self.active_pairs:
                handler = self.active_pairs.pop(pair_id)
                self.userbot.remove_event_handler(handler)

            await update.message.reply_text(f"⏸️ Pair #{pair_id} paused")

        except ValueError:
            await update.message.reply_text("❌ Invalid pair ID")

    async def resume_pair_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resume specific pair"""
        if not context.args:
            await update.message.reply_text("Usage: `/resume_pair <pair_id>`")
            return

        try:
            pair_id = int(context.args[0])
            pair = self.db.get_pair(pair_id)
            if not pair:
                await update.message.reply_text(f"❌ Pair #{pair_id} not found")
                return

            pair.status = "active"
            self.db.update_pair(pair)

            await self.start_pair_monitoring(pair_id)
            await update.message.reply_text(f"▶️ Pair #{pair_id} resumed")

        except ValueError:
            await update.message.reply_text("❌ Invalid pair ID")

    async def delete_pair_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Delete specific pair"""
        if not context.args:
            await update.message.reply_text("Usage: `/delete_pair <pair_id>`")
            return

        try:
            pair_id = int(context.args[0])
            pair = self.db.get_pair(pair_id)
            if not pair:
                await update.message.reply_text(f"❌ Pair #{pair_id} not found")
                return

            # Stop monitoring
            if pair_id in self.active_pairs:
                handler = self.active_pairs.pop(pair_id)
                self.userbot.remove_event_handler(handler)

            self.db.delete_pair(pair_id)
            await update.message.reply_text(f"🗑️ Pair #{pair_id} deleted successfully")

        except ValueError:
            await update.message.reply_text("❌ Invalid pair ID")

    # GLOBAL CONTROL COMMANDS
    async def pause_all_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Pause all pairs"""
        self.db.set_setting('system_paused', 'true')
        self.system_paused = True
        pairs = self.db.get_all_pairs()
        paused_count = 0

        for pair in pairs:
            if pair.status == "active":
                pair.status = "paused"
                self.db.update_pair(pair)
                paused_count += 1

            if pair.id in self.active_pairs:
                handler = self.active_pairs.pop(pair.id)
                self.userbot.remove_event_handler(handler)

        await update.message.reply_text(
            f"⏸️ **ALL PAIRS PAUSED**\n\n"
            f"Paused: {paused_count} pairs\n"
            f"System status: Halted\n\n"
            f"Use `/resume_all` to resume"
        )

    async def resume_all_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resume all pairs"""
        self.db.set_setting('system_paused', 'false')
        self.system_paused = False
        pairs = self.db.get_all_pairs()
        resumed_count = 0

        for pair in pairs:
            if pair.status == "paused":
                pair.status = "active"
                self.db.update_pair(pair)
                resumed_count += 1
                await self.start_pair_monitoring(pair.id)

        await update.message.reply_text(
            f"▶️ **ALL PAIRS RESUMED**\n\n"
            f"Resumed: {resumed_count} pairs\n"
            f"System status: Active\n\n"
            f"Message processing started"
        )

    # WORD BLOCKING COMMANDS
    async def block_word_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Block word/phrase"""
        if len(context.args) < 2:
            await update.message.reply_text(
                "Usage: `/block_word <word> <scope>`\n\n"
                "Scope: 'all' for global or pair ID for specific\n"
                "Example: `/block_word spam all`",
                parse_mode='Markdown'
            )
            return

        word = context.args[0].lower()
        scope = context.args[1].lower()

        try:
            if scope == "all":
                # Global block
                global_blocks = json.loads(self.db.get_setting('global_blocks', '{"words": []}'))
                if word not in global_blocks['words']:
                    global_blocks['words'].append(word)
                    self.db.set_setting('global_blocks', json.dumps(global_blocks))

                    await update.message.reply_text(
                        f"🚫 **Word Blocked Globally**\n\n"
                        f"Word: '{word}'\n"
                        f"Scope: All pairs\n"
                        f"Effect: Applied to all current and future pairs"
                    )
                else:
                    await update.message.reply_text(f"⚠️ Word '{word}' already blocked globally")
            else:
                # Pair-specific block
                pair_id = int(scope)
                pair = self.db.get_pair(pair_id)
                if not pair:
                    await update.message.reply_text(f"❌ Pair #{pair_id} not found")
                    return

                if word not in pair.filters['blocked_words']:
                    pair.filters['blocked_words'].append(word)
                    self.db.update_pair(pair)

                    await update.message.reply_text(
                        f"🚫 **Word Blocked for Pair**\n\n"
                        f"Word: '{word}'\n"
                        f"Pair: #{pair_id} - {pair.name}\n"
                        f"Effect: Applied only to this pair"
                    )
                else:
                    await update.message.reply_text(f"⚠️ Word '{word}' already blocked for pair #{pair_id}")

        except ValueError:
            await update.message.reply_text("❌ Invalid pair ID")

    async def unblock_word_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Unblock word/phrase"""
        if len(context.args) < 2:
            await update.message.reply_text(
                "Usage: `/unblock_word <word> <scope>`\n\n"
                "Example: `/unblock_word spam all`"
            )
            return

        word = context.args[0].lower()
        scope = context.args[1].lower()

        try:
            if scope == "all":
                global_blocks = json.loads(self.db.get_setting('global_blocks', '{"words": []}'))
                if word in global_blocks['words']:
                    global_blocks['words'].remove(word)
                    self.db.set_setting('global_blocks', json.dumps(global_blocks))
                    await update.message.reply_text(f"✅ Word '{word}' unblocked globally")
                else:
                    await update.message.reply_text(f"⚠️ Word '{word}' not found in global blocks")
            else:
                pair_id = int(scope)
                pair = self.db.get_pair(pair_id)
                if not pair:
                    await update.message.reply_text(f"❌ Pair #{pair_id} not found")
                    return

                if word in pair.filters['blocked_words']:
                    pair.filters['blocked_words'].remove(word)
                    self.db.update_pair(pair)
                    await update.message.reply_text(f"✅ Word '{word}' unblocked for pair #{pair_id}")
                else:
                    await update.message.reply_text(f"⚠️ Word '{word}' not blocked for pair #{pair_id}")

        except ValueError:
            await update.message.reply_text("❌ Invalid pair ID")

    async def list_blocks_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List blocked words"""
        scope = context.args[0].lower() if context.args else "all"

        if scope == "all":
            global_blocks = json.loads(self.db.get_setting('global_blocks', '{"words": []}'))
            global_words = global_blocks.get('words', [])

            text = "🚫 **Blocked Words**\n\n"
            if global_words:
                text += f"🌐 **Global ({len(global_words)}):**\n"
                for word in global_words[:10]:
                    text += f"• `{word}`\n"
                if len(global_words) > 10:
                    text += f"... and {len(global_words) - 10} more\n"
            else:
                text += "🌐 **Global:** None\n"

            await update.message.reply_text(text, parse_mode='Markdown')
        else:
            try:
                pair_id = int(scope)
                pair = self.db.get_pair(pair_id)
                if not pair:
                    await update.message.reply_text(f"❌ Pair #{pair_id} not found")
                    return

                pair_words = pair.filters.get('blocked_words', [])
                global_blocks = json.loads(self.db.get_setting('global_blocks', '{"words": []}'))
                global_words = global_blocks.get('words', [])

                text = f"🚫 **Blocked Words - Pair #{pair_id}**\n\n"

                if global_words:
                    text += f"🌐 **Global affecting this pair:** {len(global_words)} words\n"

                if pair_words:
                    text += f"🔗 **Pair-specific:** {len(pair_words)} words\n"
                    for word in pair_words:
                        text += f"• `{word}`\n"
                else:
                    text += "🔗 **Pair-specific:** None\n"

                await update.message.reply_text(text, parse_mode='Markdown')

            except ValueError:
                await update.message.reply_text("❌ Invalid pair ID")

    # ENHANCED FILTERING COMMANDS
    async def set_mention_removal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Configure mention removal for pairs"""
        if len(context.args) < 2:
            await update.message.reply_text(
                "**Mention Removal Configuration**\n\n"
                "Usage: `/set_mention_removal <scope> <action> [placeholder]`\n\n"
                "**Options:**\n"
                "• Action: on/off\n"
                "• Placeholder: Custom text to replace mentions (optional)\n\n"
                "**Examples:**\n"
                "• `/set_mention_removal 1 on`\n"
                "• `/set_mention_removal all off`\n"
                "• `/set_mention_removal 2 on [HIDDEN]`",
                parse_mode='Markdown'
            )
            return

        scope = context.args[0]
        action = context.args[1].lower()
        placeholder = " ".join(context.args[2:]) if len(context.args) > 2 else "[User]"

        if action not in ['on', 'off']:
            await update.message.reply_text("❌ Action must be 'on' or 'off'")
            return

        enable = action == 'on'

        try:
            if scope == "all":
                pairs = self.db.get_all_pairs()
                updated_count = 0
                for pair in pairs:
                    pair.filters['remove_mentions'] = enable
                    if enable:
                        pair.filters['mention_placeholder'] = placeholder
                    self.db.update_pair(pair)
                    updated_count += 1

                await update.message.reply_text(
                    f"✅ **Mention Removal Updated Globally**\n\n"
                    f"Status: {'Enabled' if enable else 'Disabled'}\n"
                    f"Placeholder: {placeholder if enable else 'N/A'}\n"
                    f"Affected Pairs: {updated_count}",
                    parse_mode='Markdown'
                )
            else:
                pair_id = int(scope)
                pair = self.db.get_pair(pair_id)
                if not pair:
                    await update.message.reply_text(f"❌ Pair #{pair_id} not found")
                    return

                pair.filters['remove_mentions'] = enable
                if enable:
                    pair.filters['mention_placeholder'] = placeholder
                self.db.update_pair(pair)

                await update.message.reply_text(
                    f"✅ **Mention Removal Updated**\n\n"
                    f"Pair: #{pair_id} - {pair.name}\n"
                    f"Status: {'Enabled' if enable else 'Disabled'}\n"
                    f"Placeholder: {placeholder if enable else 'N/A'}",
                    parse_mode='Markdown'
                )

        except ValueError:
            await update.message.reply_text("❌ Invalid pair ID")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def add_header_pattern_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add header removal pattern"""
        if len(context.args) < 2:
            await update.message.reply_text(
                "**Add Header Pattern**\n\n"
                "Usage: `/add_header_pattern <pair_id> <pattern>`\n\n"
                "**Examples:**\n"
                "• `/add_header_pattern 1 'Breaking News:'`\n"
                "• `/add_header_pattern 2 '^📰.*'`\n\n"
                "Patterns support regex.",
                parse_mode='Markdown'
            )
            return

        try:
            pair_id = int(context.args[0])
            pattern = " ".join(context.args[1:])

            pair = self.db.get_pair(pair_id)
            if not pair:
                await update.message.reply_text(f"❌ Pair #{pair_id} not found")
                return

            if 'header_patterns' not in pair.filters:
                pair.filters['header_patterns'] = []

            if pattern not in pair.filters['header_patterns']:
                pair.filters['header_patterns'].append(pattern)
                pair.filters['remove_headers'] = True  # Auto-enable
                self.db.update_pair(pair)

                await update.message.reply_text(
                    f"✅ **Header Pattern Added**\n\n"
                    f"Pair: #{pair_id} - {pair.name}\n"
                    f"Pattern: `{pattern}`\n"
                    f"Header removal: Enabled\n"
                    f"Total patterns: {len(pair.filters['header_patterns'])}",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text("⚠️ Pattern already exists")

        except ValueError:
            await update.message.reply_text("❌ Invalid pair ID")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def add_footer_pattern_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add footer removal pattern"""
        if len(context.args) < 2:
            await update.message.reply_text(
                "**Add Footer Pattern**\n\n"
                "Usage: `/add_footer_pattern <pair_id> <pattern>`\n\n"
                "**Examples:**\n"
                "• `/add_footer_pattern 1 'Source: CNN'`\n"
                "• `/add_footer_pattern 2 '©.*$'`\n\n"
                "Patterns support regex.",
                parse_mode='Markdown'
            )
            return

async def add_footer_pattern_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add footer removal pattern"""
    try:
        pair_id = int(context.args[0])
        pattern = " ".join(context.args[1:])

        pair = self.db.get_pair(pair_id)
        if not pair:
            await update.message.reply_text(f"❌ Pair #{pair_id} not found")
            return

        if 'footer_patterns' not in pair.filters:
            pair.filters['footer_patterns'] = []

        if pattern not in pair.filters['footer_patterns']:
            pair.filters['footer_patterns'].append(pattern)
            pair.filters['remove_footers'] = True
            self.db.update_pair(pair)

            await update.message.reply_text(
                f"✅ **Footer Pattern Added**\n\n"
                f"Pair: #{pair_id} - {pair.name}\n"
                f"Pattern: `{pattern}`\n"
                f"Footer removal: Enabled\n"
                f"Total patterns: {len(pair.filters['footer_patterns'])}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("⚠️ Pattern already exists")

    except ValueError:
        await update.message.reply_text("❌ Invalid pair ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def list_patterns_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List header/footer patterns for pair"""
    if not context.args:
        await update.message.reply_text("Usage: `/list_patterns <pair_id>`")
        return

    try:
        pair_id = int(context.args[0])
        pair = self.db.get_pair(pair_id)
        if not pair:
            await update.message.reply_text(f"❌ Pair #{pair_id} not found")
            return

        text = f"🎨 **Patterns for Pair #{pair_id}**\n\n"
        text += f"**Name:** {pair.name}\n\n"

        # Header patterns
        header_patterns = pair.filters.get('header_patterns', [])
        text += f"**🔝 Header Removal:** {'✅ Enabled' if pair.filters.get('remove_headers', False) else '❌ Disabled'}\n"
        if header_patterns:
            text += f"**Header Patterns ({len(header_patterns)}):**\n"
            for i, pattern in enumerate(header_patterns, 1):
                text += f"{i}. `{pattern}`\n"
        else:
            text += "**Header Patterns:** None\n"

        text += "\n"

        # Footer patterns
        footer_patterns = pair.filters.get('footer_patterns', [])
        text += f"**🔚 Footer Removal:** {'✅ Enabled' if pair.filters.get('remove_footers', False) else '❌ Disabled'}\n"
        if footer_patterns:
            text += f"**Footer Patterns ({len(footer_patterns)}):**\n"
            for i, pattern in enumerate(footer_patterns, 1):
                text += f"{i}. `{pattern}`\n"
        else:
            text += "**Footer Patterns:** None\n"

        # Mention removal
        text += f"\n**👤 Mention Removal:** {'✅ Enabled' if pair.filters.get('remove_mentions', False) else '❌ Disabled'}\n"
        if pair.filters.get('remove_mentions', False):
            text += f"**Placeholder:** {pair.filters.get('mention_placeholder', '[User]')}\n"

        await update.message.reply_text(text, parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid pair ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def remove_pattern_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove header/footer pattern"""
    if len(context.args) < 3:
        await update.message.reply_text(
            "**Remove Pattern**\n\n"
            "Usage: `/remove_pattern <pair_id> <type> <index>`\n\n"
            "**Examples:**\n"
            "• `/remove_pattern 1 header 2`\n"
            "• `/remove_pattern 3 footer 1`",
            parse_mode='Markdown'
        )
        return

    try:
        pair_id = int(context.args[0])
        pattern_type = context.args[1].lower()
        pattern_index = int(context.args[2]) - 1

        if pattern_type not in ['header', 'footer']:
            await update.message.reply_text("❌ Pattern type must be 'header' or 'footer'")
            return

        pair = self.db.get_pair(pair_id)
        if not pair:
            await update.message.reply_text(f"❌ Pair #{pair_id} not found")
            return

        pattern_key = f'{pattern_type}_patterns'
        patterns = pair.filters.get(pattern_key, [])

        if 0 <= pattern_index < len(patterns):
            removed_pattern = patterns.pop(pattern_index)
            self.db.update_pair(pair)

            await update.message.reply_text(
                f"✅ **Pattern Removed**\n\n"
                f"Pair: #{pair_id} - {pair.name}\n"
                f"Type: {pattern_type.title()}\n"
                f"Removed: `{removed_pattern}`\n"
                f"Remaining: {len(patterns)} patterns",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"❌ Invalid pattern index. Available: 1-{len(patterns)}")

    except ValueError:
        await update.message.reply_text("❌ Invalid pair ID or pattern index")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# IMAGE BLOCKING COMMANDS
async def block_image_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Block image using PHash"""
    if not IMAGE_PROCESSING_AVAILABLE:
        await update.message.reply_text("❌ Image processing not available")
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text(
            "Usage: Reply to an image with `/block_image <scope>`\n\n"
            "Scope: 'all' for global or pair ID\n"
            "Example: Reply to image + `/block_image all`"
        )
        return

    if not context.args:
        await update.message.reply_text("❌ Please specify scope: 'all' or pair ID")
        return

    scope = context.args[0].lower()
    blocked_by = update.effective_user.username or str(update.effective_user.id)

    try:
        pair_id = None if scope == "all" else int(scope)

        if pair_id is not None:
            pair = self.db.get_pair(pair_id)
            if not pair:
                await update.message.reply_text(f"❌ Pair #{pair_id} not found")
                return

        # Download image
        photo = update.message.reply_to_message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
            await file.download_to_drive(temp_file.name)
            temp_path = temp_file.name

        # Block image
        success, phash = self.filter_manager.image_blocker.block_image_from_file(
            temp_path, pair_id, blocked_by=blocked_by
        )

        os.unlink(temp_path)

        if success:
            scope_text = "all pairs" if pair_id is None else f"pair #{pair_id}"
            await update.message.reply_text(
                f"🚫 **Image Blocked**\n\n"
                f"Hash: `{phash}`\n"
                f"Scope: {scope_text}\n"
                f"Blocked by: @{blocked_by}"
            )
        else:
            await update.message.reply_text("⚠️ Image already blocked for this scope")

    except ValueError:
        await update.message.reply_text("❌ Invalid pair ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def list_blocked_images_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List blocked images"""
    if not IMAGE_PROCESSING_AVAILABLE:
        await update.message.reply_text("❌ Image processing not available")
        return

    scope = context.args[0].lower() if context.args else "all"

    try:
        pair_id = None if scope == "all" else int(scope)
        blocked_hashes = self.db.get_blocked_images(pair_id)

        if not blocked_hashes:
            scope_text = "all pairs" if pair_id is None else f"pair #{pair_id}"
            await update.message.reply_text(f"📭 No blocked images for {scope_text}")
            return

        text = f"🚫 **Blocked Images**\n\n"
        text += f"Scope: {'All pairs' if pair_id is None else f'Pair #{pair_id}'}\n"
        text += f"Count: {len(blocked_hashes)}\n\n"

        for i, phash in enumerate(blocked_hashes[:10], 1):
            text += f"{i}. `{phash}`\n"

        if len(blocked_hashes) > 10:
            text += f"... and {len(blocked_hashes) - 10} more"

        await update.message.reply_text(text, parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid pair ID")

async def block_image_global_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Block image globally across all pairs"""
    if not IMAGE_PROCESSING_AVAILABLE:
        await update.message.reply_text("❌ Image processing not available")
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text(
            "🌐 Global Image Blocking\n\n"
            "Usage: Reply to an image with /block_image_global [description]\n\n"
            "Examples:\n"
            "• Reply to image + /block_image_global Spam content\n"
            "• Reply to image + /block_image_global\n\n"
            "This will block the image across ALL pairs globally."
        )
        return

    description = " ".join(context.args) if context.args else "Globally blocked image"
    blocked_by = update.effective_user.username or str(update.effective_user.id)

    try:
        # Download image
        photo = update.message.reply_to_message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
            await file.download_to_drive(temp_file.name)
            temp_path = temp_file.name

        # Block globally
        success, phash = self.filter_manager.image_blocker.block_image_globally(
            temp_path, description, blocked_by
        )

        os.unlink(temp_path)

        if success:
            await update.message.reply_text(
                f"🌐 **Image Blocked Globally**\n\n"
                f"Hash: `{phash}`\n"
                f"Description: {description}\n"
                f"Blocked by: @{blocked_by}\n"
                f"Scope: All pairs\n\n"
                f"✅ This image will now be blocked across all current and future pairs.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("⚠️ Image already blocked globally")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def list_global_blocks_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all globally blocked images"""
    if not IMAGE_PROCESSING_AVAILABLE:
        await update.message.reply_text("❌ Image processing not available")
        return

    try:
        blocked_images = self.filter_manager.image_blocker.get_global_blocked_images()

        if not blocked_images:
            await update.message.reply_text("📭 No globally blocked images found")
            return

        text = f"🌐 **Globally Blocked Images ({len(blocked_images)})**\n\n"

        for i, img_info in enumerate(blocked_images[:10], 1):
            text += (
                f"**#{i}**\n"
                f"Hash: `{img_info['phash']}`\n"
                f"Description: {img_info['description'] or 'No description'}\n"
                f"Blocked by: {img_info['blocked_by']}\n"
                f"Usage: {img_info['usage_count']} times\n"
                f"Threshold: {img_info['similarity_threshold']}\n\n"
            )

        if len(blocked_images) > 10:
            text += f"... and {len(blocked_images) - 10} more"

        await update.message.reply_text(text, parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def remove_global_block_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove global image block"""
    if not IMAGE_PROCESSING_AVAILABLE:
        await update.message.reply_text("❌ Image processing not available")
        return

    if not context.args:
        await update.message.reply_text(
            "**Remove Global Block**\n\n"
            "Usage: `/remove_global_block <hash>`\n\n"
            "Example: `/remove_global_block a1b2c3d4e5f6g7h8`\n\n"
            "Use `/list_global_blocks` to see available hashes.",
            parse_mode='Markdown'
        )
        return

    phash = context.args[0]

    try:
        success = self.filter_manager.image_blocker.remove_global_block(phash)

        if success:
            await update.message.reply_text(
                f"✅ **Global Block Removed**\n\n"
                f"Hash: `{phash}`\n"
                f"The image is no longer blocked globally.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"❌ Hash `{phash}` not found in global blocks", parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def check_image_status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check if an image is blocked"""
    if not IMAGE_PROCESSING_AVAILABLE:
        await update.message.reply_text("❌ Image processing not available")
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text(
            "🔍 **Check Image Status**\n\n"
            "Usage: Reply to an image with `/check_image_status`\n\n"
            "This will show if the image is blocked globally or in specific pairs.",
            parse_mode='Markdown'
        )
        return

    try:
        # Download image
        photo = update.message.reply_to_message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
            await file.download_to_drive(temp_file.name)
            temp_path = temp_file.name

        # Check global blocking
        is_blocked, reason, block_info = self.filter_manager.image_blocker.is_image_blocked_globally(temp_path)

        # Calculate hash for display
        phash = self.filter_manager.image_blocker.calculator.calculate_phash(temp_path)

        os.unlink(temp_path)

        text = f"🔍 **Image Status Check**\n\n"
        text += f"Image Hash: `{phash}`\n\n"

        if is_blocked:
            text += f"🚫 **Status:** BLOCKED GLOBALLY\n"
            text += f"**Reason:** {reason}\n"
            text += f"**Description:** {block_info.get('description', 'No description')}\n"
            text += f"**Blocked by:** {block_info.get('blocked_by', 'Unknown')}\n"
            text += f"**Usage Count:** {block_info.get('usage_count', 0)}\n"
        else:
            text += f"✅ **Status:** NOT BLOCKED\n"
            text += f"**Info:** This image is not blocked globally"

        await update.message.reply_text(text, parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# UTILITY COMMANDS
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show enhanced system statistics"""
    pairs = self.db.get_all_pairs()
    active_pairs = [p for p in pairs if p.status == "active"]
    
    total_copied = sum(p.stats.get('messages_copied', 0) for p in pairs)
    total_filtered = sum(p.stats.get('messages_filtered', 0) for p in pairs)
    total_replies = sum(p.stats.get('replies_preserved', 0) for p in pairs)
    total_edits = sum(p.stats.get('edits_synced', 0) for p in pairs)
    total_deletes = sum(p.stats.get('deletes_synced', 0) for p in pairs)
    total_mentions = sum(p.stats.get('mentions_removed', 0) for p in pairs)
    total_headers = sum(p.stats.get('headers_removed', 0) for p in pairs)
    total_footers = sum(p.stats.get('footers_removed', 0) for p in pairs)

    queue_stats = self.queue_manager.get_queue_stats()
    total_pending = queue_stats.get('total_pending', 0)

    text = (
        f"📊 **Enhanced System Statistics**\n\n"
        f"**📋 Pairs:**\n"
        f"• Total: {len(pairs)}\n"
        f"• Active: {len(active_pairs)}\n"
        f"• Paused: {len(pairs) - len(active_pairs)}\n\n"
        f"**📨 Messages:**\n"
        f"• Copied: {total_copied:,}\n"
        f"• Filtered: {total_filtered:,}\n"
        f"• Pending: {total_pending:,}\n\n"
        f"**🔄 Sync Features:**\n"
        f"• Replies Preserved: {total_replies:,}\n"
        f"• Edits Synced: {total_edits:,}\n"
        f"• Deletes Synced: {total_deletes:,}\n\n"
        f"**🎯 Content Processing:**\n"
        f"• Mentions Removed: {total_mentions:,}\n"
        f"• Headers Removed: {total_headers:,}\n"
        f"• Footers Removed: {total_footers:,}\n\n"
        f"**🤖 System:**\n"
        f"• Bot Tokens: {len(BOT_TOKENS)}\n"
        f"• Processing Rate: {queue_stats.get('processing_rate', 0):.1f}/sec\n"
        f"• Success Rate: {queue_stats.get('success_rate', 0):.1f}%\n"
        f"• Status: {'🔴 Paused' if self.system_paused else '🟢 Active'}"
    )

    await update.message.reply_text(text, parse_mode='Markdown')

async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show complete help"""
    help_text = (
        "🤖 **Complete Telegram Message Copying Bot**\n\n"
        "**📋 Pair Management:**\n"
        "• `/create_pair <source> <dest> <name>` - Create pair\n"
        "• `/list_pairs` - List all pairs\n"
        "• `/pause_pair <id>` - Pause pair\n"
        "• `/resume_pair <id>` - Resume pair\n"
        "• `/delete_pair <id>` - Delete pair\n\n"
        "**🌐 Global Controls:**\n"
        "• `/pause_all` - Pause all pairs\n"
        "• `/resume_all` - Resume all pairs\n\n"
        "**🚫 Word Filtering:**\n"
        "• `/block_word <word> <scope>` - Block word\n"
        "• `/unblock_word <word> <scope>` - Unblock word\n"
        "• `/list_blocks [scope]` - List blocked words\n\n"
        "**🎯 Enhanced Filtering:**\n"
        "• `/set_mention_removal <scope> <on/off> [placeholder]` - Configure mentions\n"
        "• `/add_header_pattern <pair_id> <pattern>` - Add header pattern\n"
        "• `/add_footer_pattern <pair_id> <pattern>` - Add footer pattern\n"
        "• `/list_patterns <pair_id>` - List all patterns\n"
        "• `/remove_pattern <pair_id> <type> <index>` - Remove pattern\n\n"
    )

    if IMAGE_PROCESSING_AVAILABLE:
        help_text += (
            "**🖼️ Image Blocking:**\n"
            "• `/block_image <scope>` - Block image (reply to image)\n"
            "• `/list_blocked_images [scope]` - List blocked images\n"
            "• `/block_image_global [description]` - Block image globally (reply to image)\n"
            "• `/list_global_blocks` - List globally blocked images\n"
            "• `/remove_global_block <hash>` - Remove global block\n"
            "• `/check_image_status` - Check image blocking status (reply to image)\n\n"
        )

    help_text += (
        "**⚙️ Sync Settings:**\n"
        "• `/sync_settings <scope> <setting> <on/off>` - Configure sync\n\n"
        "**📊 Utilities:**\n"
        "• `/stats` - Enhanced statistics\n"
        "• `/queue_stats` - Smart queue statistics\n"
        "• `/queue_settings <setting> <value>` - Configure queue\n"
        "• `/get_chat_id` - Get chat ID\n"
        "• `/help` - This help\n\n"
        "**🚀 Smart Queue Features:**\n"
        "• Intelligent load balancing across multiple bots\n"
        "• Priority processing (URGENT → HIGH → NORMAL → LOW)\n"
        "• Adaptive rate limiting and auto-optimization\n"
        "• Real-time performance monitoring\n\n"
        "**💡 Notes:**\n"
        "• Use 'all' for global scope or pair ID for specific\n"
        "• Sync settings: sync_edits, sync_deletes, preserve_replies\n"
        "• Patterns support regex expressions\n"
        "• Smart queue automatically balances load across bots"
    )

    await update.message.reply_text(help_text, parse_mode='Markdown')

async def get_chat_id_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get chat ID"""
    if update.message.forward_from_chat:
        chat = update.message.forward_from_chat
        await update.message.reply_text(
            f"📋 **Chat Information**\n\n"
            f"**Name:** {chat.title}\n"
            f"**ID:** `{chat.id}`\n"
            f"**Type:** {chat.type}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "Forward a message from the target chat to get its ID"
        )

async def queue_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed queue statistics"""
    stats = self.queue_manager.get_queue_stats()

    text = f"📊 **Smart Queue Statistics**\n\n"
    text += f"**📈 Overall Performance:**\n"
    text += f"• Total Processed: {stats['total_processed']:,}\n"
    text += f"• Total Pending: {stats['total_pending']:,}\n"
    text += f"• Processing Rate: {stats['processing_rate']:.1f}/sec\n"
    text += f"• Success Rate: {stats['success_rate']:.1f}%\n"
    text += f"• Uptime: {stats['uptime_seconds']:.1f}s\n\n"
    text += f"**⚙️ Configuration:**\n"
    text += f"• Algorithm: {stats['load_balance_algorithm']}\n"
    text += f"• Adaptive: {'✅' if stats['adaptive_enabled'] else '❌'}\n\n"
    text += f"**🤖 Bot Performance:**\n"

    for bot_name, bot_stats in stats['bot_stats'].items():
        bot_num = bot_name.split('_')[1]
        status = "🚫" if bot_stats['rate_limited'] else "✅"
        text += f"{status} **Bot #{bot_num}:**\n"
        text += f"  Queue: {bot_stats['queue_size']}\n"
        text += f"  Success: {bot_stats['success_rate']:.1f}%\n"
        text += f"  Speed: {bot_stats['avg_processing_time']:.2f}s\n\n"

    await update.message.reply_text(text, parse_mode='Markdown')

async def queue_settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configure queue settings"""
    if len(context.args) < 2:
        await update.message.reply_text(
            "**Queue Settings**\n\n"
            "Usage: `/queue_settings <setting> <value>`\n\n"
            "**Available Settings:**\n"
            "• `algorithm` - round_robin, least_loaded, smart\n"
            "• `adaptive` - on, off\n\n"
            "**Examples:**\n"
            "• `/queue_settings algorithm smart`\n"
            "• `/queue_settings adaptive on`",
            parse_mode='Markdown'
        )
        return

    setting = context.args[0].lower()
    value = context.args[1].lower()

    try:
        if setting == 'algorithm':
            if value in ['round_robin', 'least_loaded', 'smart']:
                self.queue_manager.update_settings({'load_balance_algorithm': value})
                await update.message.reply_text(f"✅ Load balancing algorithm set to: **{value}**", parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Invalid algorithm. Use: round_robin, least_loaded, or smart")

        elif setting == 'adaptive':
            if value in ['on', 'off']:
                adaptive_enabled = value == 'on'
                self.queue_manager.update_settings({'adaptive_enabled': adaptive_enabled})
                await update.message.reply_text(f"✅ Adaptive queue management: **{value}**", parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Invalid value. Use: on or off")

        else:
            await update.message.reply_text("❌ Unknown setting")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def sync_settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configure sync settings for pairs"""
    if len(context.args) < 3:
        await update.message.reply_text(
            "⚙️ **Sync Settings Configuration**\n\n"
            "Usage: `/sync_settings <scope> <setting> <action>`\n\n"
            "**Available Settings:**\n"
            "• `sync_edits` - Synchronize message edits\n"
            "• `sync_deletes` - Synchronize message deletions\n"
            "• `preserve_replies` - Maintain reply chains\n\n"
            "**Examples:**\n"
            "• `/sync_settings 1 sync_edits on`\n"
            "• `/sync_settings all sync_deletes off`\n"
            "• `/sync_settings 2 preserve_replies on`",
            parse_mode='Markdown'
        )
        return

    scope = context.args[0]
    setting = context.args[1]
    action = context.args[2].lower()

    if action not in ['on', 'off']:
        await update.message.reply_text("❌ Action must be 'on' or 'off'")
        return

    enable = action == 'on'

    try:
        if scope == "all":
            pairs = self.db.get_all_pairs()
            updated_count = 0
            for pair in pairs:
                pair.filters[setting] = enable
                self.db.update_pair(pair)
                updated_count += 1

            await update.message.reply_text(
                f"✅ **Global Sync Setting Updated**\n\n"
                f"⚙️ **Setting:** {setting}\n"
                f"🔄 **Status:** {'Enabled' if enable else 'Disabled'}\n"
                f"📊 **Affected Pairs:** {updated_count}",
                parse_mode='Markdown'
            )

        else:
            pair_id = int(scope)
            pair = self.db.get_pair(pair_id)
            if not pair:
                await update.message.reply_text(f"❌ Pair #{pair_id} not found")
                return

            pair.filters[setting] = enable
            self.db.update_pair(pair)

            await update.message.reply_text(
                f"✅ **Sync Setting Updated**\n\n"
                f"🎯 **Pair:** #{pair_id} - {pair.name}\n"
                f"⚙️ **Setting:** {setting}\n"
                f"🔄 **Status:** {'Enabled' if enable else 'Disabled'}",
                parse_mode='Markdown'
            )

    except ValueError:
        await update.message.reply_text("❌ Invalid pair ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# CORE FUNCTIONALITY
async def start_pair_monitoring(self, pair_id: int):
    """Start monitoring pair with complete functionality"""
    pair = self.db.get_pair(pair_id)
    if not pair or pair.status != "active":
        return

    if pair_id in self.active_pairs:
        return

    async def message_handler(event):
        if self.system_paused:
            return

        try:
            await self.process_message_complete(event, pair)
        except Exception as e:
            logger.error(f"Message processing error: {e}")

    handler = self.userbot.add_event_handler(
        message_handler,
        events.NewMessage(chats=[pair.source_chat_id])
    )

    self.active_pairs[pair_id] = handler
    logger.info(f"Started complete monitoring for pair #{pair_id}")

async def process_message_complete(self, event, pair: MessagePair):
    """Complete message processing with all features"""
    try:
        message = event.message
        original_text = message.text or ""
        
        logger.info(f"Processing message from {pair.source_chat_id} to {pair.destination_chat_id} (pair {pair.id})")

        # Initialize message_data with all required fields
        message_data = {
            'text': original_text,
            'has_media': bool(message.media),
            'entities': [],
            'pair_id': pair.id,
            'source_message_id': message.id,
            'destination_chat_id': pair.destination_chat_id,
            'source_chat_id': pair.source_chat_id,
            'is_reply': bool(message.reply_to),
            'reply_to_msg_id': message.reply_to.reply_to_msg_id if message.reply_to else None,
            'bot_index': pair.assigned_bot_index,
            'message_type': self.determine_message_type(message),
            'has_web_preview': self.has_web_preview(message),
            'is_premium_emoji': self.has_premium_emoji_or_sticker(message)
        }

        # Check if message should be filtered
        should_filter, reason = self.filter_manager.should_filter_message(original_text, pair)
        if should_filter:
            logger.info(f"Message filtered: {reason}")
            pair.stats['messages_filtered'] = pair.stats.get('messages_filtered', 0) + 1
            self.db.update_pair(pair)
            return

        # Check for global image blocking first
        if message.media and IMAGE_PROCESSING_AVAILABLE:
            is_blocked, reason, block_info = await self.check_global_image_blocking(message)
            if is_blocked:
                logger.debug(f"Image globally blocked: {reason}")
                pair.stats['messages_filtered'] = pair.stats.get('messages_filtered', 0) + 1
                if block_info.get('phash'):
                    self.filter_manager.image_blocker.update_usage_count(block_info['phash'])
                self.db.update_pair(pair)
                return

            # Check pair-specific image blocking
            is_blocked, reason = await self.check_image_blocking(message, pair.id)
            if is_blocked:
                logger.debug(f"Image blocked for pair {pair.id}: {reason}")
                pair.stats['messages_filtered'] = pair.stats.get('messages_filtered', 0) + 1
                self.db.update_pair(pair)
                return

        # Process text with formatting preservation
        if message.entities:
            entities = self.extract_telethon_entities_directly(message)
            processed_text, processing_stats, updated_entities = self.filter_manager.process_message_text_preserve_format(
                original_text, pair, entities
            )
            message_data['entities'] = updated_entities
        else:
            processed_text, processing_stats, preserved_entities = self.filter_manager.process_message_text(
                original_text, pair
            )
            message_data['entities'] = preserved_entities

        # Update text in message_data
        message_data['text'] = processed_text

        # Update processing statistics
        pair.stats['mentions_removed'] = pair.stats.get('mentions_removed', 0) + processing_stats.get('mentions_removed', 0)
        pair.stats['headers_removed'] = pair.stats.get('headers_removed', 0) + processing_stats.get('headers_removed', 0)
        pair.stats['footers_removed'] = pair.stats.get('footers_removed', 0) + processing_stats.get('footers_removed', 0)

        # Handle reply mapping
        if message.reply_to:
            reply_to_dest_id = self.message_mapper.get_reply_destination_id(
                message.reply_to.reply_to_msg_id, pair.id
            )
            if reply_to_dest_id:
                message_data['reply_to_message_id'] = reply_to_dest_id
                message_data['reply_to_source_id'] = message.reply_to.reply_to_msg_id

        # Handle media download and processing
        temp_path = None
        if message.media and not self.is_web_preview_media_only(message):
            try:
                file_extension = self.get_media_extension(message)
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension, dir=self.temp_dir) as temp_file:
                    temp_path = temp_file.name

                async with self.download_semaphore:
                    download_task = asyncio.create_task(message.download_media(temp_path))
                    try:
                        await asyncio.wait_for(download_task, timeout=30.0)

                        # Check for duplicate image by hash
                        if IMAGE_PROCESSING_AVAILABLE and message.photo:
                            try:
                                phash = self.filter_manager.image_blocker.calculator.calculate_phash(temp_path)
                                if phash and phash in self.media_cache:
                                    logger.info(f"Duplicate image detected, skipping for pair {pair.id}")
                                    os.unlink(temp_path)
                                    return
                                if phash:
                                    self.media_cache[phash] = time.time()
                            except Exception as hash_e:
                                logger.error(f"Hash calculation error: {hash_e}")

                        message_data['media'] = temp_path
                        message_data['original_filename'] = self.get_original_filename(message, file_extension)

                    except asyncio.TimeoutError:
                        logger.warning(f"Media download timeout for message {message.id}")
                        if temp_path and os.path.exists(temp_path):
                            os.unlink(temp_path)

            except Exception as download_e:
                logger.error(f"Error during media download for message {message.id}: {download_e}")
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except:
                        pass

        # Queue message for processing using smart queue
        if await self.queue_manager.enqueue_message(message_data, pair.assigned_bot_index):
            logger.debug(f"Smart-queued message for pair {pair.id}")
        else:
            logger.warning(f"Failed to queue message for pair {pair.id}")
            # Cleanup media file on queue failure
            if message_data.get('media') and os.path.exists(message_data['media']):
                try:
                    os.unlink(message_data['media'])
                except:
                    pass

    except Exception as e:
        logger.error(f"Message processing error: {str(e)}", exc_info=True)

def is_web_preview_media_only(self, message) -> bool:
    """Check if media is only from web preview and shouldn't be downloaded separately"""
    try:
        if message.media and hasattr(message.media, '__class__'):
            media_type = message.media.__class__.__name__
            if media_type == 'MessageMediaWebPage':
                return True
        return False
    except:
        return False

def get_original_filename(self, message, file_extension: str) -> str:
    """Get original filename from message attributes"""
    try:
        if hasattr(message.media, 'document') and message.media.document:
            document = message.media.document
            if hasattr(document, 'attributes'):
                for attr in document.attributes:
                    if hasattr(attr, 'file_name') and attr.file_name:
                        return attr.file_name
        return f'media{file_extension}'
    except:
        return f'media{file_extension}'

def determine_message_type(self, message) -> str:
    """Determine message type for mapping"""
    if message.photo:
        return 'photo'
    elif message.video:
        return 'video'
    elif message.document:
        return 'document'
    elif message.voice:
        return 'voice'
    elif message.video_note:
        return 'video_note'
    elif message.poll:
        return 'poll'
    elif message.audio:
        return 'audio'
    elif message.sticker:
        return 'sticker'
    else:
        return 'text'

def extract_telethon_entities_directly(self, message) -> List[Dict]:
    """Extract Telethon message entities and convert to Bot API format"""
    entities = []
    if hasattr(message, 'entities') and message.entities:
        for entity in message.entities:
            entity_dict = {
                'offset': entity.offset,
                'length': entity.length,
                'type': self.convert_entity_type(entity.__class__.__name__)
            }

            # Add additional data for specific entity types
            if hasattr(entity, 'url'):
                entity_dict['url'] = entity.url
            elif hasattr(entity, 'user_id'):
                entity_dict['user'] = {'id': entity.user_id}
            elif hasattr(entity, 'language'):
                entity_dict['language'] = entity.language

            entities.append(entity_dict)

    return entities

def convert_entity_type(self, telethon_type: str) -> str:
    """Convert Telethon entity type to Bot API entity type"""
    type_mapping = {
        'MessageEntityBold': 'bold',
        'MessageEntityItalic': 'italic',
        'MessageEntityUnderline': 'underline',
        'MessageEntityStrike': 'strikethrough',
        'MessageEntityCode': 'code',
        'MessageEntityPre': 'pre',
        'MessageEntityTextUrl': 'text_link',
        'MessageEntityUrl': 'url',
        'MessageEntityEmail': 'email',
        'MessageEntityPhone': 'phone_number',
        'MessageEntityMention': 'mention',
        'MessageEntityMentionName': 'text_mention',
        'MessageEntityHashtag': 'hashtag',
        'MessageEntityCashtag': 'cashtag',
        'MessageEntityBotCommand': 'bot_command',
        'MessageEntitySpoiler': 'spoiler',
        'MessageEntityCustomEmoji': 'custom_emoji'
    }
    return type_mapping.get(telethon_type, 'unknown')

def has_premium_emoji_or_sticker(self, message) -> bool:
    """Detect if message contains premium emoji or stickers"""
    try:
        # Check for custom emoji entities
        if hasattr(message, 'entities') and message.entities:
            for entity in message.entities:
                if entity.__class__.__name__ == 'MessageEntityCustomEmoji':
                    return True

        # Check for premium stickers
        if message.sticker and hasattr(message.sticker, 'premium'):
            return message.sticker.premium

        # Check for animated emoji
        if message.media and hasattr(message.media, 'document'):
            document = message.media.document
            if hasattr(document, 'attributes'):
                for attr in document.attributes:
                    if attr.__class__.__name__ == 'DocumentAttributeCustomEmoji':
                        return True
                    elif attr.__class__.__name__ == 'DocumentAttributeSticker':
                        if hasattr(attr, 'premium') and attr.premium:
                            return True

        return False
    except Exception as e:
        logger.warning(f"Error detecting premium emoji: {e}")
        return False

def has_web_preview(self, message) -> bool:
    """Detect if message has web preview"""
    try:
        if message.media and hasattr(message.media, '__class__'):
            media_type = message.media.__class__.__name__
            if media_type == 'MessageMediaWebPage':
                return True

        if message.text:
            import re
            # Common domains that generate previews
            preview_domains = [
                r'https?://(?:www\.)?tradingview\.com',
                r'https?://(?:www\.)?youtube\.com',
                r'https?://(?:www\.)?youtu\.be',
                r'https?://(?:www\.)?twitter\.com',
                r'https?://(?:www\.)?x\.com',
                r'https?://(?:www\.)?github\.com',
                r'https?://(?:www\.)?instagram\.com',
                r'https?://(?:www\.)?facebook\.com',
                r'https?://(?:www\.)?linkedin\.com'
            ]

            for pattern in preview_domains:
                if re.search(pattern, message.text, re.IGNORECASE):
                    return True

            # General URL check
            url_pattern = r'https?://[^\s]+\.[a-z]{2,}'
            if re.search(url_pattern, message.text, re.IGNORECASE):
                return True

        return False
    except Exception as e:
        logger.warning(f"Error detecting web preview: {e}")
        return False

def get_media_extension(self, message) -> str:
    """Get appropriate file extension for media"""
    if message.photo:
        return '.jpg'
    elif message.video:
        return '.mp4'
    elif message.voice:
        return '.ogg'
    elif message.video_note:
        return '.mp4'
    elif message.audio:
        return '.mp3'
    elif message.sticker:
        return '.webp'
    elif message.document and hasattr(message.media, 'document'):
        document = message.media.document
        if hasattr(document, 'attributes'):
            for attr in document.attributes:
                if hasattr(attr, 'file_name') and attr.file_name:
                    name = attr.file_name.lower()
                    if '.' in name:
                        return '.' + name.split('.')[-1]

        # Fallback based on mime type
        if hasattr(document, 'mime_type'):
            mime_type = document.mime_type.lower()
            mime_extensions = {
                'image/jpeg': '.jpg',
                'image/png': '.png',
                'image/gif': '.gif',
                'image/webp': '.webp',
                'video/mp4': '.mp4',
                'video/avi': '.avi',
                'video/mov': '.mov',
                'video/mkv': '.mkv',
                'audio/mpeg': '.mp3',
                'audio/wav': '.wav',
                'audio/ogg': '.ogg',
                'audio/m4a': '.m4a',
                'application/pdf': '.pdf',
                'text/plain': '.txt',
                'application/zip': '.zip',
                'application/rar': '.rar'
            }
            return mime_extensions.get(mime_type, '.bin')

        return '.bin'
    else:
        return '.tmp'

async def check_image_blocking(self, message, pair_id: int) -> Tuple[bool, str]:
    """Check if image is blocked"""
    if not IMAGE_PROCESSING_AVAILABLE:
        return False, ""

    try:
        file_extension = self.get_media_extension(message)
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            await message.download_media(temp_file.name)
            is_blocked, reason = self.filter_manager.image_blocker.is_image_blocked(temp_file.name, pair_id)
            os.unlink(temp_file.name)
            return is_blocked, reason
    except Exception as e:
        logger.error(f"Image blocking check error: {e}")
        return False, ""

async def check_global_image_blocking(self, message) -> Tuple[bool, str, Dict]:
    """Check if image is blocked globally"""
    if not IMAGE_PROCESSING_AVAILABLE:
        return False, "", {}

    try:
        file_extension = self.get_media_extension(message)
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            await message.download_media(temp_file.name)
            is_blocked, reason, block_info = self.filter_manager.image_blocker.is_image_blocked_globally(temp_file.name)
            os.unlink(temp_file.name)
            return is_blocked, reason, block_info
    except Exception as e:
        logger.error(f"Global image blocking check error: {e}")
        return False, "", {}

async def start_enhanced_workers(self):
    """Start enhanced workers with smart queue integration"""
    for i in range(len(BOT_TOKENS)):
        bot = self.load_balancer.get_bot_by_index(i)
        worker = EnhancedMessageWorker(i, bot, self.queue_manager, self)
        self.enhanced_workers.append(worker)
        # Start worker task
        asyncio.create_task(worker.start())

    # Start queue manager background tasks
    self.queue_manager.start_background_tasks()
    logger.info(f"Started {len(self.enhanced_workers)} enhanced workers")

async def start_workers(self):
    """Legacy method - redirects to enhanced workers"""
    await self.start_enhanced_workers()

async def send_message_complete(self, message_data: dict, bot: Bot) -> bool:
    """Complete message sending with mapping storage and enhanced formatting support"""
    start_time = time.time()
    try:
        chat_id = message_data['destination_chat_id']
        text = message_data.get('text', '')
        media_path = message_data.get('media')
        reply_to = message_data.get('reply_to_message_id')
        entities = message_data.get('entities', [])
        
        sent_message = None

        # Update pair stats for attempted copy
        pair = self.db.get_pair(message_data['pair_id'])
        if pair:
            pair.stats['messages_copied'] = pair.stats.get('messages_copied', 0) + 1
            self.db.update_pair(pair)

        # Handle media messages
        if media_path and os.path.exists(media_path):
            async with self.upload_semaphore:
                original_filename = message_data.get('original_filename', os.path.basename(media_path))
                caption = text[:1024] if text else None
                caption_entities = self.filter_entities_for_caption(entities, caption)

                with open(media_path, 'rb') as media_file:
                    file_ext = media_path.lower()
                    
                    if any(ext in file_ext for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                        sent_message = await bot.send_photo(
                            chat_id=chat_id,
                            photo=media_file,
                            caption=caption,
                            caption_entities=caption_entities,
                            reply_to_message_id=reply_to
                        )
                    elif any(ext in file_ext for ext in ['.mp4', '.avi', '.mov', '.mkv']):
                        sent_message = await bot.send_video(
                            chat_id=chat_id,
                            video=media_file,
                            caption=caption,
                            caption_entities=caption_entities,
                            reply_to_message_id=reply_to
                        )
                    elif any(ext in file_ext for ext in ['.mp3', '.wav', '.m4a']):
                        sent_message = await bot.send_audio(
                            chat_id=chat_id,
                            audio=media_file,
                            caption=caption,
                            caption_entities=caption_entities,
                            reply_to_message_id=reply_to
                        )
                    elif file_ext.endswith('.ogg'):
                        sent_message = await bot.send_voice(
                            chat_id=chat_id,
                            voice=media_file,
                            caption=caption,
                            caption_entities=caption_entities,
                            reply_to_message_id=reply_to
                        )
                    else:
                        from telegram import InputFile
                        document_file = InputFile(media_file, filename=original_filename)
                        sent_message = await bot.send_document(
                            chat_id=chat_id,
                            document=document_file,
                            caption=caption,
                            caption_entities=caption_entities,
                            reply_to_message_id=reply_to
                        )

                # Cleanup media file
                try:
                    os.unlink(media_path)
                except:
                    pass

        elif text:
            # Handle text messages
            if len(text) > 4096:
                chunks = [text[i:i+4096] for i in range(0, len(text), 4096)]
                for i, chunk_text in enumerate(chunks):
                    sent_message = await bot.send_message(
                        chat_id=chat_id,
                        text=chunk_text,
                        disable_web_page_preview=False,
                        reply_to_message_id=reply_to if i == 0 else None
                    )
            else:
                sent_message = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    disable_web_page_preview=False,
                    reply_to_message_id=reply_to
                )

        # Store complete message mapping
        if sent_message:
            self.message_mapper.store_message_mapping(
                source_msg_id=message_data['source_message_id'],
                dest_msg_id=sent_message.message_id,
                pair_id=message_data['pair_id'],
                bot_index=message_data['bot_index'],
                source_chat_id=message_data['source_chat_id'],
                dest_chat_id=chat_id,
                message_type=message_data.get('message_type', 'text'),
                has_media=message_data.get('has_media', False),
                is_reply=message_data.get('is_reply', False),
                reply_to_source_id=message_data.get('reply_to_source_id'),
                reply_to_dest_id=reply_to
            )

            processing_time = time.time() - start_time
            logger.debug(f"Message sent and mapped in {processing_time:.3f}s: {message_data['source_message_id']} -> {sent_message.message_id}")
            return True

    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"Send error after {processing_time:.3f}s: {e}")
        
        # Cleanup media file on error
        if message_data.get('media') and os.path.exists(message_data['media']):
            try:
                os.unlink(message_data['media'])
            except:
                pass
        return False

    return False

def filter_entities_for_caption(self, entities: List[Dict], caption: str) -> List[Dict]:
    """Filter entities that fit within caption length and limit"""
    if not entities or not caption:
        return []

    caption_length = len(caption)
    filtered_entities = []

    for entity in entities:
        offset = entity.get('offset', 0)
        length = entity.get('length', 0)

        # Check if entity is within caption bounds
        if offset + length <= caption_length:
            filtered_entities.append(entity)

        # Telegram limits caption entities to 100
        if len(filtered_entities) >= 100:
            break

    return filtered_entities

async def start_bot(self):
    """Start the complete bot system"""
    try:
        # Connect userbot
        await self.userbot.start(phone_number=PHONE_NUMBER)
        logger.info("Userbot connected successfully")

        # Start enhanced workers
        await self.start_enhanced_workers()

        # Resume active pairs
        pairs = self.db.get_all_pairs()
        for pair in pairs:
            if pair.status == "active":
                await self.start_pair_monitoring(pair.id)

        # Start telegram bot application
        logger.info("Starting Telegram bot application...")
        await self.app.initialize()
        await self.app.start()
        
        logger.info(f"🚀 Complete bot system started with {len(pairs)} pairs!")
        
        # Keep running
        await self.app.updater.start_polling()

    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise

async def stop_bot(self):
    """Stop the bot gracefully"""
    try:
        # Stop queue manager
        await self.queue_manager.stop()
        
        # Stop workers
        for worker in self.enhanced_workers:
            worker.stop()

        # Stop telegram app
        await self.app.stop()
        await self.app.shutdown()

        # Disconnect userbot
        await self.userbot.disconnect()

        logger.info("Bot stopped gracefully")

    except Exception as e:
        logger.error(f"Error stopping bot: {e}")

# MAIN EXECUTION
async def main():
    """Main execution function"""
    bot = TelegramCopyBot()
    
    try:
        await bot.start_bot()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.error(f"Critical error: {e}")
    finally:
        await bot.stop_bot()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutdown completed")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
