from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import bot


pytestmark = pytest.mark.asyncio


def user(user_id, name, *, bot=False):
    return SimpleNamespace(id=user_id, display_name=name, bot=bot)


def image_attachment():
    return SimpleNamespace(filename="spot.jpg", content_type="image/jpeg")


def message(
    *,
    message_id=555,
    channel_id=100,
    author=None,
    mentions=None,
    attachments=None,
    created_at=1000,
    reference=None,
):
    return SimpleNamespace(
        id=message_id,
        guild=SimpleNamespace(id=42),
        channel=SimpleNamespace(id=channel_id),
        author=author or user(1, "Poster"),
        mentions=mentions or [],
        attachments=attachments or [],
        created_at=created_at,
        reference=reference,
    )


def reply_to(resolved_message):
    return SimpleNamespace(resolved=resolved_message)


class FakeChannel:
    def __init__(self, messages):
        self._messages = messages
        self.history_kwargs = None

    async def history(self, **kwargs):
        self.history_kwargs = kwargs
        for item in self._messages:
            yield item


def interaction(*, administrator=True):
    return SimpleNamespace(
        user=SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=administrator)
        )
    )


async def test_has_admin_permission_checks_runtime_permissions():
    assert bot.has_admin_permission(interaction(administrator=True)) is True
    assert bot.has_admin_permission(interaction(administrator=False)) is False


async def test_process_spotted_message_upserts_valid_spotting(monkeypatch):
    calls = []

    async def fake_upsert(spotting):
        calls.append(spotting)

    async def fake_delete(message_id):
        raise AssertionError(f"unexpected delete for {message_id}")

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)

    processed = await bot.process_spotting_message(
        message(
            mentions=[user(2, "One"), user(3, "Two")],
            attachments=[image_attachment()],
        ),
        spotted_channel_id="100",
    )

    assert processed is True
    assert len(calls) == 1
    assert calls[0].spotter_id == 1
    assert calls[0].spotted_users == ((2, "One"), (3, "Two"))


async def test_process_spotted_message_deletes_invalid_existing_state_on_edit(monkeypatch):
    deleted = []

    async def fake_upsert(spotting):
        raise AssertionError(f"unexpected upsert for {spotting}")

    async def fake_delete(message_id):
        deleted.append(message_id)

    async def fake_get(message_id):
        return None

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)
    monkeypatch.setattr(bot.db, "get_spotting_message", fake_get)

    processed = await bot.process_spotting_message(
        message(),
        spotted_channel_id="100",
        reconcile_existing=True,
    )

    assert processed is False
    assert deleted == [555]


async def test_process_spotted_message_ignores_other_channels(monkeypatch):
    async def fail_upsert(spotting):
        raise AssertionError("unexpected upsert")

    async def fail_delete(message_id):
        raise AssertionError("unexpected delete")

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fail_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fail_delete)

    processed = await bot.process_spotting_message(
        message(channel_id=200, mentions=[user(2, "One")]),
        spotted_channel_id="100",
    )

    assert processed is False


async def test_process_spotted_message_pairs_photo_then_tags_within_two_minutes(monkeypatch):
    calls = []
    deleted = []
    pending = bot.PendingSpottings()

    async def fake_upsert(spotting):
        calls.append(spotting)

    async def fake_delete(message_id):
        deleted.append(message_id)

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)

    photo_processed = await bot.process_spotting_message(
        message(message_id=10, attachments=[image_attachment()], created_at=1000),
        spotted_channel_id="100",
        pending=pending,
    )
    tag_processed = await bot.process_spotting_message(
        message(message_id=11, mentions=[user(2, "One")], created_at=1060),
        spotted_channel_id="100",
        pending=pending,
    )

    assert photo_processed is False
    assert tag_processed is True
    assert deleted == []
    assert len(calls) == 1
    assert calls[0].message_id == 11
    assert calls[0].photo_message_id == 10
    assert calls[0].spotted_users == ((2, "One"),)


