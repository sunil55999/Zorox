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
- **Purpose**: Handles core message copying logic with content transformation
- **Key Features**:
  - Media handling (photos, videos, documents, audio)
  - Reply chain preservation
  - Edit/delete synchronization
  - Content sanitization and transformation

### 3. Filter System (`filters.py`)
- **Purpose**: Advanced message filtering with multiple criteria
- **Key Features**:
  - Word/phrase blocking with regex support
  - Media type filtering
  - Time-based filtering
  - User-based filtering
  - Global blocking rules

### 4. Database Manager (`database.py`)
- **Purpose**: SQLite database operations with async support
- **Key Features**:
  - Message pair management
  - Message mapping tracking
  - Automatic backups
  - Statistics tracking

### 5. Image Handler (`image_handler.py`)
- **Purpose**: Duplicate image detection using perceptual hashing
- **Key Features**:
  - Perceptual hash-based duplicate detection
  - Configurable similarity thresholds
  - Hash caching for performance

### 6. Health Monitor (`health_monitor.py`)
- **Purpose**: System health tracking and alerting
- **Key Features**:
  - Performance metrics collection
  - Error rate monitoring
  - Resource usage tracking
  - Alert thresholds

### 7. Web Dashboard (`web_dashboard.py`)
- **Purpose**: Real-time monitoring and management interface
- **Key Features**:
  - Live statistics updates via WebSockets
  - Pair management interface
  - System health visualization
  - Configuration management

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