"""Miscellaneous commands for Frozbot."""

import io
from typing import Optional

import discord
from discord import app_commands

import config
from iq import compute_deterministic_iq
from eleven import generate_tts_async, get_eleven_client


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
                print(
                    f"Interaction not found when sending IQ response for user {user.id}"
                )
                return
        else:
            try:
                await interaction.response.send_message(
                    f"{interaction.user.display_name}, your IQ is {iq_value}."
                )
            except discord.errors.NotFound:
                print(
                    f"Interaction not found when sending IQ response for user {interaction.user.id}"
                )
                return

    @tree.command(
        name="queue", description="Check the current queue status.", guild=None
    )
    async def queue_command(interaction: discord.Interaction) -> None:
        """Show the current queue status."""
        try:
            queue_size = config.REQUEST_QUEUE.qsize()

            if queue_size == 0:
                await interaction.response.send_message(
                    "📋 **Queue Status**\n\n"
                    "✅ The queue is currently empty.\n"
                    "All requests have been processed.",
                    ephemeral=True,
                )
            else:
                queue_info = f"📋 **Queue Status**\n\n"
                queue_info += f"🔄 **Active Requests:** {queue_size}\n"
                queue_info += f"⚙️ **Processor Status:** {'Running' if config.QUEUE_PROCESSOR_RUNNING else 'Stopped'}\n\n"

                if queue_size > 0:
                    queue_info += "📝 **Queue Details:**\n"
                    queue_info += f"• Total requests waiting: {queue_size}\n"
                    queue_info += f"• Estimated wait time: {queue_size * config.REQUEST_DELAY_SECONDS} seconds\n"
                    queue_info += f"• Delay between requests: {config.REQUEST_DELAY_SECONDS} seconds\n\n"
                    queue_info += "💡 **Tip:** You can use `/ask` to add your question to the queue."

                await interaction.response.send_message(queue_info, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(
                f"❌ **Error checking queue status**\n\nAn error occurred: {str(e)[:200]}...",
                ephemeral=True,
            )

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
