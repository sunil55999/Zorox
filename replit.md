# Telegram Message Copying Bot System

## Overview

This is a comprehensive, production-ready Telegram message copying bot system with advanced filtering capabilities, multi-bot support, and real-time monitoring dashboard. The system copies messages between Telegram channels/groups with sophisticated filtering, duplicate detection, and load balancing across multiple bot instances.

## User Preferences

```
Preferred communication style: Simple, everyday language.
```

## System Architecture

### Core Architecture Pattern
The system follows a modular, async-first architecture with clear separation of concerns:

- **Event-driven message processing** using Telethon for listening and python-telegram-bot for sending
- **Multi-bot load balancing** to distribute workload and avoid rate limits
- **Queue-based message processing** with priority handling and retry mechanisms
- **Real-time monitoring** with WebSocket-based dashboard updates
- **SQLite database** with automatic backups and cleanup

### Technology Stack
- **Backend**: Python 3.8+ with asyncio
- **Telegram APIs**: Telethon (receiving) + python-telegram-bot (sending)
- **Database**: SQLite with aiosqlite for async operations
- **Web Dashboard**: aiohttp with Jinja2 templating
- **Real-time Updates**: WebSockets
- **Optional**: Redis for caching (when available)
- **Image Processing**: PIL + imagehash for duplicate detection

## Key Components

### 1. Bot Manager (`bot_manager.py`)
- **Purpose**: Orchestrates multiple Telegram bots with intelligent load balancing
- **Key Features**:
  - Priority-based message queue system
  - Health monitoring per bot instance
  - Automatic failover and retry mechanisms
  - Rate limiting compliance

### 2. Message Processor (`message_processor.py`)  
- **Purpose**: Handles core message copying logic with advanced content transformation
- **Key Features**:
  - Full media handling (photos, videos, documents, audio) with entity preservation
  - Premium content support (custom emojis, special formatting, web page previews)
  - Complete reply chain preservation with mapping
  - Real-time edit/delete synchronization
  - Entity-aware content transformation maintaining formatting
  - Mention processing with placeholder replacement
  - Header/footer removal using regex patterns

### 3. Filter System (`filters.py`)
- **Purpose**: Advanced message filtering with multiple criteria and content transformation
- **Key Features**:
  - Word/phrase blocking with regex support (global and pair-specific)
  - Media type filtering with phash-based image duplicate detection
  - Mention removal with customizable placeholders
  - Regex-based header and footer removal per pair
  - Time-based filtering and user-based filtering
  - Entity preservation during text transformation
  - Content length limits and custom regex filters

### 4. Database Manager (`database.py`)
- **Purpose**: SQLite database operations with async support
- **Key Features**:
  - Message pair management
  - Message mapping tracking
  - Automatic backups
  - Statistics tracking

### 5. Image Handler (`image_handler.py`)
- **Purpose**: Comprehensive image blocking system with perceptual hashing
- **Key Features**:
  - Perceptual hash-based duplicate detection with configurable similarity thresholds
  - Global and pair-specific image blocking with usage tracking
  - Block management via bot commands with description and metadata
  - Hash caching for performance optimization
  - Automatic cleanup of unused blocks

### 6. Health Monitor (`health_monitor.py`)
- **Purpose**: System health tracking and alerting
- **Key Features**:
  - Performance metrics collection
  - Error rate monitoring
  - Resource usage tracking
  - Alert thresholds

### 7. Bot Management System (Enhanced `bot_manager.py`)
- **Purpose**: Complete bot-based management and monitoring interface
- **Key Features**:
  - Comprehensive Telegram command interface
  - Real-time system monitoring via bot commands
  - Full pair management through chat
  - Health diagnostics and error reporting

## Data Flow

### Message Processing Flow
1. **Message Reception**: Telethon client receives new messages from source chats
2. **Filtering**: Message passes through comprehensive filter system
3. **Content Processing**: Text transformation, media handling, reply preservation
4. **Queue Assignment**: Message added to priority queue with assigned bot
5. **Delivery**: Bot sends processed message to destination chat
6. **Mapping Storage**: Source-destination message mapping stored for edits/deletes
7. **Statistics Update**: Performance metrics and filter statistics updated

