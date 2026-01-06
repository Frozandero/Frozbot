"""Request queue system for Frozbot."""

import asyncio
import datetime
import io
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import discord
from PIL import Image

import config
from utils import filter_profanity
from emoji import replace_guild_emojis_in_text
from retry import (
    save_retry_media,
    save_retry_context,
    cleanup_retry_media,
    load_retry_media,
    load_retry_context,
)
from llm import try_gemini_models
from eleven import generate_tts


class RequestType(Enum):
    """Types of requests that can be queued."""

    ASK = "ask"
    RETRY = "retry"


@dataclass
class QueuedRequest:
    """A request in the processing queue."""

    request_id: str
    request_type: RequestType
    interaction: Optional[discord.Interaction]
    question: str
    context_string: str
    user_id: int
    timestamp: datetime.datetime
    priority: int = 0  # Higher number = higher priority
    media_parts: Optional[list] = None
    tts: bool = False
    message: Optional[discord.Message] = None  # For message-based requests (mentions)


async def process_request_queue() -> None:
    """Process requests from the queue sequentially with delays."""
    if config.QUEUE_PROCESSOR_RUNNING:
        return

    config.QUEUE_PROCESSOR_RUNNING = True
    print("[START] Starting request queue processor...")

    try:
        while True:
            try:
                # Get next request from queue
                request: QueuedRequest = await config.REQUEST_QUEUE.get()
                print(
                    f"[PROCESS] Processing request {request.request_id} ({request.request_type.value}) from user {request.user_id}"
                )

                # Process the request
                if request.request_type == RequestType.ASK:
                    await process_ask_request(request)
                elif request.request_type == RequestType.RETRY:
                    await process_retry_request(request)

                # Mark as done
                config.REQUEST_QUEUE.task_done()

                # Add delay between requests to avoid rate limiting
                if not config.REQUEST_QUEUE.empty():
                    print(
                        f"[WAIT] Waiting {config.REQUEST_DELAY_SECONDS} seconds before next request..."
                    )
                    await asyncio.sleep(config.REQUEST_DELAY_SECONDS)

            except asyncio.CancelledError:
                print("[STOP] Request queue processor cancelled")
                break
            except Exception as e:
                print(f"[ERROR] Error processing request: {e}")
                continue

    finally:
        config.QUEUE_PROCESSOR_RUNNING = False
        print("[STOP] Request queue processor stopped")


async def add_request_to_queue(
    request_type: RequestType,
    interaction: discord.Interaction,
    question: str,
    context_string: str,
    user_id: int,
    priority: int = 0,
    media_parts: Optional[list] = None,
    tts: bool = False,
) -> str:
    """Add a request to the queue and start the processor if needed."""
    request_id = (
        f"{request_type.value}_{user_id}_{int(datetime.datetime.now().timestamp())}"
    )

    request = QueuedRequest(
        request_id=request_id,
        request_type=request_type,
        interaction=interaction,
        question=question,
        context_string=context_string,
        user_id=user_id,
        timestamp=datetime.datetime.now(),
        priority=priority,
        media_parts=media_parts,
        tts=tts,
    )

    await config.REQUEST_QUEUE.put(request)
    print(
        f"[QUEUE] Added request {request_id} to queue (position: {config.REQUEST_QUEUE.qsize()})"
    )

    # Start the queue processor if it's not running
    if not config.QUEUE_PROCESSOR_RUNNING:
        asyncio.create_task(process_request_queue())

    return request_id


async def add_message_request_to_queue(
    request_type: RequestType,
    message: discord.Message,
    question: str,
    context_string: str,
    user_id: int,
    priority: int = 0,
    media_parts: Optional[list] = None,
) -> str:
    """Add a message-based request to the queue (for mention-based replies)."""
    request_id = (
        f"{request_type.value}_msg_{user_id}_{int(datetime.datetime.now().timestamp())}"
    )

    request = QueuedRequest(
        request_id=request_id,
        request_type=request_type,
        interaction=None,
        question=question,
        context_string=context_string,
        user_id=user_id,
        timestamp=datetime.datetime.now(),
        priority=priority,
        media_parts=media_parts,
        tts=False,
        message=message,
    )

    await config.REQUEST_QUEUE.put(request)
    print(
        f"[QUEUE] Added message request {request_id} to queue (position: {config.REQUEST_QUEUE.qsize()})"
    )

    # Start the queue processor if it's not running
    if not config.QUEUE_PROCESSOR_RUNNING:
        asyncio.create_task(process_request_queue())

    return request_id


