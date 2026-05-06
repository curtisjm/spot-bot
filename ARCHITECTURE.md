# Spot Bot Architecture

## Overview

Spot Bot tracks image-based "spottings" in a configured Discord channel. A valid spotting is either a non-bot message with both an image attachment and at least one non-bot user mention, or a tag message from the photo author that is validated by a same-author photo within two minutes.

The leaderboard has two rankings:

- **Most Spotters:** how many people each poster has spotted.
- **Most Spotted:** how many times each tagged person has been spotted.

## File Structure

```
spot-bot/
├── bot.py                 # Discord client, event handlers, slash commands
├── spotting.py            # Message parsing and validation
├── database.py            # SQLite schema and queries
├── config.py              # Environment variable configuration
├── Dockerfile             # Container image for VPS hosting
├── docker-compose.yml     # Persistent single-service deployment
├── requirements.txt       # Python dependencies
├── tests/                 # Unit tests for parser, storage, and bot processing
└── .env.example           # Template for local or Docker environment
```

## Data Flow

1. A user posts or edits a message in the configured spotted channel.
2. `spotting.parse_spotting_message` accepts same-message image+tag spottings.
3. If a message has only an image or only tags, `PendingSpottings` keeps recent same-author messages in memory for two minutes. One photo can validate multiple tag messages in that window.
4. A reply counts only when the author replies to their own photo with tags within two minutes.
5. Self-spots are filtered out, and the same spotted person can only count once per photo.
6. Valid spottings are stored as one `spot_messages` row and one `spottings` row per tagged user. For split photo/tag spottings, the tag-bearing message is the source `message_id`, and `photo_message_id` records the photo that made it valid.
7. Editing a split tag message updates that spotting. Deleting the tag message removes that spotting. Deleting the photo removes split spottings validated by that photo.
8. Leaderboards are computed from the event rows, so reprocessing a message is idempotent and multi-person photos count correctly.

## Database Schema

**spot_messages** - One row per valid Discord spotting message.

- `message_id` - Discord message ID, primary key.
- `guild_id` - Discord server ID.
- `channel_id` - Spotted channel ID.
- `spotter_id` - Poster user ID.
- `spotter_name` - Poster display name at processing time.
- `photo_message_id` - Discord message ID of the validating photo.

**spottings** - One row per tagged person per spotting message.

- `message_id` - Foreign key to `spot_messages`.
- `spotted_id` - Tagged user ID.
- `spotted_name` - Tagged user's display name at processing time.
- Primary key: `(message_id, spotted_id)`.

**guild_config** - Per-server bot configuration.

- `guild_id`
- `key`
- `value`
- Primary key: `(guild_id, key)`.

**config** remains as a legacy global fallback for older local databases.

Config keys:

- `spotted_channel_id` - Channel to monitor.
- `leaderboard_channel_id` - Channel to post leaderboard.
- `leaderboard_message_id` - Existing leaderboard message to edit.

## Slash Commands

| Command | Description | Permissions |
|---------|-------------|-------------|
| `/setup spotted #channel` | Set spotted channel for this server | Admin only |
| `/setup leaderboard #channel` | Set leaderboard channel for this server | Admin only |
| `/leaderboard` | Manually refresh this server's leaderboard | Everyone |
| `/mystats` | View your own stats in this server | Everyone |
| `/stats @user` | View another user's stats in this server | Everyone |
| `/spot add <message_link> @user` | Add a spotted user correction | Admin only |
| `/spot remove <message_link> @user` | Remove a spotted user correction | Admin only |
| `/spot rescan <message_link>` | Recompute a message and nearby two-minute context | Admin only |
| `/backfill` | Rebuild this server's stats from channel history | Admin only |

## Discord Setup

Enable the bot's Message Content Intent in the Discord Developer Portal. Discord returns empty `content`, `attachments`, and related message fields to apps without the Message Content privileged intent, and this bot needs attachments and mentions to validate spottings.

The Server Members Intent is not required for the current implementation.

## Docker Hosting

For a VPS, use Docker Compose:

```bash
cp .env.example .env
# edit DISCORD_TOKEN in .env
docker compose up -d --build
docker compose logs -f spot-bot
```

The Compose file mounts a named volume at `/data` and sets `DATABASE_PATH=/data/spot_bot.db`. Do not store the SQLite database only inside the container writable layer; it will be lost when the container is replaced.

Back up the database from the named volume regularly. A simple option is:

```bash
docker compose exec spot-bot python - <<'PY'
import sqlite3
src = sqlite3.connect('/data/spot_bot.db')
dst = sqlite3.connect('/data/spot_bot.backup.db')
src.backup(dst)
dst.close()
src.close()
PY
```

## Configuration

Environment variables:

- `DISCORD_TOKEN` (required) - Bot token from Discord Developer Portal.
- `DATABASE_PATH` (optional) - SQLite file path, default: `spot_bot.db`.
- `LEADERBOARD_UPDATE_INTERVAL` (optional) - Seconds between updates, default: `3600`.
- `LEADERBOARD_SIZE` (optional) - Users shown on leaderboard, default: `10`.