### Load Balancing Strategy
- **Health-based routing**: Messages assigned to healthiest available bot
- **Queue length consideration**: Distributes load based on current queue sizes
- **Failure handling**: Automatic reassignment on bot failures
- **Rate limit compliance**: Built-in delays and backoff strategies

### Database Schema
- **message_pairs**: Source-destination chat mappings with filters
- **message_mappings**: Individual message ID relationships
- **image_hashes**: Perceptual hashes for duplicate detection
- **filter_stats**: Performance and filtering statistics
- **bot_health**: Bot performance metrics

## External Dependencies

### Required APIs
- **Telegram Bot API**: For sending messages (requires bot tokens)
- **Telegram Client API**: For receiving messages (requires API ID/hash and phone)

### Python Packages
- **Core**: `python-telegram-bot`, `telethon`, `aiosqlite`, `aiohttp`
- **Optional**: `redis`, `PIL`, `imagehash`, `psutil`
- **Development**: `pytest`, `pytest-asyncio`

### Environment Variables
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE`
- `BOT_TOKEN_1`, `BOT_TOKEN_2`, etc. (multiple bot tokens)
- `REDIS_URL`, `USE_REDIS` (optional Redis configuration)
- Various performance and feature toggles

## Deployment Strategy

### Production Deployment
- **Process Management**: Single main process with async task management
- **Database**: SQLite with automatic backups (Postgres can be added via Drizzle later)
- **Monitoring**: Built-in health monitoring and web dashboard
- **Logging**: Structured logging to files and console
- **Error Handling**: Comprehensive error handling with automatic retries

### Scaling Considerations
- **Horizontal Scaling**: Multiple bot tokens for load distribution
- **Queue Management**: Priority-based message processing
- **Resource Monitoring**: CPU, memory, and network usage tracking
- **Database Optimization**: Automatic cleanup and indexing

### Configuration Management
- **Environment-based**: All configuration via environment variables
- **Runtime Updates**: Some settings can be changed via web dashboard
- **Validation**: Configuration validation on startup
- **Defaults**: Sensible defaults for all optional settings

### Security Features
- **Token Management**: Secure bot token handling
- **Access Control**: Source/destination chat validation
- **Content Filtering**: Comprehensive message filtering system
- **Error Isolation**: Individual bot failure doesn't affect others

## Recent Changes

### 2025-07-24: Critical Functionality Fixes - COMPLETED ✅
- **Image Blocking Commands**: Fixed `/blockimage` command by implementing Bot API download instead of Telethon client, with direct PIL/imagehash computation in bot_manager.py
- **Pair-Specific Word Filtering**: Verified and confirmed working - database persistence functional, filtering logic operational, command interface working
- **URL Forwarding**: Fixed and verified - all messages send with `disable_web_page_preview=False` throughout message_processor.py pipeline
- **Database Method Fix**: Added missing `get_pair_by_id()` method to DatabaseManager, resolving command failures
- **Command Safety**: Fixed null checking in `/blockword`, `/unblockword`, and `/blockimage` commands with proper user validation
- **Comprehensive Testing**: All fixes verified through automated testing - image blocking, word filtering, URL forwarding, and database operations all working
- **System Status**: Bot system operational with full functionality restored, all three reported critical issues resolved

### 2025-07-24: Complete Advanced Filtering System Implementation
- **Comprehensive filtering system**: Implemented phash-based image blocking with global/pair-specific scopes
- **Enhanced message processing**: Added full support for premium content, custom emojis, and special entities
- **Advanced text filtering**: Implemented mention removal with placeholders and regex-based header/footer removal
- **Bot command expansion**: Added 10+ new filtering commands for complete management
- **Entity preservation**: Full support for preserving message formatting, entities, and reply chains
- **Database enhancements**: Added blocked_images table with similarity thresholds and usage tracking

#### New Filtering Features:
- **Image blocking**: `/blockimage`, `/unblockimage`, `/listblockedimages` with perceptual hash similarity
- **Word filtering**: `/blockword`, `/unblockword`, `/listblocked` with global and pair-specific blocks
- **Advanced configuration**: `/mentions`, `/headerregex`, `/footerregex` for content transformation
- **Filter testing**: `/testfilter` for real-time filter validation

### 2025-07-24: Web Dashboard Removal and Bot-Only Management
- **Removed web dashboard components**: Deleted `web_dashboard.py`, `templates/`, `static/`, and `demo.py`
- **Enhanced bot management**: Added 20+ new Telegram bot commands for comprehensive system control
- **Updated main system**: Modified `main.py` to run without web dashboard dependencies
- **Architecture change**: System now operates entirely through Telegram bot commands, removing web interface dependency

### 2025-07-24: Complete System Enhancement and Auto Cleanup Implementation
- **Auto cleanup functionality**: Implemented comprehensive database cleanup with preview/execute modes
- **Enhanced command list**: Updated help system to show all 25+ available commands with complete descriptions
- **Premium content support**: Fixed message processing for premium emojis, custom formatting, and special entities
- **Image handling improvements**: Enhanced image processing with proper media type detection and blocking
- **Webpage preview support**: Enabled webpage preview handling in message forwarding
- **Entity preservation**: Complete entity conversion system for maintaining message formatting
- **Database cleanup methods**: Added `cleanup_old_messages`, `cleanup_old_errors`, `count_old_messages`, `count_old_errors`
- **Orphaned hash cleanup**: Implemented `cleanup_orphaned_hashes` in image handler for database optimization
- **Error rate optimization**: System health monitoring improvements to reduce false alerts
- **Critical entity parsing fix**: Fixed entity validation and conversion for proper message formatting
- **Image forwarding repair**: Enhanced media type detection and download handling for all media types
- **Premium content preservation**: Improved entity bounds checking and fallback mechanisms for premium emojis
- **Webpage preview enablement**: Removed disable_web_page_preview restrictions for proper link previews
- **Entity bounds validation**: Added text length validation to prevent entity parsing errors

### 2025-07-24: Complete Filtering System Implementation and Fixes
- **Fixed webpage previews**: Confirmed `disable_web_page_preview=False` is set throughout the system (5 instances) to enable proper link preview display
- **Implemented global word blocking**: Added `is_blocked_word()` function with configurable `GLOBAL_BLOCKED_WORDS` list that blocks messages containing spam keywords like "join", "promo", "subscribe", "contact", etc.
- **Enhanced image pHash blocking**: Confirmed `is_blocked_image()` function works with perceptual hash similarity comparison using imagehash library for duplicate image detection
- **Integrated comprehensive filtering**: All three filters (webpage previews, word blocking, image blocking) are properly integrated into the `process_new_message()` flow
- **Extended image support**: Enhanced image handler to process both MessageMediaPhoto and image documents (MIME type image/*)
- **Global configuration**: Added `GLOBAL_BLOCKED_WORDS` configuration in config.py with environment variable support for easy customization
- **Complete Bot API implementation**: All media sent via proper Bot API methods (send_photo, send_video, etc.) with bot sender appearance
- **Statistics tracking**: Added tracking for blocked words (`words_blocked`) and blocked images (`images_blocked`) in pair statistics

#### Technical Implementation Details:
- Word blocking: Case-insensitive partial matching against configurable global blocked words list
- Image blocking: Uses PIL + imagehash for perceptual hash computation and Hamming distance comparison with configurable similarity threshold
- Webpage previews: Set `disable_web_page_preview=False` in all send_message calls (text messages, media captions, and fallback scenarios)
- Integration: All filters applied before media download and message sending to maximize efficiency
- Media handling: Downloads via Telethon, sends via Bot API with automatic temporary file cleanup
- Configuration: Environment variable `GLOBAL_BLOCKED_WORDS` for customizable spam word lists