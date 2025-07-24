"""
Message filtering system with advanced pattern matching
"""

import re
import json
import logging
import asyncio
from typing import Dict, List, Optional, Any, NamedTuple, Union
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
            if global_blocks_str:
                self.global_blocks = json.loads(global_blocks_str)
            else:
                self.global_blocks = {"words": [], "patterns": []}
        except Exception as e:
            logger.error(f"Failed to load global blocks: {e}")
            self.global_blocks = {"words": [], "patterns": []}
    
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
            
            # Check if links are blocked (BUT allow URLs for webpage preview functionality)
            # NOTE: This should typically be False to allow URL forwarding with previews
            if pair.filters.get("block_links", False) and self._contains_links(text):
                filters_applied.append("block_links")
                self.filter_stats.link_filtered += 1
                logger.warning(f"URL message blocked by block_links filter: {text[:100]}... (Consider disabling block_links for URL forwarding)")
                return FilterResult(False, "Contains blocked links", filters_applied)
            
            # Check media type restrictions
            if event.media:
                allowed_media = pair.filters.get("allowed_media_types", [
                    "photo", "video", "document", "audio", "voice", "animation", "video_note", "sticker", "webpage", "unknown"
                ])
                media_type = self._get_media_type(event.media)
                
                # Special handling for URL messages with webpage media - these should always be allowed for URL forwarding
                if media_type == "webpage" or media_type == "unknown":
                    logger.info(f"Allowing webpage/unknown media type for URL forwarding: {media_type}")
                elif media_type not in allowed_media:
                    filters_applied.append("media_type")
                    self.filter_stats.media_filtered += 1
                    return FilterResult(False, f"Media type not allowed: {media_type}", filters_applied)
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
    
    async def filter_text(self, text: str, pair: MessagePair, entities: Optional[List] = None) -> tuple[str, List]:
        """Apply text transformations and filtering with entity preservation"""
        try:
            filtered_text = text
            processed_entities = entities.copy() if entities else []
            
            # Remove header/footer based on regex patterns (per-pair)
            header_patterns = pair.filters.get("header_regex", [])
            if header_patterns:
                if isinstance(header_patterns, str):
                    header_patterns = [header_patterns]
                filtered_text = self._remove_headers(filtered_text, header_patterns)
            
            footer_patterns = pair.filters.get("footer_regex", [])
            if footer_patterns:
                if isinstance(footer_patterns, str):
                    footer_patterns = [footer_patterns]  
                filtered_text = self._remove_footers(filtered_text, footer_patterns)
            
            # Process mentions with optional placeholders
            if pair.filters.get("remove_mentions", False):
                placeholder = pair.filters.get("mention_placeholder", "[User]")
                filtered_text = self._remove_mentions(filtered_text, placeholder)
                # Filter entities that may be out of bounds after mention removal
                if len(filtered_text) != len(text):
                    processed_entities = [
                        e for e in processed_entities 
                        if hasattr(e, 'offset') and hasattr(e, 'length') and 
                        e.offset + e.length <= len(filtered_text)
                    ]
            
            # Apply word replacements
            word_replacements = pair.filters.get("word_replacements", {})
            for old_word, new_word in word_replacements.items():
                filtered_text, processed_entities = self._replace_text_with_entities(
                    filtered_text, processed_entities, old_word, new_word
                )
            
            # Apply regex replacements
            regex_replacements = pair.filters.get("regex_replacements", {})
            for pattern, replacement in regex_replacements.items():
                try:
                    compiled_regex = self._get_compiled_regex(pattern)
                    filtered_text, processed_entities = self._regex_replace_with_entities(
                        filtered_text, processed_entities, compiled_regex, replacement
                    )
                except re.error as e:
                    logger.warning(f"Invalid regex pattern {pattern}: {e}")
            
            # Clean up excessive spaces while preserving newlines
            filtered_text = self._clean_excessive_spaces(filtered_text)
            
            return filtered_text, processed_entities
            
        except Exception as e:
            logger.error(f"Error filtering text: {e}")
            return text, entities or []
    
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
            if hasattr(media, 'document') and media.document and hasattr(media.document, 'mime_type'):
                mime_type = getattr(media.document, 'mime_type', '')
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
    
    def _process_mentions(self, text: str, entities: List, pair: MessagePair) -> tuple[str, List]:
        """Process mentions with optional placeholders"""
        try:
            mention_placeholder = pair.filters.get("mention_placeholder", "")
            filtered_text = text
            processed_entities = []
            offset_adjustment = 0
            
            for entity in entities or []:
                entity_type = getattr(entity, '__class__', {}).get('__name__', str(type(entity)))
                
                # Check if this is a mention entity
                if any(mention_type in entity_type.lower() for mention_type in 
                       ['mention', 'textmention', 'username']):
                    
                    entity_offset = getattr(entity, 'offset', 0)
                    entity_length = getattr(entity, 'length', 0)
                    
                    # Adjust for previous replacements
                    adjusted_offset = entity_offset + offset_adjustment
                    
                    # Extract mention text
                    mention_text = filtered_text[adjusted_offset:adjusted_offset + entity_length]
                    
                    # Replace with placeholder or remove
                    if mention_placeholder:
                        filtered_text = (
                            filtered_text[:adjusted_offset] + 
                            mention_placeholder + 
                            filtered_text[adjusted_offset + entity_length:]
                        )
                        # Adjust offset for length difference
                        length_diff = len(mention_placeholder) - entity_length
                        offset_adjustment += length_diff
                    else:
                        # Remove mention completely
                        filtered_text = (
                            filtered_text[:adjusted_offset] + 
                            filtered_text[adjusted_offset + entity_length:]
                        )
                        offset_adjustment -= entity_length
                    
                    # Don't include mention entities in final list
                    continue
                
                # Adjust entity offset for previous changes
                if hasattr(entity, 'offset'):
                    entity.offset += offset_adjustment
                processed_entities.append(entity)
            
            return filtered_text, processed_entities
            
        except Exception as e:
            logger.error(f"Error processing mentions: {e}")
            return text, entities or []
    
    def _adjust_entities_after_removal(self, entities: List, start_pos: int, removed_length: int) -> List:
        """Adjust entity offsets after text removal"""
        adjusted_entities = []
        
        for entity in entities or []:
            entity_offset = getattr(entity, 'offset', 0)
            entity_length = getattr(entity, 'length', 0)
            
            # Skip entities that are completely within the removed section
            if entity_offset >= start_pos and entity_offset + entity_length <= start_pos + removed_length:
                continue
            
            # Adjust entities that come after the removed section
            if entity_offset >= start_pos + removed_length:
                entity.offset = entity_offset - removed_length
                adjusted_entities.append(entity)
            # Keep entities that come before the removed section
            elif entity_offset + entity_length <= start_pos:
                adjusted_entities.append(entity)
            # Handle entities that partially overlap (truncate them)
            else:
                if entity_offset < start_pos:
                    # Entity starts before removal, truncate its length
                    entity.length = start_pos - entity_offset
                    adjusted_entities.append(entity)
        
        return adjusted_entities
    
    def _replace_text_with_entities(self, text: str, entities: List, old_text: str, new_text: str) -> tuple[str, List]:
        """Replace text while preserving entity positions"""
        try:
            filtered_text = text
            processed_entities = entities.copy() if entities else []
            offset_adjustment = 0
            
            # Find all occurrences of old_text
            pattern = re.compile(re.escape(old_text), re.IGNORECASE)
            matches = list(pattern.finditer(text))
            
            # Process matches in reverse order to maintain offsets
            for match in reversed(matches):
                start, end = match.span()
                
                # Replace the text
                filtered_text = filtered_text[:start] + new_text + filtered_text[end:]
                
                # Adjust entity offsets
                length_diff = len(new_text) - (end - start)
                for entity in processed_entities:
                    entity_offset = getattr(entity, 'offset', 0)
                    if entity_offset > start:
                        entity.offset += length_diff
            
            return filtered_text, processed_entities
            
        except Exception as e:
            logger.error(f"Error replacing text with entities: {e}")
            return text, entities or []
    
    def _regex_replace_with_entities(self, text: str, entities: List, 
                                   compiled_regex: re.Pattern, replacement: str) -> tuple[str, List]:
        """Apply regex replacement while preserving entities"""
        try:
            # Find all matches first
            matches = list(compiled_regex.finditer(text))
            if not matches:
                return text, entities or []
            
            filtered_text = text
            processed_entities = entities.copy() if entities else []
            
            # Process matches in reverse order
            for match in reversed(matches):
                start, end = match.span()
                
                # Apply replacement
                match_replacement = compiled_regex.sub(replacement, match.group())
                filtered_text = filtered_text[:start] + match_replacement + filtered_text[end:]
                
                # Adjust entity offsets
                length_diff = len(match_replacement) - (end - start)
                for entity in processed_entities:
                    entity_offset = getattr(entity, 'offset', 0)
                    if entity_offset > start:
                        entity.offset += length_diff
            
            return filtered_text, processed_entities
            
        except Exception as e:
            logger.error(f"Error in regex replacement with entities: {e}")
            return text, entities or []
    
    def _clean_excessive_spaces(self, text: str) -> str:
        """Clean up excessive spaces while preserving newlines"""
        if not text:
            return text
        
        # Clean multiple spaces but preserve newlines
        # Replace multiple spaces with single space
        text = re.sub(r' +', ' ', text)
        
        # Clean up spaces around newlines
        text = re.sub(r' *\n *', '\n', text)
        
        # Remove trailing spaces on lines
        text = re.sub(r' +$', '', text, flags=re.MULTILINE)
        
        return text.strip()
    
    def _normalize_whitespace_with_entities(self, text: str, entities: List) -> tuple[str, List]:
        """Normalize whitespace while preserving entity positions"""
        try:
            # Create mapping of old positions to new positions
            filtered_text = ""
            position_map = {}
            old_pos = 0
            new_pos = 0
            
            # Normalize whitespace and track position changes
            i = 0
            while i < len(text):
                position_map[i] = new_pos
                
                if text[i].isspace():
                    # Skip consecutive whitespace, keep only one space
                    if not filtered_text or not filtered_text[-1].isspace():
                        filtered_text += " "
                        new_pos += 1
                    
                    # Skip additional whitespace
                    while i < len(text) and text[i].isspace():
                        position_map[i] = new_pos - 1 if filtered_text and filtered_text[-1].isspace() else new_pos
                        i += 1
                    continue
                else:
                    filtered_text += text[i]
                    new_pos += 1
                    i += 1
            
            # Add final position mapping
            position_map[len(text)] = len(filtered_text)
            
            # Adjust entities
            processed_entities = []
            for entity in entities or []:
                entity_offset = getattr(entity, 'offset', 0)
                entity_length = getattr(entity, 'length', 0)
                
                # Map old positions to new positions
                new_offset = position_map.get(entity_offset, entity_offset)
                new_end = position_map.get(entity_offset + entity_length, entity_offset + entity_length)
                new_length = new_end - new_offset
                
                if new_length > 0:
                    entity.offset = new_offset
                    entity.length = new_length
                    processed_entities.append(entity)
            
            return filtered_text.strip(), processed_entities
            
        except Exception as e:
            logger.error(f"Error normalizing whitespace with entities: {e}")
            return text, entities or []
    
    async def add_pair_word_block(self, pair_id: int, word: str):
        """Add word to pair-specific block list"""
        try:
            pair = await self.db_manager.get_pair_by_id(pair_id)
            if not pair:
                return False
            
            blocked_words = pair.filters.get("blocked_words", [])
            if word not in blocked_words:
                blocked_words.append(word)
                pair.filters["blocked_words"] = blocked_words
                await self.db_manager.update_pair(pair)
                logger.info(f"Added word block for pair {pair_id}: {word}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add pair word block: {e}")
            return False
    
    async def remove_pair_word_block(self, pair_id: int, word: str):
        """Remove word from pair-specific block list"""
        try:
            pair = await self.db_manager.get_pair_by_id(pair_id)
            if not pair:
                return False
            
            blocked_words = pair.filters.get("blocked_words", [])
            if word in blocked_words:
                blocked_words.remove(word)
                pair.filters["blocked_words"] = blocked_words
                await self.db_manager.update_pair(pair)
                logger.info(f"Removed word block for pair {pair_id}: {word}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove pair word block: {e}")
            return False
    
    async def set_pair_header_footer_regex(self, pair_id: int, header_regex: str = None, footer_regex: str = None):
        """Set header/footer regex patterns for pair"""
        try:
            pair = await self.db_manager.get_pair_by_id(pair_id)
            if not pair:
                return False
            
            if header_regex is not None:
                if header_regex:
                    # Validate regex
                    try:
                        re.compile(header_regex)
                        pair.filters["header_regex"] = header_regex
                    except re.error as e:
                        logger.error(f"Invalid header regex: {e}")
                        return False
                else:
                    # Remove header regex
                    pair.filters.pop("header_regex", None)
            
            if footer_regex is not None:
                if footer_regex:
                    # Validate regex
                    try:
                        re.compile(footer_regex)
                        pair.filters["footer_regex"] = footer_regex
                    except re.error as e:
                        logger.error(f"Invalid footer regex: {e}")
                        return False
                else:
                    # Remove footer regex
                    pair.filters.pop("footer_regex", None)
            
            await self.db_manager.update_pair(pair)
            logger.info(f"Updated header/footer regex for pair {pair_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set header/footer regex: {e}")
            return False
    
    async def set_mention_removal(self, pair_id: int, remove_mentions: bool, placeholder: str = ""):
        """Configure mention removal for pair"""
        try:
            pair = await self.db_manager.get_pair_by_id(pair_id)
            if not pair:
                return False
            
            pair.filters["remove_mentions"] = remove_mentions
            if remove_mentions and placeholder:
                pair.filters["mention_placeholder"] = placeholder
            else:
                pair.filters.pop("mention_placeholder", None)
            
            await self.db_manager.update_pair(pair)
            logger.info(f"Updated mention removal for pair {pair_id}: {remove_mentions}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set mention removal: {e}")
            return False
    
    def _remove_mentions(self, text: str, placeholder: str = "[User]") -> str:
        """Enhanced mention removal with comprehensive pattern matching and clean formatting"""
        if not text:
            return text
        try:
            original_text = text
            
            # Comprehensive mention patterns covering all edge cases
            mention_patterns = [
                # Mentions in parentheses like (@xyz) - handle before standard patterns
                r'\(@[a-zA-Z0-9_]+\)',
                # Mentions with dots like .@xyz
                r'\.@[a-zA-Z0-9_]+',
                # Standard @username patterns (letters, numbers, underscores)
                r'@[a-zA-Z0-9_]+',
                # User links with IDs
                r'tg://user\?id=\d+',
            ]
            
            # Apply patterns strategically to handle edge cases
            for pattern in mention_patterns:
                if pattern == r'\(@[a-zA-Z0-9_]+\)':
                    # Replace parentheses mentions, remove parentheses
                    text = re.sub(pattern, placeholder, text)
                elif pattern == r'\.@[a-zA-Z0-9_]+':
                    # Replace dot mentions, remove dot
                    text = re.sub(pattern, placeholder, text)
                else:
                    # Standard patterns
                    text = re.sub(pattern, placeholder, text)
            
            # Clean up multiple spaces and formatting issues
            # Remove duplicate placeholders
            text = re.sub(f'{re.escape(placeholder)}(\\s*{re.escape(placeholder)})+', placeholder, text)
            
            # Clean up extra spaces around placeholders
            text = re.sub(f'\\s+{re.escape(placeholder)}\\s+', f' {placeholder} ', text)
            text = re.sub(f'^\\s*{re.escape(placeholder)}\\s*', f'{placeholder} ', text)
            text = re.sub(f'\\s*{re.escape(placeholder)}\\s*$', f' {placeholder}', text)
            
            # Clean up multiple spaces
            text = re.sub(r'\s+', ' ', text)
            
            # Remove leading/trailing spaces
            text = text.strip()
            
            # If placeholder removal left empty text, return original
            if not text or text == placeholder:
                placeholder_only_pattern = f'^\\s*{re.escape(placeholder)}\\s*$'
                if re.match(placeholder_only_pattern, text):
                    return original_text
            
            return text
            
        except Exception as e:
            logger.error(f"Error removing mentions: {e}")
            return text
    
    def _remove_headers(self, text: str, patterns: List[str]) -> str:
        """Enhanced header removal with exact text matching and formatting preservation"""
        try:
            if not text:
                return text
                
            original_text = text
            
            # If no patterns provided, use conservative exact-match patterns
            if not patterns:
                # More conservative default patterns for exact header removal
                exact_header_patterns = [
                    r'^🔥\s*VIP\s*ENTRY.*?$',      # Exact: "🔥 VIP ENTRY:"
                    r'^📢\s*SIGNAL\s*ALERT.*?$',   # Exact: "📢 SIGNAL ALERT"
                    r'^VIP\s*Channel.*?$',         # Exact: "VIP Channel:"
                    r'^📊\s*Analysis.*?$',         # Exact: "📊 Analysis"
                    r'^🚨\s*Alert.*?$',            # Exact: "🚨 Alert"
                ]
                patterns = exact_header_patterns
            
            # Apply patterns with line-by-line precision
            lines = text.split('\n')
            filtered_lines = []
            
            for line in lines:
                line_removed = False
                
                # Check each pattern against the current line
                for pattern in patterns:
                    try:
                        # Compile with case-insensitive matching for flexibility
                        compiled_pattern = re.compile(pattern, re.IGNORECASE)
                        
                        # Check if this line matches the header pattern
                        if compiled_pattern.match(line):
                            line_removed = True
                            logger.debug(f"Header removed: '{line}' matched pattern: {pattern}")
                            break
                    except re.error as regex_error:
                        logger.warning(f"Invalid header regex pattern '{pattern}': {regex_error}")
                        continue
                
                # Only keep lines that don't match any header pattern
                if not line_removed:
                    filtered_lines.append(line)
            
            # Rejoin lines preserving original structure
            result_text = '\n'.join(filtered_lines)
            
            # Clean up leading/trailing whitespace but preserve internal newlines
            result_text = result_text.strip()
            
            # If result is empty or only whitespace, return original
            if not result_text or result_text.isspace():
                return original_text
            
            return result_text
            
        except Exception as e:
            logger.error(f"Error removing headers: {e}")
            return text
    
    def _remove_footers(self, text: str, patterns: List[str]) -> str:
        """Enhanced footer removal with exact text matching and formatting preservation"""
        try:
            if not text:
                return text
                
            original_text = text
            
            # If no patterns provided, use conservative exact-match patterns
            if not patterns:
                # More conservative default patterns for exact footer removal
                exact_footer_patterns = [
                    r'\n.*?🔚\s*END.*?$',          # Exact: "🔚 END"
                    r'\n.*?👉\s*Join.*?$',         # Exact: "👉 Join our VIP channel"
                    r'\n.*?Contact\s*@admin.*?$',  # Exact: "Contact @admin for more info"
                    r'\n.*?📱\s*Contact.*?$',      # Exact: "📱 Contact us"
                    r'\n.*?💌\s*Subscribe.*?$',    # Exact: "💌 Subscribe to"
                ]
                patterns = exact_footer_patterns
            
            # Apply patterns working from the end backwards to preserve content
            lines = text.split('\n')
            filtered_lines = list(lines)  # Copy the lines
            
            # Process lines from bottom to top to remove footers cleanly
            for i in range(len(lines) - 1, -1, -1):
                line = lines[i]
                line_removed = False
                
                # Check each pattern against the current line
                for pattern in patterns:
                    try:
                        # Compile with case-insensitive matching for flexibility
                        compiled_pattern = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                        
                        # Create a test string with newline prefix for footer patterns
                        test_string = '\n' + line
                        
                        # Check if this line matches the footer pattern
                        if compiled_pattern.search(test_string):
                            # Remove this line from the filtered list
                            if i < len(filtered_lines):
                                filtered_lines.pop(i)
                                line_removed = True
                                logger.debug(f"Footer removed: '{line}' matched pattern: {pattern}")
                                break
                    except re.error as regex_error:
                        logger.warning(f"Invalid footer regex pattern '{pattern}': {regex_error}")
                        continue
                
                # If we removed a footer line, continue checking from this position
                if line_removed:
                    break
            
            # Rejoin lines preserving original structure  
            result_text = '\n'.join(filtered_lines)
            
            # Clean up leading/trailing whitespace but preserve internal newlines
            result_text = result_text.strip()
            
            # If result is empty or only whitespace, return original
            if not result_text or result_text.isspace():
                return original_text
            
            return result_text
            
        except Exception as e:
            logger.error(f"Error removing footers: {e}")
            return text
    
    def _remove_mentions_with_entities(self, text: str, entities: List, placeholder: str = "[User]") -> tuple[str, List]:
        """Remove mentions while preserving message entities and formatting"""
        if not text:
            return text, entities
        
        try:
            # Use enhanced mention removal
            filtered_text = self._remove_mentions(text, placeholder)
            
            # If text didn't change, return original entities
            if filtered_text == text:
                return text, entities
            
            # Calculate entity adjustments based on text changes
            adjusted_entities = self._adjust_entities_after_text_transformation(
                text, filtered_text, entities
            )
            
            return filtered_text, adjusted_entities
            
        except Exception as e:
            logger.error(f"Error removing mentions with entities: {e}")
            return text, entities
    
    def _adjust_entities_after_text_transformation(self, original_text: str, new_text: str, entities: List) -> List:
        """Adjust entity offsets after text transformation while preserving formatting"""
        if not entities or original_text == new_text:
            return entities
        
        try:
            adjusted_entities = []
            
            for entity in entities:
                if not hasattr(entity, 'offset') or not hasattr(entity, 'length'):
                    continue
                
                entity_start = entity.offset
                entity_end = entity.offset + entity.length
                
                # Ensure entity is within new text bounds
                if entity_start < len(new_text):
                    # Adjust length if entity extends beyond new text
                    if entity_end > len(new_text):
                        new_length = len(new_text) - entity_start
                        if new_length > 0:
                            # Create new entity with adjusted length
                            adjusted_entity = type(entity)(
                                type=entity.type,
                                offset=entity.offset,
                                length=new_length
                            )
                            adjusted_entities.append(adjusted_entity)
                    else:
                        # Entity fits within new text, keep as is
                        adjusted_entities.append(entity)
            
            return adjusted_entities
            
        except Exception as e:
            logger.error(f"Error adjusting entities after transformation: {e}")
            return entities
