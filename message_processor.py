"""
Message Processor - Handles message filtering and copying logic
"""

import asyncio
import logging
import re
import time
from typing import Dict, List, Optional, Any, Tuple
from io import BytesIO
from datetime import datetime

from telegram import Bot, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.error import TelegramError, BadRequest, Forbidden
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument
)

from database import DatabaseManager, MessagePair, MessageMapping
from filters import MessageFilter
from image_handler import ImageHandler
from config import Config

logger = logging.getLogger(__name__)

class MessageProcessor:
    """Advanced message processor with filtering and media handling"""
    
    def __init__(self, db_manager: DatabaseManager, config: Config):
        self.db_manager = db_manager
        self.config = config
        self.message_filter = MessageFilter(db_manager, config)
        self.image_handler = ImageHandler(db_manager, config)
        
        # Processing statistics
        self.stats = {
            'messages_processed': 0,
            'messages_copied': 0,
            'messages_filtered': 0,
            'errors': 0,
            'media_processed': 0
        }
    
    async def initialize(self):
        """Initialize message processor components"""
        await self.message_filter.initialize()
    
    async def process_new_message(self, event, pair: MessagePair, bot: Bot, bot_index: int) -> bool:
        """Process new message from source chat"""
        try:
            self.stats['messages_processed'] += 1
            
            # Apply filters
            filter_result = await self.message_filter.should_copy_message(event, pair)
            if not filter_result.should_copy:
                logger.debug(f"Message filtered: {filter_result.reason}")
                self.stats['messages_filtered'] += 1
                
                # Update pair stats
                pair.stats['messages_filtered'] += 1
                await self.db_manager.update_pair(pair)
                return True  # Successfully filtered (not an error)
            
            # Process message content
            processed_content = await self._process_message_content(event, pair)
            if not processed_content:
                logger.warning("Failed to process message content")
                return False
            
            # Handle media if present
            media_info = None
            if event.media:
                media_info = await self._process_media(event, pair, bot)
                if media_info is False:  # Media blocked
                    self.stats['messages_filtered'] += 1
                    pair.stats['messages_filtered'] += 1
                    await self.db_manager.update_pair(pair)
                    return True
            
            # Handle replies
            reply_to_message_id = None
            if event.is_reply and pair.filters.get("preserve_replies", True):
                reply_to_message_id = await self._find_reply_target(event, pair)
            
            # Send message
            sent_message = await self._send_message(
                bot, pair.destination_chat_id, processed_content, 
                media_info, reply_to_message_id
            )
            
            if sent_message:
                # Save message mapping
                mapping = MessageMapping(
                    id=0,
                    source_message_id=event.id,
                    destination_message_id=sent_message.message_id,
                    pair_id=pair.id,
                    bot_index=bot_index,
                    source_chat_id=pair.source_chat_id,
                    destination_chat_id=pair.destination_chat_id,
                    message_type=self._get_message_type(event),
                    has_media=bool(event.media),
                    is_reply=bool(reply_to_message_id),
                    reply_to_source_id=event.reply_to_msg_id if event.is_reply else None,
                    reply_to_dest_id=reply_to_message_id
                )
                
                await self.db_manager.save_message_mapping(mapping)
                
                # Update statistics
                self.stats['messages_copied'] += 1
                pair.stats['messages_copied'] += 1
                pair.stats['last_activity'] = datetime.now().isoformat()
                
                if event.media:
                    self.stats['media_processed'] += 1
                
                if reply_to_message_id:
                    pair.stats['replies_preserved'] += 1
                
                await self.db_manager.update_pair(pair)
                
                logger.debug(f"Message copied: {event.id} -> {sent_message.message_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error processing new message: {e}")
            self.stats['errors'] += 1
            pair.stats['errors'] += 1
            await self.db_manager.update_pair(pair)
            return False
    
    async def process_message_edit(self, event, pair: MessagePair, bot: Bot, bot_index: int) -> bool:
        """Process message edit"""
        try:
            # Find original message mapping
            mapping = await self.db_manager.get_message_mapping(event.id, pair.id)
            if not mapping:
                logger.debug(f"No mapping found for edited message {event.id}")
                return True  # Not an error if we don't have the original
            
            # Process edited content
            processed_content = await self._process_message_content(event, pair)
            if not processed_content:
                return False
            
            # Edit the destination message
            try:
                await bot.edit_message_text(
                    chat_id=pair.destination_chat_id,
                    message_id=mapping.destination_message_id,
                    text=processed_content.text,
                    parse_mode=processed_content.parse_mode,
                    disable_web_page_preview=True
                )
                
                # Update statistics
                pair.stats['edits_synced'] += 1
                await self.db_manager.update_pair(pair)
                
                logger.debug(f"Message edited: {mapping.destination_message_id}")
                return True
                
            except BadRequest as e:
                if "message is not modified" in str(e).lower():
                    return True  # Content unchanged, not an error
                logger.warning(f"Failed to edit message: {e}")
                return False
            
        except Exception as e:
            logger.error(f"Error processing message edit: {e}")
            return False
    
    async def process_message_delete(self, event, pair: MessagePair, bot: Bot, bot_index: int) -> bool:
        """Process message deletion"""
        try:
            deleted_count = 0
            
            # Handle multiple deleted messages
            for message_id in event.deleted_ids:
                mapping = await self.db_manager.get_message_mapping(message_id, pair.id)
                if mapping:
                    try:
                        await bot.delete_message(
                            chat_id=pair.destination_chat_id,
                            message_id=mapping.destination_message_id
                        )
                        deleted_count += 1
                        logger.debug(f"Message deleted: {mapping.destination_message_id}")
                        
                    except BadRequest as e:
                        if "message to delete not found" not in str(e).lower():
                            logger.warning(f"Failed to delete message: {e}")
            
            # Update statistics
            if deleted_count > 0:
                pair.stats['deletes_synced'] += deleted_count
                await self.db_manager.update_pair(pair)
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing message deletion: {e}")
            return False
    
    async def _process_message_content(self, event, pair: MessagePair) -> Optional['ProcessedContent']:
        """Process and filter message content"""
        try:
            text = event.text or event.raw_text or ""
            
            # Apply text filters
            filtered_text = await self.message_filter.filter_text(text, pair)
            
            # Apply content transformations
            if pair.filters.get("remove_mentions", False):
                filtered_text = self._remove_mentions(
                    filtered_text, 
                    pair.filters.get("mention_placeholder", "[User]")
                )
                if filtered_text != text:
                    pair.stats['mentions_removed'] += 1
            
            # Remove headers if configured
            if pair.filters.get("remove_headers", False):
                original_text = filtered_text
                filtered_text = self._remove_headers(filtered_text, pair.filters.get("header_patterns", []))
                if filtered_text != original_text:
                    pair.stats['headers_removed'] += 1
            
            # Remove footers if configured
            if pair.filters.get("remove_footers", False):
                original_text = filtered_text
                filtered_text = self._remove_footers(filtered_text, pair.filters.get("footer_patterns", []))
                if filtered_text != original_text:
                    pair.stats['footers_removed'] += 1
            
            # Check length limits
            min_length = pair.filters.get("min_message_length", 0)
            max_length = pair.filters.get("max_message_length", 0)
            
            if min_length > 0 and len(filtered_text) < min_length:
                return None
            
            if max_length > 0 and len(filtered_text) > max_length:
                filtered_text = filtered_text[:max_length] + "..."
            
            return ProcessedContent(
                text=filtered_text,
                parse_mode=None,
                entities=event.entities if hasattr(event, 'entities') else None
            )
            
        except Exception as e:
            logger.error(f"Error processing message content: {e}")
            return None
    
    async def _process_media(self, event, pair: MessagePair, bot: Bot) -> Optional[Any]:
        """Process media content"""
        try:
            media = event.media
            
            # Check if media type is allowed
            allowed_types = pair.filters.get("allowed_media_types", [
                "photo", "video", "document", "audio", "voice"
            ])
            
            media_type = self._get_media_type(media)
            if media_type not in allowed_types:
                logger.debug(f"Media type {media_type} not allowed")
                return False  # Media blocked
            
            # Special handling for images
            if isinstance(media, MessageMediaPhoto):
                # Check for duplicate images
                if await self.image_handler.is_image_blocked(event, pair):
                    logger.debug("Image blocked as duplicate")
                    return False
            
            # Download media
            media_data = await self._download_media(event)
            if not media_data:
                logger.warning("Failed to download media")
                return None
            
            return {
                'type': media_type,
                'data': media_data,
                'filename': getattr(media, 'file_name', None) if hasattr(media, 'file_name') else None,
                'caption': event.text or ""
            }
            
        except Exception as e:
            logger.error(f"Error processing media: {e}")
            return None
    
    async def _download_media(self, event) -> Optional[BytesIO]:
        """Download media from message"""
        try:
            # Create a BytesIO buffer
            buffer = BytesIO()
            
            # Download media to buffer
            await event.client.download_media(event.media, file=buffer)
            buffer.seek(0)
            
            return buffer
            
        except Exception as e:
            logger.error(f"Error downloading media: {e}")
            return None
    
    async def _send_message(self, bot: Bot, chat_id: int, content: 'ProcessedContent', 
                          media_info: Optional[Dict], reply_to_message_id: Optional[int] = None):
        """Send message to destination chat"""
        try:
            if media_info:
                # Send media message
                if media_info['type'] == 'photo':
                    return await bot.send_photo(
                        chat_id=chat_id,
                        photo=media_info['data'],
                        caption=content.text[:1024] if content.text else None,
                        reply_to_message_id=reply_to_message_id
                    )
                elif media_info['type'] == 'video':
                    return await bot.send_video(
                        chat_id=chat_id,
                        video=media_info['data'],
                        caption=content.text[:1024] if content.text else None,
                        reply_to_message_id=reply_to_message_id
                    )
                elif media_info['type'] == 'document':
                    return await bot.send_document(
                        chat_id=chat_id,
                        document=media_info['data'],
                        filename=media_info.get('filename'),
                        caption=content.text[:1024] if content.text else None,
                        reply_to_message_id=reply_to_message_id
                    )
                elif media_info['type'] == 'audio':
                    return await bot.send_audio(
                        chat_id=chat_id,
                        audio=media_info['data'],
                        caption=content.text[:1024] if content.text else None,
                        reply_to_message_id=reply_to_message_id
                    )
                elif media_info['type'] == 'voice':
                    return await bot.send_voice(
                        chat_id=chat_id,
                        voice=media_info['data'],
                        caption=content.text[:1024] if content.text else None,
                        reply_to_message_id=reply_to_message_id
                    )
            else:
                # Send text message
                if content.text:
                    return await bot.send_message(
                        chat_id=chat_id,
                        text=content.text,
                        parse_mode=content.parse_mode,
                        disable_web_page_preview=True,
                        reply_to_message_id=reply_to_message_id
                    )
            
            return None
            
        except Forbidden as e:
            logger.error(f"Bot forbidden in chat {chat_id}: {e}")
            return None
        except BadRequest as e:
            logger.error(f"Bad request sending message: {e}")
            return None
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return None
    
    async def _find_reply_target(self, event, pair: MessagePair) -> Optional[int]:
        """Find the destination message ID for reply"""
        try:
            if not event.reply_to_msg_id:
                return None
            
            # Look up the original message mapping
            mapping = await self.db_manager.get_message_mapping(event.reply_to_msg_id, pair.id)
            if mapping:
                return mapping.destination_message_id
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding reply target: {e}")
            return None
    
    def _get_message_type(self, event) -> str:
        """Determine message type"""
        if event.media:
            return self._get_media_type(event.media)
        return "text"
    
    def _get_media_type(self, media) -> str:
        """Determine media type"""
        if isinstance(media, MessageMediaPhoto):
            return "photo"
        elif isinstance(media, MessageMediaVideo):
            return "video"
        elif isinstance(media, MessageMediaDocument):
            if hasattr(media.document, 'mime_type'):
                mime_type = media.document.mime_type
                if mime_type.startswith('image/'):
                    return "photo"
                elif mime_type.startswith('video/'):
                    return "video"
                elif mime_type.startswith('audio/'):
                    return "audio"
            return "document"
        elif isinstance(media, MessageMediaAudio):
            return "audio"
        elif isinstance(media, MessageMediaVoice):
            return "voice"
        elif isinstance(media, MessageMediaVideoNote):
            return "video_note"
        return "unknown"
    
    def _remove_mentions(self, text: str, placeholder: str) -> str:
        """Remove mentions from text"""
        # Remove @username mentions
        text = re.sub(r'@\w+', placeholder, text)
        
        # Remove user links (tg://user?id=...)
        text = re.sub(r'tg://user\?id=\d+', placeholder, text)
        
        return text
    
    def _remove_headers(self, text: str, patterns: List[str]) -> str:
        """Remove headers based on patterns"""
        if not patterns:
            # Default header patterns
            patterns = [
                r'^.*?[:|：].*?\n',  # Lines ending with : or ：
                r'^.*?➜.*?\n',      # Lines with arrow
                r'^.*?👉.*?\n',     # Lines with pointing emoji
                r'^.*?📢.*?\n'      # Lines with megaphone
            ]
        
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.MULTILINE)
        
        return text.strip()
    
    def _remove_footers(self, text: str, patterns: List[str]) -> str:
        """Remove footers based on patterns"""
        if not patterns:
            # Default footer patterns
            patterns = [
                r'\n.*?@\w+.*?$',           # Lines with @mentions at end
                r'\n.*?t\.me/.*?$',         # Lines with t.me links at end
                r'\n.*?[📨📱💌].*?$',        # Lines with contact emojis at end
            ]
        
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.MULTILINE)
        
        return text.strip()
    
    def get_stats(self) -> Dict[str, int]:
        """Get processing statistics"""
        return self.stats.copy()

class ProcessedContent:
    """Container for processed message content"""
    
    def __init__(self, text: str, parse_mode: Optional[str] = None, entities: Optional[List] = None):
        self.text = text
        self.parse_mode = parse_mode
        self.entities = entities
