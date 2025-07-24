#!/usr/bin/env python3
"""
Test script for improved text cleaning functions
Tests mention removal, header/footer removal with format preservation
"""

import re
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_mention_removal():
    """Test the improved mention removal function"""
    
    def _remove_mentions(text: str, placeholder: str = "[User]") -> str:
        """Enhanced mention removal with comprehensive pattern matching and clean formatting"""
        if not text:
            return text
        try:
            original_text = text
            
            # Comprehensive mention patterns covering all edge cases
            mention_patterns = [
                # Mentions in parentheses like (@xyz) - remove the whole parentheses
                r'\(\s*@[a-zA-Z0-9_]{1,32}\s*\)',
                # Mentions with preceding punctuation, e.g., ,@xyz -> remove cleanly
                r'([,\.;:!?\s])\s*@[a-zA-Z0-9_]{1,32}\b',
                # Standard @username patterns at word boundaries
                r'\b@[a-zA-Z0-9_]{1,32}\b',
                # User links with IDs
                r'tg://user\?id=\d+',
            ]
            
            # Apply patterns with specific replacement logic
            for i, pattern in enumerate(mention_patterns):
                if i == 0:  # Parentheses mentions - remove entirely
                    text = re.sub(pattern, '', text)
                elif i == 1:  # Mentions with preceding punctuation - keep punctuation
                    text = re.sub(pattern, r'\1', text)
                else:  # Standard patterns - replace with placeholder if provided
                    if placeholder:
                        text = re.sub(pattern, placeholder, text)
                    else:
                        text = re.sub(pattern, '', text)
            
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

def test_header_removal():
    """Test the improved header removal function"""
    
    def _remove_headers(text: str, patterns: list = None) -> str:
        """Enhanced header removal with exact phrase matching at beginning of message"""
        try:
            if not text:
                return text
                
            original_text = text
            
            # If no patterns provided, use conservative exact-match patterns
            if not patterns:
                # More conservative default patterns for exact header removal
                exact_header_patterns = [
                    r'^🔥\s*VIP\s*ENTRY\b.*?$',      # Exact: "🔥 VIP ENTRY"
                    r'^📢\s*SIGNAL\s*ALERT\b.*?$',   # Exact: "📢 SIGNAL ALERT"
                    r'^VIP\s*Channel\b.*?$',         # Exact: "VIP Channel"
                    r'^📊\s*Analysis\b.*?$',         # Exact: "📊 Analysis"
                    r'^🚨\s*Alert\b.*?$',            # Exact: "🚨 Alert"
                    r'^🔚\s*END\b.*?$',              # Exact: "🔚 END"
                ]
                patterns = exact_header_patterns
            
            # Process headers at beginning of message only
            lines = text.split('\n')
            filtered_lines = []
            header_section = True  # Track if we're still in header section
            
            for line in lines:
                line_removed = False
                
                # Only check for headers at the beginning of the message
                if header_section and line.strip():
                    # Check each pattern against the current line
                    for pattern in patterns:
                        try:
                            # Create exact match pattern for headers
                            # Match the exact phrase at start of line
                            if re.match(pattern, line.strip(), re.IGNORECASE):
                                line_removed = True
                                break
                        except re.error as regex_error:
                            continue
                    
                    # Once we encounter a non-header line, stop looking for headers
                    if not line_removed:
                        header_section = False
                
                # Keep lines that don't match header patterns
                if not line_removed:
                    filtered_lines.append(line)
            
            # Rejoin lines preserving original formatting
            result_text = '\n'.join(filtered_lines)
            
            # Clean up leading whitespace but preserve formatting
            result_text = result_text.lstrip()
            
            # If result is empty or only whitespace, return original
            if not result_text or result_text.isspace():
                return original_text
            
            return result_text
            
        except Exception as e:
            print(f"Error removing headers: {e}")
            return text
    
    # Test cases
    test_cases = [
        # Basic header removal
        ("🔥 VIP ENTRY\nThis is the main content", "This is the main content"),
        ("📢 SIGNAL ALERT: Important\nActual message here", "Actual message here"),
        
        # Multiple headers
        ("🔥 VIP ENTRY\n📢 SIGNAL ALERT\nContent starts here", "Content starts here"),
        
        # Header with formatting
        ("🔥 VIP ENTRY: **Bold header**\n*Italic content* follows", "*Italic content* follows"),
        
        # No header
        ("Regular message without header", "Regular message without header"),
        
        # Header in middle (should not be removed)
        ("Content here\n🔥 VIP ENTRY\nMore content", "Content here\n🔥 VIP ENTRY\nMore content"),
        
        # Empty input
        ("", ""),
    ]
    
    print("=== HEADER REMOVAL TESTS ===")
    all_passed = True
    
    for i, (input_text, expected) in enumerate(test_cases, 1):
        result = _remove_headers(input_text)
        passed = result == expected
        all_passed = all_passed and passed
        
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"Test {i}: {status}")
        print(f"  Input:    '{repr(input_text)}'")
        print(f"  Expected: '{repr(expected)}'")
        print(f"  Got:      '{repr(result)}'")
        print()
    
    return all_passed

