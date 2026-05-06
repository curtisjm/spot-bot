import discord
from discord import app_commands
from discord.ext import tasks
import database as db
from config import (
    DISCORD_TOKEN,
    LEADERBOARD_UPDATE_INTERVAL,
    LEADERBOARD_SIZE,
)
from spotting import parse_spotting_message


class SpotBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await db.init_db()
        await self.tree.sync()
        self.update_leaderboard_task.start()

    @tasks.loop(seconds=LEADERBOARD_UPDATE_INTERVAL)
    async def update_leaderboard_task(self):
        """Periodically update the leaderboard."""
        await self.wait_until_ready()
        await update_leaderboard(self)

    async def on_ready(self):
        print(f"Logged in as {self.user}")


bot = SpotBot()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    spotted_channel_id = await db.get_config("spotted_channel_id")
    if not spotted_channel_id:
        return

    await process_spotting_message(message, spotted_channel_id)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if after.author.bot:
        return

    spotted_channel_id = await db.get_config("spotted_channel_id")
    if not spotted_channel_id:
        return

    await process_spotting_message(after, spotted_channel_id)


@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot:
        return

    spotted_channel_id = await db.get_config("spotted_channel_id")
    if not spotted_channel_id or str(message.channel.id) != spotted_channel_id:
        return

    await db.delete_spotting_message(message.id)


async def process_spotting_message(
    message: discord.Message,
    spotted_channel_id: str,
) -> bool:
    """Store or remove spotting data for a message in the spotted channel."""
    if str(message.channel.id) != spotted_channel_id:
        return False

    spotting = parse_spotting_message(message)
    if not spotting:
        await db.delete_spotting_message(message.id)
        return False

    await db.upsert_spotting_message(spotting)
    return True


async def update_leaderboard(client: discord.Client):
    """Update or post the leaderboard in the configured channel."""
    leaderboard_channel_id = await db.get_config("leaderboard_channel_id")
    if not leaderboard_channel_id:
        return

    channel = client.get_channel(int(leaderboard_channel_id))
    if not channel:
        return

    # Build the leaderboard embed
    embed = await build_leaderboard_embed()

    # Check if we have an existing leaderboard message to edit
    leaderboard_message_id = await db.get_config("leaderboard_message_id")
    if leaderboard_message_id:
        try:
            message = await channel.fetch_message(int(leaderboard_message_id))
            await message.edit(embed=embed)
            return
        except discord.NotFound:
            pass

    # Post a new leaderboard message
    message = await channel.send(embed=embed)
    await db.set_config("leaderboard_message_id", str(message.id))


async def build_leaderboard_embed() -> discord.Embed:
    """Build the leaderboard embed."""
    embed = discord.Embed(
        title="Spotted Leaderboard",
        color=discord.Color.gold()
    )

    # Top spotters (spotted the most people)
    top_senders = await db.get_top_senders(LEADERBOARD_SIZE)
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
    top_receivers = await db.get_top_receivers(LEADERBOARD_SIZE)
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
    if channel_type == "spotted":
        await db.set_config("spotted_channel_id", str(channel.id))
        await interaction.response.send_message(
            f"Spotted channel set to {channel.mention}",
            ephemeral=True
        )
    elif channel_type == "leaderboard":
        await db.set_config("leaderboard_channel_id", str(channel.id))
        # Clear old message ID so a new one gets posted
        await db.set_config("leaderboard_message_id", "")
        await interaction.response.send_message(
            f"Leaderboard channel set to {channel.mention}",
            ephemeral=True
        )


@bot.tree.command(name="leaderboard", description="Refresh the leaderboard")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await update_leaderboard(bot)
    await interaction.followup.send("Leaderboard updated!", ephemeral=True)


@bot.tree.command(name="mystats", description="View your spotted stats")
async def mystats(interaction: discord.Interaction):
    people_spotted, times_spotted = await db.get_user_stats(interaction.user.id)

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
    people_spotted, times_spotted = await db.get_user_stats(user.id)

    embed = discord.Embed(
        title=f"Stats for {user.display_name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="People Spotted", value=str(people_spotted), inline=True)
    embed.add_field(name="Times Spotted", value=str(times_spotted), inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="backfill", description="Import all existing messages from the spotted channel")
@app_commands.default_permissions(administrator=True)
async def backfill(interaction: discord.Interaction):
    spotted_channel_id = await db.get_config("spotted_channel_id")
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
    async for message in channel.history(limit=None):
        spotting = parse_spotting_message(message)
        if not spotting:
            continue
        spottings.append(spotting)
        message_count += 1

    await db.replace_all_spotting_messages(spottings)

    # Update the leaderboard
    await update_leaderboard(bot)

    await interaction.followup.send(
        f"Backfill complete! Processed {message_count} messages with mentions.",
        ephemeral=True
    )


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("Error: DISCORD_TOKEN not set in .env file")
        exit(1)
    bot.run(DISCORD_TOKEN)
