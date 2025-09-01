"""
Message processing system with topic support
Handles both channel → channel and topic → channel forwarding
"""

import asyncio
import logging
import time
import tempfile
import os
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from dataclasses import dataclass, field

from database import DatabaseManager, MessagePair, MessageMapping
from filters import MessageFilter, FilterResult
from image_handler import ImageHandler
from topic_manager import TopicManager
from config import Config

logger = logging.getLogger(__name__)

@dataclass
class ProcessingResult:
    """Result of message processing"""
    success: bool
    message_id: Optional[int] = None
    error: Optional[str] = None
    filtered: bool = False
    filter_reason: Optional[str] = None

class MessageProcessor:
    """Enhanced message processor with topic support"""
    
    def __init__(self, db_manager: DatabaseManager, config: Config):
        self.db_manager = db_manager
        self.config = config
        self.message_filter = MessageFilter(db_manager, config)
        self.image_handler = ImageHandler(db_manager, config)
        self.topic_manager = TopicManager(db_manager)
        
        # Processing statistics
        self.stats = {
            "messages_processed": 0,
            "messages_filtered": 0,
            "errors": 0,
            "topic_messages": 0,
            "channel_messages": 0,
            "replies_preserved": 0,
            "edits_synced": 0,
            "deletes_synced": 0
        }
        
    async def initialize(self):
        """Initialize message processor"""
        try:
            await self.message_filter.initialize()
            await self.topic_manager.initialize()
            logger.info("Message processor initialized")
        except Exception as e:
            logger.error(f"Failed to initialize message processor: {e}")
            raise
    
    async def shutdown(self):
        """Shutdown message processor"""
        try:
            await self.topic_manager.shutdown()
            logger.info("Message processor shutdown complete")
        except Exception as e:
            logger.error(f"Error during message processor shutdown: {e}")
    
    async def process_new_message(self, event, bot_manager) -> List[ProcessingResult]:
        """Process new message - handles both channel and topic messages"""
        results = []
        
        try:
            self.stats["messages_processed"] += 1
            
            # Determine if this is a topic message
            if self.topic_manager.is_topic_message(event):
                logger.debug(f"Processing topic message from chat {event.chat_id}")
                self.stats["topic_messages"] += 1
                results = await self._process_topic_message(event, bot_manager)
            else:
                logger.debug(f"Processing channel message from chat {event.chat_id}")
                self.stats["channel_messages"] += 1
                results = await self._process_channel_message(event, bot_manager)
            
            # Update statistics
            for result in results:
                if result.filtered:
                    self.stats["messages_filtered"] += 1
                if not result.success:
                    self.stats["errors"] += 1
            
            return results
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            self.stats["errors"] += 1
            return [ProcessingResult(success=False, error=str(e))]
    
    async def _process_topic_message(self, event, bot_manager) -> List[ProcessingResult]:
        """Process message from group topic"""
        results = []
        
        try:
            source_chat_id = event.chat_id
            topic_id = self.topic_manager._extract_topic_id(event)
            
            if topic_id is None:
                logger.warning(f"Could not extract topic ID from event in chat {source_chat_id}")
                return [ProcessingResult(success=False, error="Could not extract topic ID")]
            
            # Get all destinations for this topic
            destinations = await self.topic_manager.get_topic_destinations(source_chat_id, topic_id)
            
            if not destinations:
                logger.debug(f"No destinations configured for topic {topic_id} in chat {source_chat_id}")
                return [ProcessingResult(success=False, error="No destinations configured")]
            
            # Process for each destination
            for dest_info in destinations:
                try:
                    pair = dest_info['pair']
                    dest_channel_id = dest_info['dest_channel_id']
                    
                    # Apply filters
                    filter_result = await self.message_filter.should_copy_message(event, pair)
                    if not filter_result.should_copy:
                        logger.debug(f"Message filtered for topic pair {pair.id}: {filter_result.reason}")
                        results.append(ProcessingResult(
                            success=True, 
                            filtered=True, 
                            filter_reason=filter_result.reason
                        ))
                        continue
                    
                    # Check for image blocking
                    if await self.image_handler.is_image_blocked(event, pair):
                        logger.debug(f"Image blocked for topic pair {pair.id}")
                        results.append(ProcessingResult(
                            success=True, 
                            filtered=True, 
                            filter_reason="Image blocked as duplicate"
                        ))
                        continue
                    
                    # Handle reply logic
                    reply_to_msg_id = None
                    if hasattr(event, 'reply_to') and event.reply_to:
                        reply_to_source_id = getattr(event.reply_to, 'reply_to_msg_id', None)
                        if reply_to_source_id:
                            reply_to_msg_id = await self.topic_manager.get_forwarded_message_id(
                                source_chat_id, topic_id, reply_to_source_id, dest_channel_id
                            )
                            if reply_to_msg_id:
                                logger.debug(f"Found reply mapping: {reply_to_source_id} → {reply_to_msg_id}")
                                self.stats["replies_preserved"] += 1
                    
                    # Forward the message
                    result = await self._forward_topic_message(
                        event, pair, bot_manager, reply_to_msg_id
                    )
                    
                    # Store mapping if successful
                    if result.success and result.message_id:
                        await self.topic_manager.store_mapping(
                            source_chat_id, topic_id, event.id,
                            dest_channel_id, result.message_id
                        )
                        
                        # Also store in regular message mapping for consistency
                        mapping = MessageMapping(
                            id=0,
                            source_message_id=event.id,
                            destination_message_id=result.message_id,
                            pair_id=pair.id,
                            bot_index=pair.assigned_bot_index,
                            source_chat_id=source_chat_id,
                            destination_chat_id=dest_channel_id,
                            message_type=self._get_message_type(event),
                            has_media=bool(event.media),
                            is_reply=bool(reply_to_msg_id),
                            reply_to_source_id=getattr(event.reply_to, 'reply_to_msg_id', None) if hasattr(event, 'reply_to') and event.reply_to else None,
                            reply_to_dest_id=reply_to_msg_id
                        )
                        await self.db_manager.save_message_mapping(mapping)
                    
                    results.append(result)
                    
                except Exception as e:
                    logger.error(f"Error processing topic message for destination {dest_channel_id}: {e}")
                    results.append(ProcessingResult(success=False, error=str(e)))
            
            return results
            
        except Exception as e:
            logger.error(f"Error in topic message processing: {e}")
            return [ProcessingResult(success=False, error=str(e))]
    
    async def _process_channel_message(self, event, bot_manager) -> List[ProcessingResult]:
        """Process message from channel (existing logic)"""
        results = []
        
        try:
            # Get pairs for this source chat
            pairs = await self.db_manager.get_all_pairs()
            source_pairs = [
                pair for pair in pairs 
                if pair.source_chat_id == event.chat_id and 
                pair.status == "active" and
                pair.filters.get('topic_id') is None  # Exclude topic pairs
            ]
            
            if not source_pairs:
                return [ProcessingResult(success=False, error="No active pairs found")]
            
            # Process for each destination
            for pair in source_pairs:
                try:
                    # Apply filters
                    filter_result = await self.message_filter.should_copy_message(event, pair)
                    if not filter_result.should_copy:
                        results.append(ProcessingResult(
                            success=True, 
                            filtered=True, 
                            filter_reason=filter_result.reason
                        ))
                        continue
                    
                    # Check for image blocking
                    if await self.image_handler.is_image_blocked(event, pair):
                        results.append(ProcessingResult(
                            success=True, 
                            filtered=True, 
                            filter_reason="Image blocked as duplicate"
                        ))
                        continue
                    
                    # Handle reply logic (existing channel logic)
                    reply_to_msg_id = None
                    if hasattr(event, 'reply_to') and event.reply_to:
                        reply_to_source_id = getattr(event.reply_to, 'reply_to_msg_id', None)
                        if reply_to_source_id:
                            # Look up in regular message mapping
                            mapping = await self.db_manager.get_message_mapping(reply_to_source_id, pair.id)
                            if mapping:
                                reply_to_msg_id = mapping.destination_message_id
                                self.stats["replies_preserved"] += 1
                    
                    # Forward the message
                    result = await self._forward_channel_message(
                        event, pair, bot_manager, reply_to_msg_id
                    )
                    
                    # Store mapping if successful
                    if result.success and result.message_id:
                        mapping = MessageMapping(
                            id=0,
                            source_message_id=event.id,
                            destination_message_id=result.message_id,
                            pair_id=pair.id,
                            bot_index=pair.assigned_bot_index,
                            source_chat_id=event.chat_id,
                            destination_chat_id=pair.destination_chat_id,
                            message_type=self._get_message_type(event),
                            has_media=bool(event.media),
                            is_reply=bool(reply_to_msg_id),
                            reply_to_source_id=getattr(event.reply_to, 'reply_to_msg_id', None) if hasattr(event, 'reply_to') and event.reply_to else None,
                            reply_to_dest_id=reply_to_msg_id
                        )
                        await self.db_manager.save_message_mapping(mapping)
                    
                    results.append(result)
                    
                except Exception as e:
                    logger.error(f"Error processing channel message for pair {pair.id}: {e}")
                    results.append(ProcessingResult(success=False, error=str(e)))
            
            return results
            
        except Exception as e:
            logger.error(f"Error in channel message processing: {e}")
            return [ProcessingResult(success=False, error=str(e))]
    
    async def _forward_topic_message(self, event, pair: MessagePair, bot_manager, reply_to_msg_id: Optional[int]) -> ProcessingResult:
        """Forward topic message to channel"""
        try:
            # Get bot for this pair
            bot = bot_manager.get_bot_for_pair(pair)
            if not bot:
                return ProcessingResult(success=False, error="No bot available")
            
            # Process message content
            processed_content = await self._process_message_content(event, pair)
            
            # Prepare media if present
            media_file = None
            if event.media:
                media_file = await self._download_and_prepare_media(event, pair)
            
            # Send message
            sent_message = await self._send_message(
                bot, pair.destination_chat_id, processed_content, 
                media_file, reply_to_msg_id
            )
            
            # Cleanup temp file
            if media_file and os.path.exists(media_file):
                try:
                    os.unlink(media_file)
                except:
                    pass
            
            if sent_message:
                return ProcessingResult(success=True, message_id=sent_message.message_id)
            else:
                return ProcessingResult(success=False, error="Failed to send message")
            
        except Exception as e:
            logger.error(f"Error forwarding topic message: {e}")
            return ProcessingResult(success=False, error=str(e))
    
    async def _forward_channel_message(self, event, pair: MessagePair, bot_manager, reply_to_msg_id: Optional[int]) -> ProcessingResult:
        """Forward channel message (existing logic)"""
        try:
            # Get bot for this pair
            bot = bot_manager.get_bot_for_pair(pair)
            if not bot:
                return ProcessingResult(success=False, error="No bot available")
            
            # Process message content
            processed_content = await self._process_message_content(event, pair)
            
            # Prepare media if present
            media_file = None
            if event.media:
                media_file = await self._download_and_prepare_media(event, pair)
            
            # Send message
            sent_message = await self._send_message(
                bot, pair.destination_chat_id, processed_content, 
                media_file, reply_to_msg_id
            )
            
            # Cleanup temp file
            if media_file and os.path.exists(media_file):
                try:
                    os.unlink(media_file)
                except:
                    pass
            
            if sent_message:
                return ProcessingResult(success=True, message_id=sent_message.message_id)
            else:
                return ProcessingResult(success=False, error="Failed to send message")
            
        except Exception as e:
            logger.error(f"Error forwarding channel message: {e}")
            return ProcessingResult(success=False, error=str(e))
    
    async def process_edit(self, event, bot_manager) -> List[ProcessingResult]:
        """Process message edit - handles both channel and topic edits"""
        results = []
        
        try:
            self.stats["edits_synced"] += 1
            
            # Check if this is a topic message
            if self.topic_manager.is_topic_message(event):
                # Topic edit logic
                source_chat_id = event.chat_id
                topic_id = self.topic_manager._extract_topic_id(event)
                
                if topic_id is not None:
                    forwarded_copies = await self.topic_manager.process_topic_edit(
                        event, source_chat_id, topic_id
                    )
                    
                    for dest_channel_id, dest_msg_id in forwarded_copies:
                        # Get pair for filtering
                        destinations = await self.topic_manager.get_topic_destinations(source_chat_id, topic_id)
                        pair = None
                        for dest_info in destinations:
                            if dest_info['dest_channel_id'] == dest_channel_id:
                                pair = dest_info['pair']
                                break
                        
                        if pair:
                            result = await self._edit_forwarded_message(
                                event, pair, bot_manager, dest_channel_id, dest_msg_id
                            )
                            results.append(result)
            else:
                # Channel edit logic (existing)
                pairs = await self.db_manager.get_all_pairs()
                source_pairs = [
                    pair for pair in pairs 
                    if pair.source_chat_id == event.chat_id and 
                    pair.status == "active" and
                    pair.filters.get('topic_id') is None
                ]
                
                for pair in source_pairs:
                    # Find the forwarded message
                    mapping = await self.db_manager.get_message_mapping(event.id, pair.id)
                    if mapping:
                        result = await self._edit_forwarded_message(
                            event, pair, bot_manager, 
                            mapping.destination_chat_id, mapping.destination_message_id
                        )
                        results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Error processing edit: {e}")
            return [ProcessingResult(success=False, error=str(e))]
    
    async def process_delete(self, event, bot_manager) -> List[ProcessingResult]:
        """Process message delete - handles both channel and topic deletes"""
        results = []
        
        try:
            self.stats["deletes_synced"] += 1
            
            # Check if this is a topic message
            if self.topic_manager.is_topic_message(event):
                # Topic delete logic
                source_chat_id = event.chat_id
                topic_id = self.topic_manager._extract_topic_id(event)
                
                if topic_id is not None:
                    forwarded_copies = await self.topic_manager.process_topic_delete(
                        event, source_chat_id, topic_id
                    )
                    
                    for dest_channel_id, dest_msg_id in forwarded_copies:
                        result = await self._delete_forwarded_message(
                            bot_manager, dest_channel_id, dest_msg_id
                        )
                        results.append(result)
            else:
                # Channel delete logic (existing)
                pairs = await self.db_manager.get_all_pairs()
                source_pairs = [
                    pair for pair in pairs 
                    if pair.source_chat_id == event.chat_id and 
                    pair.status == "active" and
                    pair.filters.get('topic_id') is None
                ]
                
                for pair in source_pairs:
                    # Find the forwarded message
                    mapping = await self.db_manager.get_message_mapping(event.id, pair.id)
                    if mapping:
                        result = await self._delete_forwarded_message(
                            bot_manager, mapping.destination_chat_id, mapping.destination_message_id
                        )
                        results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Error processing delete: {e}")
            return [ProcessingResult(success=False, error=str(e))]
    
    async def _process_message_content(self, event, pair: MessagePair) -> Dict[str, Any]:
        """Process message content with all filters applied"""
        try:
            # Get original text and entities
            original_text = event.text or event.raw_text or ""
            entities = getattr(event, 'entities', []) or []
            
            # Apply text filtering
            filtered_text, filtered_entities = await self.message_filter.filter_text(
                original_text, pair, entities
            )
            
            # Prepare content
            content = {
                'text': filtered_text,
                'entities': filtered_entities,
                'parse_mode': None  # Use entities instead of parse_mode
            }
            
            # Add watermark if enabled
            watermark_text = pair.filters.get("watermark_text", "")
            if pair.filters.get("watermark_enabled", False) and watermark_text:
                if content['text']:
                    content['text'] += f"\n\n{watermark_text}"
                else:
                    content['text'] = watermark_text
            
            return content
            
        except Exception as e:
            logger.error(f"Error processing message content: {e}")
            return {'text': event.text or "", 'entities': [], 'parse_mode': None}
    
    async def _download_and_prepare_media(self, event, pair: MessagePair) -> Optional[str]:
        """Download and prepare media with watermarking if enabled"""
        try:
            if not event.media:
                return None
            
            # Create temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
            temp_path = temp_file.name
            temp_file.close()
            
            try:
                # Download media
                await event.client.download_media(event.media, file=temp_path)
                
                # Check if watermarking is enabled for images
                watermark_enabled = pair.filters.get("watermark_enabled", False)
                watermark_text = pair.filters.get("watermark_text", "")
                
                # Apply watermark if enabled and it's an image
                if watermark_enabled and watermark_text:
                    from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
                    
                    is_image = False
                    if isinstance(event.media, MessageMediaPhoto):
                        is_image = True
                    elif isinstance(event.media, MessageMediaDocument):
                        document = getattr(event.media, 'document', None)
                        if document and hasattr(document, 'mime_type'):
                            mime_type = getattr(document, 'mime_type', '').lower()
                            is_image = mime_type.startswith('image/')
                    
                    if is_image:
                        # Create watermarked version
                        watermarked_path = f"{temp_path}.watermarked.jpg"
                        if self.image_handler.add_text_watermark(temp_path, watermarked_path, watermark_text):
                            # Replace original with watermarked version
                            os.unlink(temp_path)
                            temp_path = watermarked_path
                            logger.debug(f"Applied watermark to image: {watermark_text}")
                
                return temp_path
                
            except Exception as e:
                # Clean up on error
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                logger.error(f"Error downloading/preparing media: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Error in media preparation: {e}")
            return None
    
    async def _send_message(self, bot, chat_id: int, content: Dict[str, Any], 
                          media_file: Optional[str], reply_to_msg_id: Optional[int]) -> Optional[Any]:
        """Send message using bot"""
        try:
            # Prepare message parameters
            kwargs = {
                'chat_id': chat_id,
                'text': content.get('text', ''),
            }
            
            # Add reply if specified
            if reply_to_msg_id:
                kwargs['reply_to_message_id'] = reply_to_msg_id
            
            # Add entities if present
            entities = content.get('entities', [])
            if entities:
                # Convert Telethon entities to python-telegram-bot format if needed
                kwargs['entities'] = entities
            
            # Send with or without media
            if media_file and os.path.exists(media_file):
                # Determine media type and send accordingly
                if media_file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                    with open(media_file, 'rb') as f:
                        sent_message = await bot.send_photo(photo=f, **kwargs)
                else:
                    with open(media_file, 'rb') as f:
                        sent_message = await bot.send_document(document=f, **kwargs)
            else:
                # Text-only message
                if kwargs['text']:
                    sent_message = await bot.send_message(**kwargs)
                else:
                    logger.warning("Empty message content, skipping send")
                    return None
            
            return sent_message
            
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return None
    
    async def _edit_forwarded_message(self, event, pair: MessagePair, bot_manager, 
                                    dest_chat_id: int, dest_msg_id: int) -> ProcessingResult:
        """Edit forwarded message"""
        try:
            # Get bot for this pair
            bot = bot_manager.get_bot_for_pair(pair)
            if not bot:
                return ProcessingResult(success=False, error="No bot available")
            
            # Process updated content
            processed_content = await self._process_message_content(event, pair)
            
            # Edit the message
            try:
                await bot.edit_message_text(
                    chat_id=dest_chat_id,
                    message_id=dest_msg_id,
                    text=processed_content['text'],
                    entities=processed_content.get('entities', [])
                )
                return ProcessingResult(success=True, message_id=dest_msg_id)
            except Exception as edit_error:
                logger.error(f"Failed to edit message {dest_msg_id} in chat {dest_chat_id}: {edit_error}")
                return ProcessingResult(success=False, error=str(edit_error))
            
        except Exception as e:
            logger.error(f"Error editing forwarded message: {e}")
            return ProcessingResult(success=False, error=str(e))
    
    async def _delete_forwarded_message(self, bot_manager, dest_chat_id: int, dest_msg_id: int) -> ProcessingResult:
        """Delete forwarded message"""
        try:
            # Get any available bot (for delete operations)
            bot = bot_manager.get_any_available_bot()
            if not bot:
                return ProcessingResult(success=False, error="No bot available")
            
            # Delete the message
            try:
                await bot.delete_message(chat_id=dest_chat_id, message_id=dest_msg_id)
                return ProcessingResult(success=True, message_id=dest_msg_id)
            except Exception as delete_error:
                logger.error(f"Failed to delete message {dest_msg_id} in chat {dest_chat_id}: {delete_error}")
                return ProcessingResult(success=False, error=str(delete_error))
            
        except Exception as e:
            logger.error(f"Error deleting forwarded message: {e}")
            return ProcessingResult(success=False, error=str(e))
    
    def _get_message_type(self, event) -> str:
        """Get message type from event"""
        try:
            if event.media:
                from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
                
                if isinstance(event.media, MessageMediaPhoto):
                    return "photo"
                elif isinstance(event.media, MessageMediaDocument):
                    return "document"
                else:
                    return "media"
            elif event.text:
                return "text"
            else:
                return "unknown"
                
        except Exception:
            return "unknown"
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        return self.stats.copy()
    
    def reset_stats(self):
        """Reset processing statistics"""
        for key in self.stats:
            self.stats[key] = 0
        logger.info("Processing statistics reset")