# Frozbot - Discord AI Bot

## Overview
Frozbot is a feature-rich Discord bot built with Python that provides AI-powered conversations, image generation, text-to-speech, and entertainment features. It uses Google's Gemini AI for intelligent responses and ElevenLabs for voice synthesis.

## Tech Stack
- **Runtime**: Python 3.10+
- **Discord Library**: discord.py 2.x
- **AI/LLM**: Google Gemini (gemini-2.5-pro, gemini-2.5-flash, gemini-2.0-flash with fallback)
- **TTS**: ElevenLabs API
- **Database**: SQLite (database.db)
- **Image Processing**: Pillow (PIL)
- **Audio Processing**: FFmpeg (for MP3 to OGG conversion)

## Project Structure

```
frozbot/
├── bot.py           # Main bot code (3140 lines) - commands, handlers, context building
├── database.py      # SQLite database operations for memories and banned users
├── llm.py           # Gemini API integration with model fallback
├── eleven.py        # ElevenLabs TTS integration and audio processing
├── database.db      # SQLite database file
├── config.env.example  # Example environment configuration
├── requirements.txt # Python dependencies
├── deploy.sh        # Deployment script
├── frozbot.service  # Systemd service file for Linux deployment
└── venv/            # Virtual environment
```

## Key Features

### 1. AI Chat (`/ask`)
- Context-aware responses using Gemini AI
- Supports text questions with optional image attachments
- Optional TTS (text-to-speech) for audio responses
- Rich context injection including:
  - Server information and memories
  - User details (roles, join date, recent messages)
  - Mentioned users' information and messages
  - Channel context (recent messages, LLM-generated summary)
  - Guild custom emojis (auto-replaced in responses)
- Rate limiting (configurable cooldown, TTS has 5x longer cooldown)
- Request queue system with retry functionality
- Model fallback: tries multiple Gemini models if quota exceeded

### 2. Image Generation (`/imagine`)
- Text-to-image and image-to-image generation
- Uses `gemini-2.0-flash-preview-image-generation` model
- Supports user mentions (fetches profile pictures as reference)
- Rate limited (configurable cooldown)

### 3. IQ Command (`/iq`)
- Deterministic, fake IQ calculation for entertainment
- Uses SHA-256 hash of stable user identifiers
- Normal distribution (mean: 100, stddev: 15)

### 4. Memory System
- Persistent memories stored in SQLite
- Supports per-user memories and generic server memories (username='*')
- Channel-scoped memories
- Pagination support for viewing memories
- Commands: `/setmemory`, `/getmemory`, `/deletememory` (owner-only for set/delete)

### 5. Channel Context
- **Raw Context**: Last N messages from the channel
- **Summary**: LLM-generated summary of recent conversation (cached with TTL)
- Configurable depth and caching

## Slash Commands

### User Commands
| Command | Description |
|---------|-------------|
| `/ask <question> [image] [tts]` | Ask the AI a question (optional image/TTS) |
| `/imagine <prompt> [image]` | Generate an image from text/image |
| `/iq [user]` | Get deterministic IQ for user |
| `/queue` | Check request queue status |
| `/getmemory [user] [limit]` | View stored memories |

### Owner Commands
| Command | Description |
|---------|-------------|
| `/setmemory <memory> [user]` | Store a memory |
| `/deletememory <id>` | Delete a memory |
| `/clearqueue` | Clear the request queue |
| `/togglellmban <user>` | Ban/unban user from AI features |
| `/config` | View current bot configuration |
| `/sethistorylimit [number]` | Set messages per user (1-50) |
| `/setsearchdepth [number]` | Set channel search depth (100-10000) |
| `/setimagineenabled [bool]` | Toggle image generation |
| `/setask [bool]` | Toggle ask command |
| `/setcontextincludebots [bool]` | Include bot messages in context |
| `/debugemojis` | Debug emoji replacement issues |
| `/refresh` | Refresh slash commands (dev server only) |

## Environment Variables

### Required
```env
DISCORD_BOT_TOKEN=your-bot-token
OWNER_ID=your-discord-user-id
GEMINI_API_KEY=your-gemini-api-key
```

