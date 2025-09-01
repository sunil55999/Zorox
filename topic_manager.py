"""
Topic-to-Channel forwarding manager with reply mapping
Handles Group Topic → Channel forwarding while preserving channel → channel logic
"""

import json
import logging
import asyncio
import os
from typing import Dict, Optional, Tuple, Any, List
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
        # Value: list of destination channel IDs with their pair configs
        self.topic_pairs: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
        
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
            
            logger.info(f"Topic manager initialized with {len(self.forwarded_map)} mappings and {len(self.topic_pairs)} topic pairs")
            
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
                    try:
                        # Parse key string like "(123, 456, 789)"
                        key_parts = key_str.strip('()').split(', ')
                        key = tuple(int(part) for part in key_parts)
                        self.forwarded_map[key] = tuple(value)
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Skipping invalid mapping key: {key_str} - {e}")
                
                for key_str, value in data.get('reverse_map', {}).items():
                    try:
                        key_parts = key_str.strip('()').split(', ')
                        key = tuple(int(part) for part in key_parts)
                        self.reverse_map[key] = tuple(value)
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Skipping invalid reverse mapping key: {key_str} - {e}")
                    
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
                'last_saved': datetime.now().isoformat(),
                'total_mappings': len(self.forwarded_map)
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
                # Check if source is a topic (has topic_id in filters)
                topic_id = pair.filters.get('topic_id')
                if topic_id is not None:
                    key = (pair.source_chat_id, topic_id)
                    if key not in self.topic_pairs:
                        self.topic_pairs[key] = []
                    
                    # Store full pair info for filtering
                    self.topic_pairs[key].append({
                        'pair_id': pair.id,
                        'dest_channel_id': pair.destination_chat_id,
                        'pair': pair
                    })
                    
            logger.info(f"Loaded {len(self.topic_pairs)} topic pairs")
            
        except Exception as e:
            logger.error(f"Failed to load topic pairs: {e}")
    
    def is_topic_message(self, event) -> bool:
        """Check if message is from a group topic"""
        try:
            # Extract topic ID
            topic_id = self._extract_topic_id(event)
            if topic_id is None:
                return False
            
            # Check if this chat/topic combination is in our topic pairs
            key = (event.chat_id, topic_id)
            is_topic = key in self.topic_pairs
            
            if is_topic:
                logger.debug(f"Detected topic message: chat {event.chat_id}, topic {topic_id}")
            
            return is_topic
            
        except Exception as e:
            logger.debug(f"Error checking if topic message: {e}")
            return False
    
    def _extract_topic_id(self, event) -> Optional[int]:
        """Extract topic ID from event"""
        try:
            # Method 1: Check reply_to for forum topic
            if hasattr(event, 'reply_to') and event.reply_to:
                if hasattr(event.reply_to, 'reply_to_top_id') and event.reply_to.reply_to_top_id:
                    return event.reply_to.reply_to_top_id
                if hasattr(event.reply_to, 'forum_topic') and event.reply_to.forum_topic:
                    return getattr(event.reply_to.forum_topic, 'id', None)
            
            # Method 2: Check message reply_to
            if hasattr(event, 'message') and event.message:
                if hasattr(event.message, 'reply_to') and event.message.reply_to:
                    if hasattr(event.message.reply_to, 'reply_to_top_id') and event.message.reply_to.reply_to_top_id:
                        return event.message.reply_to.reply_to_top_id
            
            # Method 3: Check if chat is forum and extract from context
            if hasattr(event, 'chat') and event.chat:
                if hasattr(event.chat, 'forum') and event.chat.forum:
                    # For forum messages, topic ID might be in different places
                    if hasattr(event, 'reply_to_msg_id') and event.reply_to_msg_id:
                        # This might be the topic root message ID
                        return event.reply_to_msg_id
            
            return None
            
        except Exception as e:
            logger.debug(f"Error extracting topic ID: {e}")
            return None
    
    async def get_topic_destinations(self, source_chat_id: int, topic_id: int) -> List[Dict[str, Any]]:
        """Get destination channels and their pair configs for a topic"""
        key = (source_chat_id, topic_id)
        return self.topic_pairs.get(key, [])
    
    async def add_topic_pair(self, source_chat_id: int, topic_id: int, dest_channel_id: int, name: str, bot_index: int = 0) -> int:
        """Add a new topic → channel pair"""
        try:
            # Create pair in database with topic_id in filters
            filters = {
                "topic_id": topic_id,
                "blocked_words": [],
                "remove_mentions": False,
                "preserve_replies": True,
                "sync_edits": True,
                "sync_deletes": True,
                "allowed_media_types": ["photo", "video", "document", "audio", "voice", "animation", "video_note", "sticker", "webpage", "unknown"]
            }
            
            pair_id = await self.db_manager.create_pair(
                source_chat_id=source_chat_id,
                destination_chat_id=dest_channel_id,
                name=f"{name} (Topic {topic_id})",
                bot_index=bot_index
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
                
                self.topic_pairs[key].append({
                    'pair_id': pair_id,
                    'dest_channel_id': dest_channel_id,
                    'pair': pair
                })
            
            logger.info(f"Added topic pair: {source_chat_id}:{topic_id} → {dest_channel_id} (pair_id: {pair_id})")
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
    
    async def handle_topic_reply(self, event, source_chat_id: int, topic_id: int) -> Optional[int]:
        """Handle reply logic for topic messages"""
        try:
            # Check if this is a reply
            reply_to_msg_id = None
            if hasattr(event, 'reply_to') and event.reply_to:
                if hasattr(event.reply_to, 'reply_to_msg_id'):
                    reply_to_msg_id = event.reply_to.reply_to_msg_id
            elif hasattr(event, 'reply_to_msg_id') and event.reply_to_msg_id:
                reply_to_msg_id = event.reply_to_msg_id
            
            if not reply_to_msg_id:
                return None  # Not a reply
            
            # Get all destinations for this topic
            destinations = await self.get_topic_destinations(source_chat_id, topic_id)
            
            # For each destination, check if the replied-to message was forwarded
            for dest_info in destinations:
                dest_channel_id = dest_info['dest_channel_id']
                forwarded_msg_id = await self.get_forwarded_message_id(
                    source_chat_id, topic_id, reply_to_msg_id, dest_channel_id
                )
                
                if forwarded_msg_id:
                    logger.debug(f"Found reply mapping: {reply_to_msg_id} → {forwarded_msg_id} in channel {dest_channel_id}")
                    return forwarded_msg_id
            
            logger.debug(f"No reply mapping found for message {reply_to_msg_id} in topic {topic_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error handling topic reply: {e}")
            return None
    
    async def process_topic_edit(self, event, source_chat_id: int, topic_id: int) -> List[Tuple[int, int]]:
        """Process edit for topic message, return list of (dest_channel_id, dest_msg_id) to update"""
        try:
            source_msg_id = event.id
            key = (source_chat_id, topic_id, source_msg_id)
            
            # Find all forwarded copies
            forwarded_copies = []
            for (dest_channel_id, dest_msg_id), source_key in self.reverse_map.items():
                if source_key == key:
                    forwarded_copies.append((dest_channel_id, dest_msg_id))
            
            logger.debug(f"Found {len(forwarded_copies)} forwarded copies to edit for topic message {source_msg_id}")
            return forwarded_copies
            
        except Exception as e:
            logger.error(f"Error processing topic edit: {e}")
            return []
    
    async def process_topic_delete(self, event, source_chat_id: int, topic_id: int) -> List[Tuple[int, int]]:
        """Process delete for topic message, return list of (dest_channel_id, dest_msg_id) to delete"""
        try:
            source_msg_id = event.id
            key = (source_chat_id, topic_id, source_msg_id)
            
            # Find all forwarded copies
            forwarded_copies = []
            for (dest_channel_id, dest_msg_id), source_key in self.reverse_map.items():
                if source_key == key:
                    forwarded_copies.append((dest_channel_id, dest_msg_id))
            
            # Remove mappings
            await self.remove_mapping(source_chat_id, topic_id, source_msg_id)
            
            logger.debug(f"Found {len(forwarded_copies)} forwarded copies to delete for topic message {source_msg_id}")
            return forwarded_copies
            
        except Exception as e:
            logger.error(f"Error processing topic delete: {e}")
            return []
    
    async def cleanup_old_mappings(self, days: int = 30):
        """Clean up old mappings to prevent memory bloat"""
        try:
            removed_count = 0
            
            # If mappings exceed reasonable size, remove oldest entries
            if len(self.forwarded_map) > 50000:  # Configurable threshold for large systems
                # Sort by key (message ID is roughly chronological)
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
                "reverse_mappings": len(self.reverse_map),
                "last_saved": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting mapping stats: {e}")
            return {}
    
    async def refresh_topic_pairs(self):
        """Refresh topic pairs from database"""
        try:
            self.topic_pairs.clear()
            await self._load_topic_pairs()
            logger.info("Topic pairs refreshed from database")
        except Exception as e:
            logger.error(f"Failed to refresh topic pairs: {e}")
    
    def get_all_topic_pairs(self) -> Dict[Tuple[int, int], List[Dict[str, Any]]]:
        """Get all topic pairs for management"""
        return self.topic_pairs.copy()
    
    async def remove_topic_pair(self, source_chat_id: int, topic_id: int, dest_channel_id: int) -> bool:
        """Remove a specific topic pair"""
        try:
            key = (source_chat_id, topic_id)
            if key in self.topic_pairs:
                # Remove the specific destination
                self.topic_pairs[key] = [
                    dest for dest in self.topic_pairs[key] 
                    if dest['dest_channel_id'] != dest_channel_id
                ]
                
                # If no destinations left, remove the key
                if not self.topic_pairs[key]:
                    del self.topic_pairs[key]
                
                # Also remove from database
                pairs = await self.db_manager.get_all_pairs()
                for pair in pairs:
                    if (pair.source_chat_id == source_chat_id and 
                        pair.destination_chat_id == dest_channel_id and
                        pair.filters.get('topic_id') == topic_id):
                        await self.db_manager.delete_pair(pair.id)
                        break
                
                logger.info(f"Removed topic pair: {source_chat_id}:{topic_id} → {dest_channel_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to remove topic pair: {e}")
            return False