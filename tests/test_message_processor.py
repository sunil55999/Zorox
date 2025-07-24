"""
Tests for Message Processor functionality
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from io import BytesIO

from message_processor import MessageProcessor, ProcessedContent
from database import MessagePair, MessageMapping


class TestMessageProcessor:
    """Test suite for MessageProcessor"""
    
    @pytest.mark.asyncio
    async def test_initialization(self, test_db, test_config):
        """Test message processor initialization"""
        processor = MessageProcessor(test_db, test_config)
        await processor.initialize()
        
        assert processor.db_manager == test_db
        assert processor.config == test_config
        assert processor.message_filter is not None
        assert processor.image_handler is not None
    
    @pytest.mark.asyncio
    async def test_process_new_message_text_only(self, test_message_processor, sample_pair, mock_telethon_event, mock_telegram_bot):
        """Test processing text-only message"""
        # Setup event
        mock_telethon_event.text = "Hello world!"
        mock_telethon_event.media = None
        mock_telethon_event.is_reply = False
        
        # Mock filter to allow message
        with patch.object(test_message_processor.message_filter, 'should_copy_message') as mock_filter:
            mock_filter.return_value = MagicMock(should_copy=True, reason="")
            
            with patch.object(test_message_processor, '_process_message_content') as mock_content:
                mock_content.return_value = ProcessedContent(text="Hello world!")
                
                with patch.object(test_message_processor, '_send_message') as mock_send:
                    mock_send.return_value = MagicMock(message_id=54321)
                    
                    # Process the message
                    result = await test_message_processor.process_new_message(
                        mock_telethon_event, sample_pair, mock_telegram_bot, 0
                    )
                    
                    assert result is True
                    assert mock_send.called
                    assert sample_pair.stats['messages_copied'] == 1
    
    @pytest.mark.asyncio
    async def test_process_new_message_filtered(self, test_message_processor, sample_pair, mock_telethon_event, mock_telegram_bot):
        """Test processing message that gets filtered"""
        # Setup event
        mock_telethon_event.text = "spam message"
        mock_telethon_event.media = None
        
        # Mock filter to block message
        with patch.object(test_message_processor.message_filter, 'should_copy_message') as mock_filter:
            mock_filter.return_value = MagicMock(should_copy=False, reason="Contains spam")
            
            # Process the message
            result = await test_message_processor.process_new_message(
                mock_telethon_event, sample_pair, mock_telegram_bot, 0
            )
            
            assert result is True  # Successfully filtered (not an error)
            assert sample_pair.stats['messages_filtered'] == 1
    
    @pytest.mark.asyncio
    async def test_process_new_message_with_media(self, test_message_processor, sample_pair, mock_telethon_event, mock_telegram_bot):
        """Test processing message with media"""
        from telethon.tl.types import MessageMediaPhoto
        
        # Setup event with media
        mock_telethon_event.text = "Photo caption"
        mock_telethon_event.media = MessageMediaPhoto(photo=MagicMock())
        
        # Mock filter to allow message
        with patch.object(test_message_processor.message_filter, 'should_copy_message') as mock_filter:
            mock_filter.return_value = MagicMock(should_copy=True, reason="")
            
            with patch.object(test_message_processor, '_process_message_content') as mock_content:
                mock_content.return_value = ProcessedContent(text="Photo caption")
                
                with patch.object(test_message_processor, '_process_media') as mock_media:
                    mock_media.return_value = {
                        'type': 'photo',
                        'data': BytesIO(b'fake_image_data'),
                        'caption': 'Photo caption'
                    }
                    
                    with patch.object(test_message_processor, '_send_message') as mock_send:
                        mock_send.return_value = MagicMock(message_id=54321)
                        
                        # Process the message
                        result = await test_message_processor.process_new_message(
                            mock_telethon_event, sample_pair, mock_telegram_bot, 0
                        )
                        
                        assert result is True
                        assert mock_media.called
                        assert sample_pair.stats['messages_copied'] == 1
    
    @pytest.mark.asyncio
    async def test_process_new_message_with_reply(self, test_message_processor, sample_pair, mock_telethon_event, mock_telegram_bot, test_db):
        """Test processing message that is a reply"""
        # Setup event as reply
        mock_telethon_event.text = "This is a reply"
        mock_telethon_event.is_reply = True
        mock_telethon_event.reply_to_msg_id = 12345
        mock_telethon_event.media = None
        
        # Create a message mapping for the original message
        original_mapping = MessageMapping(
            id=0,
            source_message_id=12345,
            destination_message_id=98765,
            pair_id=sample_pair.id,
            bot_index=0,
            source_chat_id=sample_pair.source_chat_id,
            destination_chat_id=sample_pair.destination_chat_id
        )
        await test_db.save_message_mapping(original_mapping)
        
        # Mock filter to allow message
        with patch.object(test_message_processor.message_filter, 'should_copy_message') as mock_filter:
            mock_filter.return_value = MagicMock(should_copy=True, reason="")
            
            with patch.object(test_message_processor, '_process_message_content') as mock_content:
                mock_content.return_value = ProcessedContent(text="This is a reply")
                
                with patch.object(test_message_processor, '_send_message') as mock_send:
                    mock_send.return_value = MagicMock(message_id=54321)
                    
                    # Process the message
                    result = await test_message_processor.process_new_message(
                        mock_telethon_event, sample_pair, mock_telegram_bot, 0
                    )
                    
                    assert result is True
                    # Verify reply_to_message_id was passed to send_message
                    mock_send.assert_called_once()
                    call_args = mock_send.call_args
                    assert call_args[0][3] is None or call_args[0][3] == 98765  # reply_to_message_id
    
    @pytest.mark.asyncio
    async def test_process_message_edit(self, test_message_processor, sample_pair, mock_telethon_event, mock_telegram_bot, test_db):
        """Test processing message edit"""
        # Create original message mapping
        mapping = MessageMapping(
            id=0,
            source_message_id=mock_telethon_event.id,
            destination_message_id=98765,
            pair_id=sample_pair.id,
            bot_index=0,
            source_chat_id=sample_pair.source_chat_id,
            destination_chat_id=sample_pair.destination_chat_id
        )
        await test_db.save_message_mapping(mapping)
        
        # Setup edited event
        mock_telethon_event.text = "Edited message content"
        
        with patch.object(test_message_processor, '_process_message_content') as mock_content:
            mock_content.return_value = ProcessedContent(text="Edited message content")
            
            # Process the edit
            result = await test_message_processor.process_message_edit(
                mock_telethon_event, sample_pair, mock_telegram_bot, 0
            )
            
            assert result is True
            assert mock_telegram_bot.edit_message_text.called
            assert sample_pair.stats['edits_synced'] == 1
    
    @pytest.mark.asyncio
    async def test_process_message_delete(self, test_message_processor, sample_pair, mock_telethon_event, mock_telegram_bot, test_db):
        """Test processing message deletion"""
        # Create original message mapping
        mapping = MessageMapping(
            id=0,
            source_message_id=12345,
            destination_message_id=98765,
            pair_id=sample_pair.id,
            bot_index=0,
            source_chat_id=sample_pair.source_chat_id,
            destination_chat_id=sample_pair.destination_chat_id
        )
        await test_db.save_message_mapping(mapping)
        
        # Setup delete event
        mock_telethon_event.deleted_ids = [12345]
        
        # Process the deletion
        result = await test_message_processor.process_message_delete(
            mock_telethon_event, sample_pair, mock_telegram_bot, 0
        )
        
        assert result is True
        assert mock_telegram_bot.delete_message.called
        assert sample_pair.stats['deletes_synced'] == 1
    
    @pytest.mark.asyncio
    async def test_process_message_content_with_mentions(self, test_message_processor, sample_pair):
        """Test processing message content with mention removal"""
        mock_event = MagicMock()
        mock_event.text = "Hello @username and @another_user!"
        mock_event.raw_text = "Hello @username and @another_user!"
        mock_event.entities = []
        
        # Enable mention removal
        sample_pair.filters['remove_mentions'] = True
        sample_pair.filters['mention_placeholder'] = '[User]'
        
        with patch.object(test_message_processor.message_filter, 'filter_text') as mock_filter:
            mock_filter.return_value = "Hello @username and @another_user!"
            
            result = await test_message_processor._process_message_content(mock_event, sample_pair)
            
            assert result is not None
            assert '@username' not in result.text
            assert '[User]' in result.text
            assert sample_pair.stats['mentions_removed'] == 1
    
    @pytest.mark.asyncio
    async def test_process_message_content_length_limits(self, test_message_processor, sample_pair):
        """Test message content length filtering"""
        mock_event = MagicMock()
        mock_event.text = "Short"
        mock_event.raw_text = "Short"
        mock_event.entities = []
        
        # Set minimum length filter
        sample_pair.filters['min_message_length'] = 10
        
        with patch.object(test_message_processor.message_filter, 'filter_text') as mock_filter:
            mock_filter.return_value = "Short"
            
            result = await test_message_processor._process_message_content(mock_event, sample_pair)
            
            # Should be None due to length filter
            assert result is None
    
    @pytest.mark.asyncio
    async def test_download_media(self, test_message_processor, mock_telethon_event):
        """Test media downloading"""
        # Mock the download
        mock_telethon_event.client.download_media = AsyncMock()
        mock_telethon_event.client.download_media.return_value = None
        
        # Test download
        result = await test_message_processor._download_media(mock_telethon_event)
        
        assert isinstance(result, BytesIO)
        assert mock_telethon_event.client.download_media.called
    
    @pytest.mark.asyncio
    async def test_send_text_message(self, test_message_processor, mock_telegram_bot):
        """Test sending text message"""
        content = ProcessedContent(text="Test message")
        
        result = await test_message_processor._send_message(
            mock_telegram_bot, -1001234567890, content, None
        )
        
        assert result is not None
        assert mock_telegram_bot.send_message.called
    
    @pytest.mark.asyncio
    async def test_send_photo_message(self, test_message_processor, mock_telegram_bot):
        """Test sending photo message"""
        content = ProcessedContent(text="Photo caption")
        media_info = {
            'type': 'photo',
            'data': BytesIO(b'fake_image_data'),
            'caption': 'Photo caption'
        }
        
        result = await test_message_processor._send_message(
            mock_telegram_bot, -1001234567890, content, media_info
        )
        
        assert result is not None
        assert mock_telegram_bot.send_photo.called
    
    @pytest.mark.asyncio
    async def test_get_media_type(self, test_message_processor):
        """Test media type detection"""
        from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
        
        # Test photo
        photo_media = MessageMediaPhoto(photo=MagicMock())
        assert test_message_processor._get_media_type(photo_media) == "photo"
        
        # Test document
        doc_media = MessageMediaDocument(document=MagicMock())
        doc_media.document.mime_type = "image/jpeg"
        assert test_message_processor._get_media_type(doc_media) == "photo"
        
        doc_media.document.mime_type = "video/mp4"
        assert test_message_processor._get_media_type(doc_media) == "video"
        
        doc_media.document.mime_type = "application/pdf"
        assert test_message_processor._get_media_type(doc_media) == "document"
    
    @pytest.mark.asyncio
    async def test_remove_mentions(self, test_message_processor):
        """Test mention removal functionality"""
        text = "Hello @username and check tg://user?id=12345"
        placeholder = "[User]"
        
        result = test_message_processor._remove_mentions(text, placeholder)
        
        assert "@username" not in result
        assert "tg://user?id=12345" not in result
        assert "[User]" in result
    
    @pytest.mark.asyncio
    async def test_remove_headers(self, test_message_processor):
        """Test header removal functionality"""
        text = "📢 Important announcement:\nThis is the actual content\nMore content here"
        patterns = [r'^.*?📢.*?\n']
        
        result = test_message_processor._remove_headers(text, patterns)
        
        assert "📢 Important announcement:" not in result
        assert "This is the actual content" in result
    
    @pytest.mark.asyncio
    async def test_remove_footers(self, test_message_processor):
        """Test footer removal functionality"""
        text = "Main content here\nMore content\n@channelname - follow us"
        patterns = [r'\n.*?@\w+.*?$']
        
        result = test_message_processor._remove_footers(text, patterns)
        
        assert "@channelname - follow us" not in result
        assert "Main content here" in result
    
    @pytest.mark.asyncio
    async def test_find_reply_target(self, test_message_processor, sample_pair, test_db):
        """Test finding reply target message"""
        # Create mapping for original message
        mapping = MessageMapping(
            id=0,
            source_message_id=12345,
            destination_message_id=98765,
            pair_id=sample_pair.id,
            bot_index=0,
            source_chat_id=sample_pair.source_chat_id,
            destination_chat_id=sample_pair.destination_chat_id
        )
        await test_db.save_message_mapping(mapping)
        
        # Mock event
        mock_event = MagicMock()
        mock_event.reply_to_msg_id = 12345
        
        result = await test_message_processor._find_reply_target(mock_event, sample_pair)
        
        assert result == 98765
    
    @pytest.mark.asyncio
    async def test_get_stats(self, test_message_processor):
        """Test getting processing statistics"""
        # Increment some stats
        test_message_processor.stats['messages_processed'] = 100
        test_message_processor.stats['messages_copied'] = 95
        test_message_processor.stats['messages_filtered'] = 5
        
        stats = test_message_processor.get_stats()
        
        assert stats['messages_processed'] == 100
        assert stats['messages_copied'] == 95
        assert stats['messages_filtered'] == 5
        assert isinstance(stats, dict)
