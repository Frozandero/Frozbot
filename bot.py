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
        user.created_at.isoformat() if getattr(user, "created_at", None) else ""
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
    """Generate a deterministic IQ-like value for a user from a normal distribution.

    The distribution uses mean 100 and standard deviation 15, which is conventional for IQ.
    The value is rounded to the nearest integer and floored at 0 to avoid negative results.
    """
    seed_value: int = compute_seed_from_user(user)
    rng = random.Random(seed_value)
    iq_value: float = rng.normalvariate(mean, stddev)
    return max(0, int(round(iq_value)))


load_dotenv()

TOKEN: Optional[str] = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID_ENV: Optional[str] = os.getenv("DISCORD_GUILD_ID")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@tree.command(
    name="iq",
    description="Get your (fake) IQ, deterministically calculated from your account.",
)
async def iq_command(interaction: discord.Interaction) -> None:
    user = interaction.user
    iq_value: int = compute_deterministic_iq(user)
    await interaction.response.send_message(f"{user.mention}, your IQ is {iq_value}.")


@client.event
async def on_ready() -> None:
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    try:
        if GUILD_ID_ENV:
            test_guild = discord.Object(id=int(GUILD_ID_ENV))
            # Copy global commands to the test guild for instant availability
            tree.copy_global_to(guild=test_guild)
            await tree.sync(guild=test_guild)
            print(f"Slash commands synced to guild {GUILD_ID_ENV}.")
        else:
            await tree.sync()
            print("Slash commands synced globally (may take up to an hour to appear).")
    except (
        Exception
    ) as sync_error:  # noqa: BLE001 - broad by design for startup logging
        print(f"Failed to sync commands: {sync_error}")


def main() -> None:
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN environment variable is not set. "
            "Create a .env file or set the variable and try again."
        )
    client.run(TOKEN)


if __name__ == "__main__":
    main()
