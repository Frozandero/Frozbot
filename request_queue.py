"""Request queue system for Frozbot."""

import asyncio
from collections import deque
import datetime
import hashlib
import io
import logging
import math
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
    cleanup_retry_record,
    save_retry_record,
)
from llm import generate_response_with_llm
from eleven import generate_tts_async
from logging_utils import context_log_fields, text_log_fields, token_usage_log_fields

logger = logging.getLogger(__name__)

_DEFAULT_PROCESSING_SECONDS = 45.0
_ACTIVE_REQUESTS: dict[str, "QueuedRequest"] = {}
_PENDING_REQUESTS: dict[str, "QueuedRequest"] = {}
_CANCELLED_REQUESTS: set[str] = set()
_WORKER_TASKS: set[asyncio.Task] = set()
_PROCESSING_DURATIONS: deque[float] = deque(maxlen=25)
_WORKER_SEQUENCE = 0


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
    position_at_enqueue: int = 0
    estimated_wait_seconds_at_enqueue: int = 0


@dataclass
class QueueCancelResult:
    """Result of a queued-request cancellation attempt."""

    cancelled: bool
    reason: str
    state: str
    request_id: str


def _build_queue_item(request: QueuedRequest) -> tuple[int, int, QueuedRequest]:
    """Build an asyncio.PriorityQueue item for a request."""
    sequence = next(config.REQUEST_QUEUE_SEQUENCE)
    return (-request.priority, sequence, request)


def _unpack_queue_item(item) -> QueuedRequest:
    """Return the QueuedRequest from current or legacy queue item shapes."""
    if isinstance(item, tuple) and len(item) == 3:
        return item[2]
    return item


def _queued_requests_in_order() -> list[QueuedRequest]:
    """Return pending queue requests in priority order."""
    try:
        queue_items = sorted(list(config.REQUEST_QUEUE._queue))
    except Exception:
        queue_items = []

    requests: list[QueuedRequest] = []
    for item in queue_items:
        request = _unpack_queue_item(item)
        if request.request_id in _CANCELLED_REQUESTS:
            continue
        if request.request_id not in _PENDING_REQUESTS:
            continue
        requests.append(request)
    return requests


def _average_processing_seconds() -> float:
    if not _PROCESSING_DURATIONS:
        return _DEFAULT_PROCESSING_SECONDS
    return sum(_PROCESSING_DURATIONS) / len(_PROCESSING_DURATIONS)


def _estimate_wait_seconds_for_position(position: Optional[int]) -> int:
    if not position or position <= 0:
        return 0

    worker_count = max(1, config.MAX_CONCURRENT_REQUESTS)
    available_workers = max(0, worker_count - len(_ACTIVE_REQUESTS))
    if position <= available_workers:
        return 0

    requests_ahead = position - available_workers
    batches = math.ceil(requests_ahead / worker_count)
    seconds = batches * (_average_processing_seconds() + config.REQUEST_DELAY_SECONDS)
    return max(0, int(seconds))


def get_request_status(request_id: str) -> dict:
    """Return status for one queued request."""
    if request_id in _ACTIVE_REQUESTS:
        return {
            "request_id": request_id,
            "state": "active",
            "position": 0,
            "estimated_wait_seconds": 0,
        }

    if request_id in _CANCELLED_REQUESTS:
        return {
            "request_id": request_id,
            "state": "cancelled",
            "position": None,
            "estimated_wait_seconds": None,
        }

    queued_requests = _queued_requests_in_order()
    for index, request in enumerate(queued_requests, 1):
        if request.request_id == request_id:
            return {
                "request_id": request_id,
                "state": "queued",
                "position": index,
                "estimated_wait_seconds": _estimate_wait_seconds_for_position(index),
            }

    return {
        "request_id": request_id,
        "state": "unknown",
        "position": None,
        "estimated_wait_seconds": None,
    }


def format_wait_estimate(seconds: Optional[int]) -> str:
    """Format wait seconds for Discord messages."""
    if seconds is None:
        return "unknown"
    if seconds <= 0:
        return "starting soon"
    if seconds < 60:
        return f"about {seconds} seconds"
    minutes = max(1, round(seconds / 60))
    return f"about {minutes} minute{'s' if minutes != 1 else ''}"


