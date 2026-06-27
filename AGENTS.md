# Frozbot Agent Guide

Do not use code formatters unless explicitly instructed.

## Purpose

Frozbot is a personal Discord AI bot written in Python. It supports slash-command and mention-based LLM chat, image generation, ElevenLabs TTS, custom emoji replacement, retry buttons, per-channel memories in SQLite, and owner-only admin commands.

This file is the primary orientation document for future coding agents. Keep it accurate when changing architecture, commands, environment variables, or operational workflows.

## Quick Start For Agents

1. Check current state with `git status --short`.
2. Read this file, then inspect the specific modules you will touch.
3. Do not read `.env`, `database.db`, `venv/`, `.venv/`, `temp_media/`, or generated caches unless the task explicitly requires it.
4. Avoid live Discord, Gemini, xAI, ElevenLabs, or FFmpeg calls unless the user asks for integration testing.
5. Prefer small, local verification:
   - `python -m compileall -q .`
   - `python -m unittest discover -s tests`
   - For full dependency coverage, run these inside an activated environment after `pip install -r requirements.txt`.
6. If you change commands or runtime behavior, update `README.md`, `config.env.example`, and this file when relevant.

## Runtime

- Python 3.10+
- `discord.py` for Discord client, app commands, messages, views, and interactions
- Provider-based LLM layer under `llm_providers/`
- SQLite file storage through `database.py`
- Pillow for image inputs and generated image handling
- ElevenLabs for TTS, plus an external `ffmpeg` executable for MP3 to OGG/Opus conversion

Required environment:

- `DISCORD_BOT_TOKEN`
- `OWNER_ID`
- `GEMINI_API_KEY` when `LLM_PROVIDER=gemini`
- `XAI_API_KEY` when `LLM_PROVIDER=xai`

Important optional environment:

- `DISCORD_GUILD_ID` for guild-scoped command sync
- `DEV_SERVER_ID` for dev-only admin commands
- `LLM_PROVIDER`, currently `gemini` or `xai`
- `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`
- `ASK_ENABLE`, `IMAGINE_ENABLE`, `REQUIRE_EXPLICIT_MENTION`
- cooldown, context-depth, and channel-summary variables in `config.env.example`

## Architecture Map

- `bot.py`: Creates the Discord client, command tree, database tables, commands, handlers, and runs the bot.
- `config.py`: Loads environment variables and owns mutable runtime state such as cooldowns, retry caches, channel-summary cache, and the request queue.
- `commands/`: Registers slash commands by feature area.
  - `ask.py`: `/ask`, context assembly for slash commands, optional image and TTS.
  - `imagine.py`: `/imagine`, image generation, optional prompt reference images and mentioned-user avatars.
  - `memory.py`: `/setmemory`, `/getmemory`, `/deletememory`.
  - `admin.py`: owner-only settings, queue/cache controls, bans, refresh, emoji debug.
  - `misc.py`: `/iq`, `/queue`, `/say`.
- `handlers.py`: Discord events, retry-button interactions, mention-based chat, command sync on ready.
- `context.py`: Shared context construction for recent messages, channel summaries, user/member info, replied-message context, memories, and final system prompt.
- `request_queue.py`: Priority-aware async request processing for ask/retry requests and response delivery.
- `llm.py`: Provider-neutral facade around the provider system.
- `llm_providers/`: Provider abstraction and concrete Gemini/xAI implementations.
- `emoji.py`: Guild custom emoji discovery, replacement, and debug output.
- `eleven.py`: ElevenLabs TTS and FFmpeg conversion.
- `retry.py`: Persistent retry records plus temporary persisted image files for retry buttons.
- `database.py`: Synchronous SQLite helpers for bans and channel-scoped memories.
- `views.py`: Discord UI views, currently memory pagination.
- `iq.py`: Pure deterministic entertainment IQ calculation.

## Coding Rules

- Preserve the provider abstraction. New LLM backends should implement `LLMProvider`, be wired in `llm_providers/__init__.py`, and expose config in `config.env.example`.
- The Gemini provider uses `google-genai>=2.3.0` and the Interactions API (`client.interactions.create`) with `store=False`. Do not reintroduce deprecated `google-generativeai` or `models.generate_content` paths unless intentionally adding a compatibility layer.
- Keep slash-command `/ask` and mention-based chat behavior aligned. If you change context assembly in `commands/ask.py`, check whether `_build_message_context()` in `handlers.py` needs the same change.
- Always defer Discord interactions before long work such as history reads, LLM calls, image processing, TTS, or network fetches.
- Never call blocking SDK/network work directly on the event loop. Existing provider code uses executors around blocking clients.
- Keep user-visible Discord messages within the 2000-character limit or use attachments/files when appropriate.
- Keep owner-only commands guarded with `config.is_owner()`.
- Keep memory behavior channel-scoped unless intentionally changing the data model.
- Avoid adding persistent state to globals unless it belongs in `config.py` and has a clear lifecycle.
- Do not commit secrets, local databases, virtual environments, generated media, or generated agent artifacts.
- Do not run the bot with `python bot.py` as a verification step unless the user explicitly wants a live run.

## Testing Guidance

There is no full integration test harness for Discord/API behavior. Favor pure unit tests for deterministic helpers and mock/fake objects for Discord-facing code.

Create or refresh a local environment when dependencies are missing:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Recommended checks after edits:

```powershell
python -m compileall -q .
python -m unittest discover -s tests
```

Some tests may skip in a bare interpreter when runtime dependencies are not installed. A clean run in an activated dependency environment is stronger than a bare-interpreter smoke run.

When adding tests:

- Use `unittest` unless the project explicitly adopts another test runner.
- Do not require API keys, `.env`, Discord connections, FFmpeg, or network access.
- Prefer tiny fake objects over importing or constructing live Discord models.

## Known Technical Debt

- LLM provider model names and SDK behavior can drift over time. Verify provider changes against official provider docs before changing model IDs or request shapes.

## Operational Notes

- Slash command sync happens in `handlers.on_ready()`. `DISCORD_GUILD_ID` gives fast guild sync; otherwise global sync can take up to an hour.
- `DEV_SERVER_ID` controls dev-only command registration via `config.IS_DEV_SERVER_COMMAND`.
- `database.db` is local runtime data and is intentionally ignored by git.
- `temp_media/` is runtime retry media and should remain ignored.