async def _create_retry_button_and_schedule_expiry(
    interaction: discord.Interaction,
    request: QueuedRequest,
    error_msg: str,
) -> None:
    """Create a retry button and schedule its expiry."""
    # Create retry button with one-time token and timestamp
    retry_token = uuid.uuid4().hex[:8]
    retry_timestamp = int(datetime.datetime.now().timestamp())
    custom_id = f"retry_{request.user_id}_{hash(request.question) % 1000000}_{retry_token}_{retry_timestamp}"

    # Persist media and original context for retry if present
    try:
        save_retry_media(custom_id, request.media_parts)
    except Exception:
        pass
    try:
        save_retry_context(custom_id, request.context_string)
    except Exception:
        pass

    retry_button = discord.ui.Button(
        style=discord.ButtonStyle.primary,
        label="🔄 Retry",
        custom_id=custom_id,
    )

    view = discord.ui.View()
    view.add_item(retry_button)

    message = await interaction.followup.send(content=error_msg, view=view)

    # Auto-disable the button after expiration if unused
    async def schedule_disable_retry_button(
        msg: Optional[discord.Message], cid: str, delay_seconds: int
    ) -> None:
        try:
            if msg is None:
                return
            await asyncio.sleep(delay_seconds)
            if cid in config.USED_RETRY_BUTTONS:
                return
            disable_view = discord.ui.View()
            disable_view.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.primary,
                    label="🔄 Retry",
                    custom_id=cid,
                    disabled=True,
                )
            )
            await msg.edit(view=disable_view)
            # Cleanup any persisted media/context now that the button expired
            cleanup_retry_media(cid)
            try:
                config.RETRY_CONTEXT_TEMP.pop(cid, None)
            except Exception:
                pass
        except Exception:
            pass

    asyncio.create_task(
        schedule_disable_retry_button(
            message, custom_id, config.RETRY_BUTTON_EXPIRE_MINUTES * 60
        )
    )


async def process_ask_request(request: QueuedRequest) -> None:
    """Process an ask request from the queue."""
    is_message_request = request.message is not None

    try:
        print(f"[ASK] Processing ask request: {request.question[:50]}...")
        print(f"[CONTEXT] Context length: {len(request.context_string)} chars")
        print(
            f"[CONTEXT] Context preview (first 500 chars): {request.context_string[:500]}..."
        )

        # Try to get response from Gemini with model fallback
        response = await asyncio.wait_for(
            try_gemini_models(
                request.question, request.context_string, request.media_parts
            ),
            timeout=60.0,
        )

        if response:
            # Update cooldown only on successful response
            if not config.is_owner(request.user_id):
                config.ASK_COMMAND_COOLDOWNS[request.user_id] = datetime.datetime.now()

            # Format the response
            filtered_question = filter_profanity(request.question)

            # Replace :emoji_name: with actual guild emoji mentions
            async def _replace_emotes(text: str) -> str:
                guild = (
                    request.message.guild
                    if is_message_request
                    else (request.interaction.guild if request.interaction else None)
                )
                if guild and hasattr(guild, "id") and hasattr(guild, "emojis"):
                    return await replace_guild_emojis_in_text(text, guild)
                else:
                    print(
                        f"[WARN] Invalid guild object in ask request, skipping emoji replacement"
                    )
                    return text

            replaced_answer = await _replace_emotes(response)

            # For message-based requests, show just the answer (no "Question:" prefix)
            if is_message_request:
                formatted_response = replaced_answer
            else:
                formatted_response = f"**Question:** {filtered_question}\n\n**Answer:** {replaced_answer}"

            # Prepare optional image attachment for visibility (only for interaction-based requests)
            files_param = None
            if not is_message_request:
                try:
                    if request.media_parts:
                        for part in request.media_parts:
                            if isinstance(part, Image.Image):
                                img_buf = io.BytesIO()
                                part.convert("RGB").save(img_buf, format="PNG")
                                img_buf.seek(0)
                                files_param = [
                                    discord.File(img_buf, filename="question.png")
                                ]
                                break
                except Exception:
                    files_param = None

            # Generate TTS if requested (only for interaction-based requests)
            if request.tts and not is_message_request:
                try:
                    print(f"[TTS] Generating TTS for response...")
                    tts_audio = generate_tts(replaced_answer)
                    if not tts_audio:
                        print(f"[ERROR] Failed to generate TTS")
                        return
                    tts_buf = io.BytesIO(tts_audio)
                    tts_file = discord.File(tts_buf, filename="response.ogg")

                    if files_param:
                        files_param.append(tts_file)
                    else:
                        files_param = [tts_file]

                    print(f"[OK] TTS audio generated successfully")
                except Exception as e:
                    print(f"[ERROR] Failed to generate TTS: {e}")

            formatted_response = (
                formatted_response
                if len(formatted_response) <= 2000
                else formatted_response[:1997] + "..."
            )

            # Send response via appropriate method
            if is_message_request:
                await request.message.reply(content=formatted_response)
            elif files_param:
                await request.interaction.followup.send(
                    content=formatted_response, files=files_param
                )
            else:
                await request.interaction.followup.send(content=formatted_response)

            print(f"[OK] Successfully processed ask request {request.request_id}")
        else:
            # All models failed
            filtered_question = filter_profanity(request.question)
            all_failed_msg = (
                "🚫 **All AI Models Failed**\n\n"
                "The bot was unable to process your request with any available AI model. "
                "This could be due to:\n"
                "• Quota limits (daily API limits reached)\n"
                "• Temporary server errors\n"
                "• Service maintenance\n"
                "• Network connectivity issues\n\n"
                "**Question:** " + filtered_question + "\n\n"
                "**Status:** Unable to process request\n\n"
                "Please try again later or contact the bot owner if the problem persists."
            )

            if is_message_request:
                await request.message.reply(content=all_failed_msg)
                print(f"[ERROR] All models failed for ask request {request.request_id}")
                return

            await _create_retry_button_and_schedule_expiry(
                request.interaction, request, all_failed_msg
            )
            print(f"[ERROR] All models failed for ask request {request.request_id}")

    except asyncio.TimeoutError:
        filtered_question = filter_profanity(request.question)
        timeout_msg = (
            f"⏰ **Request timed out**\n\n"
            f"**Question:** {filtered_question}\n\n"
            "The AI model took too long to respond. Please try again with a simpler question or try again later."
        )

        if is_message_request:
            await request.message.reply(content=timeout_msg)
            print(f"[TIMEOUT] Timeout for ask request {request.request_id}")
            return

        await _create_retry_button_and_schedule_expiry(
            request.interaction, request, timeout_msg
        )
        print(f"[TIMEOUT] Timeout for ask request {request.request_id}")

    except Exception as e:
        filtered_question = filter_profanity(request.question)
        error_msg = (
            f"❌ **An error occurred while processing your question**\n\n"
            f"**Question:** {filtered_question}\n\n"
            f"**Error:** {str(e)[:200]}...\n\n"
            "Please try again later or contact the bot owner if the problem persists."
        )

        if is_message_request:
            try:
                await request.message.reply(content=error_msg)
            except Exception:
                pass
            print(f"[ERROR] Error in ask request {request.request_id}: {e}")
            return

        await _create_retry_button_and_schedule_expiry(
            request.interaction, request, error_msg
        )
        print(f"[ERROR] Error in ask request {request.request_id}: {e}")