def get_queue_snapshot(user_id: Optional[int] = None) -> dict:
    """Return a user-safe queue status snapshot."""
    queued_requests = _queued_requests_in_order()
    user_requests = []
    for index, request in enumerate(queued_requests, 1):
        if user_id is not None and request.user_id != user_id:
            continue
        user_requests.append(
            {
                "request_id": request.request_id,
                "type": request.request_type.value,
                "position": index,
                "estimated_wait_seconds": _estimate_wait_seconds_for_position(index),
                "priority": request.priority,
            }
        )

    return {
        "pending_count": len(queued_requests),
        "active_count": len(_ACTIVE_REQUESTS),
        "worker_count": len(_WORKER_TASKS),
        "max_concurrent_requests": config.MAX_CONCURRENT_REQUESTS,
        "processor_running": config.QUEUE_PROCESSOR_RUNNING,
        "average_processing_seconds": int(_average_processing_seconds()),
        "estimated_wait_seconds_for_new_request": _estimate_wait_seconds_for_position(
            len(queued_requests) + 1
        ),
        "user_requests": user_requests,
        "active_request_ids": list(_ACTIVE_REQUESTS),
    }


def cancel_queued_request(
    request_id: str, *, user_id: int, is_owner: bool = False
) -> QueueCancelResult:
    """Cancel a queued request before a worker starts it."""
    requested_id = request_id
    if request_id not in _PENDING_REQUESTS and request_id not in _ACTIVE_REQUESTS:
        matches = [
            pending_id
            for pending_id, pending_request in _PENDING_REQUESTS.items()
            if pending_id.startswith(request_id)
            and (is_owner or pending_request.user_id == user_id)
        ]
        if len(matches) == 1:
            request_id = matches[0]
        elif len(matches) > 1:
            return QueueCancelResult(False, "ambiguous request id", "queued", requested_id)

    if request_id in _ACTIVE_REQUESTS:
        return QueueCancelResult(False, "already active", "active", request_id)

    request = _PENDING_REQUESTS.get(request_id)
    if request is None:
        state = "cancelled" if request_id in _CANCELLED_REQUESTS else "unknown"
        return QueueCancelResult(False, "request not found", state, request_id)

    if not is_owner and request.user_id != user_id:
        return QueueCancelResult(False, "not your request", "queued", request_id)

    _PENDING_REQUESTS.pop(request_id, None)
    _CANCELLED_REQUESTS.add(request_id)
    logger.info(
        "queue_request_cancelled",
        extra={
            "request_id": request_id,
            "request_type": request.request_type.value,
            "user_id": request.user_id,
            "cancelled_by": user_id,
        },
    )
    return QueueCancelResult(True, "cancelled", "cancelled", request_id)


def clear_pending_requests() -> int:
    """Clear pending queue entries and return the number removed."""
    removed = len(_PENDING_REQUESTS)
    for request_id in list(_PENDING_REQUESTS):
        _CANCELLED_REQUESTS.add(request_id)
    _PENDING_REQUESTS.clear()

    while True:
        try:
            config.REQUEST_QUEUE.get_nowait()
            config.REQUEST_QUEUE.task_done()
        except asyncio.QueueEmpty:
            break
        except ValueError:
            break

    logger.info("queue_pending_cleared", extra={"removed": removed})
    return removed


def _worker_task_done(task: asyncio.Task) -> None:
    _WORKER_TASKS.discard(task)
    config.QUEUE_PROCESSOR_RUNNING = bool(_WORKER_TASKS)
    if task.cancelled():
        return
    error = task.exception()
    if error:
        logger.exception(
            "queue_worker_exited_with_error",
            exc_info=(type(error), error, error.__traceback__),
        )


