import pytest
import pytest_asyncio

import database as db
from spotting import SpottingMessage


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", str(tmp_path / "spot_bot.db"))
    await db.init_db()


async def test_message_with_three_people_counts_three_spots(isolated_db):
    await db.upsert_spotting_message(
        SpottingMessage(
            message_id=10,
            guild_id=42,
            channel_id=100,
            spotter_id=1,
            spotter_name="Poster",
            spotted_users=((2, "One"), (3, "Two"), (4, "Three")),
        )
    )

    assert await db.get_top_senders() == [(1, "Poster", 3)]
    assert await db.get_top_receivers() == [
        (2, "One", 1),
        (3, "Two", 1),
        (4, "Three", 1),
    ]
    assert await db.get_user_stats(1) == (3, 0)
    assert await db.get_user_stats(2) == (0, 1)


async def test_reprocessing_message_replaces_mentions_without_double_counting(isolated_db):
    await db.upsert_spotting_message(
        SpottingMessage(
            message_id=10,
            guild_id=42,
            channel_id=100,
            spotter_id=1,
            spotter_name="Poster",
            spotted_users=((2, "One"), (3, "Two")),
        )
    )
    await db.upsert_spotting_message(
        SpottingMessage(
            message_id=10,
            guild_id=42,
            channel_id=100,
            spotter_id=1,
            spotter_name="Poster Renamed",
            spotted_users=((2, "One Renamed"),),
        )
    )

    assert await db.get_top_senders() == [(1, "Poster Renamed", 1)]
    assert await db.get_top_receivers() == [(2, "One Renamed", 1)]
    assert await db.get_user_stats(3) == (0, 0)


async def test_deleting_message_removes_its_spottings(isolated_db):
    await db.upsert_spotting_message(
        SpottingMessage(
            message_id=10,
            guild_id=42,
            channel_id=100,
            spotter_id=1,
            spotter_name="Poster",
            spotted_users=((2, "One"),),
        )
    )

    await db.delete_spotting_message(10)

    assert await db.get_top_senders() == []
    assert await db.get_top_receivers() == []
    assert await db.get_user_stats(1) == (0, 0)
