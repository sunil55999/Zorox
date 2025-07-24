
import asyncio
import logging
from config import Config
from database import DatabaseManager
from message_processor import MessageProcessor

# Mock classes for testing
class MockEvent:
    def __init__(self, text, media=None):
        self.text = text
        self.raw_text = text
        self.id = 12345
        self.media = media
        self.is_reply = False
        self.reply_to_msg_id = None
        self.entities = []

class MockBot:
    def __init__(self):
        self.calls = []
    
    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        print(f"Bot.send_message called with: {kwargs}")
        
        # Check if disable_web_page_preview is False (previews enabled)
        preview_disabled = kwargs.get('disable_web_page_preview', True)
        if not preview_disabled:
            print("✅ Webpage previews are ENABLED")
        else:
            print("❌ Webpage previews are DISABLED")
        
        return type('MockMessage', (), {'message_id': 123})()

class MockPair:
    def __init__(self):
        self.id = 1
        self.destination_chat_id = -1001234567890
        self.filters = {"preserve_original_formatting": True}
        self.stats = {}

async def test_url_preview():
    print("🔍 Testing URL Preview Fix")
    print("=" * 40)
    
    # Initialize components
    config = Config()
    db_manager = DatabaseManager()
    await db_manager.initialize()
    
    processor = MessageProcessor(db_manager, config)
    await processor.initialize()
    
    # Test URLs
    test_urls = [
        "Check this chart: https://tradingview.com/chart/BTCUSDT",
        "Watch this video: https://youtube.com/watch?v=abc123",
        "Visit our site: www.example.com",
        "Telegram link: t.me/example",
        "Regular text without URLs"
    ]
    
    mock_bot = MockBot()
    mock_pair = MockPair()
    
    for i, url_text in enumerate(test_urls, 1):
        print(f"\n{i}. Testing: {url_text}")
        print("-" * 30)
        
        # Test URL detection
        contains_urls = processor._contains_urls(url_text)
        print(f"Contains URLs: {contains_urls}")
        
        # Test sending message
        mock_event = MockEvent(url_text)
        
        try:
            result = await processor._send_message(
                bot=mock_bot,
                chat_id=mock_pair.destination_chat_id,
                content=url_text,
                media_info=None,
                reply_to_message_id=None,
                entities=[]
            )
            
            if result:
                print("✅ Message sent successfully")
            else:
                print("❌ Message sending failed")
                
        except Exception as e:
            print(f"❌ Error: {e}")
    
    print(f"\n📊 Total bot calls: {len(mock_bot.calls)}")
    
    # Check all calls had previews enabled
    all_previews_enabled = all(
        not call.get('disable_web_page_preview', True) 
        for call in mock_bot.calls
    )
    
    if all_previews_enabled:
        print("✅ ALL TESTS PASSED: Webpage previews enabled for all messages")
    else:
        print("❌ SOME TESTS FAILED: Not all messages have previews enabled")

if __name__ == "__main__":
    asyncio.run(test_url_preview())
