"""Summarize command for Frozbot."""

from typing import Optional

import discord
from discord import app_commands

import config
from context import get_or_refresh_channel_summary
from database import is_banned
from llm import get_llm_client


def setup_summarize_commands(tree: app_commands.CommandTree, client: discord.Client):
    """Setup summarization commands."""

    @tree.command(
        name="summarize",
        description="Summarize recent messages in this channel.",
        guild=None,
    )
    @app_commands.describe(
        depth="Number of recent messages to consider, from 5 to 200.",
        refresh="Force a fresh summary instead of using the cache.",
    )
    async def summarize_command(
        interaction: discord.Interaction,
        depth: Optional[int] = None,
        refresh: bool = False,
    ) -> None:
        """Summarize recent channel conversation."""
        if is_banned(interaction.user.id):
            await interaction.response.send_message(
                "You are banned from using LLM commands.",
                ephemeral=True,
            )
            return

        if not get_llm_client():
            await interaction.response.send_message(
                "The bot is not configured with an LLM provider. Please contact the server owner.",
                ephemeral=True,
            )
            return

        if interaction.channel is None:
            await interaction.response.send_message(
                "This command needs a channel to summarize.",
                ephemeral=True,
            )
            return

        if depth is None:
            effective_depth = max(5, min(config.CHANNEL_SUMMARY_DEPTH, 200))
        else:
            effective_depth = depth

        if depth is not None and (effective_depth < 5 or effective_depth > 200):
            await interaction.response.send_message(
                "Please choose a depth between 5 and 200 messages.",
                ephemeral=True,
            )
            return

        try:
            await interaction.response.defer(thinking=True)
        except discord.errors.NotFound:
            return

        summary_depth = effective_depth if depth is not None else None
        summary, _newest_id, refreshed = await get_or_refresh_channel_summary(
            interaction.channel,
            depth=summary_depth,
            use_cache=True,
            force_refresh=refresh,
            respect_config=False,
        )

        if not summary:
            await interaction.followup.send(
                "No recent messages were available to summarize.",
                ephemeral=True,
            )
            return

        source_label = "fresh" if refreshed else "cached"
        content = (
            f"**Channel Summary** ({source_label}, last up to {effective_depth} messages)\n\n"
            f"{summary}"
        )
        if len(content) > 2000:
            content = content[:1997] + "..."

        await interaction.followup.send(content=content)