### Optional
```env
# Guild/Server Configuration
DISCORD_GUILD_ID=guild-id          # For instant command sync (dev)
DEV_SERVER_ID=dev-server-id        # For dev-only commands

# TTS Configuration
ELEVENLABS_API_KEY=your-key        # Required for TTS
ELEVENLABS_VOICE_ID=voice-id       # Default: JBFqnCBsd6RMkjVDRZzb

# Feature Toggles
CENSOR_MESSAGES=false              # Enable profanity filter
ASK_ENABLE=true                    # Enable /ask command
IMAGINE_ENABLE=true                # Enable /imagine command

# Rate Limiting
ASK_COMMAND_COOLDOWN_MINUTES=30
IMAGINE_COMMAND_COOLDOWN_MINUTES=15
RETRY_BUTTON_EXPIRE_MINUTES=5

# Message History
MESSAGE_HISTORY_LIMIT=10           # Messages per user (1-50)
MESSAGE_HISTORY_SEARCH_DEPTH=10000 # Channel search depth

# Channel Context
CHANNEL_CONTEXT_LAST=10            # Raw context messages
CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES=false
CHANNEL_SUMMARY_ENABLE=true        # LLM summary generation
CHANNEL_SUMMARY_DEPTH=50           # Messages for summary
CHANNEL_SUMMARY_TTL_MIN=3          # Summary cache duration
```

## Architecture Details

### Request Queue System
- Asynchronous queue for handling AI requests
- Prevents rate limiting and ensures orderly processing
- Priority system (owner > retry > regular)
- 2-second delay between requests
- Retry functionality with one-time buttons

### LLM Integration (`llm.py`)
- Model fallback chain: gemini-2.5-pro → gemini-2.5-flash → gemini-2.5-flash-lite → gemini-2.0-flash → gemini-2.0-flash-lite
- Configurable thinking budgets per model
- URL context tool support for web-aware responses
- Automatic retry on server errors (500, 502, 503, 504)
- 30-second timeout per request
- Separate function for message summarization

### TTS System (`eleven.py`)
- ElevenLabs API integration
- Markdown stripping for clean TTS output
- Discord emote name extraction (`:emote:` → "emote")
- MP3 to OGG/Opus conversion via FFmpeg (48kHz, 32kbps)

### Database Schema (`database.py`)
```sql
-- Banned users table
CREATE TABLE banned_users (
    user_id INTEGER PRIMARY KEY
);

-- Memories table
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,          -- User's name or '*' for generic
    memory TEXT,
    channel_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Context Building
The bot builds rich context for each `/ask` request:
1. **Server Context**: Server name + generic memories
2. **User Context**: Name, username, roles, join date, recent messages, user-specific memories
3. **Mentioned Users**: Full details for any @mentioned users
4. **Channel Context**: Recent raw messages + optional LLM summary
5. **Emoji Context**: List of available guild emojis
6. **Date/Time**: Current timestamp

### Emoji Handling
- Detects `:emoji_name:` patterns in AI responses
- Looks up guild custom emojis by name
- Auto-replaces with proper Discord emoji format
- Fetches from API if not in cache

## Discord Intents Required
- `message_content` - For AI context
- `members` - For user information
- `guilds` - For server information

## Running the Bot

### Development
```bash
# Create virtual environment
python -m venv venv

# Activate (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Activate (Linux/macOS)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp config.env.example .env
# Edit .env with your tokens

# Run
python bot.py
```

### Production (Linux with systemd)
Use `frozbot.service` and `deploy.sh` for systemd-based deployment.

## Important Code Patterns

### Rate Limiting
```python
# Cooldown tracking
ASK_COMMAND_COOLDOWNS: Dict[int, datetime.datetime] = {}

# Check and apply cooldown
if user_id in ASK_COMMAND_COOLDOWNS:
    time_diff = current_time - ASK_COMMAND_COOLDOWNS[user_id]
    if time_diff.total_seconds() / 60 < cooldown_minutes:
        # Rate limited
```

### Request Queue
```python
# Add to queue
await add_request_to_queue(
    RequestType.ASK,
    interaction,
    question,
    context_string,
    user_id,
    priority=1,  # Owner priority
    media_parts=media_parts,
    tts=tts,
)
```

### Deferred Response
```python
# For long-running operations
await interaction.response.defer(thinking=True)
# ... do work ...
await interaction.followup.send(content=response)
```

## Known Considerations
- TTS cooldown is 5x the ask cooldown to manage API costs
- Channel summary is cached to reduce LLM calls
- Retry buttons expire after configurable minutes
- Bot messages are excluded from context by default
- Model fallback ensures availability but may vary quality
- Large channel histories impact response time

