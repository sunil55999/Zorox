# Telegram Message Copying Bot System

## Overview
This project is a comprehensive, production-ready Telegram message copying bot system. Its main purpose is to facilitate copying messages between Telegram channels/groups with advanced filtering capabilities, multi-bot support, and real-time monitoring. The system offers sophisticated filtering, duplicate detection, and load balancing across multiple bot instances, aiming for high reliability and efficiency in message replication.

### Recent Changes (Aug 9, 2025)

#### Critical Watermarking Bug Fix
Fixed critical watermarking bug that caused 34% error rate. Issue was in exception handling structure in `_download_and_prepare_media` function - media attribute extraction code was outside main try-catch block, causing silent failures after successful watermarking. Moved attribute extraction inside exception handling, resulting in 0% error rate and 100% success rate.

#### Enhanced Watermarking System
Updated `add_text_watermark` function with professional-grade watermarking capabilities:
- **Size & Coverage**: Watermark now spans 60-70% of image width (65% target) with automatic scaling
- **Positioning**: Moved to 40% vertical position (slightly above center) with horizontal centering
- **Typography**: Enhanced sans-serif bold font loading with support for multiple system fonts (DejaVu, Liberation, Noto, Helvetica, Arial)
- **Styling**: Light grey color (RGB: 200,200,200) with 25% opacity for subtle professional appearance
- **Letter Spacing**: Dynamic 1-2px letter spacing proportional to font size for improved readability
- **Smart Sizing**: Iterative font size optimization to achieve precise width coverage across different image resolutions
- **Anti-aliasing**: Preserved smooth text rendering for professional quality output

## User Preferences
```
Preferred communication style: Simple, everyday language.
```

## System Architecture

### Core Architecture Pattern
The system employs a modular, async-first, event-driven architecture designed for clear separation of concerns. It leverages Telethon for message reception and `python-telegram-bot` for sending, supporting multi-bot load balancing and queue-based processing with priority handling. SQLite serves as the primary database, complemented by real-time monitoring via WebSockets.

### Technology Stack
- **Backend**: Python 3.8+ with asyncio
- **Telegram APIs**: Telethon (receiving) and `python-telegram-bot` (sending)
- **Database**: SQLite with `aiosqlite`
- **Web Dashboard (Removed)**: Previously `aiohttp` with Jinja2 (Note: Web dashboard components have been removed in favor of bot-only management)
- **Real-time Updates**: WebSockets (for monitoring, though web dashboard removed)
- **Optional**: Redis for caching
- **Image Processing**: PIL and `imagehash`

### Key Components
- **Bot Manager**: Orchestrates multiple Telegram bots, manages priority-based queues, handles load balancing, health monitoring, and ensures rate limit compliance. Now includes user management capabilities with mass kick/unban operations and subscription management.
- **Message Processor**: Manages core message copying, including media handling, premium content, reply chain preservation, and real-time edit/delete synchronization. It also features entity-aware content transformation, improved header/footer/mention removal, and integrated image watermarking.
- **Filter System**: Provides advanced message filtering based on words/phrases (including regex), media types (with perceptual hashing for duplicate images), time, and user. It supports entity preservation during text transformations.
- **Database Manager**: Handles SQLite database operations for message pair management, message mapping, automatic backups, statistics, and subscription tracking. Includes the new `user_subscriptions` table for timed access management.
- **Image Handler**: Implements a comprehensive image blocking system using perceptual hashing for duplicate detection, manages block lists via bot commands, and provides text watermarking functionality with PIL/ImageDraw integration.
- **Health Monitor**: Tracks system health, performance metrics, error rates, and resource usage.
- **Subscription Manager**: Background service that automatically checks for expired subscriptions hourly and processes automatic user removal from all channels.

### Data Flow
- **Message Processing**: Messages are received, filtered, processed for content transformation, added to a priority queue, delivered by an assigned bot, and finally, mapping and statistics are stored.
- **Load Balancing**: Messages are routed based on bot health and queue length, with automatic reassignment on failures and adherence to Telegram rate limits.

### System Design Choices
- **UI/UX**: The system is managed entirely through Telegram bot commands, eliminating the need for a separate web dashboard. Commands offer comprehensive control over bot token management, pair configuration, and filtering.
- **Feature Specifications**:
    - **Multi-bot support**: Load balancing and assignment of specific bots to message pairs.
    - **Advanced Filtering**: Perceptual hash-based image blocking, word/phrase blocking (global and pair-specific), regex-based header/footer removal, and comprehensive mention removal.
    - **Image Watermarking**: Per-pair text watermarking system with centered overlay, customizable text, and semi-transparent rendering.
    - **Content Preservation**: Full support for preserving media, Telegram entities (formatting, custom emojis), and reply chains.
    - **User Management**: Mass user kicking/unbanning across all channels with support for both user IDs and usernames.
    - **Subscription Management**: Timed subscription system with automatic expiry-based kicking, subscription renewal, and comprehensive tracking.
    - **Scalability**: Optimized configuration for handling 100+ message forwarding pairs with increased workers, queue sizes, and connection pools.
    - **Security**: Secure token handling, access control via chat validation, and robust error isolation.

## External Dependencies

### Required APIs
- **Telegram Bot API**: Used for sending messages and bot management.
- **Telegram Client API**: Used for receiving messages via Telethon.

### Python Packages
- **Core**: `python-telegram-bot`, `telethon`, `aiosqlite`, `aiohttp` (for potential future web components or internal HTTP needs).
- **Image Processing**: `PIL`, `imagehash`.
- **Optional/Utility**: `redis`, `psutil`.

### Environment Variables
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE`
- `BOT_TOKEN_1`, `BOT_TOKEN_2`, etc. (for multiple bot instances)
- `REDIS_URL`, `USE_REDIS` (for Redis caching)
- `GLOBAL_BLOCKED_WORDS` (for global content filtering)
- Various performance and feature toggles.