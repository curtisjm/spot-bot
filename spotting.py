from dataclasses import dataclass
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".apng", ".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


@dataclass(frozen=True)
class SpottingMessage:
    message_id: int
    guild_id: int
    channel_id: int
    spotter_id: int
    spotter_name: str
    spotted_users: tuple[tuple[int, str], ...]

    @property
    def spot_count(self) -> int:
        return len(self.spotted_users)


@dataclass(frozen=True)
class PartialSpottingMessage:
    message_id: int
    guild_id: int
    channel_id: int
    spotter_id: int
    spotter_name: str
    spotted_users: tuple[tuple[int, str], ...]
    has_image: bool
    created_at: float


def parse_spotting_message(message: Any) -> SpottingMessage | None:
    """Return normalized spotting data for valid image messages."""
    if getattr(getattr(message, "author", None), "bot", False):
        return None

    if getattr(message, "guild", None) is None:
        return None

    if not _has_image_attachment(getattr(message, "attachments", ())):
        return None

    spotted_users = _unique_non_bot_mentions(getattr(message, "mentions", ()))
    if not spotted_users:
        return None

    return SpottingMessage(
        message_id=int(message.id),
        guild_id=int(message.guild.id),
        channel_id=int(message.channel.id),
        spotter_id=int(message.author.id),
        spotter_name=message.author.display_name,
        spotted_users=tuple(spotted_users),
    )


def parse_partial_spotting_message(message: Any) -> PartialSpottingMessage | None:
    """Return spotting components for photo-only or tag-only adjacent matching."""
    if getattr(getattr(message, "author", None), "bot", False):
        return None

    if getattr(message, "guild", None) is None:
        return None

    has_image = _has_image_attachment(getattr(message, "attachments", ()))
    spotted_users = tuple(_unique_non_bot_mentions(getattr(message, "mentions", ())))
    if not has_image and not spotted_users:
        return None

    return PartialSpottingMessage(
        message_id=int(message.id),
        guild_id=int(message.guild.id),
        channel_id=int(message.channel.id),
        spotter_id=int(message.author.id),
        spotter_name=message.author.display_name,
        spotted_users=spotted_users,
        has_image=has_image,
        created_at=_message_created_timestamp(message),
    )


def combine_partial_spottings(
    first: PartialSpottingMessage,
    second: PartialSpottingMessage,
) -> SpottingMessage | None:
    """Combine adjacent photo-only and tag-only messages from the same author."""
    if (
        first.guild_id != second.guild_id
        or first.channel_id != second.channel_id
        or first.spotter_id != second.spotter_id
        or first.has_image == second.has_image
    ):
        return None

    image_message = first if first.has_image else second
    tag_message = second if first.has_image else first
    if not tag_message.spotted_users:
        return None

    return SpottingMessage(
        message_id=image_message.message_id,
        guild_id=image_message.guild_id,
        channel_id=image_message.channel_id,
        spotter_id=image_message.spotter_id,
        spotter_name=image_message.spotter_name,
        spotted_users=tag_message.spotted_users,
    )


def _message_created_timestamp(message: Any) -> float:
    created_at = getattr(message, "created_at", None)
    if created_at is None:
        return 0.0
    if isinstance(created_at, int | float):
        return float(created_at)
    return float(created_at.timestamp())


def _has_image_attachment(attachments: Any) -> bool:
    for item in attachments:
        content_type = getattr(item, "content_type", None)
        if content_type and content_type.lower().startswith("image/"):
            return True

        suffix = Path(getattr(item, "filename", "")).suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            return True

    return False


def _unique_non_bot_mentions(mentions: Any) -> list[tuple[int, str]]:
    seen: set[int] = set()
    users: list[tuple[int, str]] = []

    for mentioned_user in mentions:
        user_id = int(mentioned_user.id)
        if user_id in seen or getattr(mentioned_user, "bot", False):
            continue

        seen.add(user_id)
        users.append((user_id, mentioned_user.display_name))

    return users
