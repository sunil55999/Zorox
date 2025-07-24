#!/usr/bin/env python3
"""
Test script to verify URL forwarding functionality
"""

import re
from message_processor import MessageProcessor
from config import Config
from database import DatabaseManager

def test_url_detection():
    """Test URL detection patterns"""
    
    # Initialize processor (mock for testing)
    class MockProcessor:
        def _contains_urls(self, text: str) -> bool:
            """Check if text contains URLs that should have webpage previews"""
            if not text:
                return False
            
            import re
            # Enhanced URL patterns that typically generate webpage previews
            url_patterns = [
                r'https?://[^\s<>")\]]+',                       # HTTP/HTTPS URLs (exclude ) and ])
                r'www\.[^\s<>")\]]+\.[a-zA-Z]{2,}[^\s<>")\]]*', # www URLs with domain and optional path
                r't\.me/[^\s<>")\]]+',                          # Telegram links
                r'(?<![a-zA-Z0-9@])[a-zA-Z0-9.-]+\.(com|org|net|edu|gov|co|io|tv|me|ly|to|cc|repl|dev|app)[^\s<>")\]]*', # Common TLD URLs (exclude emails)
                r'ftp://[^\s<>")\]]+',                          # FTP URLs
                r'[a-zA-Z0-9.-]+\.replit\.com[^\s<>")\]]*',     # Replit URLs
                r'[a-zA-Z0-9.-]+\.replit\.app[^\s<>")\]]*',     # Replit app URLs
            ]
            
            # Check for markdown-style links: [text](url)
            markdown_link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
            markdown_matches = re.findall(markdown_link_pattern, text)
            if markdown_matches:
                for link_text, link_url in markdown_matches:
                    # Check if the URL part contains a valid URL
                    for pattern in url_patterns:
                        if re.search(pattern, link_url, re.IGNORECASE):
                            print(f"✅ Found markdown URL in text: [{link_text}]({link_url})")
                            return True
            
            # Check for regular URL patterns
            for pattern in url_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    print(f"✅ Found URL pattern '{pattern}' in text: {text[:200]}... (matched: {match.group()})")
                    return True
            
            print(f"❌ No URL patterns found in text: {text[:200]}...")
            return False
    
    processor = MockProcessor()
    
    # Test cases
    test_cases = [
        # Regular URLs
        ("https://example.com", True),
        ("http://test.org", True),
        ("www.google.com", True),
        ("replit.com", True),
        ("user.replit.app", True),
        ("t.me/channel", True),
        
        # Markdown URLs
        ("[Click here](https://example.com)", True),
        ("[Replit Project](https://replit.com/@user/project)", True),
        ("[GitHub](https://github.com/user/repo)", True),
        
        # Mixed content
        ("Check out [this link](https://example.com) for more info", True),
        ("Visit https://test.com or [click here](https://another.com)", True),
        
        # Non-URLs
        ("Just plain text", False),
        ("No links here", False),
        ("email@example.com", False),  # Email addresses shouldn't trigger URL preview
        
        # Edge cases
        ("[broken link](not-a-url)", False),
        ("https://", False),  # Incomplete URL
        ("", False),  # Empty string
    ]
    
    print("🧪 Testing URL Detection Functionality\n")
    
    passed = 0
    total = len(test_cases)
    
    for i, (text, expected) in enumerate(test_cases, 1):
        result = processor._contains_urls(text)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        print(f"{i:2d}. {status} | Expected: {expected:5} | Got: {result:5} | Text: '{text}'")
        if result == expected:
            passed += 1
        print()
    
    print(f"📊 Results: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    
    return passed == total

if __name__ == "__main__":
    test_url_detection()