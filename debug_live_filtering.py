#!/usr/bin/env python3
"""
Debug live message filtering to find why mentions aren't being removed
"""

import asyncio
import aiosqlite
import json
import sys
import os

async def debug_live_filtering():
    """Debug the actual live message filtering pipeline"""
    
    print("🔍 DEBUGGING LIVE MESSAGE FILTERING PIPELINE")
    print("=" * 60)
    
    # Check current database state
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute("SELECT * FROM pairs WHERE id = 1") as cursor:
            pair_row = await cursor.fetchone()
            
        if not pair_row:
            print("❌ No pair with ID 1 found")
            return
            
        async with db.execute("PRAGMA table_info(pairs)") as cursor:
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
        
        pair_data = dict(zip(column_names, pair_row))
        filters = json.loads(pair_data['filters']) if pair_data['filters'] else {}
        
        print(f"📊 CURRENT PAIR STATE:")
        print(f"   ID: {pair_data['id']}")
        print(f"   Name: {pair_data['name']}")
        print(f"   Source: {pair_data['source_chat_id']}")
        print(f"   Destination: {pair_data['destination_chat_id']}")
        print(f"   Status: {pair_data['status']}")
        print()
        
        print(f"🔧 CURRENT FILTERS:")
        print(f"   remove_mentions: {filters.get('remove_mentions', False)}")
        print(f"   mention_placeholder: {filters.get('mention_placeholder', 'None')}")
        print(f"   header_regex: {filters.get('header_regex', 'None')}")
        print(f"   footer_regex: {filters.get('footer_regex', 'None')}")
        print()
        
        # Now test the actual message processor flow
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        
        from message_processor import MessageProcessor
        from database import DatabaseManager, MessagePair
        from config import Config
        from filters import MessageFilter
        
        # Initialize components
        config = Config()
        db_manager = DatabaseManager()
        message_filter = MessageFilter(db_manager, config)
        await message_filter.initialize()
        
        # Create MessagePair object
        pair = MessagePair(
            id=pair_data['id'],
            source_chat_id=pair_data['source_chat_id'],
            destination_chat_id=pair_data['destination_chat_id'],
            name=pair_data['name'],
            status=pair_data['status'],
            assigned_bot_index=pair_data['assigned_bot_index'],
            filters=filters,
            stats=json.loads(pair_data['stats']) if pair_data['stats'] else {}
        )
        
        # Test various message scenarios
        test_messages = [
            "Hello @john how are you?",
            "Check this out (@username)",
            "🔥 VIP ENTRY\nImportant message here",
            "Main content here\n🔚 END",
            "Contact me at admin@site.org for help",
            "🔥 VIP ENTRY\nHello @john, check email@test.com\n🔚 END"
        ]
        
        print("🧪 TESTING ACTUAL MESSAGE PROCESSOR PIPELINE:")
        print("-" * 50)
        
        for i, test_msg in enumerate(test_messages, 1):
            print(f"Test {i}: {test_msg[:50]}{'...' if len(test_msg) > 50 else ''}")
            
            try:
                # Simulate actual message processing
                filtered_text, entities = await message_filter.filter_text(test_msg, pair, [])
                
                print(f"  Input:  '{test_msg}'")
                print(f"  Output: '{filtered_text}'")
                
                if test_msg != filtered_text:
                    print(f"  Status: ✅ FILTERING APPLIED")
                else:
                    print(f"  Status: ❌ NO FILTERING APPLIED")
                    
            except Exception as e:
                print(f"  Status: ❌ ERROR: {e}")
                
            print()
        
        # Check if the issue is in message_processor.py
        print("🔍 CHECKING message_processor.py INTEGRATION:")
        print("-" * 50)
        
        # Check if message_processor actually calls the filter
        message_processor = MessageProcessor(db_manager, config)
        
        # This should call the filtering pipeline
        try:
            # Simulate a telethon message object (basic structure)
            class MockMessage:
                def __init__(self, text):
                    self.text = text
                    self.message = text
                    self.media = None
                    self.entities = []
                    self.id = 12345
                    self.date = None
                    self.reply_to_msg_id = None
            
            mock_message = MockMessage("Hello @john test message")
            
            # This would normally process the message
            print(f"📝 Mock message created: '{mock_message.text}'")
            print("   This should go through the filtering pipeline...")
            
        except Exception as e:
            print(f"❌ Error creating mock message: {e}")

if __name__ == "__main__":
    asyncio.run(debug_live_filtering())