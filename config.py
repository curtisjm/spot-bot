import os
from dotenv import load_dotenv

load_dotenv()

# Bot token from environment
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Database file path
DATABASE_PATH = os.getenv("DATABASE_PATH", "spot_bot.db")

# Leaderboard auto-update interval in seconds (default: 1 hour)
LEADERBOARD_UPDATE_INTERVAL = int(os.getenv("LEADERBOARD_UPDATE_INTERVAL", 3600))

# Number of users to show on leaderboard
LEADERBOARD_SIZE = int(os.getenv("LEADERBOARD_SIZE", 10))

# Logging level
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Messages scanned between backfill progress updates
BACKFILL_PROGRESS_INTERVAL = int(os.getenv("BACKFILL_PROGRESS_INTERVAL", 500))
