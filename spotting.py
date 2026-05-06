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
