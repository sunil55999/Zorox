# Setup Guide for Telegram Message Copying Bot

## Quick Setup

1. **Copy environment file**:
   ```bash
   cp .env.example .env
   ```

2. **Get Telegram API credentials** from https://my.telegram.org/auth:
   - `TELEGRAM_API_ID` - Your API ID number
   - `TELEGRAM_API_HASH` - Your API hash string
   - `TELEGRAM_PHONE` - Your phone number with country code

3. **Create bot tokens** via @BotFather on Telegram:
   - `ADMIN_BOT_TOKEN` - For system management commands
   - `TELEGRAM_BOT_TOKEN_1` - For sending messages (main bot)
   - Additional tokens (optional) for load balancing

4. **Set admin user IDs**:
   - `ADMIN_USER_IDS` - Comma-separated list of user IDs who can control the bot

5. **Run the system**:
   ```bash
   python main.py
   ```

## Required Environment Variables

### Essential Configuration
```env
# Telegram API (from https://my.telegram.org/auth)
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdefghijklmnopqrstuvwxyz123456
TELEGRAM_PHONE=+1234567890

# Bot Tokens (from @BotFather)
ADMIN_BOT_TOKEN=1234567893:ABCDefGhIjKlMnOpQrStUvWxYz123456789
TELEGRAM_BOT_TOKEN_1=1234567890:ABCDefGhIjKlMnOpQrStUvWxYz123456789

# Admin Users
ADMIN_USER_IDS=123456789,987654321
```

## Bot Commands

### System Management
- `/start` - Get welcome message and help
- `/help` - Show available commands
- `/health` - Check system health
- `/status` - Show system status

### Pair Management
- `/addpair <source_id> <dest_id>` - Add message copying pair
- `/listpairs` - List all active pairs
- `/removepair <pair_id>` - Remove a pair
- `/pairinfo <pair_id>` - Get pair details

### Filtering Commands
- `/blockword <word> [pair_id]` - Block word globally or for specific pair
- `/unblockword <word> [pair_id]` - Remove word block
- `/listblocked [pair_id]` - List blocked words
- `/blockimage <pair_id>` - Block image (reply to image)
- `/unblockimage <hash> [pair_id]` - Remove image block
- `/listblockedimages [pair_id]` - List blocked images

### Advanced Filtering
- `/mentions <pair_id> <on/off> [placeholder]` - Configure mention removal
- `/headerregex <pair_id> <regex>` - Set header removal pattern
- `/footerregex <pair_id> <regex>` - Set footer removal pattern
- `/testfilter <pair_id> <text>` - Test filters on text

### Topic Forwarding
- `/addtopicpair <source_chat> <topic_id> <dest_channel> <name>` - Add topic→channel pair
- `/listtopicpairs` - List all topic pairs  
- `/removetopicpair <source_chat> <topic_id> <dest_channel>` - Remove topic pair
- `/topicstats` - Topic forwarding statistics

## Features

### Image Blocking
- **Perceptual hash-based duplicate detection**
- **Global and pair-specific blocking**
- **Configurable similarity thresholds**
- **Usage tracking and statistics**

### Text Filtering
- **Word/phrase blocking with regex support**
- **Mention removal with custom placeholders**
- **Header/footer removal using regex patterns**
- **Entity preservation during transformation**

### Premium Content Support
- **Custom emojis and special formatting**
- **Web page previews maintained**
- **Complete reply chain preservation**
- **Real-time edit/delete synchronization**

### Topic Forwarding Support
- **Group Topic → Channel forwarding**
- **Reply mapping and preservation**
- **Edit/delete synchronization for topics**
- **All existing filters apply to topic messages**
- **Channel → Channel forwarding remains unaffected**

### Multi-Bot Load Balancing
- **Automatic load distribution**
- **Health monitoring per bot**
- **Failover and retry mechanisms**
- **Rate limiting compliance**

## Getting Bot Tokens

1. **Message @BotFather** on Telegram
2. **Send `/newbot`** and follow instructions
3. **Choose a name** for your bot (e.g., "My Message Bot")
4. **Choose a username** (must end in 'bot', e.g., "mymessagebot")
5. **Copy the token** provided by BotFather
6. **Repeat for admin bot** (recommended to have separate bots)

## Getting Chat IDs

To copy messages between chats, you need their chat IDs:

1. **For channels**: Forward a message from the channel to @userinfobot
2. **For groups**: Add @userinfobot to the group and send `/id`
3. **For private chats**: Send `/id` to @userinfobot

## Getting Topic IDs

For group topics, you need the topic ID:

1. **Enable forum mode** in your group (Group Settings → Topics)
2. **Create or find the topic** you want to forward from
3. **Send a message** in that topic and check the message details
4. **Use developer tools** or forward a topic message to get the topic ID
5. **Alternative**: Use `/addtopicpair` with trial and error for topic ID

## Security Notes

- **Keep your tokens secure** - never share them publicly
- **Set admin user IDs** to restrict bot control access  
- **Use different tokens** for admin and message sending
- **Regular backups** are created automatically

## Troubleshooting

### Common Issues
1. **"Invalid configuration"** - Check all required environment variables are set
2. **"Cannot send messages"** - Verify bot tokens are correct and bots are added to chats
3. **"Permission denied"** - Make sure bots have proper permissions in channels/groups
4. **"Flood wait"** - System automatically handles rate limiting

### Getting Help
- Check logs in `logs/bot.log`
- Use `/health` command to check system status
- Verify environment variables match `.env.example`