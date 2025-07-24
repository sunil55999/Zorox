# Telegram Message Copying Bot System

A comprehensive, production-ready Telegram message copying bot system with advanced filtering capabilities, multi-bot support, and real-time monitoring dashboard.

## 🚀 Features

### Core Functionality
- **Multi-Bot Support**: Load balancing across multiple bot tokens
- **Real-Time Message Copying**: Instant synchronization between channels/groups
- **Advanced Message Filtering**: Comprehensive filtering system with multiple criteria
- **Image Duplicate Detection**: Perceptual hash-based duplicate image blocking
- **Reply Preservation**: Maintains message threading and reply relationships
- **Edit/Delete Sync**: Synchronizes message edits and deletions
- **Media Support**: Handles photos, videos, documents, audio, and voice messages

### Advanced Features
- **Smart Load Balancing**: Distributes workload across multiple bots
- **Health Monitoring**: Real-time system health and performance monitoring
- **Rate Limiting**: Intelligent rate limiting to avoid Telegram API limits
- **Error Recovery**: Automatic retry mechanisms with exponential backoff
- **Database Management**: SQLite with automatic backups and cleanup
- **Web Dashboard**: Modern web interface for monitoring and management
- **Real-Time Updates**: WebSocket-based live dashboard updates

### Filtering Capabilities
- **Word Blocking**: Block messages containing specific words or phrases
- **Regex Filtering**: Advanced pattern matching with custom regex
- **Media Type Filtering**: Allow/block specific media types
- **Length Filtering**: Minimum/maximum message length constraints
- **Time-Based Filtering**: Filter by time of day, day of week, message age
- **User-Based Filtering**: Block/allow specific users or bots
- **Link Blocking**: Block messages containing URLs or mentions
- **Forward Blocking**: Block forwarded messages
- **Global Blocks**: System-wide blocking rules across all pairs

### Content Processing
- **Mention Removal**: Replace @mentions with placeholders
- **Header/Footer Removal**: Remove promotional headers and footers
- **Text Transformation**: Word replacements and regex substitutions
- **Content Sanitization**: Clean and normalize message content

## 📋 Requirements

### System Requirements
- Python 3.8 or higher
- SQLite 3.x (included with Python)
- 4GB RAM minimum (8GB recommended for high-volume operations)
- 1GB disk space minimum

### Python Dependencies
All dependencies are automatically installed during setup:

