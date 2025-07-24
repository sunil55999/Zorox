#!/usr/bin/env python3
"""
Final test script for all improved text cleaning functions
Demonstrates the fixed mention removal, header/footer removal with format preservation
"""

import re

def test_improved_mention_removal():
    """Test the fixed mention removal that addresses all the requirements"""
    
    def _remove_mentions(text: str, placeholder: str = "[User]") -> str:
        if not text:
            return text
        try:
            original_text = text
            
            # Step 1: Handle mentions in parentheses - remove entire parentheses
            text = re.sub(r'\(\s*@[a-zA-Z0-9_]{1,32}\s*\)', '', text)
            
            # Step 2: Handle @mentions preceded by punctuation - clean up punctuation  
            text = re.sub(r'([,\.;:!?]\s*)@[a-zA-Z0-9_]{1,32}\b', r'\1', text)
            
            # Step 3: Handle standard @mentions (but not email addresses) - replace with placeholder or remove
            if placeholder:
                # Match @mentions at word boundaries, but not after alphanumeric chars (emails)
                text = re.sub(r'(?<!\w)@[a-zA-Z0-9_]{1,32}\b', placeholder, text)
            else:
                text = re.sub(r'(?<!\w)@[a-zA-Z0-9_]{1,32}\b', '', text)
            
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
    
    test_cases = [
        # Requirement 1: Remove all @mentions
        ("Hello @john how are you?", "Hello [User] how are you?"),
        ("@alice and @bob are here", "[User] and [User] are here"),
        
        # Requirement 1: Mentions in parentheses
        ("Check this out (@username)", "Check this out"),
        ("Message from (@alice) to you", "Message from to you"),
        
        # Requirement 1: Mentions at start, middle, end
        ("@user at start", "[User] at start"),
        ("In middle @user here", "In middle [User] here"),
        ("At the end @user", "At the end [User]"),
        
        # Requirement 1: Remove trailing punctuation without breaking sentences
        ("Hello, @john!", "Hello!"),
        ("Thanks @admin.", "Thanks."),
        
        # Requirement 3: Preserve formatting
        ("**Bold text** with @mention", "**Bold text** with [User]"),
        ("*Italic text* and @user here", "*Italic text* and [User] here"),
        ("_Underline_ @mention", "_Underline_ [User]"),
        ("[Link](http://example.com) @mention", "[Link](http://example.com) [User]"),
        
        # Requirement 3: Don't break markdown
        ("**Bold @user text**", "**Bold [User] text**"),
        ("_Italic @mention here_", "_Italic [User] here_"),
        
        # Edge cases - don't break emails
        ("email@domain.com is not a mention", "email@domain.com is not a mention"),
        ("Contact me at admin@site.org for help", "Contact me at admin@site.org for help"),
    ]
    
    print("=== IMPROVED MENTION REMOVAL TESTS ===")
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
        if not passed:
            print(f"  ISSUE:    Different from expected")
        print()
    
    return all_passed

