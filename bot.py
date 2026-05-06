import re
from dataclasses import dataclass
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import tasks
import database as db
from config import (
    DISCORD_TOKEN,
    LEADERBOARD_UPDATE_INTERVAL,
    LEADERBOARD_SIZE,
)
from spotting import (
    PartialSpottingMessage,
    SpottingMessage,
    combine_partial_spottings,
    parse_partial_spotting_message,
    parse_spotting_message,
)


ADJACENT_SPOTTING_WINDOW_SECONDS = 120
MESSAGE_LINK_RE = re.compile(
    r"^https://(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/"
    r"(?P<guild_id>\d+)/(?P<channel_id>\d+)/(?P<message_id>\d+)$"
)


@dataclass(frozen=True)
class MessageReference:
    guild_id: int
    channel_id: int
    message_id: int


class PendingSpottings:
    """Tracks short-lived photo-only or tag-only messages for adjacent matching."""

    def __init__(self, window_seconds: int = ADJACENT_SPOTTING_WINDOW_SECONDS):
        self.window_seconds = window_seconds
        self._photos: dict[tuple[int, int, int], list[PartialSpottingMessage]] = {}
        self._tags: dict[tuple[int, int, int], list[PartialSpottingMessage]] = {}

    def resolve(
        self,
        partial: PartialSpottingMessage,
    ) -> list[SpottingMessage]:
        self._expire(partial.created_at)
        key = (partial.guild_id, partial.channel_id, partial.spotter_id)
        if partial.has_image:
            return self._resolve_photo(key, partial)

        photo = self._latest_photo_for(key, partial)
        if photo:
            combined = combine_partial_spottings(photo, partial)
            return [combined] if combined else []

        self._tags.setdefault(key, []).append(partial)
        return []

    def discard_message(self, message_id: int):
        for items in (self._photos, self._tags):
            for key, partials in list(items.items()):
                remaining = [
                    partial
                    for partial in partials
                    if partial.message_id != message_id
                ]
                if remaining:
                    items[key] = remaining
                else:
                    items.pop(key, None)

    def _expire(self, now: float):
        for items in (self._photos, self._tags):
            for key, partials in list(items.items()):
                remaining = [
                    partial
                    for partial in partials
                    if abs(now - partial.created_at) <= self.window_seconds
                ]
                if remaining:
                    items[key] = remaining
                else:
                    items.pop(key, None)

    def _resolve_photo(
        self,
        key: tuple[int, int, int],
        photo: PartialSpottingMessage,
    ) -> list[SpottingMessage]:
        self._photos.setdefault(key, []).append(photo)
        matched = []
        remaining_tags = []
        for tag in self._tags.get(key, []):
            if self._within_window(photo, tag):
                combined = combine_partial_spottings(tag, photo)
                if combined:
                    matched.append(combined)
            else:
                remaining_tags.append(tag)

        if remaining_tags:
            self._tags[key] = remaining_tags
        else:
            self._tags.pop(key, None)

        return matched

    def _latest_photo_for(
        self,
        key: tuple[int, int, int],
        tag: PartialSpottingMessage,
    ) -> PartialSpottingMessage | None:
        candidates = [
            photo
            for photo in self._photos.get(key, [])
            if self._within_window(photo, tag)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda photo: photo.created_at)

    def _within_window(
        self,
        first: PartialSpottingMessage,
        second: PartialSpottingMessage,
    ) -> bool:
        return abs(second.created_at - first.created_at) <= self.window_seconds


class SpotBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.pending_spottings = PendingSpottings()

    async def setup_hook(self):
        await db.init_db()
        await self.tree.sync()
        self.update_leaderboard_task.start()

    @tasks.loop(seconds=LEADERBOARD_UPDATE_INTERVAL)
    async def update_leaderboard_task(self):
        """Periodically update the leaderboard."""
        await self.wait_until_ready()
        await update_all_leaderboards(self)

    async def on_ready(self):
        print(f"Logged in as {self.user}")


