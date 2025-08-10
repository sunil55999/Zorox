#!/usr/bin/env python3
"""
Test script to verify that /addpair command fix works correctly
"""

import asyncio
import aiosqlite
import os
from database import DatabaseManager
from config import Config

async def test_addpair_fix():
    """Test the bot token retrieval methods"""
    
    # Initialize database with config
    config = Config()
    db_manager = DatabaseManager(config)
    await db_manager.initialize()
    
    print("Testing bot token retrieval methods...")
    print("=" * 50)
    
    # First, let's see if we have any bot tokens
    tokens = await db_manager.get_bot_tokens(active_only=False)
    print(f"Found {len(tokens)} bot tokens in database")
    
    if tokens:
        token_id = tokens[0]['id']
        print(f"\nTesting with token ID: {token_id}")
        
        # Test the old method that returns only string
        token_string = await db_manager.get_bot_token_string_by_id(token_id)
        print(f"get_bot_token_string_by_id({token_id}) returns: {type(token_string)} - {token_string}")
        
        # Test the correct method that returns full dict
        token_dict = await db_manager.get_bot_token_by_id(token_id)
        print(f"get_bot_token_by_id({token_id}) returns: {type(token_dict)}")
        if token_dict:
            print(f"  - id: {token_dict['id']}")
            print(f"  - name: {token_dict['name']}")
            print(f"  - username: {token_dict['username']}")
            print(f"  - is_active: {token_dict['is_active']}")
        
        print("\n✅ Fix verification:")
        print("- get_bot_token_string_by_id returns string (would cause error when accessing ['is_active'])")
        print("- get_bot_token_by_id returns dict (correct method for /addpair command)")
        
        # Test what would happen with the old buggy code
        try:
            # This would fail with old method
            if token_string and token_string['is_active']:  # This line would fail
                print("This should not print")
        except TypeError as e:
            print(f"\n❌ Old code would fail with: {e}")
        
        # Test with the fixed method
        try:
            if token_dict and token_dict['is_active']:
                print("✅ Fixed code works correctly")
        except Exception as e:
            print(f"❌ Fixed code failed: {e}")
    else:
        print("No bot tokens found in database. Add a token first using /addtoken command.")

if __name__ == "__main__":
    asyncio.run(test_addpair_fix())