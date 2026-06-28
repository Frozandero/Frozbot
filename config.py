"""Configuration and global state for Frozbot."""

import os
import datetime
import asyncio
import itertools
from typing import Dict, Any, Optional

from dotenv import load_dotenv
import discord

# Load environment variables
load_dotenv()

# ============================================================================
# ENVIRONMENT VARIABLES
# ============================================================================

# Required tokens and IDs
TOKEN: Optional[str] = os.getenv("DISCORD_BOT_TOKEN")
OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))
GUILD_ID_ENV: Optional[str] = os.getenv("DISCORD_GUILD_ID")

# Guild objects for dev server commands
GUILD_ID_IF_PRESENT: Optional[discord.Object] = (
    discord.Object(id=int(os.getenv("DEV_SERVER_ID", "0")))
    if os.getenv("DEV_SERVER_ID")
    else None
)

IS_DEV_SERVER_COMMAND: Optional[discord.Object] = (
    discord.Object(id=int(os.getenv("DEV_SERVER_ID", "0")))
    if os.getenv("DEV_SERVER_ID")
    else None
)

# LLM Provider Configuration
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini").lower()
ELEVENLABS_API_KEY: Optional[str] = os.getenv("ELEVENLABS_API_KEY")

# Feature toggles
CENSOR_MESSAGES: bool = os.getenv("CENSOR_MESSAGES", "false").lower() == "true"
IMAGINE_ENABLE: bool = os.getenv("IMAGINE_ENABLE", "true").lower() == "true"
ASK_ENABLE: bool = os.getenv("ASK_ENABLE", "true").lower() == "true"
REQUIRE_EXPLICIT_MENTION: bool = (
    os.getenv("REQUIRE_EXPLICIT_MENTION", "false").lower() == "true"
)

# Rate limiting settings
CONFIG_DEPRECATION_WARNINGS: list[str] = []


def _read_cooldown_seconds(
    seconds_env: str,
    deprecated_minutes_env: str,
    default_seconds: int,
) -> int:
    """Read cooldown seconds with deprecated minute-based env compatibility."""
    seconds_value = os.getenv(seconds_env)
    minutes_value = os.getenv(deprecated_minutes_env)

    if seconds_value is not None and seconds_value.strip():
        if minutes_value is not None and minutes_value.strip():
            CONFIG_DEPRECATION_WARNINGS.append(
                f"{deprecated_minutes_env} is deprecated and ignored because {seconds_env} is set. "
                f"Use {seconds_env} only."
            )
        return max(0, int(seconds_value))

    if minutes_value is not None and minutes_value.strip():
        converted_seconds = max(0, int(minutes_value) * 60)
        CONFIG_DEPRECATION_WARNINGS.append(
            f"{deprecated_minutes_env} is deprecated. Converted {minutes_value} minute(s) "
            f"to {converted_seconds} seconds. Use {seconds_env} instead."
        )
        return converted_seconds

    return default_seconds


ASK_COMMAND_COOLDOWN_SECONDS: int = _read_cooldown_seconds(
    "ASK_COMMAND_COOLDOWN_SECONDS",
    "ASK_COMMAND_COOLDOWN_MINUTES",
    30 * 60,
)
IMAGINE_COMMAND_COOLDOWN_SECONDS: int = _read_cooldown_seconds(
    "IMAGINE_COMMAND_COOLDOWN_SECONDS",
    "IMAGINE_COMMAND_COOLDOWN_MINUTES",
    15 * 60,
)
# Backward-compatible aliases for older imports. New code should use seconds.
ASK_COMMAND_COOLDOWN_MINUTES: int = ASK_COMMAND_COOLDOWN_SECONDS // 60
IMAGINE_COMMAND_COOLDOWN_MINUTES: int = IMAGINE_COMMAND_COOLDOWN_SECONDS // 60
RETRY_BUTTON_EXPIRE_MINUTES: int = int(os.getenv("RETRY_BUTTON_EXPIRE_MINUTES", "5"))
RETRY_BUTTON_TTL_MINUTES: int = 60

# Message history settings
MESSAGE_HISTORY_LIMIT: int = int(os.getenv("MESSAGE_HISTORY_LIMIT", "10"))
MESSAGE_HISTORY_SEARCH_DEPTH: int = int(
    os.getenv("MESSAGE_HISTORY_SEARCH_DEPTH", "10000")
)

# Channel context and summary settings
CHANNEL_CONTEXT_LAST: int = int(os.getenv("CHANNEL_CONTEXT_LAST", "10"))
CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES: bool = (
    os.getenv("CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES", "false").lower() == "true"
)
CHANNEL_SUMMARY_DEPTH: int = int(os.getenv("CHANNEL_SUMMARY_DEPTH", "50"))
CHANNEL_SUMMARY_ENABLE: bool = (
    os.getenv("CHANNEL_SUMMARY_ENABLE", "true").lower() == "true"
)
CHANNEL_SUMMARY_TTL_MIN: int = int(os.getenv("CHANNEL_SUMMARY_TTL_MIN", "3"))

# Queue settings
REQUEST_DELAY_SECONDS: int = int(os.getenv("REQUEST_DELAY_SECONDS", "2"))
MAX_CONCURRENT_REQUESTS: int = max(
    1, int(os.getenv("MAX_CONCURRENT_REQUESTS", "1"))
)
MAX_STORED_QUESTIONS: int = 5

# Image input validation
MAX_IMAGE_ATTACHMENT_BYTES: int = int(
    os.getenv("MAX_IMAGE_ATTACHMENT_BYTES", str(8 * 1024 * 1024))
)
MAX_IMAGE_PIXELS: int = int(os.getenv("MAX_IMAGE_PIXELS", "16000000"))
ALLOWED_IMAGE_FORMATS: str = os.getenv("ALLOWED_IMAGE_FORMATS", "JPEG,PNG,WEBP,GIF")

# ============================================================================
# GLOBAL STATE (Mutable runtime state)
# ============================================================================

# Rate limiting tracking
ASK_COMMAND_COOLDOWNS: Dict[int, datetime.datetime] = {}
IMAGINE_COMMAND_COOLDOWNS: Dict[int, datetime.datetime] = {}

# Recent questions for retry functionality
RECENT_QUESTIONS: Dict[int, list] = {}

# Track used retry buttons
USED_RETRY_BUTTONS: Dict[str, datetime.datetime] = {}

# Channel summary cache
CHANNEL_SUMMARY_CACHE: Dict[int, Dict[str, Any]] = {}

# Temp storage for retryable media and context
TEMP_MEDIA_DIR: str = os.path.join(os.getcwd(), "temp_media")
ASK_IMAGES_DIR: str = os.path.join(TEMP_MEDIA_DIR, "ask_images")
RETRY_RECORDS_DIR: str = os.path.join(TEMP_MEDIA_DIR, "retry_records")
RETRY_MEDIA_TEMP: Dict[str, list] = {}
RETRY_CONTEXT_TEMP: Dict[str, str] = {}

# Request queue
REQUEST_QUEUE: asyncio.PriorityQueue = asyncio.PriorityQueue()
REQUEST_QUEUE_SEQUENCE = itertools.count()
QUEUE_PROCESSOR_RUNNING: bool = False


def get_owner_id() -> int:
    """Get the owner ID from environment."""
    return int(os.getenv("OWNER_ID", "0"))


def is_owner(user_id: int) -> bool:
    """Check if a user is the bot owner."""
    return user_id == get_owner_id()


def is_tts_configured() -> bool:
    """Return whether ElevenLabs TTS has the minimum required configuration."""
    return bool(ELEVENLABS_API_KEY)
