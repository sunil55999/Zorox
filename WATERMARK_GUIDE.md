# Text Watermark Feature Guide

## Overview
The Telegram Message Copying Bot System now supports per-pair text watermarking for forwarded images. This feature allows you to add semi-transparent text overlays to images before they are forwarded to destination channels.

## Features
- **Per-pair toggle**: Enable or disable watermarking for each message pair independently
- **Custom text**: Set custom watermark text for each pair
- **Semi-transparent overlay**: Watermark appears with 40% opacity for subtle branding
- **Auto-scaling**: Font size automatically scales to 5% of image width (minimum 12px)
- **Center positioning**: Text is automatically centered on the image
- **Multiple formats**: Works with JPEG, PNG, and WebP images
- **Quality preservation**: Images are saved as high-quality JPEG (95% quality)

## Usage

### Enable Watermarking
```
/watermark <pair_id> enable <text>
```
**Examples:**
- `/watermark 5 enable @Traders_Hive`
- `/watermark 1 enable © My Channel`
- `/watermark 3 enable Trading Signals 2024`

### Disable Watermarking
```
/watermark <pair_id> disable
```
**Example:**
- `/watermark 5 disable`

### Update Watermark Text
Simply use the enable command with new text:
```
/watermark 5 enable @NewChannelName
```

## Technical Details

### Database Storage
Watermark settings are stored in the `filters` JSON column of the `pairs` table:
```json
{
  "watermark_enabled": true,
  "watermark_text": "@Traders_Hive"
}
```

### Processing Pipeline
1. Message received via Telethon
2. Image downloaded to temporary file
3. Watermark applied if enabled for the pair
4. Watermarked image sent via Bot API
5. Temporary files cleaned up

### Font Handling
The system attempts to load fonts in this order:
1. DejaVu Sans Bold (Linux)
2. Arial (macOS/Windows)
3. System default font
4. Basic text rendering (fallback)

### Performance Considerations
- Watermarking adds minimal processing time (~0.1-0.5 seconds per image)
- Original image quality is preserved with high-quality JPEG output
- Memory usage is optimized with proper cleanup of temporary files
- Supports concurrent processing across multiple bot instances

### Image Format Support
- **Input formats**: All formats supported by PIL (JPEG, PNG, WebP, BMP, etc.)
- **Output format**: JPEG (for consistent compatibility)
- **Quality**: 95% JPEG quality to maintain visual fidelity

### Error Handling
- Graceful fallback if image processing libraries unavailable
- Automatic cleanup of temporary files on errors
- Detailed logging for troubleshooting
- Original image forwarded if watermarking fails

## Examples

### Basic Setup
```bash
# Enable watermarking for pair 1 with channel name
/watermark 1 enable @MyTradingChannel

# Check current status
/pairinfo 1
```

### Advanced Usage
```bash
# Enable with copyright notice
/watermark 2 enable © Trading Insights 2024

# Enable with multiple elements
/watermark 3 enable @Channel | Premium Signals

# Disable watermarking but keep text for future use
/watermark 2 disable
```

### Batch Configuration
```bash
# Configure multiple pairs with same watermark
/watermark 1 enable @TradingHub
/watermark 2 enable @TradingHub  
/watermark 3 enable @TradingHub
```

## Troubleshooting

### Common Issues

**Watermark not appearing:**
- Verify watermarking is enabled: `/pairinfo <pair_id>`
- Check that watermark text is set
- Ensure image processing libraries are available

**Text too small/large:**
- Font size automatically scales to image width
- Minimum font size is 12px regardless of image size
- For very small images, consider the text length

**Performance concerns:**
- Watermarking processes images sequentially per bot
- Multiple bots can process different pairs simultaneously
- Consider pair distribution across bots for high-volume scenarios

### Log Messages
- `Applied watermark to image for pair X` - Success
- `Failed to apply watermark to image for pair X` - Processing error
- `Image processing not available, skipping watermark` - Missing libraries

## Integration Notes

The watermark feature integrates seamlessly with existing functionality:
- **Works with**: All existing filters and processing
- **Compatible with**: Multi-bot load balancing
- **Preserves**: Original message entities and metadata
- **Maintains**: Reply chains and message mapping

## Requirements

- PIL (Python Imaging Library) - Available in environment
- imagehash library - Available in environment
- System fonts (for best appearance)

## Security Notes

- Watermark text is stored in the database
- No sensitive information should be used in watermark text
- Admin-only command access (respects existing permission system)
- Temporary files are securely cleaned up after processing