def test_footer_removal():
    """Test the improved footer removal function"""
    
    def _remove_footers(text: str, patterns: list = None) -> str:
        """Enhanced footer removal with exact phrase matching at end of message"""
        try:
            if not text:
                return text
                
            original_text = text
            
            # If no patterns provided, use conservative exact-match patterns
            if not patterns:
                # More conservative default patterns for exact footer removal
                exact_footer_patterns = [
                    r'^🔚\s*END\b.*?$',              # Exact: "🔚 END"
                    r'^👉\s*Join\b.*?$',             # Exact: "👉 Join our VIP channel"
                    r'^Contact\s*@admin\b.*?$',      # Exact: "Contact @admin for more info"
                    r'^📱\s*Contact\b.*?$',          # Exact: "📱 Contact us"
                    r'^💌\s*Subscribe\b.*?$',        # Exact: "💌 Subscribe to"
                ]
                patterns = exact_footer_patterns
            
            # Process footers at end of message only
            lines = text.split('\n')
            filtered_lines = list(lines)
            
            # Process lines from bottom to top to remove footers cleanly
            footer_section = True  # Track if we're still in footer section
            
            for i in range(len(lines) - 1, -1, -1):
                line = lines[i]
                line_removed = False
                
                # Only check for footers at the end of the message
                if footer_section and line.strip():
                    # Check each pattern against the current line
                    for pattern in patterns:
                        try:
                            # Create exact match pattern for footers
                            # Match the exact phrase at start of line (footers are typically single lines)
                            if re.match(pattern, line.strip(), re.IGNORECASE):
                                # Remove this line from the filtered list
                                if i < len(filtered_lines):
                                    filtered_lines.pop(i)
                                    line_removed = True
                                    break
                        except re.error as e:
                            continue
                    
                    # Once we encounter a non-footer line, stop looking for footers
                    if not line_removed:
                        footer_section = False
                # Skip empty lines while in footer section
                elif not line.strip():
                    continue
                else:
                    footer_section = False
            
            # Rejoin lines preserving original formatting
            result_text = '\n'.join(filtered_lines)
            
            # Clean up trailing whitespace but preserve formatting
            result_text = result_text.rstrip()
            
            # If result is empty or only whitespace, return original
            if not result_text or result_text.isspace():
                return original_text
            
            return result_text
            
        except Exception as e:
            print(f"Error removing footers: {e}")
            return text
    
    # Test cases
    test_cases = [
        # Basic footer removal
        ("Main content here\n🔚 END", "Main content here"),
        ("Important message\n👉 Join our VIP channel", "Important message"),
        
        # Multiple footers
        ("Content\n👉 Join us\n🔚 END", "Content"),
        
        # Footer with formatting
        ("*Bold content*\n📱 Contact us for more", "*Bold content*"),
        
        # No footer
        ("Regular message without footer", "Regular message without footer"),
        
        # Footer in middle (should not be removed)
        ("Content\n🔚 END\nMore content", "Content\n🔚 END\nMore content"),
        
        # Empty input
        ("", ""),
    ]
    
    print("=== FOOTER REMOVAL TESTS ===")
    all_passed = True
    
    for i, (input_text, expected) in enumerate(test_cases, 1):
        result = _remove_footers(input_text)
        passed = result == expected
        all_passed = all_passed and passed
        
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"Test {i}: {status}")
        print(f"  Input:    '{repr(input_text)}'")
        print(f"  Expected: '{repr(expected)}'")
        print(f"  Got:      '{repr(result)}'")
        print()
    
    return all_passed