def ensure_queue_workers() -> None:
    """Start queue workers up to MAX_CONCURRENT_REQUESTS."""
    global _WORKER_SEQUENCE
    for task in list(_WORKER_TASKS):
        if task.done():
            _WORKER_TASKS.discard(task)

    while len(_WORKER_TASKS) < config.MAX_CONCURRENT_REQUESTS:
        _WORKER_SEQUENCE += 1
        task = asyncio.create_task(_queue_worker(_WORKER_SEQUENCE))
        task.add_done_callback(_worker_task_done)
        _WORKER_TASKS.add(task)

    config.QUEUE_PROCESSOR_RUNNING = bool(_WORKER_TASKS)


async def _queue_worker(worker_id: int) -> None:
    """Process queued requests until cancelled."""
    logger.info("queue_worker_started", extra={"worker_id": worker_id})

    while True:
        queue_item = await config.REQUEST_QUEUE.get()
        request: Optional[QueuedRequest] = None
        started_at: Optional[datetime.datetime] = None
        try:
            request = _unpack_queue_item(queue_item)
            if (
                request.request_id in _CANCELLED_REQUESTS
                or request.request_id not in _PENDING_REQUESTS
            ):
                logger.info(
                    "queue_request_skipped",
                    extra={
                        "request_id": request.request_id,
                        "worker_id": worker_id,
                        "reason": "cancelled_or_removed",
                    },
                )
                continue

            _PENDING_REQUESTS.pop(request.request_id, None)
            _ACTIVE_REQUESTS[request.request_id] = request
            started_at = datetime.datetime.now()
            queue_wait_seconds = int((started_at - request.timestamp).total_seconds())
            logger.info(
                "queue_request_started",
                extra={
                    "request_id": request.request_id,
                    "worker_id": worker_id,
                    "request_type": request.request_type.value,
                    "priority": request.priority,
                    "user_id": request.user_id,
                    "queue_wait_seconds": queue_wait_seconds,
                    **text_log_fields("question", request.question),
                    **context_log_fields(request.context_string),
                },
            )

            if request.request_type == RequestType.ASK:
                await process_ask_request(request)
            elif request.request_type == RequestType.RETRY:
                await process_retry_request(request)
        except asyncio.CancelledError:
            logger.info("queue_worker_cancelled", extra={"worker_id": worker_id})
            raise
        except Exception as e:
            logger.exception(
                "queue_request_processing_error",
                extra={
                    "request_id": request.request_id if request else None,
                    "worker_id": worker_id,
                    "error_type": type(e).__name__,
                },
            )
        finally:
            if request:
                _ACTIVE_REQUESTS.pop(request.request_id, None)
                _CANCELLED_REQUESTS.discard(request.request_id)
                if started_at:
                    elapsed = (datetime.datetime.now() - started_at).total_seconds()
                    _PROCESSING_DURATIONS.append(elapsed)
                    logger.info(
                        "queue_request_finished",
                        extra={
                            "request_id": request.request_id,
                            "worker_id": worker_id,
                            "elapsed_seconds": round(elapsed, 2),
                        },
                    )
            config.REQUEST_QUEUE.task_done()

        if not config.REQUEST_QUEUE.empty():
            await asyncio.sleep(config.REQUEST_DELAY_SECONDS)


