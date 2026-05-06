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


async def test_collect_spottings_from_messages_pairs_adjacent_history():
    spottings = bot.collect_spottings_from_messages([
        message(message_id=40, attachments=[image_attachment()], created_at=1000),
        message(message_id=41, mentions=[user(2, "One")], created_at=1060),
    ])

    assert len(spottings) == 1
    assert spottings[0].message_id == 41
    assert spottings[0].photo_message_id == 40
    assert spottings[0].spotted_users == ((2, "One"),)


async def test_parse_message_link_accepts_discord_message_links():
    parsed = bot.parse_message_link(
        "https://discord.com/channels/42/100/555"
    )

    assert parsed == bot.MessageReference(guild_id=42, channel_id=100, message_id=555)


async def test_parse_message_link_rejects_non_message_links():
    with pytest.raises(ValueError):
        bot.parse_message_link("https://discord.com/channels/42/100")
