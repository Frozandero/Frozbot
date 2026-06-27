"""Event handlers for Frozbot."""

import datetime
import hashlib
import io
import re
from typing import Optional

import discord
from PIL import Image

import config
from context import (
    process_mentions_in_question,
    fetch_channel_memories,
    build_user_context,
    format_mentioned_users_context,
    format_user_context,
    get_recent_channel_messages,
    get_user_recent_messages,
    format_channel_messages,
    format_bot_previous_responses,
    build_full_context_string,
    fetch_replied_message_context,
    format_replied_message_context,
)
from database import is_banned
from emoji import list_guild_emoji_names
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

            # Build context
            context_string = await _build_message_context(
                client, message, question, media_parts
            )

            # Add to queue
            request_id = await add_message_request_to_queue(
                RequestType.ASK,
                message,
                question,
                context_string,
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


async def _build_message_context(
    client: discord.Client,
    message: discord.Message,
    question: str,
    media_parts: Optional[list],
) -> str:
    """Build context string for a message-based request."""
    # Fetch replied-to message context if this is a reply
    replied_context = None
    replied_author_id = None
    if message.reference:
        replied_context = await fetch_replied_message_context(message)
        if replied_context:
            replied_author_id = replied_context.get("author_id")

    # Process mentions
    mentioned_users_context = []
    mention_pattern = r"<@!?(\d+)>"
    matches = re.findall(mention_pattern, question)
    processed_question = question
    mentioned_user_ids = set()

    for user_id_str in matches:
        try:
            mentioned_user_id = int(user_id_str)
            if mentioned_user_id == client.user.id:
                continue

            mentioned_user_ids.add(mentioned_user_id)

            if message.guild:
                member = message.guild.get_member(mentioned_user_id)
                if member:
                    recent_messages = await get_user_recent_messages(
                        message.channel, mentioned_user_id
                    )
                    mentioned_users_context.append(
                        {
                            "name": member.display_name,
                            "username": member.name,
                            "joined_at": (
                                member.joined_at.strftime("%Y-%m-%d")
                                if member.joined_at
                                else "Unknown"
                            ),
                            "roles": (
                                [role.name for role in member.roles[1:]]
                                if len(member.roles) > 1
                                else []
                            ),
                            "top_role": (
                                member.top_role.name if member.top_role else "No roles"
                            ),
                            "nickname": member.nick if member.nick else None,
                            "recent_messages": recent_messages,
                        }
                    )
                    processed_question = processed_question.replace(
                        f"<@{mentioned_user_id}>", f"@{member.display_name}"
                    )
                    processed_question = processed_question.replace(
                        f"<@!{mentioned_user_id}>", f"@{member.display_name}"
                    )
        except ValueError:
            pass

    # Add replied-to message author to mentioned users if not already included
    if (
        replied_context
        and replied_author_id
        and replied_author_id not in mentioned_user_ids
    ):
        author_context = replied_context.get("author_context", {})
        if author_context:
            mentioned_users_context.append(author_context)
            mentioned_user_ids.add(replied_author_id)

    # Fetch memories
    sender_username = message.author.name
    mentioned_usernames = [
        u["username"] for u in mentioned_users_context if isinstance(u, dict)
    ]
    # Also include replied-to message author in memories fetch
    if replied_context and replied_author_id:
        author_context = replied_context.get("author_context", {})
        if author_context and "username" in author_context:
            author_username = author_context["username"]
            if author_username not in mentioned_usernames:
                mentioned_usernames.append(author_username)

    channel_id = message.channel.id
    generic_memories, user_memories = fetch_channel_memories(
        channel_id, sender_username, mentioned_usernames, memory_limit=5
    )

    # Build server context
    if message.guild:
        server_context_parts = [f"Name: {message.guild.name}"]
        if generic_memories:
            server_context_parts.append("Server Memories:")
            for i, (memory_id, username, memory) in enumerate(generic_memories, 1):
                server_context_parts.append(f"  {i}. {memory}")
        else:
            server_context_parts.append("Server Memories: None")
        server_context = "\n".join(server_context_parts)
    else:
        server_context = None

    # Date context
    date_context = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # User context
    user_context = build_user_context(message.author)
    user_recent_messages = await get_user_recent_messages(
        message.channel, message.author.id
    )
    user_context["recent_messages"] = user_recent_messages

    # Channel context
    channel_context = message.channel.name if hasattr(message.channel, "name") else None

    # Channel raw context
    bot_id = client.user.id if client.user else None
    recent_channel_messages, bot_recent_messages = await get_recent_channel_messages(
        message.channel,
        config.CHANNEL_CONTEXT_LAST,
        self_bot_id=bot_id,
        max_self_messages=2,
    )

    channel_raw_context_str = format_channel_messages(
        recent_channel_messages, config.CHANNEL_CONTEXT_LAST
    )
    bot_previous_responses_str = format_bot_previous_responses(bot_recent_messages)

    # Channel summary (use cached if available)
    channel_summary_str = None
    if config.CHANNEL_SUMMARY_ENABLE:
        channel_cache_id = message.channel.id
        if channel_cache_id in config.CHANNEL_SUMMARY_CACHE:
            cache_entry = config.CHANNEL_SUMMARY_CACHE[channel_cache_id]
            cached_at_val = cache_entry.get("cached_at")
            cached_at: Optional[datetime.datetime] = (
                cached_at_val if isinstance(cached_at_val, datetime.datetime) else None
            )
            if (
                cached_at
                and (datetime.datetime.now() - cached_at).total_seconds()
                < config.CHANNEL_SUMMARY_TTL_MIN * 60
            ):
                channel_summary_str = cache_entry.get("summary")

    # Guild emojis
    guild = message.guild
    emoji_names: list[str] = []
    if guild and hasattr(guild, "id") and hasattr(guild, "emojis"):
        emoji_names = await list_guild_emoji_names(guild)

    # Format contexts
    mentioned_users_str = format_mentioned_users_context(
        mentioned_users_context, user_memories
    )
    user_context_str = format_user_context(user_context, user_memories)

    # Format replied-to message context
    replied_message_str = None
    if replied_context:
        replied_message_str = format_replied_message_context(
            replied_context, user_memories
        )

    # Get bot name
    bot_name = (
        message.guild.me.nick if message.guild and message.guild.me.nick else "Frozbot"
    )

    # Build full context
    context_string = await build_full_context_string(
        bot_name=bot_name,
        server_context=server_context,
        mentioned_users_str=mentioned_users_str,
        date_context=date_context,
        message_context=processed_question,
        user_context_str=user_context_str,
        channel_context=channel_context,
        emoji_names=emoji_names,
        channel_raw_context_str=channel_raw_context_str,
        bot_previous_responses_str=bot_previous_responses_str,
        channel_summary_str=channel_summary_str,
        replied_message_str=replied_message_str,
    )

    return context_string
