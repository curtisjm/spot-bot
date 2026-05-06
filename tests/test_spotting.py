from types import SimpleNamespace

import pytest

from spotting import parse_spotting_message


def user(user_id, name, *, bot=False):
    return SimpleNamespace(id=user_id, display_name=name, bot=bot)


def attachment(filename, content_type):
    return SimpleNamespace(filename=filename, content_type=content_type)


def message(*, author=None, mentions=None, attachments=None):
    return SimpleNamespace(
        id=9001,
        guild=SimpleNamespace(id=42),
        channel=SimpleNamespace(id=100),
        author=author or user(1, "Poster"),
        mentions=mentions or [],
        attachments=attachments or [],
    )


def test_rejects_messages_without_images():
    msg = message(
        mentions=[user(2, "Spotted")],
        attachments=[attachment("notes.txt", "text/plain")],
    )

    assert parse_spotting_message(msg) is None


def test_rejects_messages_without_mentions():
    msg = message(attachments=[attachment("photo.jpg", "image/jpeg")])

    assert parse_spotting_message(msg) is None


def test_parses_unique_non_bot_mentions_from_image_message():
    spotted = user(2, "Spotted")
    bot = user(3, "Helper Bot", bot=True)
    msg = message(
        mentions=[spotted, spotted, bot, user(1, "Poster")],
        attachments=[attachment("photo.png", "image/png")],
    )

    result = parse_spotting_message(msg)

    assert result is not None
    assert result.message_id == 9001
    assert result.guild_id == 42
    assert result.channel_id == 100
    assert result.spotter_id == 1
    assert result.spotter_name == "Poster"
    assert result.spotted_users == ((2, "Spotted"),)
    assert result.photo_message_id == 9001
    assert result.spot_count == 1


def test_rejects_self_spots():
    msg = message(
        mentions=[user(1, "Poster")],
        attachments=[attachment("photo.png", "image/png")],
    )

    assert parse_spotting_message(msg) is None


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("campus.jpeg", None),
        ("campus.webp", None),
        ("campus.gif", None),
        ("campus", "image/jpeg"),
    ],
)
def test_accepts_common_image_indicators(filename, content_type):
    msg = message(
        mentions=[user(2, "Spotted")],
        attachments=[attachment(filename, content_type)],
    )

    assert parse_spotting_message(msg) is not None
