#!/usr/bin/env python3
"""
Test script to verify mention removal and header/footer removal functionality
"""

import asyncio
import sys
import sqlite3
import json
from filters import MessageFilter
from database import DatabaseManager, MessagePair
from config import Config

async def test_mention_removal():
    """Test mention removal functionality"""
    print("🧪 Testing Mention Removal...")
    
    # Initialize components
    config = Config()
    db_manager = DatabaseManager()
    await db_manager.initialize()
    
    message_filter = MessageFilter(db_manager, config)
    await message_filter.initialize()
    
    # Get existing pair from database
    pairs = await db_manager.get_all_pairs()
    if not pairs:
        print("❌ No pairs found in database")
        return False
    
    pair = pairs[0]
    print(f"📝 Testing with pair: {pair.name} (ID: {pair.id})")
    print(f"🔧 Current filters: {pair.filters}")
    
    # Test texts with mentions
    test_texts = [
        "Hello @username, how are you?",
        "This is from @trader123 and @signal_bot",
        "Check this out @everyone",
        "Contact @admin for help",
        "(@premium_member) sent this message",
        "News: @breaking_news reported that...",
        "Join tg://user?id=123456 for updates"
    ]
    
    print("\n📋 Testing mention removal:")
    for i, text in enumerate(test_texts, 1):
        filtered_text, entities = await message_filter.filter_text(text, pair, [])
        print(f"{i}. Original: '{text}'")
        print(f"   Filtered: '{filtered_text}'")
        print()
    
    await db_manager.close()
    return True

async def test_header_footer_removal():
    """Test header/footer removal functionality"""
    print("🧪 Testing Header/Footer Removal...")
    
    # Initialize components
    config = Config()
    db_manager = DatabaseManager()
    await db_manager.initialize()
    
    message_filter = MessageFilter(db_manager, config)
    await message_filter.initialize()
    
    # Get existing pair from database
    pairs = await db_manager.get_all_pairs()
    if not pairs:
        print("❌ No pairs found in database")
        return False
    
    pair = pairs[0]
    
    # Add header and footer patterns for testing
    test_filters = pair.filters.copy()
    test_filters["header_regex"] = [
        r'^🔥\s*VIP\s*ENTRY\b.*?$',
        r'^📢\s*SIGNAL\s*ALERT\b.*?$'
    ]
    test_filters["footer_regex"] = [
        r'^🔚\s*END\b.*?$',
        r'^👉\s*Join\b.*?$'
    ]
    
    # Create test pair with patterns
    test_pair = MessagePair(
        id=pair.id,
        source_chat_id=pair.source_chat_id,
        destination_chat_id=pair.destination_chat_id,
        name=pair.name,
        status=pair.status,
        assigned_bot_index=pair.assigned_bot_index,
        filters=test_filters,
        stats=pair.stats,
        created_at=pair.created_at
    )
    
    print(f"📝 Testing with pair: {test_pair.name} (ID: {test_pair.id})")
    print(f"🔧 Test filters: {test_filters}")
    
    # Test texts with headers and footers
    test_texts = [
        "🔥 VIP ENTRY Signal\nBuy EURUSD at 1.0850\nTarget: 1.0900",
        "📢 SIGNAL ALERT\nSell GBPUSD\nStop loss: 1.2650\n\n🔚 END",
        "Regular message without headers or footers",
        "Normal content\n👉 Join our VIP channel for more signals",
        "🔥 VIP ENTRY Premium Signal\nImportant trading info here\n🔚 END OF SIGNAL"
    ]
    
    print("\n📋 Testing header/footer removal:")
    for i, text in enumerate(test_texts, 1):
        filtered_text, entities = await message_filter.filter_text(text, test_pair, [])
        print(f"{i}. Original: '{text}'")
        print(f"   Filtered: '{filtered_text}'")
        print()
    
    await db_manager.close()
    return True

async def test_command_configuration():
    """Test command configuration in database"""
    print("🧪 Testing Command Configuration...")
    
    # Check database directly
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    # Check current pair configuration
    cursor.execute("SELECT id, name, filters FROM pairs")
    rows = cursor.fetchall()
    
    print(f"📊 Found {len(rows)} pairs in database:")
    for row in rows:
        pair_id, name, filters_json = row
        filters = json.loads(filters_json)
        print(f"  • Pair {pair_id}: {name}")
        print(f"    - Remove mentions: {filters.get('remove_mentions', False)}")
        print(f"    - Mention placeholder: {filters.get('mention_placeholder', 'None')}")
        print(f"    - Header regex: {filters.get('header_regex', 'None')}")
        print(f"    - Footer regex: {filters.get('footer_regex', 'None')}")
        print()
    
    conn.close()
    return True

async def main():
    """Run all tests"""
    print("🚀 Starting Command Tests...\n")
    
    try:
        success1 = await test_mention_removal()
        print("-" * 50)
        success2 = await test_header_footer_removal() 
        print("-" * 50)
        success3 = await test_command_configuration()
        
        if success1 and success2 and success3:
            print("✅ All tests completed successfully!")
            return 0
        else:
            print("❌ Some tests failed!")
            return 1
            
    except Exception as e:
        print(f"❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)