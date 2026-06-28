"""Event handlers for Frozbot."""

import datetime
import hashlib
import logging
from typing import Optional

import discord

from attachments import ImageValidationError, read_validated_attachment
import config
from context import build_ask_context
from database import is_banned
from llm import get_llm_client
from request_queue import (
    RequestType,
    add_request_to_queue,
    add_message_request_to_queue,
)
from retry import (
    cleanup_expired_retry_records,
    cleanup_retry_record,
    load_retry_context,
    load_retry_media,
    load_retry_record,
)
from utils import format_duration_seconds

logger = logging.getLogger(__name__)


def _stable_question_hash(question: str) -> str:
    return hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]


def _question_matches_retry_hash(question: str, question_hash: str) -> bool:
    legacy_hash = str(hash(question) % 1000000)
    return question_hash in {_stable_question_hash(question), legacy_hash}


async def _disable_retry_button_message(
    interaction: discord.Interaction, custom_id: str
) -> None:
    try:
        disable_view = discord.ui.View()
        disable_view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.primary,
                label="🔄 Retry",
                custom_id=custom_id,
                disabled=True,
            )
        )
        await interaction.message.edit(view=disable_view)
    except Exception:
        pass


def setup_handlers(client: discord.Client, tree: discord.app_commands.CommandTree):
    """Setup all event handlers."""

    @client.event
    async def on_interaction(interaction: discord.Interaction) -> None:
        """Handle button interactions for retry functionality."""
        # Only handle button interactions, let the command tree handle slash commands
        if interaction.type != discord.InteractionType.component:
            return

        if not interaction.data or "custom_id" not in interaction.data:
            return

        custom_id = interaction.data["custom_id"]

        # Passive cleanup of expired used retry buttons
        try:
            now = datetime.datetime.now()
            expired_custom_ids = [
                cid
                for cid, ts in list(config.USED_RETRY_BUTTONS.items())
                if (now - ts).total_seconds() >= config.RETRY_BUTTON_TTL_MINUTES * 60
            ]
            for cid in expired_custom_ids:
                del config.USED_RETRY_BUTTONS[cid]
        except Exception:
            pass

        # Check if this is a retry button
        if custom_id.startswith("retry_"):
            await _handle_retry_button(interaction, custom_id)

    @client.event
    async def on_message(message: discord.Message) -> None:
        """Handle messages that mention the bot."""
        # Ignore messages from bots (including self)
        if message.author.bot:
            return

        # Check if the bot is mentioned
        if client.user is None or client.user not in message.mentions:
            return

        # Optionally check if the mention is explicit
        if config.REQUIRE_EXPLICIT_MENTION:
            bot_mention_patterns = [f"<@{client.user.id}>", f"<@!{client.user.id}>"]
            has_explicit_mention = any(
                pattern in message.content for pattern in bot_mention_patterns
            )
            if message.reference is not None and not has_explicit_mention:
                return

        # Check if ask command is enabled
        if not config.ASK_ENABLE:
            return

        # Check if user is banned
        if is_banned(message.author.id):
            return

        # Check if LLM provider is configured
        llm_client = get_llm_client()
        if not llm_client:
            return

        # Rate limiting check (owner bypass)
        user_id = message.author.id

        if not config.is_owner(user_id):
            current_time = datetime.datetime.now()
            if user_id in config.ASK_COMMAND_COOLDOWNS:
                last_used = config.ASK_COMMAND_COOLDOWNS[user_id]
                time_diff = current_time - last_used
                seconds_passed = time_diff.total_seconds()

                if seconds_passed < config.ASK_COMMAND_COOLDOWN_SECONDS:
                    remaining_seconds = int(
                        config.ASK_COMMAND_COOLDOWN_SECONDS - seconds_passed
                    )
                    logger.info(
                        "mention_rate_limited",
                        extra={
                            "user_id": message.author.id,
                            "remaining_seconds": remaining_seconds,
                            "remaining": format_duration_seconds(remaining_seconds),
                        },
                    )
                    return

        # Extract the question by removing the bot mention
        question = message.content
        bot_mention_patterns = [f"<@{client.user.id}>", f"<@!{client.user.id}>"]
        for pattern in bot_mention_patterns:
            question = question.replace(pattern, "").strip()

        if not question:
            return

        logger.info(
            "mention_received",
            extra={
                "user_id": message.author.id,
                "channel_id": getattr(message.channel, "id", None),
            },
        )

        # Show typing indicator while processing
        async with message.channel.typing():
            # Prepare optional image media part
            media_parts: Optional[list] = None
            try:
                for attachment in message.attachments:
                    if attachment.content_type and attachment.content_type.startswith("image/"):
                        pil_img = await read_validated_attachment(
                            attachment,
                            source_name="mention_attachment",
                        )
                        media_parts = [pil_img]
                        break
            except ImageValidationError as e:
                await message.reply(f"❌ Invalid image attachment: {e}")
                return
            except Exception as e:
                logger.exception(
                    "mention_image_attachment_error",
                    extra={
                        "user_id": message.author.id,
                        "error_type": type(e).__name__,
                    },
                )
                await message.reply(
                    "❌ Invalid image attachment: the image could not be processed."
                )
                return

            built_context = await build_ask_context(
                client=client,
                user=message.author,
                channel=message.channel,
                guild=message.guild,
                question=question,
                source_message=message,
            )

            # Add to queue
            request_id = await add_message_request_to_queue(
                RequestType.ASK,
                message,
                built_context.processed_question,
                built_context.context_string,
                message.author.id,
                priority=1 if config.is_owner(message.author.id) else 0,
                media_parts=media_parts,
            )

            logger.info(
                "mention_request_queued",
                extra={
                    "request_id": request_id,
                    "user_id": message.author.id,
                },
            )

    @client.event
    async def on_ready() -> None:
        """Handle bot ready event."""
        logger.info(
            "bot_ready",
            extra={
                "bot_user": str(client.user),
                "bot_user_id": getattr(client.user, "id", None),
            },
        )
        logger.info("command_sync_started")
        removed_retry_records = cleanup_expired_retry_records(
            config.RETRY_BUTTON_EXPIRE_MINUTES * 60
        )
        if removed_retry_records:
            logger.info(
                "expired_retry_records_removed",
                extra={"removed": removed_retry_records},
            )

        # Remove disabled commands
        if not config.IMAGINE_ENABLE:
            tree.remove_command("imagine")
            logger.info(
                "imagine_command_registration_disabled",
                extra={"imagine_enable": config.IMAGINE_ENABLE},
            )

        try:
            if config.GUILD_ID_ENV:
                logger.info(
                    "guild_command_sync_configured",
                    extra={"guild_id": config.GUILD_ID_ENV},
                )
                test_guild = discord.Object(id=int(config.GUILD_ID_ENV))

                await tree.sync(guild=test_guild)
                logger.info(
                    "guild_command_sync_completed",
                    extra={"guild_id": config.GUILD_ID_ENV},
                )
            else:
                logger.info("global_command_sync_started")
                await tree.sync()
                logger.info("global_command_sync_completed")
        except Exception as sync_error:
            logger.exception(
                "command_sync_failed",
                extra={"error_type": type(sync_error).__name__},
            )


