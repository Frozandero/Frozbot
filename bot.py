import os
import hashlib
import random
from typing import Optional

import discord
from discord import app_commands
from dotenv import load_dotenv


MEAN_IQ: float = 100.0
STDDEV_IQ: float = 15.0


def build_user_seed_material(user: discord.abc.User) -> str:
    """Build a string of persistent user attributes to feed into a hash.

    Using stable identifiers ensures the generated IQ is deterministic for a given user.
    """
    user_id_str: str = str(user.id)
    created_at_iso: str = (
        user.created_at.isoformat() if getattr(user, "created_at", None) else ""  # type: ignore
    )
    username: str = getattr(user, "name", "")
    discriminator: str = getattr(
        user, "discriminator", ""
    )  # legacy, may be empty on new usernames

    seed_components = [user_id_str, created_at_iso, username, discriminator]
    return "|".join(seed_components)


def compute_seed_from_user(user: discord.abc.User) -> int:
    """Hash stable user info into a large integer seed."""
    seed_material: str = build_user_seed_material(user)
    digest_bytes: bytes = hashlib.sha256(seed_material.encode("utf-8")).digest()
    return int.from_bytes(digest_bytes, byteorder="big", signed=False)


def compute_deterministic_iq(
    user: discord.abc.User, mean: float = MEAN_IQ, stddev: float = STDDEV_IQ
) -> int:
    """Find out the IQ of a user."""
    seed_value: int = compute_seed_from_user(user)
    rng = random.Random(seed_value)
    iq_value: float = rng.normalvariate(mean, stddev)
    return max(0, int(round(iq_value)))


load_dotenv()

TOKEN: Optional[str] = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID_ENV: Optional[str] = os.getenv("DISCORD_GUILD_ID")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@tree.command(
    name="iq",
    description="Get your (fake) IQ, deterministically calculated from your account.",
)
async def iq_command(
    interaction: discord.Interaction, user: Optional[discord.Member] = None
) -> None:
    # If no user specified, use the command user
    target_user = user if user else interaction.user

    iq_value: int = compute_deterministic_iq(target_user)

    if user:
        # Someone else's IQ
        await interaction.response.send_message(
            f"{user.display_name}'s IQ is {iq_value}."
        )
    else:
        # Own IQ
        await interaction.response.send_message(
            f"{interaction.user.display_name}, your IQ is {iq_value}."
        )


# Development server refresh command (only visible on your dev server)
@tree.command(
    name="refresh",
    description="[Dev Only] Refresh slash commands on the server.",
    guild=(
        discord.Object(id=int(os.getenv("DEV_SERVER_ID", "0")))
        if os.getenv("DEV_SERVER_ID")
        else None
    ),
)
async def refresh_commands(interaction: discord.Interaction) -> None:
    # Check if the user is the bot owner (you)
    if interaction.user.id != int(os.getenv("OWNER_ID", "0")):
        await interaction.response.send_message(
            "You don't have permission to use this command.", ephemeral=True
        )
        return

    try:
        await interaction.response.defer(ephemeral=True)

        if GUILD_ID_ENV:
            test_guild = discord.Object(id=int(GUILD_ID_ENV))
            # Clear existing commands first, then sync new ones
            tree.clear_commands(guild=test_guild)
            await tree.sync(guild=test_guild)
            await interaction.followup.send(
                f"Commands cleared and refreshed on guild {GUILD_ID_ENV}!",
                ephemeral=True,
            )
        else:
            # Clear existing commands first, then sync new ones globally
            tree.clear_commands(guild=None)
            await tree.sync()
            await interaction.followup.send(
                "Commands cleared and refreshed globally! (May take up to 1 hour)",
                ephemeral=True,
            )

    except Exception as e:
        await interaction.followup.send(
            f"Failed to refresh commands: {e}", ephemeral=True
        )


@client.event
async def on_ready() -> None:
    print(f"Logged in as {client.user} (ID: {client.user.id})")  # type: ignore

    try:
        if GUILD_ID_ENV:
            test_guild = discord.Object(id=int(GUILD_ID_ENV))
            # Sync commands to the specific guild for instant availability
            await tree.sync(guild=test_guild)
            print(f"Slash commands synced to guild {GUILD_ID_ENV}.")
        else:
            await tree.sync()
            print("Slash commands synced globally (may take up to 1 hour to appear).")
    except Exception as sync_error:
        print(f"Failed to sync commands: {sync_error}")
        print(
            "Make sure your bot has the 'applications.commands' scope and proper permissions."
        )


def main() -> None:
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN environment variable is not set. "
            "Create a .env file or set the variable and try again."
        )
    client.run(TOKEN)


if __name__ == "__main__":
    main()
