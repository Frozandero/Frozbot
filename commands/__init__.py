"""Command modules for Frozbot."""

from commands.ask import setup_ask_commands
from commands.imagine import setup_imagine_commands
from commands.memory import setup_memory_commands
from commands.admin import setup_admin_commands
from commands.misc import setup_misc_commands


def setup_all_commands(tree, client):
    """Setup all command modules."""
    setup_ask_commands(tree, client)
    setup_imagine_commands(tree, client)
    setup_memory_commands(tree, client)
    setup_admin_commands(tree, client)
    setup_misc_commands(tree, client)
