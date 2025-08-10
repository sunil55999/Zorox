#!/usr/bin/env python3
"""
Test script to demonstrate the fixed word blocking functionality
"""

import re

def old_contains_blocked_words(text: str, blocked_words: list) -> bool:
    """Old implementation using substring matching"""
    if not blocked_words:
        return False
    
    text_lower = text.lower()
    for word in blocked_words:
        if word.lower() in text_lower:
            return True
    
    return False

def new_contains_blocked_words(text: str, blocked_words: list) -> bool:
    """New implementation using whole-word matching"""
    if not blocked_words:
        return False
    
    for word in blocked_words:
        # Use regex word boundaries to match whole words only
        pattern = r'\b' + re.escape(word.lower()) + r'\b'
        if re.search(pattern, text.lower()):
            return True
    
    return False

def test_word_blocking():
    """Test both implementations to show the difference"""
    
    # Test cases
    test_cases = [
        ("cat", "I love my cat"),           # Should block
        ("cat", "I love my cats"),          # Should block (plural)
        ("cat", "category is important"),   # Should NOT block (old version would)
        ("cat", "caterpillar crawls"),      # Should NOT block (old version would)
        ("cat", "communication works"),     # Should NOT block
        ("test", "This is a test"),         # Should block
        ("test", "testing in progress"),    # Should NOT block (old version would)
        ("hello", "hello world"),           # Should block
        ("hello", "say hello"),             # Should block
        ("world", "wonderful place"),       # Should NOT block (old version would)
    ]
    
    blocked_words = ["cat", "test", "hello", "world"]
    
    print("Word Blocking Test Results:")
    print("=" * 50)
    print(f"Blocked words: {blocked_words}")
    print()
    
    for word, text in test_cases:
        old_result = old_contains_blocked_words(text, blocked_words)
        new_result = new_contains_blocked_words(text, blocked_words)
        
        status = "✓ FIXED" if old_result != new_result else "Same"
        
        print(f"Text: '{text}'")
        print(f"  Old method (substring): {'BLOCKED' if old_result else 'ALLOWED'}")
        print(f"  New method (whole-word): {'BLOCKED' if new_result else 'ALLOWED'}")
        print(f"  Status: {status}")
        print()

if __name__ == "__main__":
    test_word_blocking()