def test_header_footer_removal():
    """Test header and footer removal with exact phrase matching"""
    
    def _remove_headers(text: str, patterns: list = None) -> str:
        try:
            if not text:
                return text
                
            original_text = text
            
            if not patterns:
                exact_header_patterns = [
                    r'^🔥\s*VIP\s*ENTRY\b.*?$',
                    r'^📢\s*SIGNAL\s*ALERT\b.*?$', 
                    r'^🔚\s*END\b.*?$',
                ]
                patterns = exact_header_patterns
            
            lines = text.split('\n')
            filtered_lines = []
            header_section = True
            
            for line in lines:
                line_removed = False
                
                if header_section and line.strip():
                    for pattern in patterns:
                        try:
                            if re.match(pattern, line.strip(), re.IGNORECASE):
                                line_removed = True
                                break
                        except re.error:
                            continue
                    
                    if not line_removed:
                        header_section = False
                
                if not line_removed:
                    filtered_lines.append(line)
            
            result_text = '\n'.join(filtered_lines).lstrip()
            
            if not result_text or result_text.isspace():
                return original_text
            
            return result_text
            
        except Exception as e:
            print(f"Error removing headers: {e}")
            return text

    def _remove_footers(text: str, patterns: list = None) -> str:
        try:
            if not text:
                return text
                
            original_text = text
            
            if not patterns:
                exact_footer_patterns = [
                    r'^🔚\s*END\b.*?$',
                    r'^👉\s*Join\b.*?$',
                ]
                patterns = exact_footer_patterns
            
            lines = text.split('\n')
            filtered_lines = list(lines)
            footer_section = True
            
            for i in range(len(lines) - 1, -1, -1):
                line = lines[i]
                line_removed = False
                
                if footer_section and line.strip():
                    for pattern in patterns:
                        try:
                            if re.match(pattern, line.strip(), re.IGNORECASE):
                                if i < len(filtered_lines):
                                    filtered_lines.pop(i)
                                    line_removed = True
                                    break
                        except re.error:
                            continue
                    
                    if not line_removed:
                        footer_section = False
                elif not line.strip():
                    continue
                else:
                    footer_section = False
            
            result_text = '\n'.join(filtered_lines).rstrip()
            
            if not result_text or result_text.isspace():
                return original_text
            
            return result_text
            
        except Exception as e:
            print(f"Error removing footers: {e}")
            return text

    test_cases = [
        # Requirement 2: Only exact header/footer phrases at beginning/end
        ("🔥 VIP ENTRY\nThis is the main content", "This is the main content"),
        ("📢 SIGNAL ALERT: Important\nActual message here", "Actual message here"),
        ("Main content here\n🔚 END", "Main content here"),
        ("Important message\n👉 Join our VIP channel", "Important message"),
        
        # Requirement 2: Don't disrupt markdown formatting
        ("🔥 VIP ENTRY\n**Bold content** follows", "**Bold content** follows"),
        ("*Italic message*\n🔚 END", "*Italic message*"),
        
        # Requirement 2: Don't modify other parts (middle of message)
        ("Content here\n🔥 VIP ENTRY\nMore content", "Content here\n🔥 VIP ENTRY\nMore content"),
        ("Content\n🔚 END\nMore content", "Content\n🔚 END\nMore content"),
        
        # Requirement 3: Preserve URLs and links
        ("🔥 VIP ENTRY\n[Chart](http://example.com) shows **trend**", "[Chart](http://example.com) shows **trend**"),
    ]
    
    print("=== HEADER/FOOTER REMOVAL TESTS ===")
    all_passed = True
    
    for i, (input_text, expected) in enumerate(test_cases, 1):
        # Test header removal
        result = _remove_headers(input_text)
        if result != input_text:  # If header was removed, test that
            expected_after_header = expected
        else:
            # Test footer removal
            result = _remove_footers(input_text)
            expected_after_header = expected
        
        passed = result == expected
        all_passed = all_passed and passed
        
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"Test {i}: {status}")
        print(f"  Input:    '{repr(input_text)}'")
        print(f"  Expected: '{repr(expected)}'")
        print(f"  Got:      '{repr(result)}'")
        print()
    
    return all_passed

if __name__ == "__main__":
    print("Testing All Improved Text Cleaning Functions")
    print("=" * 60)
    
    mention_passed = test_improved_mention_removal()
    header_footer_passed = test_header_footer_removal()
    
    print("=" * 60)
    print("FINAL TEST SUMMARY:")
    print(f"✓ Mention Removal (Fixed): {'PASS' if mention_passed else 'FAIL'}")
    print(f"✓ Header/Footer Removal:   {'PASS' if header_footer_passed else 'FAIL'}")
    print()
    
    if mention_passed and header_footer_passed:
        print("🎉 ALL TEXT CLEANING IMPROVEMENTS IMPLEMENTED SUCCESSFULLY!")
        print()
        print("SUMMARY OF FIXES:")
        print("1. ✓ Mention Removal:")
        print("   - Removes @username, (@username), ,@username properly")
        print("   - Preserves email addresses (email@domain.com)")
        print("   - Cleans up trailing punctuation without breaking sentences")
        print("   - Preserves markdown formatting (**bold**, _italic_, [links](url))")
        print()
        print("2. ✓ Header/Footer Removal:")
        print("   - Only removes exact phrases at beginning/end of messages")
        print("   - Preserves markdown formatting and URLs")
        print("   - Does not modify content in middle of messages")
        print()
        print("3. ✓ Format Preservation:")
        print("   - Maintains all markdown: *bold*, _italic_, **, __, [text](url)")
        print("   - No extra *, _, or unnecessary characters added")
        print("   - Original formatting structure preserved")
    else:
        print("❌ Some tests failed - improvements need refinement")
        import sys
        sys.exit(1)