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
):
    return SimpleNamespace(
        id=message_id,
        guild=SimpleNamespace(id=42),
        channel=SimpleNamespace(id=channel_id),
        author=author or user(1, "Poster"),
        mentions=mentions or [],
        attachments=attachments or [],
        created_at=created_at,
    )


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

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)

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
    assert calls[0].message_id == 10
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
    assert calls[0].message_id == 21
    assert calls[0].spotted_users == ((2, "One"),)


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


async def test_collect_spottings_from_messages_pairs_adjacent_history():
    spottings = bot.collect_spottings_from_messages([
        message(message_id=40, attachments=[image_attachment()], created_at=1000),
        message(message_id=41, mentions=[user(2, "One")], created_at=1060),
    ])

    assert len(spottings) == 1
    assert spottings[0].message_id == 40
    assert spottings[0].spotted_users == ((2, "One"),)