async def test_process_spotted_message_pairs_tags_then_photo_within_two_minutes(monkeypatch):
    calls = []
    pending = bot.PendingSpottings()

    async def fake_upsert(spotting):
        calls.append(spotting)

    async def fake_delete(message_id):
        raise AssertionError(f"unexpected delete for {message_id}")

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)

    tag_processed = await bot.process_spotting_message(
        message(message_id=20, mentions=[user(2, "One")], created_at=1000),
        spotted_channel_id="100",
        pending=pending,
    )
    photo_processed = await bot.process_spotting_message(
        message(message_id=21, attachments=[image_attachment()], created_at=1060),
        spotted_channel_id="100",
        pending=pending,
    )

    assert tag_processed is False
    assert photo_processed is True
    assert len(calls) == 1
    assert calls[0].message_id == 20
    assert calls[0].photo_message_id == 21
    assert calls[0].spotted_users == ((2, "One"),)


async def test_process_spotted_message_counts_multiple_tag_messages_after_photo(monkeypatch):
    calls = []
    pending = bot.PendingSpottings()

    async def fake_upsert(spotting):
        calls.append(spotting)

    async def fake_delete(message_id):
        raise AssertionError(f"unexpected delete for {message_id}")

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)

    await bot.process_spotting_message(
        message(message_id=25, attachments=[image_attachment()], created_at=1000),
        spotted_channel_id="100",
        pending=pending,
    )
    await bot.process_spotting_message(
        message(message_id=26, mentions=[user(2, "One")], created_at=1020),
        spotted_channel_id="100",
        pending=pending,
    )
    await bot.process_spotting_message(
        message(message_id=27, mentions=[user(3, "Two")], created_at=1040),
        spotted_channel_id="100",
        pending=pending,
    )

    assert [call.message_id for call in calls] == [26, 27]
    assert [call.spotted_users for call in calls] == [((2, "One"),), ((3, "Two"),)]


async def test_process_spotted_message_does_not_pair_after_two_minutes(monkeypatch):
    calls = []
    pending = bot.PendingSpottings()

    async def fake_upsert(spotting):
        calls.append(spotting)

    async def fake_delete(message_id):
        raise AssertionError(f"unexpected delete for {message_id}")

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)

    await bot.process_spotting_message(
        message(message_id=30, attachments=[image_attachment()], created_at=1000),
        spotted_channel_id="100",
        pending=pending,
    )
    processed = await bot.process_spotting_message(
        message(message_id=31, mentions=[user(2, "One")], created_at=1121),
        spotted_channel_id="100",
        pending=pending,
    )

    assert processed is False
    assert calls == []


async def test_process_spotted_message_does_not_pair_different_authors(monkeypatch):
    calls = []
    pending = bot.PendingSpottings()

    async def fake_upsert(spotting):
        calls.append(spotting)

    async def fake_delete(message_id):
        raise AssertionError(f"unexpected delete for {message_id}")

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)

    await bot.process_spotting_message(
        message(
            message_id=35,
            author=user(1, "Poster"),
            attachments=[image_attachment()],
            created_at=1000,
        ),
        spotted_channel_id="100",
        pending=pending,
    )
    processed = await bot.process_spotting_message(
        message(
            message_id=36,
            author=user(9, "Other Poster"),
            mentions=[user(2, "One")],
            created_at=1060,
        ),
        spotted_channel_id="100",
        pending=pending,
    )

    assert processed is False
    assert calls == []


async def test_process_spotted_message_counts_reply_to_own_photo(monkeypatch):
    calls = []
    pending = bot.PendingSpottings()
    photo = message(message_id=37, attachments=[image_attachment()], created_at=1000)

    async def fake_upsert(spotting):
        calls.append(spotting)

    async def fake_delete(message_id):
        raise AssertionError(f"unexpected delete for {message_id}")

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)

    processed = await bot.process_spotting_message(
        message(
            message_id=38,
            mentions=[user(2, "One")],
            created_at=1060,
            reference=reply_to(photo),
        ),
        spotted_channel_id="100",
        pending=pending,
    )

    assert processed is True
    assert calls[0].message_id == 38
    assert calls[0].photo_message_id == 37


