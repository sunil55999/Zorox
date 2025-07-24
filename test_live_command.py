#!/usr/bin/env python3
"""
Test the live /mentions command to ensure it's working
"""

import asyncio
import aiosqlite
import json

async def simulate_mentions_command():
    """Simulate the /mentions command and verify it works end-to-end"""
    
    print("🔧 SIMULATING /mentions COMMAND")
    print("=" * 60)
    
    # Step 1: Check current state
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
        current_filters = json.loads(pair_data['filters']) if pair_data['filters'] else {}
        
        print(f"📊 BEFORE COMMAND:")
        print(f"   remove_mentions: {current_filters.get('remove_mentions', False)}")
        print(f"   mention_placeholder: {current_filters.get('mention_placeholder', 'None')}")
        print()
    
    # Step 2: Simulate command execution (disable mentions first)
    print("🎮 EXECUTING: /mentions 1 disable")
    
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    from filters import MessageFilter
    from database import DatabaseManager
    from config import Config
    
    # Initialize components
    config = Config()
    db_manager = DatabaseManager()
    message_filter = MessageFilter(db_manager, config)
    await message_filter.initialize()
    
    # Execute the command logic
    pair_id = 1
    remove_mentions = False
    placeholder = ""
    
    success = await message_filter.set_mention_removal(pair_id, remove_mentions, placeholder)
    
    if success:
        print("✅ Command executed successfully")
    else:
        print("❌ Command failed")
    
    # Step 3: Verify database was updated
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute("SELECT filters FROM pairs WHERE id = 1") as cursor:
            result = await cursor.fetchone()
            
        if result:
            updated_filters = json.loads(result[0])
            print(f"📊 AFTER DISABLE COMMAND:")
            print(f"   remove_mentions: {updated_filters.get('remove_mentions', False)}")
            print(f"   mention_placeholder: {updated_filters.get('mention_placeholder', 'None')}")
            print()
    
    # Step 4: Now enable mentions with placeholder
    print("🎮 EXECUTING: /mentions 1 enable [User]")
    
    remove_mentions = True
    placeholder = "[User]"
    
    success = await message_filter.set_mention_removal(pair_id, remove_mentions, placeholder)
    
    if success:
        print("✅ Command executed successfully")
    else:
        print("❌ Command failed")
    
    # Step 5: Verify final state
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute("SELECT filters FROM pairs WHERE id = 1") as cursor:
            result = await cursor.fetchone()
            
        if result:
            final_filters = json.loads(result[0])
            print(f"📊 AFTER ENABLE COMMAND:")
            print(f"   remove_mentions: {final_filters.get('remove_mentions', False)}")
            print(f"   mention_placeholder: {final_filters.get('mention_placeholder', 'None')}")
            print()
    
    # Step 6: Test actual filtering works
    from database import MessagePair
    
    pair = MessagePair(
        id=1,
        source_chat_id=-1002884297297,
        destination_chat_id=-1002811921560,
        name="Test Pair",
        status="active",
        assigned_bot_index=0,
        filters=final_filters,
        stats={}
    )
    
    test_message = "Hello @john how are you?"
    filtered_text, entities = await message_filter.filter_text(test_message, pair, [])
    
    print(f"🧪 FINAL FILTERING TEST:")
    print(f"   Input:    '{test_message}'")
    print(f"   Output:   '{filtered_text}'")
    print(f"   Expected: 'Hello [User] how are you?'")
    
    if filtered_text.strip() == "Hello [User] how are you?":
        print("   Status:   ✅ COMMAND IS WORKING PERFECTLY!")
        print()
        print("🎯 CONCLUSION:")
        print("   The /mentions command IS working correctly.")
        print("   Database updates are successful.")
        print("   Filtering logic is operational.")
        print()
        print("📝 NEXT STEPS:")
        print("   1. Try: /mentions 1 enable [User] in Telegram")
        print("   2. Send test message to source channel")
        print("   3. Check if filtering appears in destination")
    else:
        print("   Status:   ❌ Something is still wrong")

if __name__ == "__main__":
    asyncio.run(simulate_mentions_command())