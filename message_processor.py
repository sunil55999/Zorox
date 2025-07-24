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
            
            # Process message content with entities
            processed_content, processed_entities = await self._process_message_content(event, pair)
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
            
            # Send message with entities
            sent_message = await self._send_message(
                bot, pair.destination_chat_id, processed_content, 
                media_info, reply_to_message_id, processed_entities
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
            
            # Process edited content with entities
            processed_content, processed_entities = await self._process_message_content(event, pair)
            if not processed_content:
                return False
            
            # Edit the destination message
            try:
                await bot.edit_message_text(
                    chat_id=pair.destination_chat_id,
                    message_id=mapping.destination_message_id,
                    text=processed_content,
                    entities=processed_entities,
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
    
    async def _process_message_content(self, event, pair: MessagePair) -> tuple[Optional[str], List]:
        """Process and filter message content with full entity support"""
        try:
            text = event.text or event.raw_text or ""
            entities = getattr(event, 'entities', []) or []
            
            # Apply text filters with entity preservation
            filtered_text, processed_entities = await self.message_filter.filter_text(text, pair, entities)
            
            # Check length limits
            min_length = pair.filters.get("min_message_length", 0)
            max_length = pair.filters.get("max_message_length", 0)
            
            if min_length > 0 and len(filtered_text) < min_length:
                return None, []
            
            if max_length > 0 and len(filtered_text) > max_length:
                # Truncate text and adjust entities
                filtered_text = filtered_text[:max_length] + "..."
                processed_entities = [
                    e for e in processed_entities 
                    if getattr(e, 'offset', 0) + getattr(e, 'length', 0) <= max_length
                ]
            
            return filtered_text, processed_entities
            
        except Exception as e:
            logger.error(f"Error processing message content: {e}")
            return None, []
    
    async def _process_media(self, event, pair: MessagePair, bot: Bot) -> Optional[Any]:
        """Process media content with enhanced type detection"""
        try:
            media = event.media
            
            # Check if media type is allowed
            allowed_types = pair.filters.get("allowed_media_types", [
                "photo", "video", "document", "audio", "voice", "animation", "video_note"
            ])
            
            media_type = self._get_media_type(media)
            if media_type not in allowed_types:
                logger.debug(f"Media type {media_type} not allowed")
                return False  # Media blocked
            
            # Special handling for images
            if media_type == "photo" or (isinstance(media, MessageMediaDocument) and media_type == "photo"):
                # Check for duplicate images with phash
                if await self.image_handler.is_image_blocked(event, pair):
                    logger.debug("Image blocked as duplicate")
                    pair.stats['images_blocked'] = pair.stats.get('images_blocked', 0) + 1
                    return False
            
            # Download media with proper error handling
            try:
                media_data = await self._download_media(event)
                if not media_data:
                    logger.warning("Failed to download media")
                    return None
            except Exception as download_error:
                logger.error(f"Media download failed: {download_error}")
                return None
            
            # Get additional media attributes
            filename = None
            if hasattr(media, 'document') and hasattr(media.document, 'attributes'):
                for attr in media.document.attributes:
                    if hasattr(attr, 'file_name') and attr.file_name:
                        filename = attr.file_name
                        break
            
            return {
                'type': media_type,
                'data': media_data,
                'filename': filename,
                'caption': event.text or "",
                'original_media': media
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
    
    async def _send_message(self, bot: Bot, chat_id: int, content: str, 
                          media_info: Optional[Dict], reply_to_message_id: Optional[int] = None,
                          entities: List = None):
        """Send message to destination chat with enhanced formatting support"""
        try:
            # Validate and convert entities for proper formatting and premium emoji support
            converted_entities = self._validate_and_convert_entities(content, entities) if entities else None
            
            if media_info:
                # Send media message with enhanced content handling
                caption = content[:1024] if content else None
                caption_entities = self._validate_and_convert_entities(caption, entities) if caption and entities else None
                
                if media_info['type'] == 'photo':
                    return await bot.send_photo(
                        chat_id=chat_id,
                        photo=media_info['data'],
                        caption=caption,
                        caption_entities=caption_entities,
                        reply_to_message_id=reply_to_message_id
                    )
                elif media_info['type'] == 'video':
                    return await bot.send_video(
                        chat_id=chat_id,
                        video=media_info['data'],
                        caption=caption,
                        caption_entities=caption_entities,
                        reply_to_message_id=reply_to_message_id
                    )
                elif media_info['type'] == 'document':
                    return await bot.send_document(
                        chat_id=chat_id,
                        document=media_info['data'],
                        filename=media_info.get('filename'),
                        caption=caption,
                        caption_entities=caption_entities,
                        reply_to_message_id=reply_to_message_id
                    )
                elif media_info['type'] == 'audio':
                    return await bot.send_audio(
                        chat_id=chat_id,
                        audio=media_info['data'],
                        caption=caption,
                        caption_entities=caption_entities,
                        reply_to_message_id=reply_to_message_id
                    )
                elif media_info['type'] == 'voice':
                    return await bot.send_voice(
                        chat_id=chat_id,
                        voice=media_info['data'],
                        caption=caption,
                        caption_entities=caption_entities,
                        reply_to_message_id=reply_to_message_id
                    )
                elif media_info['type'] == 'animation':
                    return await bot.send_animation(
                        chat_id=chat_id,
                        animation=media_info['data'],
                        caption=caption,
                        caption_entities=caption_entities,
                        reply_to_message_id=reply_to_message_id
                    )
                elif media_info['type'] == 'video_note':
                    return await bot.send_video_note(
                        chat_id=chat_id,
                        video_note=media_info['data'],
                        reply_to_message_id=reply_to_message_id
                    )
            else:
                # Send text message with enhanced formatting support
                if content:
                    return await bot.send_message(
                        chat_id=chat_id,
                        text=content,
                        entities=converted_entities,
                        disable_web_page_preview=False,  # Enable webpage previews
                        reply_to_message_id=reply_to_message_id
                    )
            
            return None
            
        except Forbidden as e:
            logger.error(f"Bot forbidden in chat {chat_id}: {e}")
            return None
        except BadRequest as e:
            logger.warning(f"Bad request sending message, trying fallback: {e}")
            # Fallback: send without entities if entity parsing fails
            try:
                if media_info:
                    caption = content[:1024] if content else None
                    if media_info['type'] == 'photo':
                        return await bot.send_photo(chat_id=chat_id, photo=media_info['data'], caption=caption, reply_to_message_id=reply_to_message_id)
                    elif media_info['type'] == 'document':
                        return await bot.send_document(chat_id=chat_id, document=media_info['data'], caption=caption, reply_to_message_id=reply_to_message_id)
                else:
                    return await bot.send_message(chat_id=chat_id, text=content, reply_to_message_id=reply_to_message_id, disable_web_page_preview=False)
            except Exception as fallback_error:
                logger.error(f"Fallback send also failed: {fallback_error}")
                return None
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return None

    def _validate_and_convert_entities(self, text: str, entities: List) -> List:
        """Validate entities against text and convert them"""
        if not text or not entities:
            return []
        
        text_length = len(text.encode('utf-16-le')) // 2  # UTF-16 length for Telegram
        converted_entities = self._convert_entities_for_telegram(entities)
        
        # Filter out entities that exceed text bounds
        valid_entities = []
        for entity in converted_entities:
            if hasattr(entity, 'offset') and hasattr(entity, 'length'):
                if entity.offset + entity.length <= text_length:
                    valid_entities.append(entity)
                else:
                    logger.warning(f"Entity exceeds text bounds: offset={entity.offset}, length={entity.length}, text_length={text_length}")
        
        return valid_entities
    
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
        """Determine media type with enhanced detection"""
        try:
            if isinstance(media, MessageMediaPhoto):
                return "photo"
            elif isinstance(media, MessageMediaDocument):
                document = media.document
                
                # Check MIME type first
                if hasattr(document, 'mime_type') and document.mime_type:
                    mime_type = document.mime_type.lower()
                    
                    # Image types
                    if mime_type.startswith('image/'):
                        if 'gif' in mime_type:
                            return "animation"
                        return "photo"
                    
                    # Video types
                    elif mime_type.startswith('video/'):
                        return "video"
                    
                    # Audio types
                    elif mime_type.startswith('audio/'):
                        # Check if it's a voice message
                        if hasattr(document, 'attributes'):
                            for attr in document.attributes:
                                if 'DocumentAttributeAudio' in str(type(attr)):
                                    if getattr(attr, 'voice', False):
                                        return "voice"
                        return "audio"
                
                # Check document attributes for more specific type detection
                if hasattr(document, 'attributes'):
                    for attr in document.attributes:
                        attr_type = str(type(attr))
                        
                        if 'DocumentAttributeAnimated' in attr_type:
                            return "animation"
                        elif 'DocumentAttributeVideo' in attr_type:
                            if getattr(attr, 'round_message', False):
                                return "video_note"
                            return "video"
                        elif 'DocumentAttributeAudio' in attr_type:
                            if getattr(attr, 'voice', False):
                                return "voice"
                            return "audio"
                        elif 'DocumentAttributeSticker' in attr_type:
                            return "sticker"
                
                return "document"
            
            return "unknown"
            
        except Exception as e:
            logger.error(f"Error determining media type: {e}")
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
    
    def _convert_entities_for_telegram(self, entities: List) -> List:
        """Convert Telethon entities to python-telegram-bot format with validation"""
        try:
            from telegram import MessageEntity
            
            if not entities:
                return []
            
            converted_entities = []
            
            for entity in entities:
                try:
                    entity_type = getattr(entity, '__class__', {}).get('__name__', str(type(entity)))
                    offset = getattr(entity, 'offset', 0)
                    length = getattr(entity, 'length', 0)
                    
                    # Validate entity bounds
                    if offset < 0 or length <= 0:
                        continue
                    
                    # Map Telethon entity types to Telegram entity types
                    if 'Bold' in entity_type:
                        converted_entities.append(MessageEntity(MessageEntity.BOLD, offset, length))
                    elif 'Italic' in entity_type:
                        converted_entities.append(MessageEntity(MessageEntity.ITALIC, offset, length))
                    elif 'Code' in entity_type:
                        converted_entities.append(MessageEntity(MessageEntity.CODE, offset, length))
                    elif 'Pre' in entity_type:
                        language = getattr(entity, 'language', None)
                        converted_entities.append(MessageEntity(MessageEntity.PRE, offset, length, language=language))
                    elif 'Strike' in entity_type or 'Strikethrough' in entity_type:
                        converted_entities.append(MessageEntity(MessageEntity.STRIKETHROUGH, offset, length))
                    elif 'Underline' in entity_type:
                        converted_entities.append(MessageEntity(MessageEntity.UNDERLINE, offset, length))
                    elif 'Spoiler' in entity_type:
                        converted_entities.append(MessageEntity(MessageEntity.SPOILER, offset, length))
                    elif 'Url' in entity_type:
                        converted_entities.append(MessageEntity(MessageEntity.URL, offset, length))
                    elif 'TextUrl' in entity_type:
                        url = getattr(entity, 'url', '')
                        if url:
                            converted_entities.append(MessageEntity(MessageEntity.TEXT_LINK, offset, length, url=url))
                    elif 'Mention' in entity_type:
                        converted_entities.append(MessageEntity(MessageEntity.MENTION, offset, length))
                    elif 'MentionName' in entity_type:
                        user_id = getattr(entity, 'user_id', None)
                        if user_id:
                            converted_entities.append(MessageEntity(MessageEntity.TEXT_MENTION, offset, length, user=user_id))
                    elif 'CustomEmoji' in entity_type:
                        custom_emoji_id = getattr(entity, 'document_id', '')
                        if custom_emoji_id:
                            converted_entities.append(MessageEntity(MessageEntity.CUSTOM_EMOJI, offset, length, custom_emoji_id=str(custom_emoji_id)))
                    elif 'Hashtag' in entity_type:
                        converted_entities.append(MessageEntity(MessageEntity.HASHTAG, offset, length))
                    elif 'Cashtag' in entity_type:
                        converted_entities.append(MessageEntity(MessageEntity.CASHTAG, offset, length))
                    elif 'BotCommand' in entity_type:
                        converted_entities.append(MessageEntity(MessageEntity.BOT_COMMAND, offset, length))
                    elif 'Email' in entity_type:
                        converted_entities.append(MessageEntity(MessageEntity.EMAIL, offset, length))
                    elif 'Phone' in entity_type:
                        converted_entities.append(MessageEntity(MessageEntity.PHONE_NUMBER, offset, length))
                        
                except Exception as entity_error:
                    logger.warning(f"Failed to convert entity {entity_type}: {entity_error}")
                    continue
            
            return converted_entities
            
        except Exception as e:
            logger.error(f"Error converting entities: {e}")
            return []
    
    def get_stats(self) -> Dict[str, int]:
        """Get processing statistics"""
        return self.stats.copy()
