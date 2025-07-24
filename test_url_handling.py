
import asyncio
import logging
from unittest.mock import Mock, AsyncMock
from config import Config
from database import DatabaseManager, MessagePair
from message_processor import MessageProcessor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MockEvent:
    def __init__(self, text):
        self.text = text
        self.raw_text = text
        self.media = None
        self.entities = []
        self.is_reply = False
        self.reply_to_msg_id = None
        self.id = 12345

class MockBot:
    def __init__(self):
        self.send_message = AsyncMock(return_value=Mock(message_id=67890))
        self.call_log = []
        
        # Override send_message to log calls
        original_send = self.send_message
        async def logged_send(*args, **kwargs):
            self.call_log.append(kwargs)
            logger.info(f"Bot.send_message called with: {kwargs}")
            return await original_send(*args, **kwargs)
        
        self.send_message = logged_send

class MockPair:
    def __init__(self):
        self.id = 1
        self.source_chat_id = -1001234567890
        self.destination_chat_id = -1001234567891
        self.name = "Test Pair"
        self.status = "active"
        self.assigned_bot_index = 0
        self.filters = {"preserve_original_formatting": True}
        self.stats = {}

async def test_url_handling():
    """Test comprehensive URL handling"""
    print("🔗 Testing URL Handling in Telegram Bot")
    print("=" * 50)
    
    # Initialize components
    config = Config()
    db_manager = DatabaseManager()
    await db_manager.initialize()
    
    processor = MessageProcessor(db_manager, config)
    await processor.initialize()
    
    # Test URLs
    test_messages = [
        "Check this TradingView chart: https://tradingview.com/chart/BTCUSDT",
        "Watch this YouTube video: https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "Visit our website: https://example.com/page",
        "Check out www.google.com for search",
        "Join our Telegram: t.me/example_channel",
        "Download from ftp://files.example.com/file.zip",
        "Visit example.com/path for more info",
        "Check github.com/user/repo for code",
        "Mixed content with https://link.com and text",
        "Multiple links: https://site1.com and https://site2.com",
        "Regular text without any URLs"
    ]
    
    mock_bot = MockBot()
    mock_pair = MockPair()
    
    url_count = 0
    success_count = 0
    
    for i, message_text in enumerate(test_messages, 1):
        print(f"\n{i}. Testing: {message_text}")
        print("-" * 40)
        
        # Test URL detection
        contains_urls = processor._contains_urls(message_text)
        print(f"Contains URLs: {contains_urls}")
        
        if contains_urls:
            url_count += 1
        
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
                
                # Check if bot was called correctly
                if mock_bot.call_log:
                    last_call = mock_bot.call_log[-1]
                    preview_disabled = last_call.get('disable_web_page_preview', False)
                    print(f"Webpage preview {'DISABLED' if preview_disabled else 'ENABLED'}")
                    
                    if contains_urls and not preview_disabled:
                        print("✅ URL handling correct")
                    elif not contains_urls:
                        print("ℹ️ No URLs detected (expected)")
                    else:
                        print("❌ URL handling incorrect")
                        
            else:
                print("❌ Message processing failed")
                
        except Exception as e:
            print(f"❌ Error processing message: {e}")
    
    print(f"\n" + "=" * 50)
    print(f"📊 Test Results:")
    print(f"Total messages: {len(test_messages)}")
    print(f"Messages with URLs: {url_count}")
    print(f"Successfully processed: {success_count}")
    print(f"Success rate: {success_count/len(test_messages)*100:.1f}%")
    
    print(f"\n📋 Bot call summary:")
    print(f"Total bot calls: {len(mock_bot.call_log)}")
    
    # Analyze URL handling
    url_messages_with_preview = 0
    for i, call in enumerate(mock_bot.call_log):
        text = call.get('text', '')
        preview_disabled = call.get('disable_web_page_preview', False)
        contains_urls = processor._contains_urls(text)
        
        if contains_urls and not preview_disabled:
            url_messages_with_preview += 1
    
    print(f"URL messages with preview enabled: {url_messages_with_preview}")
    
    if url_messages_with_preview == url_count:
        print("✅ ALL URL MESSAGES HANDLED CORRECTLY")
    else:
        print("❌ SOME URL MESSAGES NOT HANDLED CORRECTLY")
    
    await db_manager.close()

if __name__ == "__main__":
    asyncio.run(test_url_handling())
