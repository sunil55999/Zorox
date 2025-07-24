"""
Tests for Database Manager functionality
"""

import pytest
import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta

from database import DatabaseManager, MessagePair, MessageMapping


class TestDatabaseManager:
    """Test suite for DatabaseManager"""
    
    @pytest.mark.asyncio
    async def test_initialization(self, temp_dir):
        """Test database initialization"""
        db_path = os.path.join(temp_dir, "test_init.db")
        db_manager = DatabaseManager(db_path)
        
        await db_manager.initialize()
        
        # Check that database file was created
        assert os.path.exists(db_path)
        
        # Check that backup was created
        assert os.path.exists(f"{db_path}.backup")
        
        await db_manager.close()
    
    @pytest.mark.asyncio
    async def test_create_pair(self, test_db):
        """Test creating message pairs"""
        source_id = -1001234567890
        dest_id = -1009876543210
        name = "Test Pair"
        bot_index = 0
        
        pair_id = await test_db.create_pair(source_id, dest_id, name, bot_index)
        
        assert isinstance(pair_id, int)
        assert pair_id > 0
        
        # Verify pair was created
        pair = await test_db.get_pair(pair_id)
        assert pair is not None
        assert pair.source_chat_id == source_id
        assert pair.destination_chat_id == dest_id
        assert pair.name == name
        assert pair.assigned_bot_index == bot_index
    
    @pytest.mark.asyncio
    async def test_create_duplicate_pair(self, test_db):
        """Test creating duplicate pair should fail"""
        source_id = -1001234567890
        dest_id = -1009876543210
        name = "Test Pair"
        
        # Create first pair
        pair_id1 = await test_db.create_pair(source_id, dest_id, name)
        assert pair_id1 > 0
        
        # Try to create duplicate
        with pytest.raises(ValueError, match="Pair already exists"):
            await test_db.create_pair(source_id, dest_id, "Duplicate Pair")
    
    @pytest.mark.asyncio
    async def test_get_pair(self, test_db, sample_pair):
        """Test retrieving pair by ID"""
        retrieved_pair = await test_db.get_pair(sample_pair.id)
        
        assert retrieved_pair is not None
        assert retrieved_pair.id == sample_pair.id
        assert retrieved_pair.name == sample_pair.name
        assert retrieved_pair.source_chat_id == sample_pair.source_chat_id
        assert retrieved_pair.destination_chat_id == sample_pair.destination_chat_id
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_pair(self, test_db):
        """Test retrieving non-existent pair"""
        pair = await test_db.get_pair(99999)
        assert pair is None
    
    @pytest.mark.asyncio
    async def test_get_all_pairs(self, test_db):
        """Test retrieving all pairs"""
        # Create multiple pairs
        await test_db.create_pair(-1001111111111, -1002222222222, "Pair 1")
        await test_db.create_pair(-1003333333333, -1004444444444, "Pair 2")
        await test_db.create_pair(-1005555555555, -1006666666666, "Pair 3")
        
        pairs = await test_db.get_all_pairs()
        
        assert len(pairs) >= 3
        assert all(isinstance(pair, MessagePair) for pair in pairs)
        
        # Check that pairs are ordered by ID
        pair_ids = [pair.id for pair in pairs]
        assert pair_ids == sorted(pair_ids)
    
    @pytest.mark.asyncio
    async def test_update_pair(self, test_db, sample_pair):
        """Test updating pair"""
        # Modify pair
        sample_pair.name = "Updated Name"
        sample_pair.status = "inactive"
        sample_pair.stats['messages_copied'] = 100
        
        await test_db.update_pair(sample_pair)
        
        # Retrieve and verify
        updated_pair = await test_db.get_pair(sample_pair.id)
        assert updated_pair.name == "Updated Name"
        assert updated_pair.status == "inactive"
        assert updated_pair.stats['messages_copied'] == 100
    
    @pytest.mark.asyncio
    async def test_delete_pair(self, test_db, sample_pair):
        """Test deleting pair"""
        pair_id = sample_pair.id
        
        # Create some message mappings
        mapping = MessageMapping(
            id=0,
            source_message_id=12345,
            destination_message_id=54321,
            pair_id=pair_id,
            bot_index=0,
            source_chat_id=sample_pair.source_chat_id,
            destination_chat_id=sample_pair.destination_chat_id
        )
        await test_db.save_message_mapping(mapping)
        
        # Delete pair
        await test_db.delete_pair(pair_id)
        
        # Verify pair is deleted
        deleted_pair = await test_db.get_pair(pair_id)
        assert deleted_pair is None
        
        # Verify related mappings are deleted (cascade)
        retrieved_mapping = await test_db.get_message_mapping(12345, pair_id)
        assert retrieved_mapping is None
    
    @pytest.mark.asyncio
    async def test_save_message_mapping(self, test_db, sample_pair):
        """Test saving message mapping"""
        mapping = MessageMapping(
            id=0,
            source_message_id=12345,
            destination_message_id=54321,
            pair_id=sample_pair.id,
            bot_index=0,
            source_chat_id=sample_pair.source_chat_id,
            destination_chat_id=sample_pair.destination_chat_id,
            message_type="text",
            has_media=False,
            is_reply=False
        )
        
        await test_db.save_message_mapping(mapping)
        
        # Retrieve and verify
        retrieved = await test_db.get_message_mapping(12345, sample_pair.id)
        assert retrieved is not None
        assert retrieved.source_message_id == 12345
        assert retrieved.destination_message_id == 54321
        assert retrieved.pair_id == sample_pair.id
        assert retrieved.message_type == "text"
        assert retrieved.has_media is False
    
    @pytest.mark.asyncio
    async def test_save_message_mapping_with_reply(self, test_db, sample_pair):
        """Test saving message mapping with reply information"""
        # Create original message mapping
        original_mapping = MessageMapping(
            id=0,
            source_message_id=11111,
            destination_message_id=22222,
            pair_id=sample_pair.id,
            bot_index=0,
            source_chat_id=sample_pair.source_chat_id,
            destination_chat_id=sample_pair.destination_chat_id
        )
        await test_db.save_message_mapping(original_mapping)
        
        # Create reply mapping
        reply_mapping = MessageMapping(
            id=0,
            source_message_id=33333,
            destination_message_id=44444,
            pair_id=sample_pair.id,
            bot_index=0,
            source_chat_id=sample_pair.source_chat_id,
            destination_chat_id=sample_pair.destination_chat_id,
            is_reply=True,
            reply_to_source_id=11111,
            reply_to_dest_id=22222
        )
        
        await test_db.save_message_mapping(reply_mapping)
        
        # Retrieve and verify
        retrieved = await test_db.get_message_mapping(33333, sample_pair.id)
        assert retrieved.is_reply is True
        assert retrieved.reply_to_source_id == 11111
        assert retrieved.reply_to_dest_id == 22222
    
    @pytest.mark.asyncio
    async def test_log_error(self, test_db):
        """Test error logging"""
        await test_db.log_error(
            error_type="test_error",
            error_message="Test error message",
            pair_id=1,
            bot_index=0,
            stack_trace="Stack trace here"
        )
        
        # Verify error was logged
        async with test_db.get_connection() as conn:
            cursor = await conn.execute(
                'SELECT * FROM error_logs WHERE error_type = ?',
                ("test_error",)
            )
            row = await cursor.fetchone()
            
            assert row is not None
            assert row[2] == "Test error message"  # error_message
            assert row[3] == 1  # pair_id
            assert row[4] == 0  # bot_index
            assert row[5] == "Stack trace here"  # stack_trace
    
    @pytest.mark.asyncio
    async def test_settings(self, test_db):
        """Test system settings management"""
        # Set setting
        await test_db.set_setting("test_key", "test_value")
        
        # Get setting
        value = await test_db.get_setting("test_key")
        assert value == "test_value"
        
        # Get non-existent setting with default
        value = await test_db.get_setting("non_existent", "default")
        assert value == "default"
        
        # Update setting
        await test_db.set_setting("test_key", "updated_value")
        value = await test_db.get_setting("test_key")
        assert value == "updated_value"
    
    @pytest.mark.asyncio
    async def test_get_stats(self, test_db, sample_pair):
        """Test getting system statistics"""
        # Create some test data
        for i in range(5):
            mapping = MessageMapping(
                id=0,
                source_message_id=10000 + i,
                destination_message_id=20000 + i,
                pair_id=sample_pair.id,
                bot_index=0,
                source_chat_id=sample_pair.source_chat_id,
                destination_chat_id=sample_pair.destination_chat_id
            )
            await test_db.save_message_mapping(mapping)
        
        # Log some errors
        await test_db.log_error("test_error", "Error 1")
        await test_db.log_error("test_error", "Error 2")
        
        # Get stats
        stats = await test_db.get_stats()
        
        assert 'total_pairs' in stats
        assert 'active_pairs' in stats
        assert 'total_messages' in stats
        assert 'messages_24h' in stats
        assert 'errors_24h' in stats
        assert 'database_size_mb' in stats
        
        assert stats['total_pairs'] >= 1
        assert stats['total_messages'] >= 5
        assert stats['errors_24h'] >= 2
    
    @pytest.mark.asyncio
    async def test_cleanup_old_data(self, test_db, sample_pair):
        """Test cleanup of old data"""
        # Create old message mapping
        old_mapping = MessageMapping(
            id=0,
            source_message_id=99999,
            destination_message_id=88888,
            pair_id=sample_pair.id,
            bot_index=0,
            source_chat_id=sample_pair.source_chat_id,
            destination_chat_id=sample_pair.destination_chat_id
        )
        await test_db.save_message_mapping(old_mapping)
        
        # Manually set old timestamp
        old_date = (datetime.now() - timedelta(days=35)).isoformat()
        async with test_db.get_connection() as conn:
            await conn.execute(
                'UPDATE message_mapping SET created_at = ? WHERE source_message_id = ?',
                (old_date, 99999)
            )
            await conn.commit()
        
        # Make pair inactive to allow cleanup
        sample_pair.status = "inactive"
        await test_db.update_pair(sample_pair)
        
        # Log old error
        await test_db.log_error("old_error", "Old error message")
        async with test_db.get_connection() as conn:
            await conn.execute(
                'UPDATE error_logs SET created_at = ? WHERE error_type = ?',
                (old_date, "old_error")
            )
            await conn.commit()
        
        # Run cleanup
        await test_db.cleanup_old_data(days=30)
        
        # Verify old data was cleaned up
        async with test_db.get_connection() as conn:
            # Check message mapping
            cursor = await conn.execute(
                'SELECT COUNT(*) FROM message_mapping WHERE source_message_id = ?',
                (99999,)
            )
            count = (await cursor.fetchone())[0]
            assert count == 0  # Should be deleted
            
            # Check error logs
            cursor = await conn.execute(
                'SELECT COUNT(*) FROM error_logs WHERE error_type = ?',
                ("old_error",)
            )
            count = (await cursor.fetchone())[0]
            assert count == 0  # Should be deleted
    
    @pytest.mark.asyncio
    async def test_message_pair_defaults(self):
        """Test MessagePair default values"""
        pair = MessagePair(
            id=1,
            source_chat_id=-1001234567890,
            destination_chat_id=-1009876543210,
            name="Test Pair"
        )
        
        # Check default filters
        assert "blocked_words" in pair.filters
        assert "remove_mentions" in pair.filters
        assert "preserve_replies" in pair.filters
        assert "sync_edits" in pair.filters
        assert "sync_deletes" in pair.filters
        
        # Check default stats
        assert "messages_copied" in pair.stats
        assert "messages_filtered" in pair.stats
        assert "errors" in pair.stats
        assert pair.stats["messages_copied"] == 0
    
    @pytest.mark.asyncio
    async def test_connection_context_manager(self, test_db):
        """Test database connection context manager"""
        async with test_db.get_connection() as conn:
            cursor = await conn.execute('SELECT 1')
            result = await cursor.fetchone()
            assert result[0] == 1
        
        # Connection should be closed after context
        # No direct way to test this with aiosqlite, but no exceptions should occur
    
    @pytest.mark.asyncio
    async def test_database_backup_creation(self, temp_dir):
        """Test database backup creation"""
        db_path = os.path.join(temp_dir, "test_backup.db")
        backup_path = f"{db_path}.backup"
        
        db_manager = DatabaseManager(db_path)
        await db_manager.initialize()
        
        # Create some data
        await db_manager.create_pair(-1001111111111, -1002222222222, "Test Pair")
        
        # Create another backup
        await db_manager._create_backup()
        
        # Verify backup exists and has content
        assert os.path.exists(backup_path)
        assert os.path.getsize(backup_path) > 0
        
        await db_manager.close()
    
    @pytest.mark.asyncio
    async def test_concurrent_operations(self, test_db):
        """Test concurrent database operations"""
        async def create_pairs(start_id):
            tasks = []
            for i in range(5):
                task = test_db.create_pair(
                    source_chat_id=start_id + i,
                    destination_chat_id=start_id + i + 1000000,
                    name=f"Concurrent Pair {start_id + i}"
                )
                tasks.append(task)
            return await asyncio.gather(*tasks, return_exceptions=True)
        
        # Run concurrent operations
        results1 = await create_pairs(-1001000000000)
        results2 = await create_pairs(-1002000000000)
        
        # All operations should succeed
        for result in results1 + results2:
            assert isinstance(result, int) and result > 0
        
        # Verify all pairs were created
        all_pairs = await test_db.get_all_pairs()
        assert len(all_pairs) >= 10
