"""Shared execution helpers for blocking provider SDK calls."""

import asyncio
import concurrent.futures
import logging
import os
import time
from collections.abc import Callable
from typing import Optional, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

_DEFAULT_MAX_WORKERS = max(4, (os.cpu_count() or 1) * 2)
_MAX_WORKERS = int(os.getenv("LLM_EXECUTOR_MAX_WORKERS", str(_DEFAULT_MAX_WORKERS)))
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(1, _MAX_WORKERS),
    thread_name_prefix="frozbot-llm",
)


async def run_blocking_provider_call(
    func: Callable[[], T],
    *,
    provider: str,
    model: Optional[str],
    operation: str,
    timeout: float,
    request_id: Optional[str] = None,
    retries: int = 0,
    retry_delay: float = 1.0,
    is_retryable: Optional[Callable[[BaseException], bool]] = None,
) -> T:
    """Run a blocking provider call in the shared executor with timeout/retries."""
    attempts = max(1, retries + 1)
    last_error: Optional[BaseException] = None

    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        log_fields = {
            "request_id": request_id,
            "provider": provider,
            "model": model,
            "operation": operation,
            "attempt": attempt,
            "attempts": attempts,
            "timeout_seconds": timeout,
        }
        logger.info("provider_call_started", extra=log_fields)

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(_EXECUTOR, func),
                timeout=timeout,
            )
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                "provider_call_completed",
                extra={**log_fields, "elapsed_ms": elapsed_ms},
            )
            return result
        except asyncio.TimeoutError:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.warning(
                "provider_call_timed_out",
                extra={**log_fields, "elapsed_ms": elapsed_ms},
            )
            raise
        except Exception as exc:
            last_error = exc
            elapsed_ms = int((time.monotonic() - started) * 1000)
            retryable = is_retryable(exc) if is_retryable is not None else True
            will_retry = retryable and attempt < attempts
            logger.warning(
                "provider_call_failed",
                extra={
                    **log_fields,
                    "elapsed_ms": elapsed_ms,
                    "error_type": type(exc).__name__,
                    "retryable": retryable,
                    "will_retry": will_retry,
                },
                exc_info=not will_retry,
            )

            if not will_retry:
                raise
            await asyncio.sleep(retry_delay)

    if last_error:
        raise last_error
    raise RuntimeError("Provider call failed without an exception.")
