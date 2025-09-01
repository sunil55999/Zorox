"""
Topic-to-Channel forwarding manager with reply mapping
Handles Group Topic → Channel forwarding while preserving channel → channel logic
"""

import json
import logging
import asyncio
import os
from typing import Dict, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass, field

from database import DatabaseManager, MessagePair

logger = logging.getLogger(__name__)

@dataclass
class TopicMapping:
    """Topic forwarding mapping data"""
    source_chat_id: int
    topic_id: int
    source_msg_id: int
    dest_channel_id: int
    dest_msg_id: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

class TopicManager:
    """Manages Group Topic → Channel forwarding with reply mapping"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.mapping_file = "topic_mappings.json"
        
        # In-memory mapping for fast lookups
        # Key: (source_chat_id, topic_id, source_msg_id)
        # Value: (dest_channel_id, dest_msg_id)
        self.forwarded_map: Dict[Tuple[int, int, int], Tuple[int, int]] = {}
        
        # Reverse mapping for edit/delete operations
        # Key: (dest_channel_id, dest_msg_id)
        # Value: (source_chat_id, topic_id, source_msg_id)
        self.reverse_map: Dict[Tuple[int, int], Tuple[int, int, int]] = {}
        
        # Topic pairs configuration
        # Key: (source_chat_id, topic_id)
        # Value: list of destination channel IDs
        self.topic_pairs: Dict[Tuple[int, int], List[int]] = {}
        
        # Auto-save task
        self._save_task: Optional[asyncio.Task] = None
        self._dirty = False
        
    async def initialize(self):
        """Initialize topic manager and load mappings"""
        try:
            await self._load_mappings()
            await self._load_topic_pairs()
            
            # Start auto-save task
            self._save_task = asyncio.create_task(self._auto_save_loop())
            
            logger.info(f"Topic manager initialized with {len(self.forwarded_map)} mappings")
            
        except Exception as e:
            logger.error(f"Failed to initialize topic manager: {e}")
            raise
    
    async def shutdown(self):
        """Shutdown topic manager and save mappings"""
        try:
            if self._save_task:
                self._save_task.cancel()
                
            await self._save_mappings()
            logger.info("Topic manager shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during topic manager shutdown: {e}")
    
    async def _load_mappings(self):
        """Load mappings from JSON file"""
        try:
            if os.path.exists(self.mapping_file):
                with open(self.mapping_file, 'r') as f:
                    data = json.load(f)
                    
                # Convert string keys back to tuples
                for key_str, value in data.get('forwarded_map', {}).items():
                    key = tuple(map(int, key_str.strip('()').split(', ')))
                    self.forwarded_map[key] = tuple(value)
                
                for key_str, value in data.get('reverse_map', {}).items():
                    key = tuple(map(int, key_str.strip('()').split(', ')))
                    self.reverse_map[key] = tuple(value)
                    
                logger.info(f"Loaded {len(self.forwarded_map)} topic mappings from file")
            else:
                logger.info("No existing topic mappings file found, starting fresh")
                
        except Exception as e:
            logger.error(f"Failed to load topic mappings: {e}")
            # Continue with empty mappings
    
    async def _save_mappings(self):
        """Save mappings to JSON file"""
        try:
            # Convert tuple keys to strings for JSON serialization
            data = {
                'forwarded_map': {str(k): list(v) for k, v in self.forwarded_map.items()},
                'reverse_map': {str(k): list(v) for k, v in self.reverse_map.items()},
                'last_saved': datetime.now().isoformat()
            }
            
            # Atomic write
            temp_file = f"{self.mapping_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            os.rename(temp_file, self.mapping_file)
            self._dirty = False
            
            logger.debug(f"Saved {len(self.forwarded_map)} topic mappings to file")
            
        except Exception as e:
            logger.error(f"Failed to save topic mappings: {e}")
    
    async def _auto_save_loop(self):
        """Auto-save mappings periodically"""
        while True:
            try:
                await asyncio.sleep(300)  # Save every 5 minutes
                if self._dirty:
                    await self._save_mappings()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in auto-save loop: {e}")
    
    async def _load_topic_pairs(self):
        """Load topic pairs from database"""
        try:
            # Get all pairs and identify topic pairs
            pairs = await self.db_manager.get_all_pairs()
            
            for pair in pairs:
                # Check if source is a topic (negative chat ID with topic_id in filters)
                topic_id = pair.filters.get('topic_id')
                if topic_id is not None:
                    key = (pair.source_chat_id, topic_id)
                    if key not in self.topic_pairs:
                        self.topic_pairs[key] = []
                    self.topic_pairs[key].append(pair.destination_chat_id)
                    
            logger.info(f"Loaded {len(self.topic_pairs)} topic pairs")
            
        except Exception as e:
            logger.error(f"Failed to load topic pairs: {e}")
    
    def is_topic_message(self, event) -> bool:
        """Check if message is from a group topic"""
        try:
            # Check if event has topic information
            if hasattr(event, 'reply_to') and event.reply_to:
                if hasattr(event.reply_to, 'forum_topic') and event.reply_to.forum_topic:
                    return True
                if hasattr(event.reply_to, 'reply_to_top_id'):
                    return True
            
            # Check if chat is a supergroup with topics enabled
            if hasattr(event, 'chat') and event.chat:
                if hasattr(event.chat, 'forum') and event.chat.forum:
                    return True
            
            # Check if this chat/topic combination is in our topic pairs
            topic_id = self._extract_topic_id(event)
            if topic_id is not None:
                key = (event.chat_id, topic_id)
                return key in self.topic_pairs
            
            return False
            
        except Exception as e:
            logger.debug(f"Error checking if topic message: {e}")
            return False
    
    def _extract_topic_id(self, event) -> Optional[int]:
        """Extract topic ID from event"""
        try:
            # Try different ways to get topic ID
            if hasattr(event, 'reply_to') and event.reply_to:
                if hasattr(event.reply_to, 'reply_to_top_id'):
                    return event.reply_to.reply_to_top_id
                if hasattr(event.reply_to, 'forum_topic') and event.reply_to.forum_topic:
                    return getattr(event.reply_to.forum_topic, 'id', None)
            
            # Check message attributes
            if hasattr(event, 'message') and event.message:
                if hasattr(event.message, 'reply_to') and event.message.reply_to:
                    if hasattr(event.message.reply_to, 'reply_to_top_id'):
                        return event.message.reply_to.reply_to_top_id
            
            return None
            
        except Exception as e:
            logger.debug(f"Error extracting topic ID: {e}")
            return None
    
    async def get_topic_destinations(self, source_chat_id: int, topic_id: int) -> List[int]:
        """Get destination channels for a topic"""
        key = (source_chat_id, topic_id)
        return self.topic_pairs.get(key, [])
    
    async def add_topic_pair(self, source_chat_id: int, topic_id: int, dest_channel_id: int, name: str) -> int:
        """Add a new topic → channel pair"""
        try:
            # Create pair in database with topic_id in filters
            filters = {
                "topic_id": topic_id,
                "blocked_words": [],
                "remove_mentions": False,
                "preserve_replies": True,
                "sync_edits": True,
                "sync_deletes": True
            }
            
            pair_id = await self.db_manager.create_pair(
                source_chat_id=source_chat_id,
                destination_chat_id=dest_channel_id,
                name=f"{name} (Topic {topic_id})",
                bot_index=0
            )
            
            # Update pair with topic filters
            pair = await self.db_manager.get_pair(pair_id)
            if pair:
                pair.filters.update(filters)
                await self.db_manager.update_pair(pair)
            
            # Add to topic pairs
            key = (source_chat_id, topic_id)
            if key not in self.topic_pairs:
                self.topic_pairs[key] = []
            self.topic_pairs[key].append(dest_channel_id)
            
            logger.info(f"Added topic pair: {source_chat_id}:{topic_id} → {dest_channel_id}")
            return pair_id
            
        except Exception as e:
            logger.error(f"Failed to add topic pair: {e}")
            raise
    
    async def store_mapping(self, source_chat_id: int, topic_id: int, source_msg_id: int,
                          dest_channel_id: int, dest_msg_id: int):
        """Store topic message mapping"""
        try:
            key = (source_chat_id, topic_id, source_msg_id)
            value = (dest_channel_id, dest_msg_id)
            
            self.forwarded_map[key] = value
            self.reverse_map[(dest_channel_id, dest_msg_id)] = (source_chat_id, topic_id, source_msg_id)
            
            self._dirty = True
            
            logger.debug(f"Stored topic mapping: {key} → {value}")
            
        except Exception as e:
            logger.error(f"Failed to store topic mapping: {e}")
    
    async def get_forwarded_message_id(self, source_chat_id: int, topic_id: int, 
                                     source_msg_id: int, dest_channel_id: int) -> Optional[int]:
        """Get forwarded message ID for reply handling"""
        try:
            key = (source_chat_id, topic_id, source_msg_id)
            value = self.forwarded_map.get(key)
            
            if value and value[0] == dest_channel_id:
                return value[1]
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting forwarded message ID: {e}")
            return None
    
    async def get_source_mapping(self, dest_channel_id: int, dest_msg_id: int) -> Optional[Tuple[int, int, int]]:
        """Get source mapping for edit/delete operations"""
        try:
            key = (dest_channel_id, dest_msg_id)
            return self.reverse_map.get(key)
            
        except Exception as e:
            logger.error(f"Error getting source mapping: {e}")
            return None
    
    async def remove_mapping(self, source_chat_id: int, topic_id: int, source_msg_id: int):
        """Remove mapping (for delete operations)"""
        try:
            key = (source_chat_id, topic_id, source_msg_id)
            value = self.forwarded_map.pop(key, None)
            
            if value:
                reverse_key = (value[0], value[1])
                self.reverse_map.pop(reverse_key, None)
                self._dirty = True
                
                logger.debug(f"Removed topic mapping: {key}")
                
        except Exception as e:
            logger.error(f"Failed to remove topic mapping: {e}")
    
    async def cleanup_old_mappings(self, days: int = 30):
        """Clean up old mappings to prevent memory bloat"""
        try:
            cutoff_time = datetime.now().timestamp() - (days * 24 * 3600)
            removed_count = 0
            
            # Create list of keys to remove (avoid modifying dict during iteration)
            keys_to_remove = []
            
            for key in self.forwarded_map.keys():
                # Try to get timestamp from mapping (if stored)
                # For now, we'll implement a simple size-based cleanup
                pass
            
            # If mappings exceed reasonable size, remove oldest entries
            if len(self.forwarded_map) > 10000:  # Configurable threshold
                # Sort by key (which includes message ID, roughly chronological)
                sorted_keys = sorted(self.forwarded_map.keys(), key=lambda x: x[2])  # Sort by message ID
                
                # Remove oldest 20%
                remove_count = len(sorted_keys) // 5
                keys_to_remove = sorted_keys[:remove_count]
                
                for key in keys_to_remove:
                    value = self.forwarded_map.pop(key, None)
                    if value:
                        reverse_key = (value[0], value[1])
                        self.reverse_map.pop(reverse_key, None)
                        removed_count += 1
                
                self._dirty = True
                logger.info(f"Cleaned up {removed_count} old topic mappings")
            
            return removed_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old mappings: {e}")
            return 0
    
    def get_mapping_stats(self) -> Dict[str, Any]:
        """Get mapping statistics"""
        try:
            return {
                "total_mappings": len(self.forwarded_map),
                "topic_pairs": len(self.topic_pairs),
                "memory_usage_kb": len(str(self.forwarded_map)) / 1024,
                "last_saved": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting mapping stats: {e}")
            return {}