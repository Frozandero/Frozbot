import os
import hashlib
import random
import datetime
from typing import Optional

import discord
from discord import app_commands
from dotenv import load_dotenv
from google import genai
from google.genai import types

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

GUILD_ID_IF_PRESENT: Optional[discord.Object] = (
    discord.Object(id=int(os.getenv("DEV_SERVER_ID", "0")))
    if os.getenv("DEV_SERVER_ID")
    else None
)

IS_DEV_SERVER_COMMAND: Optional[discord.Object] = (
    discord.Object(id=int(os.getenv("DEV_SERVER_ID", "0")))
    if os.getenv("DEV_SERVER_ID")
    else None
)

GEMINI_CLIENT = genai.Client() if os.getenv("GEMINI_API_KEY") else None

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


@tree.command(
    name="ask",
    description="Ask the bot a question.",
    guild=discord.Object(id=int(os.getenv("DEV_SERVER_ID", "0"))),
)
async def ask_command(interaction: discord.Interaction, question: str) -> None:
    if not GEMINI_CLIENT:
        await interaction.response.send_message(
            "The bot is not configured to use Gemini AI. Please contact the server owner.",
            ephemeral=True,
        )
        return

    # Send initial response that question is being processed
    await interaction.response.send_message(
        "Question is being processed...",
        ephemeral=True,
    )

    # Gathering context
    # Gather server context
    server_context = interaction.guild.name if interaction.guild else None
    # Gather mentioned users context - for slash commands, we can check if there are any user mentions in the question
    mentioned_users_context = []
    # Check if the question contains any user mentions (e.g., @username)
    if "@" in question:
        # Extract potential usernames and fetch their server data
        words = question.split()
        for word in words:
            if word.startswith("@"):
                username = word[1:]  # Remove the @ symbol
                # Try to find the user in the server
                if interaction.guild:
                    # Search by display name first (more common in Discord)
                    member = interaction.guild.get_member_named(username)
                    if member:
                        mentioned_users_context.append(
                            {
                                "name": member.display_name,
                                "username": member.name,
                                "id": member.id,
                                "joined_at": (
                                    member.joined_at.strftime("%Y-%m-%d")
                                    if member.joined_at
                                    else "Unknown"
                                ),
                                "roles": (
                                    [role.name for role in member.roles[1:]]
                                    if len(member.roles) > 1
                                    else []
                                ),  # Skip @everyone role
                            }
                        )
                    else:
                        # If not found by display name, try to find by username
                        member = discord.utils.get(
                            interaction.guild.members, name=username
                        )
                        if member:
                            mentioned_users_context.append(
                                {
                                    "name": member.display_name,
                                    "username": member.name,
                                    "joined_at": (
                                        member.joined_at.strftime("%Y-%m-%d")
                                        if member.joined_at
                                        else "Unknown"
                                    ),
                                    "roles": (
                                        [role.name for role in member.roles[1:]]
                                        if len(member.roles) > 1
                                        else []
                                    ),
                                }
                            )
                        else:
                            # User not found in server
                            mentioned_users_context.append(
                                f"@{username} (not found in server)"
                            )
                else:
                    mentioned_users_context.append(f"@{username} (no server context)")
    # Gather date context with current timestamp
    date_context = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    # Gather message context - for slash commands, this is the question parameter
    message_context = question
    # Gather user context - get detailed information about the user asking the question
    user_context = {}
    if interaction.user:
        user_context = {
            "name": (
                interaction.user.display_name
                if hasattr(interaction.user, "display_name")
                else interaction.user.name
            ),
            "username": interaction.user.name,
            "created_at": (
                interaction.user.created_at.strftime("%Y-%m-%d")
                if hasattr(interaction.user, "created_at")
                and interaction.user.created_at
                else "Unknown"
            ),
            "bot": interaction.user.bot if hasattr(interaction.user, "bot") else False,
        }

        # If it's a member (user in a guild), get additional server-specific info
        if isinstance(interaction.user, discord.Member):
            user_context.update(
                {
                    "joined_at": (
                        interaction.user.joined_at.strftime("%Y-%m-%d")
                        if interaction.user.joined_at
                        else "Unknown"
                    ),
                    "roles": (
                        [role.name for role in interaction.user.roles[1:]]
                        if len(interaction.user.roles) > 1
                        else []
                    ),  # Skip @everyone role
                    "top_role": (
                        interaction.user.top_role.name
                        if interaction.user.top_role
                        else "No roles"
                    ),
                    "nickname": (
                        interaction.user.nick if interaction.user.nick else None
                    ),
                }
            )
    # Gather channel context
    channel_context = interaction.channel.name if getattr(interaction.channel, "name", None) else None  # type: ignore

    # Build context string as server instructions
    # Format mentioned users context nicely
    if mentioned_users_context:
        if isinstance(mentioned_users_context[0], dict):
            users_info = []
            for user_data in mentioned_users_context:
                if isinstance(user_data, dict):
                    roles_str = (
                        ", ".join(user_data["roles"])
                        if user_data["roles"]
                        else "No roles"
                    )
                    users_info.append(
                        f"- {user_data['name']} (@{user_data['username']}, ID: {user_data['id']}, Joined: {user_data['joined_at']}, Roles: {roles_str})"
                    )
                else:
                    users_info.append(str(user_data))
            mentioned_users_str = "\n".join(users_info)
        else:
            mentioned_users_str = ", ".join(mentioned_users_context)
    else:
        mentioned_users_str = "None"

    # Format user context nicely
    if user_context:
        if isinstance(user_context, dict):
            user_info_parts = []
            user_info_parts.append(f"Name: {user_context['name']}")
            user_info_parts.append(f"Username: @{user_context['username']}")
            user_info_parts.append(f"Account Created: {user_context['created_at']}")
            user_info_parts.append(f"Bot: {user_context['bot']}")

            if "joined_at" in user_context:
                user_info_parts.append(f"Joined Server: {user_context['joined_at']}")
            if "roles" in user_context:
                roles_str = (
                    ", ".join(user_context["roles"])
                    if user_context["roles"]
                    else "No roles"
                )
                user_info_parts.append(f"Roles: {roles_str}")
            if "top_role" in user_context:
                user_info_parts.append(f"Top Role: {user_context['top_role']}")
            if "nickname" in user_context and user_context["nickname"]:
                user_info_parts.append(f"Nickname: {user_context['nickname']}")

            user_context_str = "\n".join(user_info_parts)
        else:
            user_context_str = str(user_context)
    else:
        user_context_str = "Unknown"

    # Get bot name from bot nickname if it exists, otherwise use "Frozbot"
    bot_name = (
        interaction.guild.me.nick if interaction.guild.me.nick else "Frozbot"  # type: ignore
    )

    context_string = f"You are a Discord bot named {bot_name}. You don't provide context details to the querying user unless you are asked explicitly. You are to respond to the user's question based on the following context:\nServer: {server_context}\nMentioned Users:\n{mentioned_users_str}\nDate: {date_context}\nMessage: {message_context}\nUser:\n{user_context_str}\nChannel: {channel_context}"
    # Send context to Gemini
    response = GEMINI_CLIENT.models.generate_content(
        model="gemini-2.0-flash-exp",
        config=types.GenerateContentConfig(
            system_instruction=context_string,  # type: ignore
        ),
        contents=question,
    )
    # Send response to user
    await interaction.followup.send(response.text)  # type: ignore