async def test_process_spotted_message_does_not_count_reply_to_other_users_photo(monkeypatch):
    calls = []
    pending = bot.PendingSpottings()
    photo = message(
        message_id=39,
        author=user(9, "Other Poster"),
        attachments=[image_attachment()],
        created_at=1000,
    )

    async def fake_upsert(spotting):
        calls.append(spotting)

    async def fake_delete(message_id):
        raise AssertionError(f"unexpected delete for {message_id}")

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)

    processed = await bot.process_spotting_message(
        message(
            message_id=40,
            mentions=[user(2, "One")],
            created_at=1060,
            reference=reply_to(photo),
        ),
        spotted_channel_id="100",
        pending=pending,
    )

    assert processed is False
    assert calls == []


async def test_process_spotted_message_fetches_unresolved_reply_reference(monkeypatch):
    calls = []
    pending = bot.PendingSpottings()
    photo = message(message_id=41, attachments=[image_attachment()], created_at=1000)
    reply = message(
        message_id=42,
        mentions=[user(2, "One")],
        created_at=1060,
        reference=SimpleNamespace(message_id=41, resolved=None),
    )

    async def fake_fetch_message(message_id):
        assert message_id == 41
        return photo

    reply.channel.fetch_message = fake_fetch_message

    async def fake_upsert(spotting):
        calls.append(spotting)

    async def fake_delete(message_id):
        raise AssertionError(f"unexpected delete for {message_id}")

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)

    processed = await bot.process_spotting_message(
        reply,
        spotted_channel_id="100",
        pending=pending,
    )

    assert processed is True
    assert len(calls) == 1
    assert calls[0].message_id == 42
    assert calls[0].photo_message_id == 41


async def test_process_spotted_message_reconciles_edited_adjacent_tags(monkeypatch):
    calls = []
    deleted = []
    pending = bot.PendingSpottings()

    async def fake_upsert(spotting):
        calls.append(spotting)

    async def fake_delete(message_id):
        deleted.append(message_id)

    async def fake_get(message_id):
        assert message_id == 50
        return bot.SpottingMessage(
            message_id=50,
            guild_id=42,
            channel_id=100,
            spotter_id=1,
            spotter_name="Poster",
            spotted_users=((2, "Old"),),
            photo_message_id=49,
        )

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)
    monkeypatch.setattr(bot.db, "get_spotting_message", fake_get)

    processed = await bot.process_spotting_message(
        message(
            message_id=50,
            mentions=[user(2, "One"), user(3, "Two")],
            created_at=2000,
        ),
        spotted_channel_id="100",
        pending=pending,
        reconcile_existing=True,
    )

    assert processed is True
    assert deleted == [50]
    assert calls[0].message_id == 50
    assert calls[0].photo_message_id == 49
    assert calls[0].spotted_users == ((2, "One"), (3, "Two"))


async def test_process_spotted_photo_edit_preserves_adjacent_tag_spottings(monkeypatch):
    calls = []
    deleted = []
    pending = bot.PendingSpottings()

    async def fake_upsert(spotting):
        calls.append(spotting)

    async def fake_delete(message_id):
        deleted.append(message_id)

    async def fake_get(message_id):
        assert message_id == 49
        return None

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)
    monkeypatch.setattr(bot.db, "get_spotting_message", fake_get)

    processed = await bot.process_spotting_message(
        message(
            message_id=49,
            attachments=[image_attachment()],
            created_at=2000,
        ),
        spotted_channel_id="100",
        pending=pending,
        reconcile_existing=True,
    )

    assert processed is False
    assert deleted == []
    assert calls == []


async def test_collect_spottings_from_messages_pairs_adjacent_history():
    spottings = bot.collect_spottings_from_messages([
        message(message_id=40, attachments=[image_attachment()], created_at=1000),
        message(message_id=41, mentions=[user(2, "One")], created_at=1060),
    ])

    assert len(spottings) == 1
    assert spottings[0].message_id == 41
    assert spottings[0].photo_message_id == 40
    assert spottings[0].spotted_users == ((2, "One"),)


