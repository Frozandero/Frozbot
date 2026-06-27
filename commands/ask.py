"""Ask command for Frozbot."""

import datetime
import io
from typing import Optional

import discord
from discord import app_commands
from PIL import Image

import config
from context import (
    process_mentions_in_question,
    fetch_channel_memories,
    build_user_context,
    format_mentioned_users_context,
    format_user_context,
    get_recent_channel_messages,
    get_channel_messages_for_summary,
    get_user_recent_messages,
    format_channel_messages,
    format_bot_previous_responses,
    build_full_context_string,
)
from emoji import list_guild_emoji_names
from database import is_banned
from llm import get_llm_client, summarize_messages_with_llm
from eleven import get_eleven_client
from request_queue import RequestType, add_request_to_queue
from utils import store_user_question, cleanup_expired_cooldowns


def setup_ask_commands(tree: app_commands.CommandTree, client: discord.Client):
    """Setup ask-related commands."""

    @tree.command(name="ask", description="Ask the bot a question.", guild=None)
    async def ask_command(
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

        # Process mentions in question
        processed_question, mentioned_users_context = (
            await process_mentions_in_question(
                question, interaction.guild, interaction.channel, interaction.client
            )
        )

        # Fetch channel memories
        sender_username = interaction.user.name if interaction.user else "Unknown"
        mentioned_usernames = []
        for user_data in mentioned_users_context:
            if isinstance(user_data, dict) and "username" in user_data:
                mentioned_usernames.append(user_data["username"])

        channel_id = interaction.channel.id if interaction.channel else 0
        generic_memories, user_memories = fetch_channel_memories(
            channel_id, sender_username, mentioned_usernames, memory_limit=5
        )

        # Build server context
        if interaction.guild:
            server_context_parts = [f"Name: {interaction.guild.name}"]
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
        user_context = build_user_context(interaction.user)
        user_recent_messages = await get_user_recent_messages(
            interaction.channel, interaction.user.id
        )
        user_context["recent_messages"] = user_recent_messages

        # Channel context
        channel_context = getattr(interaction.channel, "name", None)

        # Channel raw context
        bot_id = client.user.id if client.user else None
        recent_channel_messages, bot_recent_messages = (
            await get_recent_channel_messages(
                interaction.channel,
                config.CHANNEL_CONTEXT_LAST,
                self_bot_id=bot_id,
                max_self_messages=2,
            )
        )

        channel_raw_context_str = format_channel_messages(
            recent_channel_messages, config.CHANNEL_CONTEXT_LAST
        )
        bot_previous_responses_str = format_bot_previous_responses(bot_recent_messages)

        # Channel summary
        channel_summary_str = None
        if config.CHANNEL_SUMMARY_ENABLE and interaction.channel:
            summary_channel_id = getattr(interaction.channel, "id", None)
            needs_summary = True

            if (
                isinstance(summary_channel_id, int)
                and summary_channel_id in config.CHANNEL_SUMMARY_CACHE
            ):
                cache_entry = config.CHANNEL_SUMMARY_CACHE[summary_channel_id]
                cached_at_val = cache_entry.get("cached_at")
                cached_at: Optional[datetime.datetime] = (
                    cached_at_val
                    if isinstance(cached_at_val, datetime.datetime)
                    else None
                )
                cache_newest: Optional[int] = cache_entry.get("newest_id")

                try:
                    _, newest_id = await get_channel_messages_for_summary(
                        interaction.channel, 1
                    )
                except Exception:
                    newest_id = None

                if (
                    cache_newest is not None
                    and newest_id is not None
                    and newest_id == cache_newest
                ):
                    channel_summary_str = cache_entry.get("summary")
                    needs_summary = False
                elif (
                    newest_id is None
                    and cached_at
                    and (datetime.datetime.now() - cached_at).total_seconds()
                    < config.CHANNEL_SUMMARY_TTL_MIN * 60
                ):
                    channel_summary_str = cache_entry.get("summary")
                    needs_summary = False

            if needs_summary:
                messages_for_summary, newest_id = (
                    await get_channel_messages_for_summary(
                        interaction.channel, config.CHANNEL_SUMMARY_DEPTH
                    )
                )
                if messages_for_summary:
                    serialized = []
                    for m in reversed(
                        messages_for_summary[-config.CHANNEL_SUMMARY_DEPTH :]
                    ):
                        line = f"[{m['timestamp']}] {m['author']}: {m['content']}"
                        if m["attachments"] > 0:
                            line += f" (+{m['attachments']} attachments)"
                        if m["embeds"] > 0:
                            line += f" (+{m['embeds']} embeds)"
                        serialized.append(line)
                    summary, summary_token_usage = await summarize_messages_with_llm(
                        "\n".join(serialized)
                    )
                    channel_summary_str = summary or None
                    # Always log token usage after summary request
                    print(
                        f"[SUMMARY] Token usage for channel summary: "
                        f"{summary_token_usage.input_tokens} input, {summary_token_usage.output_tokens} output "
                        f"(total: {summary_token_usage.total_tokens})"
                    )

                    if isinstance(summary_channel_id, int):
                        config.CHANNEL_SUMMARY_CACHE[summary_channel_id] = {
                            "summary": channel_summary_str,
                            "cached_at": datetime.datetime.now(),
                            "newest_id": newest_id,
                        }

        # Guild emojis
        guild = interaction.guild
        emoji_names: list[str] = []
        if guild and hasattr(guild, "id") and hasattr(guild, "emojis"):
            emoji_names = await list_guild_emoji_names(guild)

        # Format contexts
        mentioned_users_str = format_mentioned_users_context(
            mentioned_users_context, user_memories
        )
        user_context_str = format_user_context(user_context, user_memories)

        # Get bot name
        bot_name = (
            interaction.guild.me.nick
            if interaction.guild and interaction.guild.me.nick
            else "Frozbot"
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
        )

        # Add request to queue
        request_id = await add_request_to_queue(
            RequestType.ASK,
            interaction,
            processed_question,
            context_string,
            user_id,
            priority=1 if config.is_owner(user_id) else 0,
            media_parts=media_parts,
            tts=tts if tts else False,
        )

        print(f"[QUEUE] Request {request_id} added to queue")
