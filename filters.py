"""
Message filtering system with advanced pattern matching
"""

import re
import json
import logging
import asyncio
from typing import Dict, List, Optional, Any, NamedTuple
from dataclasses import dataclass
from datetime import datetime, timedelta

from database import DatabaseManager, MessagePair
from config import Config

logger = logging.getLogger(__name__)

class FilterResult(NamedTuple):
    """Result of message filtering"""
    should_copy: bool
    reason: str
    filters_applied: List[str]

@dataclass
class FilterStats:
    """Filter application statistics"""
    blocked_words_hits: int = 0
    regex_hits: int = 0
    length_filtered: int = 0
    media_filtered: int = 0
    link_filtered: int = 0
    forward_filtered: int = 0

class MessageFilter:
    """Advanced message filtering system"""
    
    def __init__(self, db_manager: DatabaseManager, config: Config):
        self.db_manager = db_manager
        self.config = config
        self.global_blocks = {"words": [], "patterns": []}
        self.filter_stats = FilterStats()
        
        # Compiled regex cache
        self._regex_cache: Dict[str, re.Pattern] = {}
    
    async def initialize(self):
        """Initialize filter system"""
        await self._load_global_blocks()
    
    async def _load_global_blocks(self):
        """Load global blocking rules"""
        try:
            global_blocks_str = await self.db_manager.get_setting("global_blocks", '{"words": [], "patterns": []}')
            self.global_blocks = json.loads(global_blocks_str)
        except Exception as e:
            logger.error(f"Failed to load global blocks: {e}")
    
    async def should_copy_message(self, event, pair: MessagePair) -> FilterResult:
        """Determine if message should be copied based on filters"""
        filters_applied = []
        
        try:
            text = event.text or event.raw_text or ""
            
            # Check global word blocks first
            if await self._check_global_word_blocks(text):
                self.filter_stats.blocked_words_hits += 1
                return FilterResult(False, "Global word block", ["global_words"])
            
            # Check pair-specific blocked words
            blocked_words = pair.filters.get("blocked_words", [])
            if blocked_words and self._contains_blocked_words(text, blocked_words):
                filters_applied.append("blocked_words")
                self.filter_stats.blocked_words_hits += 1
                return FilterResult(False, "Contains blocked words", filters_applied)
            
            # Check custom regex filters
            regex_filters = pair.filters.get("custom_regex_filters", [])
            if regex_filters:
                for regex_pattern in regex_filters:
                    if self._matches_regex(text, regex_pattern):
                        filters_applied.append("regex")
                        self.filter_stats.regex_hits += 1
                        return FilterResult(False, f"Matches regex: {regex_pattern}", filters_applied)
            
            # Check message length limits
            min_length = pair.filters.get("min_message_length", 0)
            max_length = pair.filters.get("max_message_length", 0)
            
            if min_length > 0 and len(text) < min_length:
                filters_applied.append("min_length")
                self.filter_stats.length_filtered += 1
                return FilterResult(False, f"Message too short: {len(text)} < {min_length}", filters_applied)
            
            if max_length > 0 and len(text) > max_length:
                filters_applied.append("max_length")
                self.filter_stats.length_filtered += 1
                return FilterResult(False, f"Message too long: {len(text)} > {max_length}", filters_applied)
            
            # Check if forwards are blocked
            if pair.filters.get("block_forwards", False) and getattr(event, 'fwd_from', None):
                filters_applied.append("block_forwards")
                self.filter_stats.forward_filtered += 1
                return FilterResult(False, "Forwarded message blocked", filters_applied)
            
            # Check if links are blocked
            if pair.filters.get("block_links", False) and self._contains_links(text):
                filters_applied.append("block_links")
                self.filter_stats.link_filtered += 1
                return FilterResult(False, "Contains blocked links", filters_applied)
            
            # Check media type restrictions
            if event.media:
                allowed_media = pair.filters.get("allowed_media_types", [
                    "photo", "video", "document", "audio", "voice"
                ])
                media_type = self._get_media_type(event.media)
                
                if media_type not in allowed_media:
                    filters_applied.append("media_type")
                    self.filter_stats.media_filtered += 1
                    return FilterResult(False, f"Media type not allowed: {media_type}", filters_applied)
            
            # Check time-based filters
            if not await self._check_time_filters(event, pair):
                filters_applied.append("time_filter")
                return FilterResult(False, "Time-based filter", filters_applied)
            
            # Check user-based filters
            if not await self._check_user_filters(event, pair):
                filters_applied.append("user_filter")
                return FilterResult(False, "User-based filter", filters_applied)
            
            # All filters passed
            return FilterResult(True, "Passed all filters", filters_applied)
            
        except Exception as e:
            logger.error(f"Error in message filtering: {e}")
            return FilterResult(False, f"Filter error: {e}", ["error"])
    
    async def filter_text(self, text: str, pair: MessagePair) -> str:
        """Apply text transformations and filtering"""
        try:
            filtered_text = text
            
            # Apply word replacements
            word_replacements = pair.filters.get("word_replacements", {})
            for old_word, new_word in word_replacements.items():
                filtered_text = re.sub(
                    re.escape(old_word), 
                    new_word, 
                    filtered_text, 
                    flags=re.IGNORECASE
                )
            
            # Apply regex replacements
            regex_replacements = pair.filters.get("regex_replacements", {})
            for pattern, replacement in regex_replacements.items():
                try:
                    compiled_regex = self._get_compiled_regex(pattern)
                    filtered_text = compiled_regex.sub(replacement, filtered_text)
                except re.error as e:
                    logger.warning(f"Invalid regex pattern {pattern}: {e}")
            
            # Remove extra whitespace
            filtered_text = re.sub(r'\s+', ' ', filtered_text).strip()
            
            return filtered_text
            
        except Exception as e:
            logger.error(f"Error filtering text: {e}")
            return text
    
    async def _check_global_word_blocks(self, text: str) -> bool:
        """Check against global blocked words"""
        try:
            global_words = self.global_blocks.get("words", [])
            if not global_words:
                return False
            
            text_lower = text.lower()
            for word in global_words:
                if word.lower() in text_lower:
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking global word blocks: {e}")
            return False
    
    def _contains_blocked_words(self, text: str, blocked_words: List[str]) -> bool:
        """Check if text contains any blocked words"""
        if not blocked_words:
            return False
        
        text_lower = text.lower()
        for word in blocked_words:
            if word.lower() in text_lower:
                return True
        
        return False
    
    def _matches_regex(self, text: str, pattern: str) -> bool:
        """Check if text matches regex pattern"""
        try:
            compiled_regex = self._get_compiled_regex(pattern)
            return bool(compiled_regex.search(text))
        except re.error as e:
            logger.warning(f"Invalid regex pattern {pattern}: {e}")
            return False
    
    def _get_compiled_regex(self, pattern: str) -> re.Pattern:
        """Get compiled regex from cache or compile new one"""
        if pattern not in self._regex_cache:
            self._regex_cache[pattern] = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        return self._regex_cache[pattern]
    
    def _contains_links(self, text: str) -> bool:
        """Check if text contains links"""
        link_patterns = [
            r'http[s]?://\S+',
            r'www\.\S+',
            r't\.me/\S+',
            r'@\w+',
            r'\w+\.\w{2,}',
        ]
        
        for pattern in link_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        
        return False
    
    def _get_media_type(self, media) -> str:
        """Get media type from media object"""
        from telethon.tl.types import (
            MessageMediaPhoto, MessageMediaDocument
        )
        
        if isinstance(media, MessageMediaPhoto):
            return "photo"
        elif isinstance(media, MessageMediaDocument):
            if hasattr(media.document, 'mime_type') and media.document.mime_type:
                mime_type = media.document.mime_type
                if mime_type.startswith('image/'):
                    return "photo"
                elif mime_type.startswith('video/'):
                    return "video"
                elif mime_type.startswith('audio/'):
                    return "audio"
                elif 'voice' in mime_type.lower():
                    return "voice"
                elif 'video_note' in mime_type.lower():
                    return "video_note"
            return "document"
        
        return "unknown"
    
    async def _check_time_filters(self, event, pair: MessagePair) -> bool:
        """Check time-based filtering rules"""
        try:
            time_filters = pair.filters.get("time_filters", {})
            if not time_filters:
                return True
            
            now = datetime.now()
            message_time = datetime.fromtimestamp(event.date.timestamp())
            
            # Check allowed hours
            allowed_hours = time_filters.get("allowed_hours", [])
            if allowed_hours and now.hour not in allowed_hours:
                return False
            
            # Check allowed days of week (0=Monday, 6=Sunday)
            allowed_days = time_filters.get("allowed_days", [])
            if allowed_days and now.weekday() not in allowed_days:
                return False
            
            # Check message age limit
            max_age_minutes = time_filters.get("max_age_minutes", 0)
            if max_age_minutes > 0:
                age_minutes = (now - message_time).total_seconds() / 60
                if age_minutes > max_age_minutes:
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error in time filtering: {e}")
            return True
    
    async def _check_user_filters(self, event, pair: MessagePair) -> bool:
        """Check user-based filtering rules"""
        try:
            user_filters = pair.filters.get("user_filters", {})
            if not user_filters:
                return True
            
            # Get sender information
            sender = await event.get_sender()
            if not sender:
                return True
            
            sender_id = sender.id
            sender_username = getattr(sender, 'username', '')
            
            # Check blocked users
            blocked_users = user_filters.get("blocked_user_ids", [])
            if sender_id in blocked_users:
                return False
            
            # Check blocked usernames
            blocked_usernames = user_filters.get("blocked_usernames", [])
            if sender_username and sender_username in blocked_usernames:
                return False
            
            # Check allowed users (whitelist)
            allowed_users = user_filters.get("allowed_user_ids", [])
            if allowed_users and sender_id not in allowed_users:
                return False
            
            # Check if user is bot
            if user_filters.get("block_bots", False) and getattr(sender, 'bot', False):
                return False
            
            # Check user verification status
            if user_filters.get("require_verified", False) and not getattr(sender, 'verified', False):
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error in user filtering: {e}")
            return True
    
    async def add_global_word_block(self, word: str):
        """Add word to global block list"""
        try:
            if word not in self.global_blocks["words"]:
                self.global_blocks["words"].append(word)
                await self.db_manager.set_setting(
                    "global_blocks", 
                    json.dumps(self.global_blocks)
                )
                logger.info(f"Added global word block: {word}")
        except Exception as e:
            logger.error(f"Failed to add global word block: {e}")
    
    async def remove_global_word_block(self, word: str):
        """Remove word from global block list"""
        try:
            if word in self.global_blocks["words"]:
                self.global_blocks["words"].remove(word)
                await self.db_manager.set_setting(
                    "global_blocks", 
                    json.dumps(self.global_blocks)
                )
                logger.info(f"Removed global word block: {word}")
        except Exception as e:
            logger.error(f"Failed to remove global word block: {e}")
    
    def get_filter_stats(self) -> Dict[str, int]:
        """Get filtering statistics"""
        return {
            "blocked_words_hits": self.filter_stats.blocked_words_hits,
            "regex_hits": self.filter_stats.regex_hits,
            "length_filtered": self.filter_stats.length_filtered,
            "media_filtered": self.filter_stats.media_filtered,
            "link_filtered": self.filter_stats.link_filtered,
            "forward_filtered": self.filter_stats.forward_filtered,
        }
    
    def clear_regex_cache(self):
        """Clear compiled regex cache"""
        self._regex_cache.clear()
        logger.info("Regex cache cleared")