# Development server refresh command (only visible on your dev server)
@tree.command(
    name="refresh",
    description="[Dev Only] Refresh slash commands on the server.",
    guild=IS_DEV_SERVER_COMMAND,
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

        # Force clear ALL commands everywhere first
        tree.clear_commands(guild=None)  # Clear global commands
        if GUILD_ID_ENV:
            test_guild = discord.Object(id=int(GUILD_ID_ENV))
            tree.clear_commands(guild=test_guild)  # Clear guild commands too

        # Now sync everything fresh
        await tree.sync()  # Sync global commands

        if GUILD_ID_ENV:
            await tree.sync(guild=test_guild)  # Sync guild commands
            await interaction.followup.send(
                f"ALL commands cleared and refreshed globally and on guild {GUILD_ID_ENV}!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "ALL commands cleared and refreshed globally! (May take up to 1 hour)",
                ephemeral=True,
            )

    except Exception as e:
        await interaction.followup.send(
            f"Failed to refresh commands: {e}", ephemeral=True
        )


@client.event
async def on_ready() -> None:
    print(f"Logged in as {client.user} (ID: {client.user.id})")  # type: ignore
    print("Bot is ready! Starting command sync...")

    try:
        if GUILD_ID_ENV:
            print(f"GUILD_ID_ENV is set to: {GUILD_ID_ENV}")
            test_guild = discord.Object(id=int(GUILD_ID_ENV))
            print(f"Created guild object: {test_guild}")

            # When testing with guild ID, sync both global and guild commands
            print("Syncing global commands...")
            await tree.sync()  # Sync global commands first
            print("Global commands synced successfully!")

            print("Syncing guild commands...")
            await tree.sync(guild=test_guild)  # Then sync to specific guild
            print(f"Slash commands synced globally and to guild {GUILD_ID_ENV}.")
        else:
            print("No GUILD_ID_ENV set, syncing globally only...")
            # Production mode: sync globally only
            await tree.sync()
            print("Slash commands synced globally (may take up to 1 hour to appear).")
    except Exception as sync_error:
        print(f"Failed to sync commands: {sync_error}")
        print(f"Error type: {type(sync_error)}")
        import traceback

        traceback.print_exc()
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
