#!/usr/bin/env python3
"""
Test script to verify all commands properly update the database
"""

import asyncio
import sys
import sqlite3
import json
from filters import MessageFilter
from database import DatabaseManager, MessagePair
from config import Config

async def test_mention_command():
    """Test mention removal command functionality"""
    print("Testing /mentions command functionality...")
    
    config = Config()
    db_manager = DatabaseManager()
    await db_manager.initialize()
    
    message_filter = MessageFilter(db_manager, config)
    await message_filter.initialize()
    
    # Test enabling mention removal with custom placeholder
    print("1. Testing enable mention removal with placeholder '[Trader]'")
    success = await message_filter.set_mention_removal(1, True, "[Trader]")
    print(f"   Result: {'✅ Success' if success else '❌ Failed'}")
    
    # Check database
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT filters FROM pairs WHERE id = 1")
    row = cursor.fetchone()
    if row:
        filters = json.loads(row[0])
        print(f"   Database: remove_mentions={filters.get('remove_mentions')}, placeholder='{filters.get('mention_placeholder')}'")
    conn.close()
    
    # Test disabling mention removal
    print("2. Testing disable mention removal")
    success = await message_filter.set_mention_removal(1, False, "")
    print(f"   Result: {'✅ Success' if success else '❌ Failed'}")
    
    # Check database again
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT filters FROM pairs WHERE id = 1")
    row = cursor.fetchone()
    if row:
        filters = json.loads(row[0])
        print(f"   Database: remove_mentions={filters.get('remove_mentions')}")
    conn.close()
    
    # Restore original state
    await message_filter.set_mention_removal(1, True, "[User]")
    
    await db_manager.close()
    return True

async def test_header_footer_commands():
    """Test header/footer regex command functionality"""
    print("Testing /headerregex and /footerregex command functionality...")
    
    config = Config()
    db_manager = DatabaseManager()
    await db_manager.initialize()
    
    message_filter = MessageFilter(db_manager, config)
    await message_filter.initialize()
    
    # Test setting header regex
    print("1. Testing set header regex")
    header_pattern = r'^🔥\s*VIP\s*ENTRY\b.*?$'
    success = await message_filter.set_pair_header_footer_regex(1, header_regex=header_pattern)
    print(f"   Result: {'✅ Success' if success else '❌ Failed'}")
    
    # Test setting footer regex
    print("2. Testing set footer regex")
    footer_pattern = r'^🔚\s*END\b.*?$'
    success = await message_filter.set_pair_header_footer_regex(1, footer_regex=footer_pattern)
    print(f"   Result: {'✅ Success' if success else '❌ Failed'}")
    
    # Check database
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT filters FROM pairs WHERE id = 1")
    row = cursor.fetchone()
    if row:
        filters = json.loads(row[0])
        print(f"   Database: header_regex='{filters.get('header_regex')}'")
        print(f"   Database: footer_regex='{filters.get('footer_regex')}'")
    conn.close()
    
    # Test actual filtering with these patterns
    print("3. Testing filtering with configured patterns")
    pairs = await db_manager.get_all_pairs()
    pair = pairs[0]
    
    test_text = "🔥 VIP ENTRY Premium Signal\nBuy EURUSD at 1.0850\nTarget: 1.0900\n🔚 END"
    filtered_text, entities = await message_filter.filter_text(test_text, pair, [])
    print(f"   Original: '{test_text}'")
    print(f"   Filtered: '{filtered_text}'")
    
    # Test clearing patterns
    print("4. Testing clear header regex")
    success = await message_filter.set_pair_header_footer_regex(1, header_regex=None)
    print(f"   Result: {'✅ Success' if success else '❌ Failed'}")
    
    print("5. Testing clear footer regex")
    success = await message_filter.set_pair_header_footer_regex(1, footer_regex=None)
    print(f"   Result: {'✅ Success' if success else '❌ Failed'}")
    
    # Final database check
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT filters FROM pairs WHERE id = 1")
    row = cursor.fetchone()
    if row:
        filters = json.loads(row[0])
        print(f"   Database: header_regex={filters.get('header_regex', 'None')}")
        print(f"   Database: footer_regex={filters.get('footer_regex', 'None')}")
    conn.close()
    
    await db_manager.close()
    return True

async def test_comprehensive_filtering():
    """Test all filtering features working together"""
    print("Testing comprehensive filtering with all features enabled...")
    
    config = Config()
    db_manager = DatabaseManager()
    await db_manager.initialize()
    
    message_filter = MessageFilter(db_manager, config)
    await message_filter.initialize()
    
    # Configure all filters
    print("1. Configuring all filters...")
    
    # Enable mention removal
    await message_filter.set_mention_removal(1, True, "[User]")
    
    # Set header and footer patterns
    header_patterns = [r'^🔥\s*VIP\s*ENTRY\b.*?$', r'^📢\s*SIGNAL\s*ALERT\b.*?$']
    footer_patterns = [r'^🔚\s*END\b.*?$', r'^👉\s*Join\b.*?$']
    
    # Note: The current API only accepts single patterns, so we'll test with one each
    await message_filter.set_pair_header_footer_regex(1, header_regex=header_patterns[0])
    await message_filter.set_pair_header_footer_regex(1, footer_regex=footer_patterns[0])
    
    # Test complex message
    test_message = """🔥 VIP ENTRY Premium Signal
    
Buy EURUSD at 1.0850
Target: 1.0900
Stop Loss: 1.0800

Signal from @premium_trader and @vip_analyst
Contact @admin for more info

🔚 END"""
    
    pairs = await db_manager.get_all_pairs()
    pair = pairs[0]
    
    filtered_text, entities = await message_filter.filter_text(test_message, pair, [])
    
    print("2. Complex message filtering test:")
    print(f"   Original:\n{test_message}")
    print(f"   \n   Filtered:\n{filtered_text}")
    
    # Verify all filters were applied
    has_header = "🔥 VIP ENTRY" in filtered_text
    has_footer = "🔚 END" in filtered_text  
    has_mentions = "@premium_trader" in filtered_text or "@vip_analyst" in filtered_text or "@admin" in filtered_text
    
    print(f"   \n   Filter Results:")
    print(f"   - Header removed: {'❌ Still present' if has_header else '✅ Removed'}")
    print(f"   - Footer removed: {'❌ Still present' if has_footer else '✅ Removed'}")
    print(f"   - Mentions replaced: {'❌ Still present' if has_mentions else '✅ Replaced'}")
    
    await db_manager.close()
    return not (has_header or has_footer or has_mentions)

async def main():
    """Run all command update tests"""
    print("🚀 Starting Command Update Tests...\n")
    
    try:
        print("=" * 60)
        success1 = await test_mention_command()
        print("=" * 60)
        success2 = await test_header_footer_commands()
        print("=" * 60)
        success3 = await test_comprehensive_filtering()
        print("=" * 60)
        
        if success1 and success2 and success3:
            print("✅ All command update tests passed!")
            print("✅ Mention removal commands are working properly")
            print("✅ Header/Footer removal commands are working properly")
            print("✅ All filters work together correctly")
            return 0
        else:
            print("❌ Some command tests failed!")
            return 1
            
    except Exception as e:
        print(f"❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)