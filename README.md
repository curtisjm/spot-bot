# Spot Bot

Spot Bot is a Discord bot for Cal Ballroom's campus spotting channel. Members post photos of people they spot around UC Berkeley and tag the people in or near the photo. The bot tracks two leaderboards:

- **Most Spotters:** how many people each poster has spotted.
- **Most Spotted:** how many times each tagged person has been spotted.

## Tracking Rules

A spotting is valid when it happens in the configured spotted channel and is posted by a non-bot user.

The bot counts these cases:

- A single message with at least one image attachment and at least one tagged non-bot user.
- A photo-only message plus tag-only message(s) from the same author within two minutes.
- A tag-only message followed by a photo from the same author within two minutes.
- A reply where someone replies to their own photo with tags within two minutes.
- Multiple tagged people in the same spotting; each tagged person counts once.
- Multiple tag messages for the same photo within two minutes; each distinct tagged person counts.

The bot does not count:

- Self-spots.
- Bot users.
- Mentions without a photo in the same message or within the two-minute same-author window.
- Replies to someone else's photo.
- Duplicate spottings of the same person in the same photo.

Edits and deletes are reconciled:

- Editing a spotting message updates the tracked users.
- Editing a split tag message updates the spotting tied to the photo.
- Deleting a tag message removes that spotting.
- Deleting a photo removes split spottings validated by that photo.
- `/backfill` rebuilds the server's data from channel history and handles adjacent photo/tag messages oldest-first.

## Slash Commands

| Command | Description | Permissions |
|---------|-------------|-------------|
| `/setup spotted #channel` | Set the channel to track spottings in this server | Admin only |
| `/setup leaderboard #channel` | Set the leaderboard channel in this server | Admin only |
| `/leaderboard` | Manually refresh this server's leaderboard | Everyone |
| `/mystats` | View your own stats in this server | Everyone |
| `/stats @user` | View another user's stats in this server | Everyone |
| `/spot add <message_link> @user` | Add a spotted user correction | Admin only |
| `/spot remove <message_link> @user` | Remove a spotted user correction | Admin only |
| `/spot rescan <message_link>` | Recompute a message and nearby two-minute context | Admin only |
| `/backfill` | Rebuild this server's stats from channel history | Admin only |

## Setup

Create a Discord application and bot in the Discord Developer Portal, then enable the **Message Content Intent**. The bot needs message attachment and mention data to validate spottings.

Server Members Intent is not required by the current implementation.

Create `.env`:

```bash
cp .env.example .env
```

Set:

```env
DISCORD_TOKEN=your_token_here
```

Then invite the bot to the server and run:

```text
/setup spotted #spotted-channel
/setup leaderboard #spotted-leaderboard
/backfill
```

## Running Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

Useful environment variables:

- `DISCORD_TOKEN` (required): bot token from the Discord Developer Portal.
- `DATABASE_PATH` (optional): SQLite file path, default `spot_bot.db`.
- `LEADERBOARD_UPDATE_INTERVAL` (optional): seconds between automatic leaderboard refreshes, default `3600`.
- `LEADERBOARD_SIZE` (optional): users shown per leaderboard section, default `10`.

## Docker Hosting

For a small VPS, Docker Compose is a good fit:

```bash
cp .env.example .env
# edit DISCORD_TOKEN in .env
docker compose up -d --build
docker compose logs -f spot-bot
```

The Compose service stores SQLite at `/data/spot_bot.db` on a named volume. Do not rely on the container writable layer for the database; it will be lost when the container is replaced.

Back up the SQLite database regularly. One simple backup command:

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

## Development

Run tests with:

```bash
python -m pytest tests -q
```

In this environment, `uv` can run the full test dependency set without a local virtualenv:

```bash
uv run --with pytest --with pytest-asyncio --with aiosqlite --with python-dotenv --with discord.py python -m pytest tests -q
```

The main files are:

- `bot.py`: Discord client, event handlers, slash commands, adjacent-message matching.
- `spotting.py`: message parsing and spotting normalization.
- `database.py`: SQLite schema, idempotent spotting storage, leaderboard queries, correction helpers.
- `tests/`: parser, storage, and bot-processing tests.