bot = SpotBot()
spot_group = app_commands.Group(
    name="spot",
    description="Correct spotted leaderboard records",
)
bot.tree.add_command(spot_group)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    spotted_channel_id = await db.get_config(
        "spotted_channel_id",
        guild_id=message.guild.id,
    )
    if not spotted_channel_id:
        return

    await process_spotting_message(message, spotted_channel_id)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if after.author.bot or not after.guild:
        return

    spotted_channel_id = await db.get_config(
        "spotted_channel_id",
        guild_id=after.guild.id,
    )
    if not spotted_channel_id:
        return

    await process_spotting_message(
        after,
        spotted_channel_id,
        reconcile_existing=True,
    )


@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    spotted_channel_id = await db.get_config(
        "spotted_channel_id",
        guild_id=message.guild.id,
    )
    if not spotted_channel_id or str(message.channel.id) != spotted_channel_id:
        return

    bot.pending_spottings.discard_message(message.id)
    await db.delete_spotting_message(message.id)


async def process_spotting_message(
    message: discord.Message,
    spotted_channel_id: str,
    pending: PendingSpottings | None = None,
    reconcile_existing: bool = False,
) -> bool:
    """Store or remove spotting data for a message in the spotted channel."""
    if str(message.channel.id) != spotted_channel_id:
        return False

    pending_spottings = pending or bot.pending_spottings
    existing = None
    if reconcile_existing:
        existing = await db.get_spotting_message(message.id)

    spottings = resolve_spotting_messages(message, pending_spottings)
    if not spottings and existing:
        edited_spotting = resolve_existing_spotting_edit(message, existing)
        if edited_spotting:
            spottings = [edited_spotting]

    if reconcile_existing:
        await db.delete_spotting_message(message.id)

    if spottings:
        for spotting in spottings:
            await db.upsert_spotting_message(spotting)
        return True

    return False


def collect_spottings_from_messages(messages) -> list[SpottingMessage]:
    """Resolve same-message and adjacent-message spottings from ordered history."""
    pending = PendingSpottings()
    spottings = []
    for message in messages:
        spottings.extend(resolve_spotting_messages(message, pending))
    return spottings


def resolve_spotting_messages(
    message: discord.Message,
    pending: PendingSpottings,
) -> list[SpottingMessage]:
    spotting = parse_spotting_message(message)
    if spotting:
        pending.discard_message(message.id)
        return [spotting]

    partial = parse_partial_spotting_message(message)
    if not partial:
        pending.discard_message(message.id)
        return []

    reply_spotting = resolve_reply_spotting(message, partial)
    if reply_spotting:
        return [reply_spotting]

    return pending.resolve(partial)


def resolve_reply_spotting(
    message: discord.Message,
    partial: PartialSpottingMessage,
) -> SpottingMessage | None:
    if partial.has_image or not partial.spotted_users:
        return None

    reference = getattr(message, "reference", None)
    referenced_message = getattr(reference, "resolved", None)
    if not referenced_message:
        return None

    referenced = parse_partial_spotting_message(referenced_message)
    if not referenced or not referenced.has_image:
        return None

    if abs(partial.created_at - referenced.created_at) > ADJACENT_SPOTTING_WINDOW_SECONDS:
        return None

    return combine_partial_spottings(referenced, partial)


def resolve_existing_spotting_edit(
    message: discord.Message,
    existing: SpottingMessage,
) -> SpottingMessage | None:
    partial = parse_partial_spotting_message(message)
    if not partial or not partial.spotted_users:
        return None

    if existing.photo_message_id == existing.message_id:
        return None

    return SpottingMessage(
        message_id=partial.message_id,
        guild_id=partial.guild_id,
        channel_id=partial.channel_id,
        spotter_id=partial.spotter_id,
        spotter_name=partial.spotter_name,
        spotted_users=partial.spotted_users,
        photo_message_id=existing.photo_message_id,
    )


async def update_all_leaderboards(client: discord.Client):
    """Update leaderboards for all configured guilds."""
    guild_ids = await db.get_configured_guild_ids()
    if not guild_ids:
        await update_leaderboard(client, guild_id=None)
        return

    for guild_id in guild_ids:
        await update_leaderboard(client, guild_id=guild_id)