async def _handle_retry_button(
    interaction: discord.Interaction, custom_id: str
) -> None:
    """Handle retry button clicks."""
    try:
        # One-time guard
        if custom_id in config.USED_RETRY_BUTTONS:
            await interaction.response.send_message(
                "⛔ This retry button was already used.", ephemeral=True
            )
            return

        # Parse the custom_id
        parts = custom_id.split("_")
        if len(parts) < 3:
            await interaction.response.send_message(
                "❌ An error occurred while processing the retry button.",
                ephemeral=True,
            )
            return

        button_user_id = int(parts[1])
        question_hash = parts[2]
        created_ts = None
        if len(parts) >= 5:
            try:
                created_ts = int(parts[4])
            except ValueError:
                created_ts = None

        # Check if the button was pressed by the original user
        if interaction.user.id != button_user_id:
            await interaction.response.send_message(
                "❌ Only the person who asked the original question can use the retry button.",
                ephemeral=True,
            )
            return

        # Check expiry before consuming a one-time retry record.
        if created_ts is not None:
            age_seconds = int(datetime.datetime.now().timestamp()) - created_ts
            if age_seconds >= config.RETRY_BUTTON_EXPIRE_MINUTES * 60:
                await _disable_retry_button_message(interaction, custom_id)
                cleanup_retry_record(custom_id)
                await interaction.response.send_message(
                    "⏰ This retry button has expired.",
                    ephemeral=True,
                )
                return

        retry_record = load_retry_record(custom_id)
        if retry_record:
            question = str(retry_record.get("question", ""))
            loaded_context = str(retry_record.get("context_string", ""))
            tts = bool(retry_record.get("tts", False))
            retry_media_parts = retry_record.get("media_parts")
        else:
            question = ""
            loaded_context = ""
            tts = False
            retry_media_parts = None

            # Compatibility fallback for retry buttons created before retry
            # records were introduced and still living in the current process.
            if button_user_id in config.RECENT_QUESTIONS:
                for question_data in config.RECENT_QUESTIONS[button_user_id]:
                    if len(question_data) >= 3:
                        candidate_question, candidate_tts, _image = question_data
                    elif len(question_data) == 2:
                        candidate_question, candidate_tts = question_data
                    else:
                        candidate_question = question_data[0] if question_data else ""
                        candidate_tts = False

                    if _question_matches_retry_hash(candidate_question, question_hash):
                        question = candidate_question
                        loaded_context = load_retry_context(custom_id) or ""
                        tts = bool(candidate_tts)
                        retry_media_parts = load_retry_media(custom_id)
                        break

        if not question:
            await interaction.response.send_message(
                "❌ The original question is no longer available for retry.",
                ephemeral=True,
            )
            return

        # Mark as used and disable button.
        config.USED_RETRY_BUTTONS[custom_id] = datetime.datetime.now()
        await _disable_retry_button_message(interaction, custom_id)
        await interaction.response.defer(ephemeral=True, thinking=True)

        request_id = await add_request_to_queue(
            RequestType.RETRY,
            interaction,
            question,
            loaded_context if loaded_context else "",
            button_user_id,
            priority=2,
            media_parts=retry_media_parts,
            tts=tts,
        )

        logger.info(
            "retry_request_queued",
            extra={
                "request_id": request_id,
                "user_id": button_user_id,
            },
        )

    except (ValueError, IndexError) as e:
        logger.warning(
            "retry_button_parse_error",
            extra={"custom_id": custom_id, "error_type": type(e).__name__},
        )
        await interaction.response.send_message(
            "❌ An error occurred while processing the retry button.",
            ephemeral=True,
        )
    except Exception as e:
        logger.exception(
            "retry_button_unexpected_error",
            extra={"custom_id": custom_id, "error_type": type(e).__name__},
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "❌ An unexpected error occurred.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "❌ An unexpected error occurred.", ephemeral=True
                )
        except Exception:
            pass
