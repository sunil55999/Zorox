# Header/Footer Removal Guide

## Quick Setup Commands

### Set Header Removal Pattern
```
/headerregex <pair_id> <pattern>
```

### Set Footer Removal Pattern  
```
/footerregex <pair_id> <pattern>
```

### Clear Patterns
```
/headerregex <pair_id> clear
/footerregex <pair_id> clear
```

## Common Patterns

### Trading Signal Headers
```
/headerregex 1 ^🔥\s*VIP\s*ENTRY\b.*?$
/headerregex 1 ^📢\s*SIGNAL\s*ALERT\b.*?$
/headerregex 1 ^⚡\s*PREMIUM\b.*?$
```

### Trading Signal Footers
```
/footerregex 1 ^🔚\s*END\b.*?$
/footerregex 1 ^✅\s*DONE\b.*?$
/footerregex 1 ^🎯\s*COMPLETE\b.*?$
```

### Channel Promotion Headers/Footers
```
/headerregex 1 ^.*JOIN.*CHANNEL.*$
/footerregex 1 ^.*@\w+.*SUBSCRIBE.*$
```

## How It Works

- **Headers**: Removed from the beginning of messages only
- **Footers**: Removed from the end of messages only  
- **Pattern matching**: Uses regex with case-insensitive matching
- **Structure preserved**: Message formatting and line breaks maintained
- **Safe removal**: Original message returned if removal would result in empty content

## Current Status
✅ Header/Footer removal system is working correctly
✅ Database patterns fixed and operational
✅ Message structure preservation confirmed