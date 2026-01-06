"""Configuration and global state for Frozbot."""

import os
import datetime
import asyncio
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

# Feature toggles
CENSOR_MESSAGES: bool = os.getenv("CENSOR_MESSAGES", "false").lower() == "true"
IMAGINE_ENABLE: bool = os.getenv("IMAGINE_ENABLE", "true").lower() == "true"
ASK_ENABLE: bool = os.getenv("ASK_ENABLE", "true").lower() == "true"
REQUIRE_EXPLICIT_MENTION: bool = (
    os.getenv("REQUIRE_EXPLICIT_MENTION", "false").lower() == "true"
)

# Rate limiting settings
ASK_COMMAND_COOLDOWN_MINUTES: int = int(os.getenv("ASK_COMMAND_COOLDOWN_MINUTES", "30"))
IMAGINE_COMMAND_COOLDOWN_MINUTES: int = int(
    os.getenv("IMAGINE_COMMAND_COOLDOWN_MINUTES", "15")
)
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
REQUEST_DELAY_SECONDS: int = 2
MAX_CONCURRENT_REQUESTS: int = 1
MAX_STORED_QUESTIONS: int = 5

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
RETRY_MEDIA_TEMP: Dict[str, list] = {}
RETRY_CONTEXT_TEMP: Dict[str, str] = {}

# Request queue
REQUEST_QUEUE: asyncio.Queue = asyncio.Queue()
QUEUE_PROCESSOR_RUNNING: bool = False


def get_owner_id() -> int:
    """Get the owner ID from environment."""
    return int(os.getenv("OWNER_ID", "0"))


def is_owner(user_id: int) -> bool:
    """Check if a user is the bot owner."""
    return user_id == get_owner_id()
