#!/usr/bin/env python3
"""
Comprehensive test for filtering functionality fixes in Telegram Bot System
Tests: text filtering, pair-specific word blocking, mention removal, header/footer removal
"""

import asyncio
import sys
import os

# Add current directory to path for imports
sys.path.insert(0, '.')

from message_processor import MessageProcessor
from filters import MessageFilter
from database import MessagePair, DatabaseManager
from config import Config
from image_handler import ImageHandler
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class MockEvent:
    """Mock Telegram event for testing"""
    def __init__(self, text="", entities=None, media=None):
        self.text = text
        self.raw_text = text
        self.entities = entities or []
        self.media = media

async def test_text_filtering():
    """Test comprehensive text filtering functionality"""
    print("🔧 Testing Text Filtering Functions...")
    
    # Initialize components
    config = Config()
    db_manager = DatabaseManager()
    await db_manager.initialize()
    
    image_handler = ImageHandler(db_manager, config)
    message_filter = MessageFilter(db_manager, config)
    processor = MessageProcessor(db_manager, config)
    
    # Create test pair with filtering enabled
    test_pair = MessagePair(
        id=1,
        source_chat_id=-100123456789,
        destination_chat_id=-100987654321,
        name="Test Pair",
        filters={
            "blocked_words": ["spam", "promo", "subscribe"],
            "remove_mentions": True,
            "mention_placeholder": "[User]",
            "header_regex": r'^.*?[:|：].*?\n',
            "footer_regex": r'\n.*?@\w+.*?$',
            "preserve_original_formatting": False
        }
    )
    
    # Test cases
    test_cases = [
        {
            "name": "Global word blocking",
            "text": "Join our channel for free promotions!",
            "should_block": True,
            "test_type": "word_blocking"
        },
        {
            "name": "Pair-specific word blocking",
            "text": "This message contains spam content",
            "should_block": True,
            "test_type": "word_blocking"
        },
        {
            "name": "Mention removal",
            "text": "Hello @username and @another_user, check this out!",
            "expected_result": "Hello [User] and [User], check this out!",
            "test_type": "text_filtering"
        },
        {
            "name": "Header removal",
            "text": "Channel Update: This is important news\nActual content here",
            "expected_result": "Actual content here",
            "test_type": "text_filtering"
        },
        {
            "name": "Footer removal", 
            "text": "Main content here\nFollow us @channel_name",
            "expected_result": "Main content here",
            "test_type": "text_filtering"
        },
        {
            "name": "Clean text (no blocking)",
            "text": "This is a normal message without any issues",
            "should_block": False,
            "test_type": "word_blocking"
        }
    ]
    
    results = {}
    
    for test_case in test_cases:
        print(f"\n  Testing: {test_case['name']}")
        
        try:
            if test_case['test_type'] == 'word_blocking':
                # Test word blocking
                event = MockEvent(test_case['text'])
                is_blocked = processor.is_blocked_word(test_case['text'], test_pair)
                
                if is_blocked == test_case['should_block']:
                    print(f"    ✅ PASS: Word blocking works correctly")
                    results[test_case['name']] = "PASS"
                else:
                    print(f"    ❌ FAIL: Expected block={test_case['should_block']}, got block={is_blocked}")
                    results[test_case['name']] = "FAIL"
                    
            elif test_case['test_type'] == 'text_filtering':
                # Test text filtering (mention removal, header/footer removal)
                event = MockEvent(test_case['text'])
                filtered_text, entities = await processor._process_message_content(event, test_pair)
                
                if 'expected_result' in test_case:
                    if filtered_text.strip() == test_case['expected_result'].strip():
                        print(f"    ✅ PASS: Text filtering works correctly")
                        print(f"    Original: {test_case['text']}")
                        print(f"    Filtered: {filtered_text}")
                        results[test_case['name']] = "PASS"
                    else:
                        print(f"    ❌ FAIL: Text filtering incorrect")
                        print(f"    Expected: {test_case['expected_result']}")
                        print(f"    Got: {filtered_text}")
                        results[test_case['name']] = "FAIL"
                else:
                    print(f"    ✅ PASS: Text processing completed without error")
                    results[test_case['name']] = "PASS"
                    
        except Exception as e:
            print(f"    ❌ ERROR: {e}")
            results[test_case['name']] = f"ERROR: {e}"
    
    # Summary
    print(f"\n📊 Test Results Summary:")
    passed = sum(1 for result in results.values() if result == "PASS")
    total = len(results)
    print(f"   Passed: {passed}/{total}")
    
    for test_name, result in results.items():
        status = "✅" if result == "PASS" else "❌"
        print(f"   {status} {test_name}: {result}")
    
    return passed == total

async def test_performance_settings():
    """Test performance optimization for 80-90 pairs"""
    print("\n🚀 Testing Performance Settings...")
    
    config = Config()
    
    # Check performance settings
    print(f"   MAX_WORKERS: {config.MAX_WORKERS} (target: ≥20 for many pairs)")
    print(f"   MESSAGE_QUEUE_SIZE: {config.MESSAGE_QUEUE_SIZE} (target: ≥5000)")
    print(f"   BATCH_SIZE: {getattr(config, 'BATCH_SIZE', 'Not set')} (target: ≥25)")
    print(f"   RETRY_DELAY: {config.RETRY_DELAY} (target: ≤1.0 for fast processing)")
    
    # Performance validation
    performance_ok = (
        config.MAX_WORKERS >= 20 and
        config.MESSAGE_QUEUE_SIZE >= 5000 and
        config.RETRY_DELAY <= 1.0 and
        getattr(config, 'BATCH_SIZE', 25) >= 25
    )
    
    if performance_ok:
        print("   ✅ Performance settings optimized for high-volume processing")
        return True
    else:
        print("   ❌ Performance settings need optimization")
        return False

async def main():
    """Run comprehensive filtering tests"""
    print("🧪 Starting Comprehensive Filtering Function Tests...\n")
    
    try:
        # Test filtering functionality
        filtering_ok = await test_text_filtering()
        
        # Test performance settings
        performance_ok = await test_performance_settings()
        
        # Overall result
        all_tests_passed = filtering_ok and performance_ok
        
        print(f"\n{'='*60}")
        if all_tests_passed:
            print("🎉 ALL TESTS PASSED! System ready for 80-90 pairs with full filtering.")
            print("\nKey fixes verified:")
            print("  ✅ Text filtering enabled (preserve_original_formatting removed)")
            print("  ✅ Pair-specific word blocking working")
            print("  ✅ Mention removal functioning")  
            print("  ✅ Header/footer removal operational")
            print("  ✅ Performance settings optimized for high volume")
            return True
        else:
            print("❌ SOME TESTS FAILED - Please review the issues above")
            return False
            
    except Exception as e:
        print(f"❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    asyncio.run(main())