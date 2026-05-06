from types import SimpleNamespace

import pytest

import bot


pytestmark = pytest.mark.asyncio


def user(user_id, name, *, bot=False):
    return SimpleNamespace(id=user_id, display_name=name, bot=bot)


def image_attachment():
    return SimpleNamespace(filename="spot.jpg", content_type="image/jpeg")


def message(*, channel_id=100, mentions=None, attachments=None):
    return SimpleNamespace(
        id=555,
        guild=SimpleNamespace(id=42),
        channel=SimpleNamespace(id=channel_id),
        author=user(1, "Poster"),
        mentions=mentions or [],
        attachments=attachments or [],
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


async def test_process_spotted_message_deletes_invalid_existing_state(monkeypatch):
    deleted = []

    async def fake_upsert(spotting):
        raise AssertionError(f"unexpected upsert for {spotting}")

    async def fake_delete(message_id):
        deleted.append(message_id)

    monkeypatch.setattr(bot.db, "upsert_spotting_message", fake_upsert)
    monkeypatch.setattr(bot.db, "delete_spotting_message", fake_delete)

    processed = await bot.process_spotting_message(
        message(mentions=[user(2, "One")]),
        spotted_channel_id="100",
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