async def test_collect_spottings_from_channel_history_reports_progress():
    progress = []
    channel = FakeChannel([
        message(message_id=60),
        message(message_id=61, attachments=[image_attachment()]),
        message(message_id=62, mentions=[user(2, "One")], created_at=1020),
    ])

    async def on_progress(scanned_count, spotting_count):
        progress.append((scanned_count, spotting_count))

    spottings, scanned_count = await bot.collect_spottings_from_channel_history(
        channel,
        progress_interval=2,
        progress_callback=on_progress,
    )

    assert scanned_count == 3
    assert len(spottings) == 1
    assert progress == [(2, 0), (3, 1)]


async def test_collect_spottings_from_channel_history_uses_start_date():
    start_at = datetime(2024, 9, 1, tzinfo=timezone.utc)
    channel = FakeChannel([
        message(message_id=61, attachments=[image_attachment()]),
        message(message_id=62, mentions=[user(2, "One")], created_at=1020),
    ])

    spottings, scanned_count = await bot.collect_spottings_from_channel_history(
        channel,
        start_at=start_at,
    )

    assert scanned_count == 2
    assert len(spottings) == 1
    assert channel.history_kwargs == {
        "limit": None,
        "oldest_first": True,
        "after": start_at - timedelta(microseconds=1),
    }


async def test_parse_backfill_start_date_accepts_date_only():
    assert bot.parse_backfill_start_date("2024-09-01") == datetime(
        2024,
        9,
        1,
        tzinfo=timezone.utc,
    )


async def test_parse_backfill_start_date_rejects_invalid_format():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        bot.parse_backfill_start_date("09/01/2024")


async def test_parse_message_link_accepts_discord_message_links():
    parsed = bot.parse_message_link(
        "https://discord.com/channels/42/100/555"
    )

    assert parsed == bot.MessageReference(guild_id=42, channel_id=100, message_id=555)


async def test_parse_message_link_rejects_non_message_links():
    with pytest.raises(ValueError):
        bot.parse_message_link("https://discord.com/channels/42/100")


async def test_update_leaderboard_fetches_uncached_channel(monkeypatch):
    sent = []
    configs = {
        "leaderboard_channel_id": "123",
        "leaderboard_message_id": "",
    }

    class FakeChannel:
        async def send(self, *, embed):
            sent.append(embed)
            return SimpleNamespace(id=456)

    class FakeClient:
        def get_channel(self, channel_id):
            assert channel_id == 123
            return None

        async def fetch_channel(self, channel_id):
            assert channel_id == 123
            return FakeChannel()

    async def fake_get_config(key, guild_id=None):
        return configs.get(key)

    async def fake_set_config(key, value, guild_id=None):
        configs[key] = value

    async def fake_build_leaderboard_embed(guild_id=None):
        return SimpleNamespace(title="leaderboard")

    monkeypatch.setattr(bot.db, "get_config", fake_get_config)
    monkeypatch.setattr(bot.db, "set_config", fake_set_config)
    monkeypatch.setattr(bot, "build_leaderboard_embed", fake_build_leaderboard_embed)

    assert await bot.update_leaderboard(FakeClient(), guild_id=42) is True
    assert len(sent) == 1
    assert configs["leaderboard_message_id"] == "456"


async def test_update_leaderboard_returns_false_when_send_fails(monkeypatch):
    configs = {
        "leaderboard_channel_id": "123",
        "leaderboard_message_id": "",
    }

    class FakeResponse:
        status = 403
        reason = "Forbidden"

    class FakeChannel:
        async def send(self, *, embed):
            raise bot.discord.Forbidden(FakeResponse(), "missing permissions")

    class FakeClient:
        def get_channel(self, channel_id):
            return FakeChannel()

    async def fake_get_config(key, guild_id=None):
        return configs.get(key)

    async def fake_build_leaderboard_embed(guild_id=None):
        return SimpleNamespace(title="leaderboard")

    monkeypatch.setattr(bot.db, "get_config", fake_get_config)
    monkeypatch.setattr(bot, "build_leaderboard_embed", fake_build_leaderboard_embed)

    assert await bot.update_leaderboard(FakeClient(), guild_id=42) is False
