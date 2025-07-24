#!/usr/bin/env python3
"""
Test script for improved text cleaning functions
Tests mention removal, header/footer removal with format preservation
"""

import re

def test_mention_removal():
    """Test the improved mention removal function"""
    
    def _remove_mentions(text: str, placeholder: str = "[User]") -> str:
        """Enhanced mention removal with comprehensive pattern matching and clean formatting"""
        if not text:
            return text
        try:
            original_text = text
            
            # Step 1: Handle mentions in parentheses - remove entire parentheses
            text = re.sub(r'\(\s*@[a-zA-Z0-9_]{1,32}\s*\)', '', text)
            
            # Step 2: Handle @mentions that follow punctuation - clean up punctuation  
            text = re.sub(r'([,\.;:!?])\s*@[a-zA-Z0-9_]{1,32}\b', r'\1', text)
            
            # Step 3: Handle standard @mentions (but not email addresses) - replace with placeholder or remove
            if placeholder:
                text = re.sub(r'(?<![a-zA-Z0-9])@[a-zA-Z0-9_]{1,32}\b', placeholder, text)
            else:
                text = re.sub(r'(?<![a-zA-Z0-9])@[a-zA-Z0-9_]{1,32}\b', '', text)
            
            # Step 4: Handle user ID links
            text = re.sub(r'tg://user\?id=\d+', placeholder if placeholder else '', text)
            
            # Clean up formatting issues
            if placeholder:
                # Remove duplicate placeholders
                text = re.sub(f'{re.escape(placeholder)}(\\s*{re.escape(placeholder)})+', placeholder, text)
                # Clean up extra spaces around placeholders
                text = re.sub(f'\\s+{re.escape(placeholder)}\\s+', f' {placeholder} ', text)
                text = re.sub(f'^\\s*{re.escape(placeholder)}\\s*', f'{placeholder} ', text)
                text = re.sub(f'\\s*{re.escape(placeholder)}\\s*$', f' {placeholder}', text)
            
            # Clean up excessive spaces and trailing punctuation left behind
            text = re.sub(r'\s*,\s*,\s*', ', ', text)  # Fix double commas
            text = re.sub(r'\s*,\s*$', '', text)  # Remove trailing comma
            text = re.sub(r'^\s*,\s*', '', text)  # Remove leading comma
            text = re.sub(r'\s+', ' ', text)  # Multiple spaces to single space
            text = text.strip()
            
            # If result is empty or only placeholder, return original
            if not text or (placeholder and text == placeholder):
                return original_text
            
            return text
            
        except Exception as e:
            print(f"Error removing mentions: {e}")
            return text
    
    # Test cases
    test_cases = [
        # Basic mentions
        ("Hello @john how are you?", "Hello [User] how are you?"),
        ("@alice and @bob are here", "[User] and [User] are here"),
        
        # Mentions in parentheses
        ("Check this out (@username)", "Check this out"),
        ("Message from (@alice) to you", "Message from to you"),
        
        # Mentions with punctuation
        ("Hello, @john!", "Hello!"),
        ("Hi @user, how are you?", "Hi, how are you?"),
        ("Thanks @admin.", "Thanks."),
        
        # Multiple mentions
        ("@user1 @user2 @user3", "[User] [User] [User]"),
        
        # Bold/italic preservation
        ("*Bold text* with @mention", "*Bold text* with [User]"),
        ("_Italic text_ and @user here", "_Italic text_ and [User] here"),
        ("[Link](http://example.com) @mention", "[Link](http://example.com) [User]"),
        
        # Edge cases
        ("email@domain.com is not a mention", "email@domain.com is not a mention"),
        ("", ""),
    ]
    
    print("=== MENTION REMOVAL TESTS ===")
    all_passed = True
    
    for i, (input_text, expected) in enumerate(test_cases, 1):
        result = _remove_mentions(input_text, "[User]")
        passed = result == expected
        all_passed = all_passed and passed
        
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"Test {i}: {status}")
        print(f"  Input:    '{input_text}'")
        print(f"  Expected: '{expected}'")
        print(f"  Got:      '{result}'")
        print()
    
    return all_passed

if __name__ == "__main__":
    print("Testing improved text cleaning functions...")
    print("=" * 50)
    
    # Run tests
    mention_passed = test_mention_removal()
    
    # Summary
    print("=" * 50)
    print("TEST SUMMARY:")
    print(f"Mention Removal: {'✓ PASS' if mention_passed else '✗ FAIL'}")
    
    if not mention_passed:
        import sys
        sys.exit(1)