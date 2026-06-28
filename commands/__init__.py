"""Command modules for Frozbot."""

import config
from commands.ask import setup_ask_commands
from commands.imagine import setup_imagine_commands
from commands.memory import setup_memory_commands
from commands.admin import setup_admin_commands
from commands.misc import setup_misc_commands
from commands.summarize import setup_summarize_commands


def setup_all_commands(tree, client):
    """Setup all command modules."""
    if config.ASK_ENABLE:
        setup_ask_commands(tree, client)
    if config.IMAGINE_ENABLE:
        setup_imagine_commands(tree, client)
    setup_summarize_commands(tree, client)
    setup_memory_commands(tree, client)
    setup_admin_commands(tree, client)
    setup_misc_commands(tree, client)


def rebuild_all_commands(tree, client):
    """Rebuild command registrations from the current in-memory config."""
    tree.clear_commands(guild=None)
    if config.IS_DEV_SERVER_COMMAND:
        tree.clear_commands(guild=config.IS_DEV_SERVER_COMMAND)
    setup_all_commands(tree, client)
