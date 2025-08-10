#!/usr/bin/env python3
"""
Script to check if bots have access to the chats in configured pairs
"""

import asyncio
import json
from database import DatabaseManager
from config import Config
from telegram import Bot
from telegram.error import TelegramError

async def check_chat_access():
    """Check if bots can access the chats configured in pairs"""
    
    config = Config()
    db_manager = DatabaseManager(config)
    await db_manager.initialize()
    
    print("Checking bot access to configured chats...")
    print("=" * 60)
    
    # Get all pairs
    pairs = await db_manager.get_pairs()
    print(f"Found {len(pairs)} configured pairs:\n")
    
    # Get bot tokens
    bot_tokens = await db_manager.get_bot_tokens(active_only=True)
    
    for pair in pairs:
        print(f"Pair {pair.id}: {pair.name}")
        print(f"  Source: {pair.source_chat_id}")
        print(f"  Destination: {pair.destination_chat_id}")
        print(f"  Status: {pair.status}")
        print(f"  Assigned bot token ID: {pair.bot_token_id}")
        
        # Determine which bot to use
        if pair.bot_token_id:
            # Use custom bot token
            custom_token = await db_manager.get_bot_token_by_id(pair.bot_token_id)
            if custom_token and custom_token['is_active']:
                bot_token = custom_token['token']
                bot_name = custom_token['name']
                print(f"  Using custom bot: {bot_name}")
            else:
                print(f"  ❌ Custom bot token {pair.bot_token_id} not found or inactive")
                continue
        else:
            # Use first available bot token
            if bot_tokens:
                bot_token = bot_tokens[0]['token']
                bot_name = bot_tokens[0]['name']
                print(f"  Using default bot: {bot_name}")
            else:
                print(f"  ❌ No active bot tokens found")
                continue
        
        # Test bot access to both chats
        bot = Bot(token=bot_token)
        
        # Test source chat access
        try:
            source_chat = await bot.get_chat(pair.source_chat_id)
            print(f"  ✅ Source chat accessible: {source_chat.title}")
        except TelegramError as e:
            print(f"  ❌ Source chat access failed: {e}")
        
        # Test destination chat access
        try:
            dest_chat = await bot.get_chat(pair.destination_chat_id)
            print(f"  ✅ Destination chat accessible: {dest_chat.title}")
        except TelegramError as e:
            print(f"  ❌ Destination chat access failed: {e}")
            if "Chat not found" in str(e):
                print(f"      This is causing the message forwarding failure!")
                print(f"      Solution: Add bot '@{bot_name}' to chat {pair.destination_chat_id}")
        
        print()

if __name__ == "__main__":
    asyncio.run(check_chat_access())