async def process_request_queue() -> None:
    """Start queue workers and wait for them. Kept for compatibility."""
    ensure_queue_workers()
    if _WORKER_TASKS:
        await asyncio.gather(*_WORKER_TASKS)


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
    request_id = str(uuid.uuid4())

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

    _PENDING_REQUESTS[request_id] = request
    await config.REQUEST_QUEUE.put(_build_queue_item(request))
    status = get_request_status(request_id)
    request.position_at_enqueue = status["position"] or 0
    request.estimated_wait_seconds_at_enqueue = status["estimated_wait_seconds"] or 0
    logger.info(
        "queue_request_added",
        extra={
            "request_id": request_id,
            "request_type": request_type.value,
            "queue_position": request.position_at_enqueue,
            "estimated_wait_seconds": request.estimated_wait_seconds_at_enqueue,
            "priority": priority,
            "user_id": user_id,
            "pending_count": len(_PENDING_REQUESTS),
        },
    )

    ensure_queue_workers()

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
    request_id = str(uuid.uuid4())

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

    _PENDING_REQUESTS[request_id] = request
    await config.REQUEST_QUEUE.put(_build_queue_item(request))
    status = get_request_status(request_id)
    request.position_at_enqueue = status["position"] or 0
    request.estimated_wait_seconds_at_enqueue = status["estimated_wait_seconds"] or 0
    logger.info(
        "queue_message_request_added",
        extra={
            "request_id": request_id,
            "request_type": request_type.value,
            "queue_position": request.position_at_enqueue,
            "estimated_wait_seconds": request.estimated_wait_seconds_at_enqueue,
            "priority": priority,
            "user_id": user_id,
            "pending_count": len(_PENDING_REQUESTS),
        },
    )

    ensure_queue_workers()

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
    question_hash = hashlib.sha256(request.question.encode("utf-8")).hexdigest()[:12]
    custom_id = f"retry_{request.user_id}_{question_hash}_{retry_token}_{retry_timestamp}"

    # Persist original retry data so retry buttons survive process restarts.
    try:
        save_retry_record(
            custom_id=custom_id,
            user_id=request.user_id,
            question=request.question,
            context_string=request.context_string,
            tts=request.tts,
            media_parts=request.media_parts,
        )
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
            cleanup_retry_record(cid)
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
        logger.info(
            "ask_request_processing",
            extra={
                "request_id": request.request_id,
                "user_id": request.user_id,
                "is_message_request": is_message_request,
                **text_log_fields("question", request.question),
                **context_log_fields(request.context_string),
            },
        )

        # Try to get response from the configured LLM provider with fallback.
        response, token_usage = await asyncio.wait_for(
            generate_response_with_llm(
                request.question,
                request.context_string,
                request.media_parts,
                request_id=request.request_id,
            ),
            timeout=60.0,
        )

        # Always log token usage after request completes
        logger.info(
            "ask_request_token_usage",
            extra={
                "request_id": request.request_id,
                "user_id": request.user_id,
                **token_usage_log_fields(token_usage),
            },
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
                    logger.warning(
                        "ask_request_invalid_guild_for_emoji_replacement",
                        extra={"request_id": request.request_id},
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
                    logger.info(
                        "ask_request_tts_started",
                        extra={"request_id": request.request_id},
                    )
                    tts_audio = await generate_tts_async(replaced_answer)
                    if not tts_audio:
                        logger.error(
                            "ask_request_tts_failed",
                            extra={"request_id": request.request_id},
                        )
                        return
                    tts_buf = io.BytesIO(tts_audio)
                    tts_file = discord.File(tts_buf, filename="response.ogg")

                    if files_param:
                        files_param.append(tts_file)
                    else:
                        files_param = [tts_file]

                    logger.info(
                        "ask_request_tts_completed",
                        extra={"request_id": request.request_id},
                    )
                except Exception as e:
                    logger.exception(
                        "ask_request_tts_error",
                        extra={
                            "request_id": request.request_id,
                            "error_type": type(e).__name__,
                        },
                    )

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

            logger.info(
                "ask_request_completed",
                extra={"request_id": request.request_id, "user_id": request.user_id},
            )
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
                logger.error(
                    "ask_request_all_models_failed",
                    extra={"request_id": request.request_id, "user_id": request.user_id},
                )
                return

            await _create_retry_button_and_schedule_expiry(
                request.interaction, request, all_failed_msg
            )
            logger.error(
                "ask_request_all_models_failed",
                extra={"request_id": request.request_id, "user_id": request.user_id},
            )

    except asyncio.TimeoutError:
        filtered_question = filter_profanity(request.question)
        timeout_msg = (
            f"⏰ **Request timed out**\n\n"
            f"**Question:** {filtered_question}\n\n"
            "The AI model took too long to respond. Please try again with a simpler question or try again later."
        )

        if is_message_request:
            await request.message.reply(content=timeout_msg)
            logger.warning(
                "ask_request_timeout",
                extra={"request_id": request.request_id, "user_id": request.user_id},
            )
            return

        await _create_retry_button_and_schedule_expiry(
            request.interaction, request, timeout_msg
        )
        logger.warning(
            "ask_request_timeout",
            extra={"request_id": request.request_id, "user_id": request.user_id},
        )

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
            logger.exception(
                "ask_request_error",
                extra={
                    "request_id": request.request_id,
                    "user_id": request.user_id,
                    "error_type": type(e).__name__,
                },
            )
            return

        await _create_retry_button_and_schedule_expiry(
            request.interaction, request, error_msg
        )
        logger.exception(
            "ask_request_error",
            extra={
                "request_id": request.request_id,
                "user_id": request.user_id,
                "error_type": type(e).__name__,
            },
        )


async def process_retry_request(request: QueuedRequest) -> None:
    """Process a retry request from the queue."""
    try:
        logger.info(
            "retry_request_processing",
            extra={
                "request_id": request.request_id,
                "user_id": request.user_id,
                **text_log_fields("question", request.question),
                **context_log_fields(request.context_string),
            },
        )

        response, token_usage = await asyncio.wait_for(
            generate_response_with_llm(
                request.question,
                request.context_string,
                request.media_parts,
                request_id=request.request_id,
            ),
            timeout=60.0,
        )

        # Always log token usage after request completes
        logger.info(
            "retry_request_token_usage",
            extra={
                "request_id": request.request_id,
                "user_id": request.user_id,
                **token_usage_log_fields(token_usage),
            },
        )

        if response:
            filtered_question = filter_profanity(request.question)
            guild = request.interaction.guild
            if guild and hasattr(guild, "id") and hasattr(guild, "emojis"):
                replaced_answer = await replace_guild_emojis_in_text(response, guild)
            else:
                logger.warning(
                    "retry_request_invalid_guild_for_emoji_replacement",
                    extra={"request_id": request.request_id},
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
                    logger.info(
                        "retry_request_tts_started",
                        extra={"request_id": request.request_id},
                    )
                    tts_audio = await generate_tts_async(replaced_answer)
                    if not tts_audio:
                        logger.error(
                            "retry_request_tts_failed",
                            extra={"request_id": request.request_id},
                        )
                        return
                    tts_buf = io.BytesIO(tts_audio)
                    tts_file = discord.File(tts_buf, filename="response.ogg")

                    if files_param:
                        files_param.append(tts_file)
                    else:
                        files_param = [tts_file]

                    logger.info(
                        "retry_request_tts_completed",
                        extra={"request_id": request.request_id},
                    )
                except Exception as e:
                    logger.exception(
                        "retry_request_tts_error",
                        extra={
                            "request_id": request.request_id,
                            "error_type": type(e).__name__,
                        },
                    )

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

            logger.info(
                "retry_request_completed",
                extra={"request_id": request.request_id, "user_id": request.user_id},
            )
        else:
            filtered_question = filter_profanity(request.question)
            await request.interaction.followup.send(
                "🚫 **Retry Failed**\n\n"
                "The retry attempt also failed. All AI models are currently unavailable.\n\n"
                "**Question:** " + filtered_question,
                ephemeral=True,
            )
            logger.error(
                "retry_request_all_models_failed",
                extra={"request_id": request.request_id, "user_id": request.user_id},
            )

    except asyncio.TimeoutError:
        filtered_question = filter_profanity(request.question)
        await request.interaction.followup.send(
            f"⏰ **Retry Timed Out**\n\n"
            f"The retry attempt timed out.\n\n"
            f"**Question:** {filtered_question}",
            ephemeral=True,
        )
        logger.warning(
            "retry_request_timeout",
            extra={"request_id": request.request_id, "user_id": request.user_id},
        )

    except Exception as e:
        filtered_question = filter_profanity(request.question)
        await request.interaction.followup.send(
            f"❌ **Retry Error**\n\n"
            f"An error occurred during the retry attempt.\n\n"
            f"**Question:** {filtered_question}\n"
            f"**Error:** {str(e)[:200]}...",
            ephemeral=True,
        )
        logger.exception(
            "retry_request_error",
            extra={
                "request_id": request.request_id,
                "user_id": request.user_id,
                "error_type": type(e).__name__,
            },
        )
