"""
Frozbot - A feature-rich Discord AI bot.

This is the main entry point for the bot. It initializes the Discord client,
sets up commands from the modular command files, and starts the bot.
"""

import discord
from discord import app_commands

import config
from database import init_db
from commands import setup_all_commands
from handlers import setup_handlers


def create_bot() -> tuple[discord.Client, app_commands.CommandTree]:
    """Create and configure the Discord bot client and command tree."""
    # Setup intents
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.guilds = True

    # Create client and command tree
    client = discord.Client(intents=intents, max_messages=10000)
    tree = app_commands.CommandTree(client)

    return client, tree


def main() -> None:
    """Main entry point for Frozbot."""
    # Check for required token
    if not config.TOKEN:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN environment variable is not set. "
            "Create a .env file or set the variable and try again."
        )

    # Initialize database
    init_db()

    # Create bot
    client, tree = create_bot()

    # Setup all commands
    setup_all_commands(tree, client)

    # Setup event handlers
    setup_handlers(client, tree)

    # Run the bot
    print("Starting Frozbot...")
    client.run(config.TOKEN)


if __name__ == "__main__":
    main()