async def update_leaderboard(
    client: discord.Client,
    guild_id: int | None = None,
):
    """Update or post the leaderboard in the configured channel."""
    leaderboard_channel_id = await db.get_config(
        "leaderboard_channel_id",
        guild_id=guild_id,
    )
    if not leaderboard_channel_id:
        return

    channel = client.get_channel(int(leaderboard_channel_id))
    if not channel:
        return

    # Build the leaderboard embed
    embed = await build_leaderboard_embed(guild_id=guild_id)

    # Check if we have an existing leaderboard message to edit
    leaderboard_message_id = await db.get_config(
        "leaderboard_message_id",
        guild_id=guild_id,
    )
    if leaderboard_message_id:
        try:
            message = await channel.fetch_message(int(leaderboard_message_id))
            await message.edit(embed=embed)
            return
        except discord.NotFound:
            pass

    # Post a new leaderboard message
    message = await channel.send(embed=embed)
    await db.set_config(
        "leaderboard_message_id",
        str(message.id),
        guild_id=guild_id,
    )


async def build_leaderboard_embed(guild_id: int | None = None) -> discord.Embed:
    """Build the leaderboard embed."""
    embed = discord.Embed(
        title="Spotted Leaderboard",
        color=discord.Color.gold()
    )

    # Top spotters (spotted the most people)
    top_senders = await db.get_top_senders(LEADERBOARD_SIZE, guild_id=guild_id)
    if top_senders:
        sender_lines = []
        for i, (user_id, username, count) in enumerate(top_senders, 1):
            medal = get_medal(i)
            sender_lines.append(f"{medal} **{username}** - {count} people")
        embed.add_field(
            name="Most Spotters",
            value="\n".join(sender_lines) or "No data yet",
            inline=False
        )
    else:
        embed.add_field(
            name="Most Spotters",
            value="No data yet",
            inline=False
        )

    # Most spotted (received most mentions)
    top_receivers = await db.get_top_receivers(LEADERBOARD_SIZE, guild_id=guild_id)
    if top_receivers:
        receiver_lines = []
        for i, (user_id, username, count) in enumerate(top_receivers, 1):
            medal = get_medal(i)
            receiver_lines.append(f"{medal} **{username}** - {count} times")
        embed.add_field(
            name="Most Spotted",
            value="\n".join(receiver_lines) or "No data yet",
            inline=False
        )
    else:
        embed.add_field(
            name="Most Spotted",
            value="No data yet",
            inline=False
        )

    embed.set_footer(text=f"Updates every {LEADERBOARD_UPDATE_INTERVAL // 60} minutes")
    return embed


def get_medal(position: int) -> str:
    """Get medal emoji for leaderboard position."""
    medals = {1: "1.", 2: "2.", 3: "3."}
    return medals.get(position, f"{position}.")


def parse_message_link(message_link: str) -> MessageReference:
    match = MESSAGE_LINK_RE.match(message_link.strip())
    if not match:
        raise ValueError("Expected a Discord message link.")

    return MessageReference(
        guild_id=int(match.group("guild_id")),
        channel_id=int(match.group("channel_id")),
        message_id=int(match.group("message_id")),
    )


async def fetch_message_from_link(
    interaction: discord.Interaction,
    message_link: str,
) -> discord.Message:
    reference = parse_message_link(message_link)
    if interaction.guild_id != reference.guild_id:
        raise ValueError("That message is not from this server.")

    channel = bot.get_channel(reference.channel_id)
    if channel is None:
        channel = await bot.fetch_channel(reference.channel_id)

    if not hasattr(channel, "fetch_message"):
        raise ValueError("That link does not point to a message channel.")

    return await channel.fetch_message(reference.message_id)


