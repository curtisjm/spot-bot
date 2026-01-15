import aiosqlite
from config import DATABASE_PATH


async def init_db():
    """Initialize the database with required tables."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mention_senders (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                message_count INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mention_receivers (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                mention_count INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.commit()


async def get_config(key: str) -> str | None:
    """Get a configuration value."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def set_config(key: str, value: str):
    """Set a configuration value."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value)
        )
        await db.commit()


async def increment_sender(user_id: int, username: str):
    """Increment the message count for a sender."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO mention_senders (user_id, username, message_count)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                message_count = message_count + 1
        """, (user_id, username))
        await db.commit()


async def increment_receiver(user_id: int, username: str, count: int = 1):
    """Increment the mention count for a receiver."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO mention_receivers (user_id, username, mention_count)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                mention_count = mention_count + ?
        """, (user_id, username, count, count))
        await db.commit()


async def get_top_senders(limit: int = 10) -> list[tuple[int, str, int]]:
    """Get the top message senders with mentions."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT user_id, username, message_count
            FROM mention_senders
            ORDER BY message_count DESC
            LIMIT ?
        """, (limit,))
        return await cursor.fetchall()


async def get_top_receivers(limit: int = 10) -> list[tuple[int, str, int]]:
    """Get the most mentioned users."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT user_id, username, mention_count
            FROM mention_receivers
            ORDER BY mention_count DESC
            LIMIT ?
        """, (limit,))
        return await cursor.fetchall()


async def get_user_stats(user_id: int) -> tuple[int, int]:
    """Get stats for a specific user. Returns (messages_sent, times_mentioned)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT message_count FROM mention_senders WHERE user_id = ?",
            (user_id,)
        )
        sender_row = await cursor.fetchone()
        messages_sent = sender_row[0] if sender_row else 0

        cursor = await db.execute(
            "SELECT mention_count FROM mention_receivers WHERE user_id = ?",
            (user_id,)
        )
        receiver_row = await cursor.fetchone()
        times_mentioned = receiver_row[0] if receiver_row else 0

        return messages_sent, times_mentioned


async def clear_stats():
    """Clear all mention tracking data."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM mention_senders")
        await db.execute("DELETE FROM mention_receivers")
        await db.commit()
