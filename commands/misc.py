"""Miscellaneous commands for Frozbot."""

import io
import logging
from typing import Optional

import discord
from discord import app_commands

import config
from iq import compute_deterministic_iq
from eleven import generate_tts_async, get_eleven_client

logger = logging.getLogger(__name__)


def setup_misc_commands(tree: app_commands.CommandTree, client: discord.Client):
    """Setup miscellaneous commands."""

    @tree.command(
        name="iq",
        description="Get the IQ of a user.",
        guild=None,
    )
    async def iq_command(
        interaction: discord.Interaction, user: Optional[discord.Member] = None
    ) -> None:
        """Get the deterministic IQ of a user."""
        target_user = user if user else interaction.user
        iq_value: int = compute_deterministic_iq(target_user)

        if user:
            try:
                await interaction.response.send_message(
                    f"{user.display_name}'s IQ is {iq_value}."
                )
            except discord.errors.NotFound:
                logger.warning(
                    "iq_response_interaction_not_found",
                    extra={"user_id": user.id},
                )
                return
        else:
            try:
                await interaction.response.send_message(
                    f"{interaction.user.display_name}, your IQ is {iq_value}."
                )
            except discord.errors.NotFound:
                logger.warning(
                    "iq_response_interaction_not_found",
                    extra={"user_id": interaction.user.id},
                )
                return

    async def _handle_say_command(
        interaction: discord.Interaction,
        message: str,
        tts: bool = False,
    ) -> None:
        """Make the bot say whatever the owner wants (owner only)."""
        try:
            if not config.is_owner(interaction.user.id):
                await interaction.response.send_message(
                    "❌ **Access Denied**\n\nOnly the bot owner can use this command.",
                    ephemeral=True,
                )
                return

            if tts:
                # Check if ElevenLabs is configured
                if not get_eleven_client():
                    await interaction.response.send_message(
                        "❌ **TTS Unavailable**\n\nElevenLabs API key not configured.",
                        ephemeral=True,
                    )
                    return

                await interaction.response.defer(thinking=True)

                tts_audio = await generate_tts_async(message)
                if not tts_audio:
                    await interaction.followup.send(
                        "❌ **TTS Failed**\n\nFailed to generate text-to-speech audio.",
                        ephemeral=True,
                    )
                    return

                tts_buf = io.BytesIO(tts_audio)
                tts_file = discord.File(tts_buf, filename="message.ogg")
                await interaction.followup.send(file=tts_file)
            else:
                await interaction.response.send_message(message)

        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"❌ **Error**\n\nAn error occurred: {str(e)[:200]}...",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"❌ **Error**\n\nAn error occurred: {str(e)[:200]}...",
                    ephemeral=True,
                )

    if config.is_tts_configured():
        @tree.command(
            name="say",
            description="[Owner Only] Make the bot say something. Use TTS to send only audio.",
            guild=None,
        )
        async def say_command(
            interaction: discord.Interaction,
            message: str,
            tts: bool = False,
        ) -> None:
            await _handle_say_command(interaction, message, tts)
    else:
        @tree.command(
            name="say",
            description="[Owner Only] Make the bot say something.",
            guild=None,
        )
        async def say_command(
            interaction: discord.Interaction,
            message: str,
        ) -> None:
            await _handle_say_command(interaction, message, False)