async def process_retry_request(request: QueuedRequest) -> None:
    """Process a retry request from the queue."""
    try:
        print(f"[RETRY] Processing retry request: {request.question[:50]}...")

        response = await asyncio.wait_for(
            try_gemini_models(
                request.question, request.context_string, request.media_parts
            ),
            timeout=60.0,
        )

        if response:
            filtered_question = filter_profanity(request.question)
            guild = request.interaction.guild
            if guild and hasattr(guild, "id") and hasattr(guild, "emojis"):
                replaced_answer = await replace_guild_emojis_in_text(response, guild)
            else:
                print(
                    f"[WARN] Invalid guild object in retry request, skipping emoji replacement"
                )
                replaced_answer = response
            formatted_response = (
                f"**Question:** {filtered_question}\n\n**Answer:** {replaced_answer}"
            )

            # Prepare optional image attachment
            files_param = None
            try:
                if request.media_parts:
                    for part in request.media_parts:
                        if isinstance(part, Image.Image):
                            img_buf = io.BytesIO()
                            part.convert("RGB").save(img_buf, format="PNG")
                            img_buf.seek(0)
                            files_param = [
                                discord.File(img_buf, filename="question.png")
                            ]
                            break
            except Exception:
                files_param = None

            # Generate TTS if requested
            if request.tts:
                try:
                    print(f"[TTS] Generating TTS for retry response...")
                    tts_audio = generate_tts(replaced_answer)
                    if not tts_audio:
                        print(f"[ERROR] Failed to generate TTS for retry")
                        return
                    tts_buf = io.BytesIO(tts_audio)
                    tts_file = discord.File(tts_buf, filename="response.ogg")

                    if files_param:
                        files_param.append(tts_file)
                    else:
                        files_param = [tts_file]

                    print(f"[OK] TTS audio generated successfully for retry")
                except Exception as e:
                    print(f"[ERROR] Failed to generate TTS for retry: {e}")

            formatted_response = (
                formatted_response
                if len(formatted_response) <= 2000
                else formatted_response[:1997] + "..."
            )

            if files_param:
                await request.interaction.followup.send(
                    content=formatted_response, files=files_param
                )
            else:
                await request.interaction.followup.send(content=formatted_response)

            print(f"[OK] Successfully processed retry request {request.request_id}")
        else:
            filtered_question = filter_profanity(request.question)
            await request.interaction.followup.send(
                "🚫 **Retry Failed**\n\n"
                "The retry attempt also failed. All AI models are currently unavailable.\n\n"
                "**Question:** " + filtered_question,
                ephemeral=True,
            )
            print(f"[ERROR] All models failed for retry request {request.request_id}")

    except asyncio.TimeoutError:
        filtered_question = filter_profanity(request.question)
        await request.interaction.followup.send(
            f"⏰ **Retry Timed Out**\n\n"
            f"The retry attempt timed out.\n\n"
            f"**Question:** {filtered_question}",
            ephemeral=True,
        )
        print(f"[TIMEOUT] Timeout for retry request {request.request_id}")

    except Exception as e:
        filtered_question = filter_profanity(request.question)
        await request.interaction.followup.send(
            f"❌ **Retry Error**\n\n"
            f"An error occurred during the retry attempt.\n\n"
            f"**Question:** {filtered_question}\n"
            f"**Error:** {str(e)[:200]}...",
            ephemeral=True,
        )
        print(f"[ERROR] Error in retry request {request.request_id}: {e}")