async def ensure_spotted_channel(
    interaction: discord.Interaction,
    message: discord.Message,
):
    spotted_channel_id = await db.get_config(
        "spotted_channel_id",
        guild_id=interaction.guild_id,
    )
    if not spotted_channel_id:
        raise ValueError("No spotted channel configured. Use `/setup spotted #channel` first.")
    if str(message.channel.id) != spotted_channel_id:
        raise ValueError("That message is not in the configured spotted channel.")


def photo_message_id_for_correction(
    message: discord.Message,
    existing: SpottingMessage | None,
) -> int:
    if existing and existing.photo_message_id:
        return existing.photo_message_id

    partial = parse_partial_spotting_message(message)
    if partial and partial.has_image:
        return message.id

    return message.id


async def rescan_message_context(message: discord.Message) -> list[SpottingMessage]:
    after = message.created_at - timedelta(seconds=ADJACENT_SPOTTING_WINDOW_SECONDS)
    before = message.created_at + timedelta(seconds=ADJACENT_SPOTTING_WINDOW_SECONDS)
    messages = [
        history_message
        async for history_message in message.channel.history(
            limit=None,
            after=after,
            before=before,
            oldest_first=True,
        )
    ]
    spottings = collect_spottings_from_messages(messages)
    return [
        spotting
        for spotting in spottings
        if spotting.message_id == message.id or spotting.photo_message_id == message.id
    ]


# Slash commands
@bot.tree.command(name="setup", description="Configure the bot channels")
@app_commands.describe(
    channel_type="Which channel to configure",
    channel="The channel to use"
)
@app_commands.choices(channel_type=[
    app_commands.Choice(name="spotted", value="spotted"),
    app_commands.Choice(name="leaderboard", value="leaderboard"),
])
@app_commands.default_permissions(administrator=True)
async def setup(
    interaction: discord.Interaction,
    channel_type: str,
    channel: discord.TextChannel
):
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "Setup can only be used in a server.",
            ephemeral=True
        )
        return

    if channel_type == "spotted":
        await db.set_config(
            "spotted_channel_id",
            str(channel.id),
            guild_id=interaction.guild_id,
        )
        await interaction.response.send_message(
            f"Spotted channel set to {channel.mention}",
            ephemeral=True
        )
    elif channel_type == "leaderboard":
        await db.set_config(
            "leaderboard_channel_id",
            str(channel.id),
            guild_id=interaction.guild_id,
        )
        # Clear old message ID so a new one gets posted
        await db.set_config(
            "leaderboard_message_id",
            "",
            guild_id=interaction.guild_id,
        )
        await interaction.response.send_message(
            f"Leaderboard channel set to {channel.mention}",
            ephemeral=True
        )


@bot.tree.command(name="leaderboard", description="Refresh the leaderboard")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await update_leaderboard(bot, guild_id=interaction.guild_id)
    await interaction.followup.send("Leaderboard updated!", ephemeral=True)


