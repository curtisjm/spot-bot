import aiosqlite
from config import DATABASE_PATH
from spotting import SpottingMessage


async def init_db():
    """Initialize the database with required tables."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS spot_messages (
                message_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                spotter_id INTEGER NOT NULL,
                spotter_name TEXT NOT NULL,
                photo_message_id INTEGER
            )
        """)
        await _ensure_column(db, "spot_messages", "photo_message_id", "INTEGER")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS spottings (
                message_id INTEGER NOT NULL,
                spotted_id INTEGER NOT NULL,
                spotted_name TEXT NOT NULL,
                PRIMARY KEY (message_id, spotted_id),
                FOREIGN KEY (message_id)
                    REFERENCES spot_messages(message_id)
                    ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_spot_messages_spotter
            ON spot_messages (spotter_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_spottings_spotted
            ON spottings (spotted_id)
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (guild_id, key)
            )
        """)
        await db.commit()


async def get_config(key: str, guild_id: int | None = None) -> str | None:
    """Get a configuration value."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        if guild_id is not None:
            cursor = await db.execute("""
                SELECT value
                FROM guild_config
                WHERE guild_id = ? AND key = ?
            """, (guild_id, key))
            row = await cursor.fetchone()
            if row:
                return row[0]

        cursor = await db.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def set_config(key: str, value: str, guild_id: int | None = None):
    """Set a configuration value."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        if guild_id is None:
            await db.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (key, value)
            )
        else:
            await db.execute("""
                INSERT OR REPLACE INTO guild_config (guild_id, key, value)
                VALUES (?, ?, ?)
            """, (guild_id, key, value))
        await db.commit()


async def get_configured_guild_ids() -> list[int]:
    """Return guilds with guild-scoped configuration."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT DISTINCT guild_id
            FROM guild_config
            ORDER BY guild_id ASC
        """)
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def upsert_spotting_message(spotting: SpottingMessage):
    """Store the current spotting state for one Discord message."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await _upsert_spotting_message(db, spotting)
        await db.commit()


async def replace_all_spotting_messages(spottings: list[SpottingMessage]):
    """Replace all spotting data in one transaction."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("DELETE FROM spottings")
        await db.execute("DELETE FROM spot_messages")
        for spotting in spottings:
            await _upsert_spotting_message(db, spotting)
        await db.commit()


async def replace_guild_spotting_messages(
    guild_id: int,
    spottings: list[SpottingMessage],
):
    """Replace spotting data for one guild in one transaction."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "DELETE FROM spot_messages WHERE guild_id = ?",
            (guild_id,)
        )
        for spotting in spottings:
            await _upsert_spotting_message(db, spotting)
        await db.commit()


