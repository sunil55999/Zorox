# Telegram Message Copying Bot System

A comprehensive, production-ready Telegram message copying bot system with advanced filtering capabilities, multi-bot support, and complete bot-based management interface.

## Overview

This system copies messages between Telegram channels/groups with sophisticated filtering, duplicate detection, and load balancing across multiple bot instances. The entire system is managed through Telegram bot commands - no web interface required.

## Features

- ✅ **Multi-bot support** with intelligent load balancing
- ✅ **Advanced message filtering** with regex support
- ✅ **Real-time synchronization** of messages, edits, and deletions
- ✅ **Image duplicate detection** using perceptual hashing
- ✅ **Reply preservation** and thread management
- ✅ **Comprehensive bot-based management** via Telegram commands
- ✅ **Health monitoring and diagnostics**
- ✅ **Queue management** with priority processing
- ✅ **Error tracking and logging**
- ✅ **Group Topic → Channel forwarding** with reply mapping
- ✅ **Mixed forwarding support** (channel→channel + topic→channel)

## Bot Management Commands

### System Management
- `/status` - System status and overview
- `/stats` - Detailed statistics
- `/health` - Health monitoring report
- `/pause` - Pause message processing
- `/resume` - Resume message processing
- `/restart` - Restart bot system (planned)

### Pair Management
- `/pairs` - List all message pairs
- `/addpair <source> <dest> <name>` - Add new pair
- `/delpair <id>` - Delete pair
- `/editpair <id> <setting> <value>` - Edit pair settings
- `/pairinfo <id>` - Detailed pair information

### Topic Forwarding
- `/addtopicpair <source_chat> <topic_id> <dest_channel> <name>` - Add topic→channel pair
- `/listtopicpairs` - List all topic pairs
- `/removetopicpair <source_chat> <topic_id> <dest_channel>` - Remove topic pair
- `/topicstats` - Topic forwarding statistics

### Bot Management
- `/bots` - List all bot instances
- `/botinfo <index>` - Detailed bot information
- `/rebalance` - Rebalance message distribution

### Queue & Processing
- `/queue` - View message queue status
- `/clearqueue` - Clear message queue

### Logs & Diagnostics
- `/logs [limit]` - View recent log entries
- `/errors [limit]` - View recent errors
- `/diagnostics` - Run system diagnostics

### Settings
- `/settings` - View current settings
- `/set <key> <value>` - Update setting

### Utilities
- `/backup` - Create database backup (planned)
- `/cleanup` - Clean old data (planned)
- `/help` - Show all available commands

## Quick Start

### 1. Environment Variables

Create a `.env` file with the following variables:

```bash
# Telegram API credentials (get from https://my.telegram.org)
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890

# Bot tokens (get from @BotFather)
BOT_TOKEN_1=your_first_bot_token
BOT_TOKEN_2=your_second_bot_token  # Optional, for load balancing
# Add more BOT_TOKEN_X as needed

# Admin user IDs (comma-separated)
ADMIN_USER_IDS=123456789,987654321

# Optional settings
DEBUG_MODE=false
MAX_WORKERS=4
MESSAGE_QUEUE_SIZE=1000
```

### 2. Install Dependencies

```bash
# Dependencies are automatically installed via pyproject.toml
python -m pip install -e .
```

### 3. Run the System

```bash
python main.py
```

### 4. Bot Setup

1. Add your bot(s) to the channels/groups you want to copy from
2. Use `/addpair <source_chat_id> <dest_chat_id> <name>` to create message pairs
3. Use `/status` to monitor system health
4. Use `/help` to see all available commands

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_API_ID` | Yes | API ID from my.telegram.org |
| `TELEGRAM_API_HASH` | Yes | API Hash from my.telegram.org |
| `TELEGRAM_PHONE` | Yes | Phone number for Telethon client |
| `BOT_TOKEN_1` | Yes | Primary bot token from @BotFather |
| `BOT_TOKEN_2` | No | Secondary bot token for load balancing |
| `ADMIN_USER_IDS` | No | Comma-separated admin user IDs |
| `DEBUG_MODE` | No | Enable debug mode (default: false) |
| `MAX_WORKERS` | No | Maximum worker threads (default: 4) |
| `MESSAGE_QUEUE_SIZE` | No | Queue size limit (default: 1000) |

### Getting Telegram Credentials

1. **API ID/Hash**: Visit https://my.telegram.org → API development tools
2. **Bot Tokens**: Message @BotFather on Telegram → /newbot
3. **Chat IDs**: Forward a message from the target chat to your bot, use `/get_chat_id`

## Architecture

The system follows a modular, async-first architecture:

- **Event-driven message processing** using Telethon for listening and python-telegram-bot for sending
- **Multi-bot load balancing** to distribute workload and avoid rate limits
- **Priority-based message queue** with retry mechanisms
- **SQLite database** with automatic backups and cleanup
- **Complete bot-based management** replacing traditional web dashboards

## File Structure

```
├── main.py                 # Main entry point
├── bot_manager.py          # Core bot management with all commands
├── database.py             # Database operations
├── message_processor.py    # Message processing logic
├── config.py              # Configuration management
├── health_monitor.py      # System health monitoring
├── filters.py             # Message filtering system
├── image_handler.py       # Image duplicate detection
├── replit.md             # Project documentation
└── tests/                # Test suite
```

## Usage Examples

### Creating a Message Pair

```
/addpair -1001234567890 -1009876543210 "News Channel → Discussion"
```

### Creating a Topic Forwarding Pair

```
/addtopicpair -1001234567890 123 -1009876543210 "Trading Signals Topic"
```

### Monitoring System Health

```
/health
/status
/diagnostics
```

### Managing Bot Load

```
/bots
/rebalance
/botinfo 0
```

### Queue Management

```
/queue
/clearqueue
```

## Troubleshooting

### Common Issues

1. **Bot not responding**: Check bot tokens and permissions
2. **Rate limits**: Use multiple bot tokens and `/rebalance`
3. **Missing messages**: Check source chat permissions
4. **High memory usage**: Use `/cleanup` and monitor `/health`

### Debug Commands

- `/diagnostics` - Full system health check
- `/errors` - Recent error log
- `/botinfo <index>` - Individual bot status

## Development

### Running Tests

```bash
python -m pytest tests/
```

### Adding New Commands

1. Add handler to `_setup_command_handlers()` in `bot_manager.py`
2. Implement command method following pattern `_cmd_commandname()`
3. Update help text in `_cmd_help()`

## License

This project is licensed under the MIT License.

## Support

For issues and questions:
1. Check `/diagnostics` for system status
2. Review logs with `/logs` and `/errors`
3. Use `/help` for command reference