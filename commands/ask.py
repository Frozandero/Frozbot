"""Ask command for Frozbot."""

import datetime
import io
from typing import Optional

import discord
from discord import app_commands
from PIL import Image

import config
from context import build_ask_context
from database import is_banned
from llm import get_llm_client
from eleven import get_eleven_client
from request_queue import RequestType, add_request_to_queue
from utils import store_user_question, cleanup_expired_cooldowns


def setup_ask_commands(tree: app_commands.CommandTree, client: discord.Client):
    """Setup ask-related commands."""

    async def _handle_ask_command(
        interaction: discord.Interaction,
        question: str,
        image: Optional[discord.Attachment] = None,
        tts: Optional[bool] = False,
    ) -> None:
        if not config.ASK_ENABLE:
            await interaction.response.send_message(
                "The ask command is disabled.",
                ephemeral=True,
            )
            return

        if is_banned(interaction.user.id):
            await interaction.response.send_message(
                "You are banned from using the ask command.",
                ephemeral=True,
            )
            return

        if tts and not get_eleven_client():
            await interaction.response.send_message(
                "TTS is not enabled. Please contact the server owner.",
                ephemeral=True,
            )
            return

        # Rate limiting check (owner bypass)
        user_id = interaction.user.id
        request_start_time = datetime.datetime.now()

        # Store the question for potential retry
        store_user_question(user_id, question, tts if tts else False, image)

        if not config.is_owner(user_id):
            current_time = request_start_time

            if user_id in config.ASK_COMMAND_COOLDOWNS:
                last_used = config.ASK_COMMAND_COOLDOWNS[user_id]
                time_diff = current_time - last_used
                minutes_passed = time_diff.total_seconds() / 60

                limit_minutes = (
                    config.ASK_COMMAND_COOLDOWN_MINUTES * 5
                    if tts
                    else config.ASK_COMMAND_COOLDOWN_MINUTES
                )

                if minutes_passed < limit_minutes:
                    remaining_minutes = int(limit_minutes - minutes_passed)
                    try:
                        await interaction.response.send_message(
                            f"⏰ Rate limit: You can only ask questions once every {limit_minutes} minutes {'(TTS)' if tts else ''}. Please wait {remaining_minutes} more minutes.",
                            ephemeral=True,
                        )
                    except discord.errors.NotFound:
                        print(
                            f"Interaction not found when sending rate limit message for user {user_id}"
                        )
                        return
                    return

        # Cleanup expired cooldowns occasionally
        if len(config.ASK_COMMAND_COOLDOWNS) > 100:
            cleanup_expired_cooldowns()

        # Also cleanup recent questions if we have too many stored
        if len(config.RECENT_QUESTIONS) > 200:
            users_to_remove = [
                uid
                for uid, questions in config.RECENT_QUESTIONS.items()
                if not questions
            ]
            for uid in users_to_remove:
                del config.RECENT_QUESTIONS[uid]

        llm_client = get_llm_client()
        if not llm_client:
            try:
                await interaction.response.send_message(
                    "The bot is not configured with an LLM provider. Please contact the server owner.",
                    ephemeral=True,
                )
            except discord.errors.NotFound:
                print(
                    f"Interaction not found when sending LLM config error for: {question}"
                )
                return
            return

        # Defer the response
        try:
            await interaction.response.defer(thinking=True)
        except discord.errors.NotFound:
            print(f"Interaction already timed out for question: {question}")
            return

        # Prepare optional image media part
        media_parts: Optional[list] = None
        try:
            if image and getattr(image, "content_type", "").startswith("image/"):
                image_bytes = await image.read()
                pil_img = Image.open(io.BytesIO(image_bytes))
                media_parts = [pil_img]
        except Exception as e:
            print(f"Failed to process image attachment: {e}")

        built_context = await build_ask_context(
            client=client,
            user=interaction.user,
            channel=interaction.channel,
            guild=interaction.guild,
            question=question,
        )

        # Add request to queue
        request_id = await add_request_to_queue(
            RequestType.ASK,
            interaction,
            built_context.processed_question,
            built_context.context_string,
            user_id,
            priority=1 if config.is_owner(user_id) else 0,
            media_parts=media_parts,
            tts=tts if tts else False,
        )

        print(f"[QUEUE] Request {request_id} added to queue")

    if config.is_tts_configured():
        @tree.command(name="ask", description="Ask the bot a question.", guild=None)
        async def ask_command(
            interaction: discord.Interaction,
            question: str,
            image: Optional[discord.Attachment] = None,
            tts: Optional[bool] = False,
        ) -> None:
            await _handle_ask_command(interaction, question, image, tts)
    else:
        @tree.command(name="ask", description="Ask the bot a question.", guild=None)
        async def ask_command(
            interaction: discord.Interaction,
            question: str,
            image: Optional[discord.Attachment] = None,
        ) -> None:
            await _handle_ask_command(interaction, question, image, False)
