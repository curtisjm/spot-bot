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


async def test_replace_all_spotting_messages_rebuilds_stats(isolated_db):
    await db.upsert_spotting_message(
        SpottingMessage(
            message_id=10,
            guild_id=42,
            channel_id=100,
            spotter_id=1,
            spotter_name="Old Poster",
            spotted_users=((2, "Old"),),
        )
    )

    await db.replace_all_spotting_messages([
        SpottingMessage(
            message_id=20,
            guild_id=42,
            channel_id=100,
            spotter_id=3,
            spotter_name="New Poster",
            spotted_users=((4, "New One"), (5, "New Two")),
        )
    ])

    assert await db.get_top_senders() == [(3, "New Poster", 2)]
    assert await db.get_top_receivers() == [(4, "New One", 1), (5, "New Two", 1)]
    assert await db.get_user_stats(1) == (0, 0)


async def test_config_values_are_scoped_by_guild(isolated_db):
    await db.set_config("spotted_channel_id", "100", guild_id=42)
    await db.set_config("spotted_channel_id", "200", guild_id=84)

    assert await db.get_config("spotted_channel_id", guild_id=42) == "100"
    assert await db.get_config("spotted_channel_id", guild_id=84) == "200"
    assert await db.get_configured_guild_ids() == [42, 84]


async def test_leaderboards_can_be_filtered_by_guild(isolated_db):
    await db.upsert_spotting_message(
        SpottingMessage(
            message_id=10,
            guild_id=42,
            channel_id=100,
            spotter_id=1,
            spotter_name="Guild A Poster",
            spotted_users=((2, "Guild A Spotted"),),
        )
    )
    await db.upsert_spotting_message(
        SpottingMessage(
            message_id=20,
            guild_id=84,
            channel_id=200,
            spotter_id=3,
            spotter_name="Guild B Poster",
            spotted_users=((4, "Guild B Spotted"),),
        )
    )

    assert await db.get_top_senders(guild_id=42) == [(1, "Guild A Poster", 1)]
    assert await db.get_top_receivers(guild_id=84) == [(4, "Guild B Spotted", 1)]
    assert await db.get_user_stats(3, guild_id=42) == (0, 0)
    assert await db.get_user_stats(3, guild_id=84) == (1, 0)


async def test_replace_guild_spotting_messages_preserves_other_guilds(isolated_db):
    await db.upsert_spotting_message(
        SpottingMessage(
            message_id=10,
            guild_id=42,
            channel_id=100,
            spotter_id=1,
            spotter_name="Guild A Poster",
            spotted_users=((2, "Guild A Spotted"),),
        )
    )
    await db.upsert_spotting_message(
        SpottingMessage(
            message_id=20,
            guild_id=84,
            channel_id=200,
            spotter_id=3,
            spotter_name="Guild B Poster",
            spotted_users=((4, "Guild B Spotted"),),
        )
    )

    await db.replace_guild_spotting_messages(
        42,
        [
            SpottingMessage(
                message_id=30,
                guild_id=42,
                channel_id=100,
                spotter_id=5,
                spotter_name="New Guild A Poster",
                spotted_users=((6, "New Guild A Spotted"),),
            )
        ],
    )

    assert await db.get_top_senders(guild_id=42) == [(5, "New Guild A Poster", 1)]
    assert await db.get_top_senders(guild_id=84) == [(3, "Guild B Poster", 1)]
