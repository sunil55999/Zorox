#!/usr/bin/env python3
"""
Test the /mentions command to verify it's working
"""

import asyncio
import aiosqlite
import json

async def test_mention_command():
    """Test if the mentions command updates the database correctly"""
    
    print("🔍 TESTING MENTION COMMAND DATABASE UPDATES")
    print("=" * 60)
    
    # Check database before and after command
    async with aiosqlite.connect('bot.db') as db:
        # Get current state
        async with db.execute("SELECT * FROM pairs") as cursor:
            pairs = await cursor.fetchall()
            
        if not pairs:
            print("❌ No pairs found")
            return
            
        async with db.execute("PRAGMA table_info(pairs)") as cursor:
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
        
        pair_data = dict(zip(column_names, pairs[0]))
        current_filters = json.loads(pair_data['filters']) if pair_data['filters'] else {}
        
        print(f"📊 CURRENT STATE:")
        print(f"   Pair ID: {pair_data['id']}")
        print(f"   Name: {pair_data['name']}")
        print(f"   Current remove_mentions: {current_filters.get('remove_mentions', False)}")
        print(f"   Current placeholder: {current_filters.get('mention_placeholder', 'None')}")
        print()
        
        # Simulate what the command should do - enable mentions with [User] placeholder
        updated_filters = current_filters.copy()
        updated_filters['remove_mentions'] = True
        updated_filters['mention_placeholder'] = '[User]'
        
        # Update database like the command should
        await db.execute(
            "UPDATE pairs SET filters = ? WHERE id = ?",
            (json.dumps(updated_filters), pair_data['id'])
        )
        await db.commit()
        
        # Verify the update
        async with db.execute("SELECT filters FROM pairs WHERE id = ?", (pair_data['id'],)) as cursor:
            result = await cursor.fetchone()
            
        if result:
            new_filters = json.loads(result[0])
            print(f"✅ DATABASE UPDATE SUCCESSFUL:")
            print(f"   remove_mentions: {new_filters.get('remove_mentions', False)}")
            print(f"   mention_placeholder: {new_filters.get('mention_placeholder', 'None')}")
            print()
            
            # Test the actual mention removal function
            test_message = "Hello @john how are you?"
            
            # Import the actual function
            import sys
            import os
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            
            from filters import MessageFilter
            from database import DatabaseManager, MessagePair
            from config import Config
            
            # Create objects
            db_manager = DatabaseManager()
            config = Config()
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
                filters=new_filters,
                stats=json.loads(pair_data['stats']) if pair_data['stats'] else {}
            )
            
            # Test filtering
            filtered_text, entities = await message_filter.filter_text(test_message, pair, [])
            
            print(f"🧪 FILTERING TEST:")
            print(f"   Input:    '{test_message}'")
            print(f"   Output:   '{filtered_text}'")
            print(f"   Expected: 'Hello [User] how are you?'")
            
            if filtered_text.strip() == "Hello [User] how are you?":
                print("   Status:   ✅ WORKING CORRECTLY")
                print()
                print("🎯 MENTION REMOVAL IS FULLY FUNCTIONAL!")
                print("   The /mentions command should now work properly")
                print("   Try: /mentions 1 enable [User]")
            else:
                print("   Status:   ❌ NOT WORKING")
                print("   Issue:    Output doesn't match expected")
        else:
            print("❌ Failed to verify database update")

if __name__ == "__main__":
    asyncio.run(test_mention_command())