async def delete_spotting_message(message_id: int):
    """Remove spotting data sourced by or validated by one Discord message."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "DELETE FROM spot_messages WHERE message_id = ? OR photo_message_id = ?",
            (message_id, message_id)
        )
        await db.commit()


async def get_spotting_message(message_id: int) -> SpottingMessage | None:
    """Fetch one stored spotting record and its tagged users."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT
                message_id,
                guild_id,
                channel_id,
                spotter_id,
                spotter_name,
                photo_message_id
            FROM spot_messages
            WHERE message_id = ?
        """, (message_id,))
        row = await cursor.fetchone()
        if not row:
            return None

        cursor = await db.execute("""
            SELECT spotted_id, spotted_name
            FROM spottings
            WHERE message_id = ?
            ORDER BY spotted_id ASC
        """, (message_id,))
        spotted_users = tuple(await cursor.fetchall())

        return SpottingMessage(
            message_id=row[0],
            guild_id=row[1],
            channel_id=row[2],
            spotter_id=row[3],
            spotter_name=row[4],
            spotted_users=spotted_users,
            photo_message_id=row[5],
        )


async def _upsert_spotting_message(
    db: aiosqlite.Connection,
    spotting: SpottingMessage,
):
    await db.execute("""
        INSERT INTO spot_messages (
            message_id,
            guild_id,
            channel_id,
            spotter_id,
            spotter_name,
            photo_message_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            guild_id = excluded.guild_id,
            channel_id = excluded.channel_id,
            spotter_id = excluded.spotter_id,
            spotter_name = excluded.spotter_name,
            photo_message_id = excluded.photo_message_id
    """, (
        spotting.message_id,
        spotting.guild_id,
        spotting.channel_id,
        spotting.spotter_id,
        spotting.spotter_name,
        spotting.photo_message_id or spotting.message_id,
    ))
    photo_message_id = spotting.photo_message_id or spotting.message_id
    await db.execute(
        "DELETE FROM spottings WHERE message_id = ?",
        (spotting.message_id,)
    )
    for spotted_id, spotted_name in spotting.spotted_users:
        await db.execute("""
            DELETE FROM spottings
            WHERE spotted_id = ?
                AND message_id IN (
                    SELECT message_id
                    FROM spot_messages
                    WHERE photo_message_id = ?
                        AND message_id != ?
                )
        """, (spotted_id, photo_message_id, spotting.message_id))
        await db.execute("""
            INSERT INTO spottings (message_id, spotted_id, spotted_name)
            VALUES (?, ?, ?)
        """, (spotting.message_id, spotted_id, spotted_name))


async def add_spotted_user(
    *,
    message_id: int,
    guild_id: int,
    channel_id: int,
    spotter_id: int,
    spotter_name: str,
    spotted_id: int,
    spotted_name: str,
    photo_message_id: int | None = None,
):
    """Admin correction: add one spotted user to a spotting record."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("""
            INSERT INTO spot_messages (
                message_id,
                guild_id,
                channel_id,
                spotter_id,
                spotter_name,
                photo_message_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                guild_id = excluded.guild_id,
                channel_id = excluded.channel_id,
                spotter_id = excluded.spotter_id,
                spotter_name = excluded.spotter_name,
                photo_message_id = COALESCE(
                    spot_messages.photo_message_id,
                    excluded.photo_message_id
                )
        """, (
            message_id,
            guild_id,
            channel_id,
            spotter_id,
            spotter_name,
            photo_message_id or message_id,
        ))
        await db.execute("""
            INSERT OR REPLACE INTO spottings (
                message_id,
                spotted_id,
                spotted_name
            )
            VALUES (?, ?, ?)
        """, (message_id, spotted_id, spotted_name))
        await db.execute("""
            DELETE FROM spottings
            WHERE spotted_id = ?
                AND message_id IN (
                    SELECT message_id
                    FROM spot_messages
                    WHERE photo_message_id = ?
                        AND message_id != ?
                )
        """, (spotted_id, photo_message_id or message_id, message_id))
        await db.commit()


async def remove_spotted_user(message_id: int, spotted_id: int):
    """Admin correction: remove one spotted user from a spotting record."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("""
            DELETE FROM spottings
            WHERE spotted_id = ?
                AND message_id IN (
                    SELECT message_id
                    FROM spot_messages
                    WHERE message_id = ? OR photo_message_id = ?
                )
        """, (spotted_id, message_id, message_id))
        await db.execute("""
            DELETE FROM spot_messages
            WHERE NOT EXISTS (
                SELECT 1
                FROM spottings
                WHERE spottings.message_id = spot_messages.message_id
            )
                AND (message_id = ? OR photo_message_id = ?)
        """, (message_id, message_id))
        await db.commit()


async def _ensure_column(
    db: aiosqlite.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
):
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    columns = {row[1] for row in await cursor.fetchall()}
    if column_name not in columns:
        await db.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )


async def get_top_senders(
    limit: int = 10,
    guild_id: int | None = None,
) -> list[tuple[int, str, int]]:
    """Get users who have spotted the most people."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT
                spot_messages.spotter_id,
                MAX(spot_messages.spotter_name) AS spotter_name,
                COUNT(spottings.spotted_id) AS spot_count
            FROM spot_messages
            JOIN spottings ON spottings.message_id = spot_messages.message_id
            WHERE (? IS NULL OR spot_messages.guild_id = ?)
            GROUP BY spot_messages.spotter_id
            ORDER BY spot_count DESC, spotter_name ASC
            LIMIT ?
        """, (guild_id, guild_id, limit))
        return await cursor.fetchall()


async def get_top_receivers(
    limit: int = 10,
    guild_id: int | None = None,
) -> list[tuple[int, str, int]]:
    """Get users who have been spotted the most."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT
                spottings.spotted_id,
                MAX(spottings.spotted_name) AS spotted_name,
                COUNT(*) AS spotted_count
            FROM spottings
            JOIN spot_messages ON spot_messages.message_id = spottings.message_id
            WHERE (? IS NULL OR spot_messages.guild_id = ?)
            GROUP BY spottings.spotted_id
            ORDER BY spotted_count DESC, spottings.spotted_id ASC
            LIMIT ?
        """, (guild_id, guild_id, limit))
        return await cursor.fetchall()


async def get_user_stats(
    user_id: int,
    guild_id: int | None = None,
) -> tuple[int, int]:
    """Get stats for a specific user. Returns (people_spotted, times_spotted)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT COUNT(spottings.spotted_id)
            FROM spot_messages
            JOIN spottings ON spottings.message_id = spot_messages.message_id
            WHERE spot_messages.spotter_id = ?
                AND (? IS NULL OR spot_messages.guild_id = ?)
        """, (user_id, guild_id, guild_id))
        sender_row = await cursor.fetchone()
        people_spotted = sender_row[0] if sender_row else 0

        cursor = await db.execute("""
            SELECT COUNT(*)
            FROM spottings
            JOIN spot_messages ON spot_messages.message_id = spottings.message_id
            WHERE spotted_id = ?
                AND (? IS NULL OR spot_messages.guild_id = ?)
        """, (user_id, guild_id, guild_id))
        receiver_row = await cursor.fetchone()
        times_spotted = receiver_row[0] if receiver_row else 0

        return people_spotted, times_spotted


async def clear_stats():
    """Clear all mention tracking data."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM spottings")
        await db.execute("DELETE FROM spot_messages")
        await db.commit()
