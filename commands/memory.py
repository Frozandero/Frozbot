"""Memory commands for Frozbot."""

from typing import Optional

import discord
from discord import app_commands

import config
from database import add_memory, delete_memory, count_memories_by_user
from views import MemoryPaginationView


def setup_memory_commands(tree: app_commands.CommandTree, client: discord.Client):
    """Setup memory-related commands."""

    @tree.command(
        name="setmemory",
        description="Set a memory for the bot.",
        guild=None,
    )
    async def set_memory_command(
        interaction: discord.Interaction,
        memory: str,
        user: Optional[discord.Member] = None,
    ) -> None:
        # Only owner can use this command
        if not config.is_owner(interaction.user.id):
            await interaction.response.send_message(
                "Only owner can set memories at the moment.",
                ephemeral=True,
            )
            return

        try:
            username = user.name if user else "*"

            add_memory(
                username, memory, interaction.channel.id if interaction.channel else 0
            )

            await interaction.response.send_message(
                f"Memory set for {username}.",
                ephemeral=True,
            )
        except Exception as e:
            print(f"Error setting memory: {e}")
            await interaction.response.send_message(
                f"Error setting memory: {e}",
                ephemeral=True,
            )

    @tree.command(
        name="getmemory",
        description="Get memories of the bot.",
        guild=None,
    )
    async def get_memory_command(
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
        limit: int = 10,
    ) -> None:
        username = user.name if user else "*"
        try:
            total_memories = count_memories_by_user(
                username, interaction.channel.id if interaction.channel else 0
            )
            if total_memories == 0:
                await interaction.response.send_message(
                    f"No memories found for {username}.",
                    ephemeral=True,
                )
                return

            # Use pagination
            page_size = min(limit, 10)
            view = MemoryPaginationView(
                username,
                page=0,
                page_size=page_size,
                channel_id=interaction.channel.id if interaction.channel else 0,
            )

            await interaction.response.send_message(
                content=view.format_memories_message(), view=view
            )
        except Exception as e:
            print(f"Error getting memory: {e}")
            await interaction.response.send_message(
                f"Error getting memory: {e}",
                ephemeral=True,
            )

    @tree.command(
        name="deletememory",
        description="Delete a memory for the bot.",
        guild=None,
    )
    async def delete_memory_command(
        interaction: discord.Interaction,
        memory_id: int,
    ) -> None:
        if not config.is_owner(interaction.user.id):
            await interaction.response.send_message(
                "Only owner can delete memories at the moment.",
                ephemeral=True,
            )
            return
        try:
            deleted = delete_memory(
                memory_id, interaction.channel.id if interaction.channel else 0
            )
            if not deleted:
                await interaction.response.send_message(
                    f"Memory {memory_id} was not found in this channel.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                f"Memory {memory_id} deleted.",
                ephemeral=True,
            )
        except Exception as e:
            print(f"Error deleting memory: {e}")
            await interaction.response.send_message(
                f"Error deleting memory: {e}",
                ephemeral=True,
            )