@bot.tree.command(name="mystats", description="View your spotted stats")
async def mystats(interaction: discord.Interaction):
    people_spotted, times_spotted = await db.get_user_stats(
        interaction.user.id,
        guild_id=interaction.guild_id,
    )

    embed = discord.Embed(
        title=f"Stats for {interaction.user.display_name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="People Spotted", value=str(people_spotted), inline=True)
    embed.add_field(name="Times Spotted", value=str(times_spotted), inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="stats", description="View another user's spotted stats")
@app_commands.describe(user="The user to check stats for")
async def stats(interaction: discord.Interaction, user: discord.Member):
    people_spotted, times_spotted = await db.get_user_stats(
        user.id,
        guild_id=interaction.guild_id,
    )

    embed = discord.Embed(
        title=f"Stats for {user.display_name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="People Spotted", value=str(people_spotted), inline=True)
    embed.add_field(name="Times Spotted", value=str(times_spotted), inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@spot_group.command(name="add", description="Add a spotted user to a message")
@app_commands.describe(
    message_link="Discord message link for the spotting",
    user="User to add as spotted",
)
@app_commands.default_permissions(administrator=True)
async def spot_add(
    interaction: discord.Interaction,
    message_link: str,
    user: discord.Member,
):
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "Spot corrections can only be used in a server.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    try:
        message = await fetch_message_from_link(interaction, message_link)
        await ensure_spotted_channel(interaction, message)
    except (discord.NotFound, discord.Forbidden, ValueError) as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return

    if user.id == message.author.id:
        await interaction.followup.send(
            "Self-spots are not counted.",
            ephemeral=True,
        )
        return

    existing = await db.get_spotting_message(message.id)
    await db.add_spotted_user(
        message_id=message.id,
        guild_id=message.guild.id,
        channel_id=message.channel.id,
        spotter_id=message.author.id,
        spotter_name=message.author.display_name,
        spotted_id=user.id,
        spotted_name=user.display_name,
        photo_message_id=photo_message_id_for_correction(message, existing),
    )
    await update_leaderboard(bot, guild_id=interaction.guild_id)
    await interaction.followup.send(
        f"Added {user.mention} to that spotting.",
        ephemeral=True,
    )


@spot_group.command(name="remove", description="Remove a spotted user from a message")
@app_commands.describe(
    message_link="Discord message link for the spotting",
    user="User to remove from spotted",
)
@app_commands.default_permissions(administrator=True)
async def spot_remove(
    interaction: discord.Interaction,
    message_link: str,
    user: discord.Member,
):
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "Spot corrections can only be used in a server.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    try:
        message = await fetch_message_from_link(interaction, message_link)
        await ensure_spotted_channel(interaction, message)
    except (discord.NotFound, discord.Forbidden, ValueError) as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return

    await db.remove_spotted_user(message.id, user.id)
    await update_leaderboard(bot, guild_id=interaction.guild_id)
    await interaction.followup.send(
        f"Removed {user.mention} from that spotting.",
        ephemeral=True,
    )


@spot_group.command(name="rescan", description="Rescan a spotting message")
@app_commands.describe(message_link="Discord message link to rescan")
@app_commands.default_permissions(administrator=True)
async def spot_rescan(
    interaction: discord.Interaction,
    message_link: str,
):
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "Spot corrections can only be used in a server.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    try:
        message = await fetch_message_from_link(interaction, message_link)
        await ensure_spotted_channel(interaction, message)
    except (discord.NotFound, discord.Forbidden, ValueError) as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return

    spottings = await rescan_message_context(message)
    await db.delete_spotting_message(message.id)
    for spotting in spottings:
        await db.upsert_spotting_message(spotting)

    await update_leaderboard(bot, guild_id=interaction.guild_id)
    await interaction.followup.send(
        f"Rescanned message and found {len(spottings)} spotting record(s).",
        ephemeral=True,
    )


@bot.tree.command(name="backfill", description="Import all existing messages from the spotted channel")
@app_commands.default_permissions(administrator=True)
async def backfill(interaction: discord.Interaction):
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "Backfill can only be used in a server.",
            ephemeral=True
        )
        return

    spotted_channel_id = await db.get_config(
        "spotted_channel_id",
        guild_id=interaction.guild_id,
    )
    if not spotted_channel_id:
        await interaction.response.send_message(
            "No spotted channel configured. Use `/setup spotted #channel` first.",
            ephemeral=True
        )
        return

    channel = bot.get_channel(int(spotted_channel_id))
    if not channel:
        await interaction.response.send_message(
            "Could not find the spotted channel.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    # Fetch and process all valid spotting messages
    message_count = 0
    spottings = []
    pending = PendingSpottings()
    async for message in channel.history(limit=None, oldest_first=True):
        resolved = resolve_spotting_messages(message, pending)
        spottings.extend(resolved)
        message_count += len(resolved)

    await db.replace_guild_spotting_messages(interaction.guild_id, spottings)

    # Update the leaderboard
    await update_leaderboard(bot, guild_id=interaction.guild_id)

    await interaction.followup.send(
        f"Backfill complete! Processed {message_count} messages with mentions.",
        ephemeral=True
    )


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("Error: DISCORD_TOKEN not set in .env file")
        exit(1)
    bot.run(DISCORD_TOKEN)
