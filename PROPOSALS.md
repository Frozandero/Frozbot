# Frozbot Improvement Proposals

This document records code improvement and feature proposals from the June 28, 2026 codebase review.

## Completed

These items have been implemented.

1. Centralized ask and mention context building.
   `/ask` and mention-based chat now use `context.build_ask_context()` instead of maintaining separate context assembly paths.

2. Hardened prompt boundaries.
   Prompt construction now separates stable bot policy from an explicit `UNTRUSTED DISCORD CONTEXT` section.

3. Moved blocking TTS work off the event loop.
   `eleven.generate_tts_async()` wraps ElevenLabs and FFmpeg work in `asyncio.to_thread()`, and async callers now await it.

4. Cleaned up SQLite connection handling and the early-return leak.
   SQLite access now goes through `connect_db()`, the database path is configurable with `FROZBOT_DB_PATH`, duplicate bans use `INSERT OR IGNORE`, and empty multi-user memory lookup returns before opening a connection.

5. Added `/summarize`.
   The command is registered through `commands/summarize.py` and uses the shared channel-summary helper. Message/thread context-menu summaries remain a separate backlog item.

## Code Improvement Proposals

1. Improve long response handling.
   `request_queue.py` truncates responses over Discord's 2000-character message limit. Send split messages or attach a text/Markdown file instead.

2. Reuse provider execution helpers.
   Gemini, Mistral, and xAI providers each create fresh `ThreadPoolExecutor` instances around blocking SDK calls. Add a shared helper for executor calls, timeout handling, retries, and logging.

3. Make the queue manager more complete.
   `MAX_CONCURRENT_REQUESTS` exists but is unused, and request IDs use second-level timestamps. Use UUID request IDs, worker tasks, queue position reporting, cancellation, and better wait estimates.

4. Replace prints with structured logging.
   Current logs are plain `print()` calls and sometimes include context previews. Use Python `logging` with request IDs, provider/model fields, token usage, and redacted context by default.

5. Validate attachments more defensively.
   Image reads in `/ask`, mention chat, and `/imagine` should enforce file size, pixel count, format, and `Image.verify()` before model use.

6. Refresh deployment docs and service metadata.
   `DEPLOYMENT.md` still mentions Python 3.8+, while the project requires Python 3.10+. The checked-in `frozbot.service` also appears older than the generated unit in `deploy.sh`.

7. Store memories by stable user identity.
   Memory lookup is still username-based. Consider migrating memories toward stable user IDs plus display names to survive username changes.

## Feature Proposals

1. Add message or thread context-menu summaries using the existing channel-summary machinery.

2. Add memory search, memory export, and owner/user delete flows such as `/forgetme`.

3. Add per-channel settings for persona, context depth, summaries, cooldowns, and feature toggles.

4. Add `/imagine` action buttons: regenerate, variation, remix prompt, and use previous output as reference.

5. Add owner `/health` or `/usage` commands showing provider availability, selected model list, token totals, failures, cooldowns, and queue state.

6. Add context-menu commands such as "explain this message" and "explain this image" that reuse the `/ask` image and reply-context path.

7. Add optional daily or on-demand channel digests for active channels.

## Completed First Pass

1. Extract a shared ask/mention context builder.
2. Split stable bot policy from untrusted context in prompts.
3. Clean up SQLite connection handling and the early-return leak.
4. Move TTS and FFmpeg work off the event loop.
5. Add `/summarize` on top of the shared context and summary helpers.
