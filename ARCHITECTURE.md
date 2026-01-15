# Spot Bot Architecture

## Overview

Spot Bot tracks @ mentions in a designated "spotted" channel and displays leaderboards showing who posts the most spots and who gets spotted most often.

## File Structure

```
spot-bot/
├── bot.py              # Main bot entry point and slash commands
├── database.py         # SQLite database operations
├── config.py           # Environment variable configuration
├── requirements.txt    # Python dependencies
├── .env                # Discord token (not in git)
└── .env.example        # Template for .env file
```

## Data Flow

1. User posts a message with @ mentions in the spotted channel
2. `on_message` event fires in `bot.py`
3. Bot checks if message is in the configured spotted channel
4. If message contains mentions:
   - Sender's count is incremented in `mention_senders` table
   - Each mentioned user's count is incremented in `mention_receivers` table
5. Leaderboard updates hourly (or on `/leaderboard` command)

## Database Schema

**mention_senders** - Tracks users who post spots
- `user_id` (INTEGER PRIMARY KEY) - Discord user ID
- `username` (TEXT) - Display name (updated on each message)
- `message_count` (INTEGER) - Number of messages with mentions

**mention_receivers** - Tracks users who get spotted
- `user_id` (INTEGER PRIMARY KEY) - Discord user ID
- `username` (TEXT) - Display name (updated when mentioned)
- `mention_count` (INTEGER) - Total times mentioned

**config** - Bot configuration
- `key` (TEXT PRIMARY KEY) - Config key name
- `value` (TEXT) - Config value

Config keys used:
- `spotted_channel_id` - Channel to monitor
- `leaderboard_channel_id` - Channel to post leaderboard
- `leaderboard_message_id` - ID of leaderboard message to edit

## Slash Commands

| Command | Description | Permissions |
|---------|-------------|-------------|
| `/setup spotted #channel` | Set spotted channel | Admin only |
| `/setup leaderboard #channel` | Set leaderboard channel | Admin only |
| `/leaderboard` | Manually refresh leaderboard | Everyone |
| `/mystats` | View your own stats | Everyone |
| `/stats @user` | View another user's stats | Everyone |

## Configuration

Environment variables in `.env`:
- `DISCORD_TOKEN` (required) - Bot token from Discord Developer Portal
- `DATABASE_PATH` (optional) - SQLite file path, default: `spot_bot.db`
- `LEADERBOARD_UPDATE_INTERVAL` (optional) - Seconds between updates, default: 3600
- `LEADERBOARD_SIZE` (optional) - Users shown on leaderboard, default: 10
