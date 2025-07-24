
import asyncio
import logging
from config import Config
from database import DatabaseManager
from message_processor import MessageProcessor

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MockEvent:
    def __init__(self, text):
        self.text = text
        self.raw_text = text
        self.id = 12345
        self.chat_id = -1001234567890
        self.media = None
        self.is_reply = False
        self.reply_to_msg_id = None
        self.entities = []

class MockBot:
    def __init__(self):
        self.call_log = []
    
    async def send_message(self, chat_id, text, entities=None, disable_web_page_preview=None, reply_to_message_id=None):
        call_info = {
            'chat_id': chat_id,
            'text': text,
            'entities': entities or [],
            'disable_web_page_preview': disable_web_page_preview,
            'reply_to_message_id': reply_to_message_id
        }
        self.call_log.append(call_info)
        logger.info(f"MockBot.send_message called with disable_web_page_preview={disable_web_page_preview}")
        
        # Mock successful response
        class MockMessage:
            def __init__(self):
                self.message_id = 54321
        
        return MockMessage()

class MockPair:
    def __init__(self):
        self.id = 1
        self.destination_chat_id = -1001987654321
        self.filters = {"preserve_original_formatting": True}
        self.stats = {}

async def test_url_forwarding():
    """Test URL forwarding with proper webpage preview settings"""
    print("🔗 Testing URL Forwarding with Webpage Previews")
    print("=" * 60)
    
    # Initialize components
    config = Config()
    db_manager = DatabaseManager()
    await db_manager.initialize()
    
    processor = MessageProcessor(db_manager, config)
    await processor.initialize()
    
    # Test messages with different URL types
    test_messages = [
        "Check this Replit project: https://replit.com/@Hogabhai/CodeMedic",
        "Visit our website: https://example.com/page",
        "Regular text without any URLs",
        "Mixed content with https://google.com and some text",
        "Check replit.com for coding",
    ]
    
    mock_bot = MockBot()
    mock_pair = MockPair()
    
    success_count = 0
    
    for i, message_text in enumerate(test_messages, 1):
        print(f"\n{i}. Testing: {message_text}")
        print("-" * 40)
        
        # Test URL detection
        contains_urls = processor._contains_urls(message_text)
        print(f"Contains URLs: {contains_urls}")
        
        # Create mock event
        mock_event = MockEvent(message_text)
        
        try:
            # Process the message
            result = await processor.process_new_message(
                mock_event, mock_pair, mock_bot, 0
            )
            
            if result:
                success_count += 1
                print("✅ Message processed successfully")
                
                # Check the bot call
                if mock_bot.call_log:
                    last_call = mock_bot.call_log[-1]
                    preview_disabled = last_call.get('disable_web_page_preview', False)
                    
                    print(f"Bot called with disable_web_page_preview={preview_disabled}")
                    
                    # Verify correct preview setting
                    if contains_urls and not preview_disabled:
                        print("✅ Correct: URLs detected and preview ENABLED")
                    elif not contains_urls and preview_disabled:
                        print("✅ Correct: No URLs and preview DISABLED")
                    elif contains_urls and preview_disabled:
                        print("❌ Error: URLs detected but preview DISABLED")
                    else:
                        print("ℹ️ No URLs but preview enabled (acceptable)")
                else:
                    print("❌ No bot calls recorded")
            else:
                print("❌ Message processing failed")
                
        except Exception as e:
            print(f"❌ Error processing message: {e}")
    
    print(f"\n" + "=" * 60)
    print(f"📊 Test Results:")
    print(f"Total messages: {len(test_messages)}")
    print(f"Successfully processed: {success_count}")
    print(f"Success rate: {success_count/len(test_messages)*100:.1f}%")
    
    print(f"\n📋 All bot calls:")
    for i, call in enumerate(mock_bot.call_log, 1):
        text = call.get('text', '')
        preview_disabled = call.get('disable_web_page_preview', False)
        contains_urls = processor._contains_urls(text)
        
        status = "✅" if (contains_urls and not preview_disabled) or (not contains_urls and preview_disabled) else "❌"
        print(f"{status} Call {i}: URLs={contains_urls}, Preview={'Disabled' if preview_disabled else 'Enabled'}")
        print(f"    Text: {text[:50]}...")
    
    await db_manager.close()
    
    if success_count == len(test_messages):
        print("\n🎉 ALL TESTS PASSED: URL forwarding should work correctly!")
    else:
        print(f"\n⚠️ Some tests failed - check your bot configuration")

if __name__ == "__main__":
    asyncio.run(test_url_forwarding())