def test_format_preservation():
    """Test that markdown and formatting is preserved during cleaning"""
    
    def _remove_mentions(text: str, placeholder: str = "[User]") -> str:
        """Enhanced mention removal with comprehensive pattern matching and clean formatting"""
        if not text:
            return text
        try:
            original_text = text
            
            # Comprehensive mention patterns covering all edge cases
            mention_patterns = [
                # Mentions in parentheses like (@xyz) - remove the whole parentheses
                r'\(\s*@[a-zA-Z0-9_]{1,32}\s*\)',
                # Mentions with preceding punctuation, e.g., ,@xyz -> remove cleanly
                r'([,\.;:!?\s])\s*@[a-zA-Z0-9_]{1,32}\b',
                # Standard @username patterns at word boundaries
                r'\b@[a-zA-Z0-9_]{1,32}\b',
                # User links with IDs
                r'tg://user\?id=\d+',
            ]
            
            # Apply patterns with specific replacement logic
            for i, pattern in enumerate(mention_patterns):
                if i == 0:  # Parentheses mentions - remove entirely
                    text = re.sub(pattern, '', text)
                elif i == 1:  # Mentions with preceding punctuation - keep punctuation
                    text = re.sub(pattern, r'\1', text)
                else:  # Standard patterns - replace with placeholder if provided
                    if placeholder:
                        text = re.sub(pattern, placeholder, text)
                    else:
                        text = re.sub(pattern, '', text)
            
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
    
    # Test cases for format preservation
    test_cases = [
        # Bold formatting
        ("**Bold text** with @mention", "**Bold text** with [User]"),
        ("*Single asterisk* @user here", "*Single asterisk* [User] here"),
        
        # Italic formatting
        ("_Italic text_ and @mention", "_Italic text_ and [User]"),
        ("__Double underscore__ @user", "__Double underscore__ [User]"),
        
        # Links
        ("[Link text](http://example.com) @mention", "[Link text](http://example.com) [User]"),
        ("Check https://example.com @user", "Check https://example.com [User]"),
        
        # Code formatting
        ("`code block` with @mention", "`code block` with [User]"),
        ("```\ncode\n``` @user", "```\ncode\n``` [User]"),
        
        # Mixed formatting
        ("**Bold** and _italic_ with @mention and [link](url)", "**Bold** and _italic_ with [User] and [link](url)"),
        
        # Complex case
        ("🔥 **SIGNAL**: Buy *CRYPTO* @trader\n\n[Chart](link) shows **strong** pattern", "🔥 **SIGNAL**: Buy *CRYPTO* [User]\n\n[Chart](link) shows **strong** pattern"),
    ]
    
    print("=== FORMAT PRESERVATION TESTS ===")
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
    
    # Run all tests
    mention_passed = test_mention_removal()
    header_passed = test_header_removal()
    footer_passed = test_footer_removal()
    format_passed = test_format_preservation()
    
    # Summary
    print("=" * 50)
    print("TEST SUMMARY:")
    print(f"Mention Removal: {'✓ PASS' if mention_passed else '✗ FAIL'}")
    print(f"Header Removal:  {'✓ PASS' if header_passed else '✗ FAIL'}")
    print(f"Footer Removal:  {'✓ PASS' if footer_passed else '✗ FAIL'}")
    print(f"Format Preservation: {'✓ PASS' if format_passed else '✗ FAIL'}")
    
    all_passed = mention_passed and header_passed and footer_passed and format_passed
    print(f"\nOVERALL: {'✓ ALL TESTS PASSED' if all_passed else '✗ SOME TESTS FAILED'}")
    
    if not all_passed:
        sys.exit(1)