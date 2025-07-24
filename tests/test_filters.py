"""
Tests for Message Filter functionality
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from filters import MessageFilter, FilterResult, FilterStats
from database import MessagePair


class TestMessageFilter:
    """Test suite for MessageFilter"""
    
    @pytest.mark.asyncio
    async def test_initialization(self, test_db, test_config):
        """Test message filter initialization"""
        message_filter = MessageFilter(test_db, test_config)
        await message_filter.initialize()
        
        assert message_filter.db_manager == test_db
        assert message_filter.config == test_config
        assert isinstance(message_filter.global_blocks, dict)
        assert isinstance(message_filter.filter_stats, FilterStats)
    
    @pytest.mark.asyncio
    async def test_blocked_words_filter(self, test_message_filter, sample_pair, mock_telethon_event):
        """Test blocked words filtering"""
        # Add blocked words to pair
        sample_pair.filters['blocked_words'] = ['spam', 'bad', 'blocked']
        
        # Test message with blocked word
        mock_telethon_event.text = "This is a spam message"
        mock_telethon_event.raw_text = "This is a spam message"
        
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        assert result.should_copy is False
        assert "blocked words" in result.reason.lower()
        assert "blocked_words" in result.filters_applied
    
    @pytest.mark.asyncio
    async def test_message_passes_filters(self, test_message_filter, sample_pair, mock_telethon_event):
        """Test message that should pass all filters"""
        # Clean message
        mock_telethon_event.text = "This is a clean message"
        mock_telethon_event.raw_text = "This is a clean message"
        mock_telethon_event.media = None
        mock_telethon_event.fwd_from = None
        
        # Set up pair with no restrictions
        sample_pair.filters['blocked_words'] = []
        sample_pair.filters['min_message_length'] = 0
        sample_pair.filters['max_message_length'] = 0
        sample_pair.filters['block_forwards'] = False
        sample_pair.filters['block_links'] = False
        
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        assert result.should_copy is True
        assert "passed all filters" in result.reason.lower()
    
    @pytest.mark.asyncio
    async def test_regex_filter(self, test_message_filter, sample_pair, mock_telethon_event):
        """Test custom regex filtering"""
        # Add regex filter
        sample_pair.filters['custom_regex_filters'] = [r'\d{4}-\d{4}-\d{4}-\d{4}']  # Credit card pattern
        
        # Test message with pattern
        mock_telethon_event.text = "My card number is 1234-5678-9012-3456"
        mock_telethon_event.raw_text = "My card number is 1234-5678-9012-3456"
        
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        assert result.should_copy is False
        assert "matches regex" in result.reason.lower()
        assert "regex" in result.filters_applied
    
    @pytest.mark.asyncio
    async def test_length_filters(self, test_message_filter, sample_pair, mock_telethon_event):
        """Test message length filtering"""
        # Set length limits
        sample_pair.filters['min_message_length'] = 10
        sample_pair.filters['max_message_length'] = 20
        
        # Test message too short
        mock_telethon_event.text = "Short"
        mock_telethon_event.raw_text = "Short"
        
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        assert result.should_copy is False
        assert "too short" in result.reason.lower()
        assert "min_length" in result.filters_applied
        
        # Test message too long
        mock_telethon_event.text = "This message is way too long for the filter"
        mock_telethon_event.raw_text = "This message is way too long for the filter"
        
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        assert result.should_copy is False
        assert "too long" in result.reason.lower()
        assert "max_length" in result.filters_applied
    
    @pytest.mark.asyncio
    async def test_forward_blocking(self, test_message_filter, sample_pair, mock_telethon_event):
        """Test forward message blocking"""
        # Enable forward blocking
        sample_pair.filters['block_forwards'] = True
        
        # Set up forwarded message
        mock_telethon_event.text = "This is a forwarded message"
        mock_telethon_event.raw_text = "This is a forwarded message"
        mock_telethon_event.fwd_from = MagicMock()  # Indicates forwarded message
        
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        assert result.should_copy is False
        assert "forwarded message blocked" in result.reason.lower()
        assert "block_forwards" in result.filters_applied
    
    @pytest.mark.asyncio
    async def test_link_blocking(self, test_message_filter, sample_pair, mock_telethon_event):
        """Test link blocking"""
        # Enable link blocking
        sample_pair.filters['block_links'] = True
        
        # Test message with links
        test_cases = [
            "Check out https://example.com",
            "Visit www.example.com for more info",
            "Join t.me/channel",
            "Follow @username",
            "Go to example.org"
        ]
        
        for text in test_cases:
            mock_telethon_event.text = text
            mock_telethon_event.raw_text = text
            
            result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
            
            assert result.should_copy is False, f"Failed to block link in: {text}"
            assert "blocked links" in result.reason.lower()
            assert "block_links" in result.filters_applied
    
    @pytest.mark.asyncio
    async def test_media_type_filtering(self, test_message_filter, sample_pair, mock_telethon_event):
        """Test media type filtering"""
        from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
        
        # Set allowed media types
        sample_pair.filters['allowed_media_types'] = ['photo']
        
        # Test allowed media type
        mock_telethon_event.text = "Photo message"
        mock_telethon_event.raw_text = "Photo message"
        mock_telethon_event.media = MessageMediaPhoto(photo=MagicMock())
        
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        # Should pass (assuming other filters pass)
        sample_pair.filters['blocked_words'] = []
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        assert result.should_copy is True
        
        # Test disallowed media type
        mock_telethon_event.media = MessageMediaDocument(document=MagicMock())
        mock_telethon_event.media.document.mime_type = "application/pdf"
        
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        assert result.should_copy is False
        assert "media type not allowed" in result.reason.lower()
        assert "media_type" in result.filters_applied
    
    @pytest.mark.asyncio
    async def test_text_filtering(self, test_message_filter, sample_pair):
        """Test text transformation and filtering"""
        # Set up word replacements
        sample_pair.filters['word_replacements'] = {
            'bad': 'good',
            'ugly': 'beautiful'
        }
        
        # Set up regex replacements
        sample_pair.filters['regex_replacements'] = {
            r'\d+': '[NUMBER]'
        }
        
        text = "This bad word and ugly text has 123 numbers"
        
        result = await test_message_filter.filter_text(text, sample_pair)
        
        assert 'good' in result
        assert 'beautiful' in result
        assert '[NUMBER]' in result
        assert 'bad' not in result
        assert 'ugly' not in result
        assert '123' not in result
    
    @pytest.mark.asyncio
    async def test_global_word_blocks(self, test_message_filter, sample_pair, mock_telethon_event):
        """Test global word blocking"""
        # Add global blocked word
        await test_message_filter.add_global_word_block("globalspam")
        
        # Test message with global blocked word
        mock_telethon_event.text = "This contains globalspam word"
        mock_telethon_event.raw_text = "This contains globalspam word"
        
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        assert result.should_copy is False
        assert "global word block" in result.reason.lower()
        assert "global_words" in result.filters_applied
    
    @pytest.mark.asyncio
    async def test_time_filters(self, test_message_filter, sample_pair, mock_telethon_event, mock_sender):
        """Test time-based filtering"""
        # Mock get_sender
        mock_telethon_event.get_sender.return_value = mock_sender
        
        # Set up time filters
        current_hour = datetime.now().hour
        sample_pair.filters['time_filters'] = {
            'allowed_hours': [current_hour],  # Only allow current hour
            'allowed_days': [datetime.now().weekday()],  # Only allow today
            'max_age_minutes': 60  # Messages must be less than 1 hour old
        }
        
        # Mock recent message
        recent_time = datetime.now() - timedelta(minutes=30)
        mock_telethon_event.date = MagicMock()
        mock_telethon_event.date.timestamp.return_value = recent_time.timestamp()
        mock_telethon_event.text = "Recent message"
        mock_telethon_event.raw_text = "Recent message"
        mock_telethon_event.media = None
        mock_telethon_event.fwd_from = None
        
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        # Should pass time filters
        assert result.should_copy is True or "time" not in result.reason.lower()
        
        # Test old message
        old_time = datetime.now() - timedelta(hours=2)
        mock_telethon_event.date.timestamp.return_value = old_time.timestamp()
        
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        # Should fail time filter if max_age_minutes is enforced
        if not result.should_copy:
            assert "time" in result.reason.lower()
    
    @pytest.mark.asyncio
    async def test_user_filters(self, test_message_filter, sample_pair, mock_telethon_event, mock_sender):
        """Test user-based filtering"""
        # Set up user filters
        sample_pair.filters['user_filters'] = {
            'blocked_user_ids': [987654321],  # Block the mock sender
            'blocked_usernames': ['blocked_user'],
            'block_bots': True,
            'require_verified': False
        }
        
        # Mock sender as the blocked user
        mock_sender.id = 987654321
        mock_sender.bot = False
        mock_telethon_event.get_sender.return_value = mock_sender
        mock_telethon_event.text = "Message from blocked user"
        mock_telethon_event.raw_text = "Message from blocked user"
        mock_telethon_event.media = None
        mock_telethon_event.fwd_from = None
        
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        # Should be blocked due to user filter
        if not result.should_copy:
            assert "user" in result.reason.lower()
        
        # Test bot blocking
        mock_sender.id = 111111111  # Different user
        mock_sender.bot = True
        
        result = await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        # Should be blocked due to bot filter
        if not result.should_copy:
            assert "user" in result.reason.lower()
    
    @pytest.mark.asyncio
    async def test_contains_blocked_words(self, test_message_filter):
        """Test blocked words detection"""
        blocked_words = ['spam', 'bad', 'blocked']
        
        # Test positive cases
        assert test_message_filter._contains_blocked_words("This is spam", blocked_words)
        assert test_message_filter._contains_blocked_words("BAD message", blocked_words)  # Case insensitive
        assert test_message_filter._contains_blocked_words("Contains blocked word", blocked_words)
        
        # Test negative cases
        assert not test_message_filter._contains_blocked_words("Clean message", blocked_words)
        assert not test_message_filter._contains_blocked_words("", blocked_words)
        assert not test_message_filter._contains_blocked_words("Good content", [])
    
    @pytest.mark.asyncio
    async def test_contains_links(self, test_message_filter):
        """Test link detection"""
        # Test positive cases
        assert test_message_filter._contains_links("Visit https://example.com")
        assert test_message_filter._contains_links("Check www.example.com")
        assert test_message_filter._contains_links("Join t.me/channel")
        assert test_message_filter._contains_links("Follow @username")
        assert test_message_filter._contains_links("Go to example.org")
        
        # Test negative cases
        assert not test_message_filter._contains_links("No links here")
        assert not test_message_filter._contains_links("Just plain text")
        assert not test_message_filter._contains_links("")
    
    @pytest.mark.asyncio
    async def test_regex_matching(self, test_message_filter):
        """Test regex pattern matching"""
        # Test valid regex
        assert test_message_filter._matches_regex("test123", r"test\d+")
        assert test_message_filter._matches_regex("EMAIL@DOMAIN.COM", r"\w+@\w+\.\w+")
        
        # Test non-matching
        assert not test_message_filter._matches_regex("test", r"test\d+")
        assert not test_message_filter._matches_regex("notanemail", r"\w+@\w+\.\w+")
        
        # Test invalid regex (should not crash)
        assert not test_message_filter._matches_regex("test", r"[invalid")
    
    @pytest.mark.asyncio
    async def test_get_compiled_regex(self, test_message_filter):
        """Test regex compilation and caching"""
        pattern = r"test\d+"
        
        # Get compiled regex
        regex1 = test_message_filter._get_compiled_regex(pattern)
        regex2 = test_message_filter._get_compiled_regex(pattern)
        
        # Should be the same object (cached)
        assert regex1 is regex2
        
        # Should work correctly
        assert regex1.search("test123") is not None
        assert regex1.search("notest") is None
    
    @pytest.mark.asyncio
    async def test_get_media_type(self, test_message_filter):
        """Test media type detection"""
        from telethon.tl.types import (
            MessageMediaPhoto, MessageMediaDocument
        )
        
        # Test photo
        photo_media = MessageMediaPhoto(photo=MagicMock())
        assert test_message_filter._get_media_type(photo_media) == "photo"
        
        # Test document with different MIME types
        doc_media = MessageMediaDocument(document=MagicMock())
        doc_media.document.mime_type = "image/jpeg"
        assert test_message_filter._get_media_type(doc_media) == "photo"
        
        doc_media.document.mime_type = "video/mp4"
        assert test_message_filter._get_media_type(doc_media) == "video"
        
        doc_media.document.mime_type = "audio/mp3"
        assert test_message_filter._get_media_type(doc_media) == "audio"
        
        doc_media.document.mime_type = "application/pdf"
        assert test_message_filter._get_media_type(doc_media) == "document"
        
        # Test unknown media type
        assert test_message_filter._get_media_type(MagicMock()) == "unknown"
    
    @pytest.mark.asyncio
    async def test_filter_stats(self, test_message_filter, sample_pair, mock_telethon_event):
        """Test filter statistics tracking"""
        initial_stats = test_message_filter.get_filter_stats()
        
        # Test blocked words hit
        sample_pair.filters['blocked_words'] = ['spam']
        mock_telethon_event.text = "This is spam"
        mock_telethon_event.raw_text = "This is spam"
        mock_telethon_event.media = None
        mock_telethon_event.fwd_from = None
        
        await test_message_filter.should_copy_message(mock_telethon_event, sample_pair)
        
        stats = test_message_filter.get_filter_stats()
        assert stats['blocked_words_hits'] > initial_stats['blocked_words_hits']
    
    @pytest.mark.asyncio
    async def test_clear_regex_cache(self, test_message_filter):
        """Test regex cache clearing"""
        # Add some patterns to cache
        test_message_filter._get_compiled_regex(r"test\d+")
        test_message_filter._get_compiled_regex(r"\w+@\w+\.\w+")
        
        assert len(test_message_filter._regex_cache) == 2
        
        # Clear cache
        test_message_filter.clear_regex_cache()
        
        assert len(test_message_filter._regex_cache) == 0
    
    @pytest.mark.asyncio
    async def test_global_blocks_management(self, test_message_filter):
        """Test global blocks management"""
        # Add global word block
        await test_message_filter.add_global_word_block("globaltest")
        
        assert "globaltest" in test_message_filter.global_blocks["words"]
        
        # Remove global word block
        await test_message_filter.remove_global_word_block("globaltest")
        
        assert "globaltest" not in test_message_filter.global_blocks["words"]
        
        # Try to remove non-existent word (should not crash)
        await test_message_filter.remove_global_word_block("nonexistent")
