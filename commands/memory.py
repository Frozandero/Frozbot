"""Memory commands for Frozbot."""

import logging
from typing import Optional

import discord
from discord import app_commands

import config
from database import add_memory, delete_memory, count_memories_by_user
from views import MemoryPaginationView

logger = logging.getLogger(__name__)


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
            user_id = user.id if user else None
            display_name = user.display_name if user else None

            add_memory(
                username,
                memory,
                interaction.channel.id if interaction.channel else 0,
                user_id=user_id,
                display_name=display_name,
            )

            label = (
                f"{display_name} (@{username}, id:{user_id})"
                if user
                else "this channel"
            )
            await interaction.response.send_message(
                f"Memory set for {label}.",
                ephemeral=True,
            )
        except Exception as e:
            logger.exception(
                "memory_set_error",
                extra={
                    "user_id": interaction.user.id,
                    "error_type": type(e).__name__,
                },
            )
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
        target_user_id = user.id if user else None
        display_name = user.display_name if user else None
        try:
            total_memories = count_memories_by_user(
                username,
                interaction.channel.id if interaction.channel else 0,
                user_id=target_user_id,
            )
            if total_memories == 0:
                label = display_name or username
                await interaction.response.send_message(
                    f"No memories found for {label}.",
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
                user_id=target_user_id,
                display_name=display_name,
            )

            await interaction.response.send_message(
                content=view.format_memories_message(), view=view
            )
        except Exception as e:
            logger.exception(
                "memory_get_error",
                extra={
                    "user_id": interaction.user.id,
                    "error_type": type(e).__name__,
                },
            )
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
            logger.exception(
                "memory_delete_error",
                extra={
                    "user_id": interaction.user.id,
                    "memory_id": memory_id,
                    "error_type": type(e).__name__,
                },
            )
            await interaction.response.send_message(
                f"Error deleting memory: {e}",
                ephemeral=True,
            )
