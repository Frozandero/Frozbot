"""Event handlers for Frozbot."""

import datetime
import hashlib
import io
from typing import Optional

import discord
from PIL import Image

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
from utils import filter_profanity


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
                minutes_passed = time_diff.total_seconds() / 60

                if minutes_passed < config.ASK_COMMAND_COOLDOWN_MINUTES:
                    remaining_seconds = int(
                        (config.ASK_COMMAND_COOLDOWN_MINUTES * 60)
                        - time_diff.total_seconds()
                    )
                    remaining_minutes = remaining_seconds // 60
                    remaining_secs = remaining_seconds % 60
                    print(
                        f"[RATELIMIT] Rate limited mention from {message.author.name} ({remaining_minutes}m {remaining_secs}s remaining)"
                    )
                    return

        # Extract the question by removing the bot mention
        question = message.content
        bot_mention_patterns = [f"<@{client.user.id}>", f"<@!{client.user.id}>"]
        for pattern in bot_mention_patterns:
            question = question.replace(pattern, "").strip()

        if not question:
            return

        print(
            f"[MENTION] Received mention from {message.author.name}: {question[:50]}..."
        )

        # Show typing indicator while processing
        async with message.channel.typing():
            # Prepare optional image media part
            media_parts: Optional[list] = None
            try:
                for attachment in message.attachments:
                    if attachment.content_type and attachment.content_type.startswith(
                        "image/"
                    ):
                        image_bytes = await attachment.read()
                        pil_img = Image.open(io.BytesIO(image_bytes))
                        media_parts = [pil_img]
                        break
            except Exception as e:
                print(f"Failed to process image attachment: {e}")

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

            print(f"[QUEUE] Message request {request_id} added to queue")

    @client.event
    async def on_ready() -> None:
        """Handle bot ready event."""
        print(f"Logged in as {client.user} (ID: {client.user.id})")
        print("Bot is ready! Starting command sync...")
        removed_retry_records = cleanup_expired_retry_records(
            config.RETRY_BUTTON_EXPIRE_MINUTES * 60
        )
        if removed_retry_records:
            print(f"[CLEANUP] Removed {removed_retry_records} expired retry records")

        # Remove disabled commands
        if not config.IMAGINE_ENABLE:
            tree.remove_command("imagine")
            print(
                "[DISABLED] Image generation is disabled - /imagine command will not be registered"
            )

        try:
            if config.GUILD_ID_ENV:
                print(f"GUILD_ID_ENV is set to: {config.GUILD_ID_ENV}")
                test_guild = discord.Object(id=int(config.GUILD_ID_ENV))

                print("Syncing guild commands only...")
                await tree.sync(guild=test_guild)
                print(f"Slash commands synced to guild {config.GUILD_ID_ENV}.")
            else:
                print("No GUILD_ID_ENV set, syncing globally only...")
                await tree.sync()
                print(
                    "Slash commands synced globally (may take up to 1 hour to appear)."
                )
        except Exception as sync_error:
            print(f"Failed to sync commands: {sync_error}")
            print(f"Error type: {type(sync_error)}")
            import traceback

            traceback.print_exc()
            print(
                "Make sure your bot has the 'applications.commands' scope and proper permissions."
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

        queue_size = config.REQUEST_QUEUE.qsize()
        filtered_question = filter_profanity(question)
        await interaction.response.send_message(
            f"🔄 **Retry queued**\n\n"
            f"**Question:** {filtered_question}\n\n"
            f"Your retry request has been added to the queue. "
            f"There are currently {queue_size} request(s) waiting.",
            ephemeral=True,
        )
        print(f"[QUEUE] Retry request {request_id} added to queue")

    except (ValueError, IndexError) as e:
        print(f"Error parsing retry button custom_id: {e}")
        await interaction.response.send_message(
            "❌ An error occurred while processing the retry button.",
            ephemeral=True,
        )
    except Exception as e:
        print(f"Unexpected error in retry button handler: {e}")
        try:
            await interaction.response.send_message(
                "❌ An unexpected error occurred.", ephemeral=True
            )
        except:
            pass

