## Discord IQ Bot (Python)

A Discord bot that provides IQ calculation and AI chat functionality through a configurable LLM provider. The bot can calculate deterministic, fake IQ values and answer questions with context-aware responses.

### Features
- Deterministic per-user IQ calculation using SHA-256 of stable identifiers
- Normal distribution with mean 100 and standard deviation 15
- AI chat functionality using the configured LLM provider with model fallback
- Context-aware responses using server, user, and message history
- Rate limiting and priority-aware request queuing system
- Retry buttons that persist retry context across bot restarts while they are unexpired
- Owner-only configuration commands
- Implemented as slash commands: `/iq`, `/ask`, `/queue`, `/config`, etc.

### Prerequisites
- Python 3.10+
- A Discord application and bot token with the following OAuth2 scopes when inviting:
  - `bot`
  - `applications.commands`
- Gemini, Mistral, or xAI API key for AI chat functionality, depending on `LLM_PROVIDER`
- `google-genai>=2.3.0` is required for Gemini's Interactions API
- `mistralai>=2.0.0` is required for Mistral chat, vision, and optional image-generation-agent support

### Setup
1. Clone or open this project.
2. Create and activate a virtual environment (recommended):
   - Windows (PowerShell):
     ```powershell
     py -3 -m venv .venv
     .venv\Scripts\Activate.ps1
     ```
   - macOS/Linux:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create a `.env` file in the project directory. You can start from `config.env.example`:
   ```bash
   copy config.env.example .env  # Windows PowerShell
   # or
   cp config.env.example .env    # macOS/Linux
   ```
   Then edit `.env` and set:
   ```env
   DISCORD_BOT_TOKEN=your-bot-token-here
   OWNER_ID=your-user-id-here
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=your-gemini-api-key-here
   # or use LLM_PROVIDER=mistral with MISTRAL_API_KEY
   # or use LLM_PROVIDER=xai with XAI_API_KEY
   # Optional: provide a test guild ID to sync commands instantly in one server
   # If omitted, commands are synced globally (can take up to 1 hour to appear)
   # DISCORD_GUILD_ID=123456789012345678
   # Optional: development server ID for testing
   # DEV_SERVER_ID=123456789012345678
   ```

### Running
From the project directory, run:
```bash
python bot.py
```

- If `DISCORD_GUILD_ID` is set, commands appear almost immediately in that server.
- If not set, commands sync globally and may take up to ~1 hour to appear.

### Commands

#### User Commands
- `/iq [user]` - Get the IQ of a user (or yourself if no user specified)
- `/ask <question>` - Ask the bot a question using AI
- `/imagine <prompt> [image]` - Generate an image from a text prompt when the configured provider supports image generation and the configured account has access. Optionally include an image for reference/modification.
- `/queue` - Check the current request queue status

#### Owner Commands
- `/config` - View current bot configuration
- `/sethistorylimit [number]` - Set number of recent messages to fetch per user (1-50)
- `/setsearchdepth [number]` - Set how far back to search in channel history (100-10000)
- `/clearqueue` - Clear the request queue
- `/refresh` - Refresh slash commands (dev server only)

### Configuration
The bot supports several configurable parameters that can be set via environment variables or owner commands:

- **Message History Limit**: Number of recent messages to fetch per user (default: 5)
- **Message History Search Depth**: How far back to search in channel history (default: 1000)
- **Ask Command Cooldown**: Rate limiting for non-owner users (default: 30 minutes)
- **Imagine Command Cooldown**: Rate limiting for non-owner users (default: 15 minutes)
- **LLM Provider**: Set `LLM_PROVIDER` to `gemini`, `mistral`, or `xai`.
- **Mistral Models**: Override `MISTRAL_TEXT_MODELS` and `MISTRAL_VISION_MODELS` for text and `/ask` image-input fallback order.
- **Mistral Image Generation**: Set `MISTRAL_IMAGE_AGENT_ID` to a Mistral agent that has the `image_generation` tool enabled if you want `/imagine` with Mistral.

### Notes
- This bot requires the Message Content intent for AI chat functionality.
- The IQ is not meant to be real or serious; it is purely for entertainment.
- AI responses are context-aware and include server, user, and message history information.
- Rate limiting applies to non-owner users to prevent spam.
- The bot uses a queue system to handle multiple requests efficiently.
- The Gemini provider uses the Interactions API with `store=False`; Frozbot sends its own Discord context each turn instead of relying on server-side Gemini conversation state.
- Slash commands are registered from startup config. Set `ASK_ENABLE=false` or `IMAGINE_ENABLE=false` before startup or `/refresh` to hide those commands from Discord.
- If ElevenLabs is not configured, TTS options are omitted from slash commands.
- Gemini text/chat and image-generation fallback models can be overridden with `GEMINI_TEXT_IMAGE_MODELS` and `GEMINI_IMAGE_MODELS`.
- Mistral text/chat and `/ask` image-input fallback models can be overridden with `MISTRAL_TEXT_MODELS` and `MISTRAL_VISION_MODELS`.
- Mistral `/imagine` requires `MISTRAL_IMAGE_AGENT_ID`; otherwise Mistral is treated as chat and vision-input only.
