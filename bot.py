import os
import re
import hashlib
import random
import datetime
import asyncio
import concurrent.futures
import uuid
import io
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
from google.genai import errors, types

import discord
from discord import app_commands
from dotenv import load_dotenv

from better_profanity import profanity
from PIL import Image

from database import (
    add_memory,
    clear_db,
    delete_memory,
    get_memories_by_user,
    get_memories_for_users,
    get_generic_memories,
    count_memories_by_user,
    init_db,
    add_banned_user,
    remove_banned_user,
    is_banned,
)
from eleven import generate_tts, get_eleven_client
from llm import get_gemini_client, summarize_messages_with_gemini, try_gemini_models

# Initialize profanity filter
profanity.load_censor_words()


def filter_profanity(text: str) -> str:
    """Filter profanity from text, replacing it with asterisks."""
    return profanity.censor(text, "■") if CENSOR_MESSAGES else text


class MemoryPaginationView(discord.ui.View):
    def __init__(
        self, username: str, channel_id: int, page: int = 0, page_size: int = 10
    ):
        super().__init__(timeout=300)  # 5 minute timeout
        self.username = username
        self.page = page
        self.page_size = page_size
        self.channel_id = channel_id
        self.total_memories = count_memories_by_user(username, channel_id)
        self.total_pages = max(1, (self.total_memories + page_size - 1) // page_size)

        # Update button states
        self.update_buttons()

    def update_buttons(self):
        # Clear existing buttons
        self.clear_items()

        # Add Previous button
        prev_button = discord.ui.Button(
            label="◀ Previous",
            style=discord.ButtonStyle.secondary,
            custom_id=f"memory_prev_{self.username}_{self.page}",
            disabled=(self.page <= 0),
        )
        prev_button.callback = self.previous_page
        self.add_item(prev_button)

        # Add page info button (non-functional, just shows page info)
        page_info = discord.ui.Button(
            label=f"Page {self.page + 1}/{self.total_pages}",
            style=discord.ButtonStyle.primary,
            disabled=True,
        )
        self.add_item(page_info)

        # Add Next button
        next_button = discord.ui.Button(
            label="Next ▶",
            style=discord.ButtonStyle.secondary,
            custom_id=f"memory_next_{self.username}_{self.page}",
            disabled=(self.page >= self.total_pages - 1),
        )
        next_button.callback = self.next_page
        self.add_item(next_button)

    def get_current_memories(self) -> list[tuple[int, str, str]]:
        offset = self.page * self.page_size
        return get_memories_by_user(
            self.username, self.channel_id, self.page_size, offset
        )

    def format_memories_message(self) -> str:
        memories = self.get_current_memories()
        if not memories:
            return f"No memories found for {self.username}."

        # Limit memory length for display to prevent overly long messages
        formatted_memories = []
        for memory in memories:
            memory_num = memory[0]
            # Truncate very long memories for readability
            display_memory = (
                memory[2] if len(memory[2]) <= 200 else memory[2][:197] + "..."
            )
            formatted_memories.append(f"{memory_num}. {memory[1]}: {display_memory}")

        memory_text = "\n".join(formatted_memories)

        return f"**Memories for {self.username}** ({self.total_memories} total):\n\n{memory_text}"

    async def previous_page(self, interaction: discord.Interaction):
        try:
            if self.page > 0:
                self.page -= 1
                self.update_buttons()
                await interaction.response.edit_message(
                    content=self.format_memories_message(), view=self
                )
            else:
                await interaction.response.defer()
        except Exception as e:
            print(f"Error in previous_page: {e}")
            await interaction.response.defer()

    async def next_page(self, interaction: discord.Interaction):
        try:
            if self.page < self.total_pages - 1:
                self.page += 1
                self.update_buttons()
                await interaction.response.edit_message(
                    content=self.format_memories_message(), view=self
                )
            else:
                await interaction.response.defer()
        except Exception as e:
            print(f"Error in next_page: {e}")
            await interaction.response.defer()

    async def on_timeout(self):
        # Disable all buttons when the view times out
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


async def debug_guild_emoji_state(guild: Optional[discord.Guild]) -> str:
    """Debug function to check the state of guild emojis and help troubleshoot issues."""
    if not guild:
        return "❌ No guild provided"

    try:
        debug_info = []
        debug_info.append(f"🔍 **Guild Debug Info**")
        debug_info.append(f"Guild ID: {getattr(guild, 'id', 'Unknown')}")
        debug_info.append(f"Guild Name: {getattr(guild, 'name', 'Unknown')}")
        debug_info.append(f"Guild Type: {type(guild)}")

        # Check guild attributes
        guild_attrs = ["emojis", "available", "unavailable", "chunked"]
        for attr in guild_attrs:
            try:
                value = getattr(guild, attr, None)
                debug_info.append(f"Guild.{attr}: {value}")
            except Exception as e:
                debug_info.append(f"Guild.{attr}: Error - {e}")

        # Check emoji cache
        try:
            cached_emojis = getattr(guild, "emojis", [])
            debug_info.append(f"📋 Cached Emojis: {len(cached_emojis)}")

            if cached_emojis:
                for i, emoji in enumerate(cached_emojis[:5]):  # Show first 5
                    try:
                        emoji_info = f"  {i+1}. :{getattr(emoji, 'name', 'Unknown')}: (ID: {getattr(emoji, 'id', 'Unknown')})"
                        debug_info.append(emoji_info)
                    except Exception as e:
                        debug_info.append(f"  {i+1}. Error processing emoji: {e}")

                if len(cached_emojis) > 5:
                    debug_info.append(f"  ... and {len(cached_emojis) - 5} more")
            else:
                debug_info.append("  No cached emojis found")

        except Exception as e:
            debug_info.append(f"❌ Error checking cached emojis: {e}")

        # Try to fetch emojis
        try:
            debug_info.append("🔄 Attempting to fetch emojis...")
            fetched = await guild.fetch_emojis()
            debug_info.append(f"📥 Fetched Emojis: {len(fetched)}")

            if fetched:
                for i, emoji in enumerate(fetched[:5]):  # Show first 5
                    try:
                        emoji_info = f"  {i+1}. :{getattr(emoji, 'name', 'Unknown')}: (ID: {getattr(emoji, 'id', 'Unknown')})"
                        debug_info.append(emoji_info)
                    except Exception as e:
                        debug_info.append(
                            f"  {i+1}. Error processing fetched emoji: {e}"
                        )

                if len(fetched) > 5:
                    debug_info.append(f"  ... and {len(fetched) - 5} more")
            else:
                debug_info.append("  No emojis returned from fetch")

        except Exception as e:
            debug_info.append(f"❌ Error fetching emojis: {e}")

        return "\n".join(debug_info)

    except Exception as e:
        return f"❌ Error in debug_guild_emoji_state: {e}"


async def replace_guild_emojis_in_text(
    text: str, guild: Optional[discord.Guild]
) -> str:
    """Replace :emoji_name: occurrences with actual guild custom emoji mentions.

    Looks up emojis by name in the provided guild. If not found in cache,
    attempts a fetch. If still not found, leaves the token unchanged.
    """
    if not text or guild is None:
        return text

    # Validate that guild is a proper Discord guild object
    if not hasattr(guild, "id") or not hasattr(guild, "emojis"):
        print(
            f"⚠️ Invalid guild object passed to replace_guild_emojis_in_text: {type(guild)}"
        )
        return text

    # Additional validation: ensure guild is in a valid state
    try:
        guild_id = getattr(guild, "id", None)
        if not guild_id:
            print("⚠️ Guild object has no valid ID")
            return text
    except Exception as e:
        print(f"⚠️ Error accessing guild ID: {e}")
        return text

    # Match :name: not part of an existing custom emoji like <:name:id> or <a:name:id>
    pattern = re.compile(r"(?<!<)(?<!<a):([A-Za-z0-9_]{2,32}):")
    names_in_text = set(pattern.findall(text))
    if not names_in_text:
        return text

    print(f"🔍 Found emoji names in text: {names_in_text}")

    # Build name -> emoji mapping (case-insensitive by name)
    name_to_emoji: Dict[str, Any] = {}
    try:
        # First try to get emojis from cache
        cached_emojis = getattr(guild, "emojis", [])
        print(f"📋 Found {len(cached_emojis)} cached emojis in guild {guild_id}")

        for e in cached_emojis:
            try:
                if hasattr(e, "name") and e.name:
                    name_to_emoji[str(e.name).lower()] = e
            except Exception as emoji_error:
                print(f"  ❌ Error processing cached emoji: {emoji_error}")
                continue

        # Check which emojis are missing from cache
        missing = {n for n in names_in_text if n.lower() not in name_to_emoji}
        if missing:
            print(f"🔄 Fetching missing emojis: {missing}")
            try:
                fetched = await guild.fetch_emojis()
                print(f"📥 Fetched {len(fetched)} emojis from guild {guild_id}")

                for e in fetched:
                    try:
                        if hasattr(e, "name") and e.name:
                            name_to_emoji[str(e.name).lower()] = e
                    except Exception as emoji_error:
                        print(f"  ❌ Error processing fetched emoji: {emoji_error}")
                        continue
            except Exception as fetch_error:
                print(f"❌ Failed to fetch emojis from guild {guild_id}: {fetch_error}")
                # Continue with cached emojis only

        # Show final mapping
        print(f"🎯 Final emoji mapping: {len(name_to_emoji)} emojis available")

        def _sub(m: re.Match) -> str:
            name = m.group(1)
            emoji = name_to_emoji.get(name.lower())
            if emoji:
                try:
                    emoji_str = str(emoji)
                    return emoji_str
                except Exception as e:
                    print(f"❌ Error converting emoji {emoji} to string: {e}")
                    return m.group(0)
            else:
                print(f"⚠️ No emoji found for :{name}:")
                return m.group(0)

        result = pattern.sub(_sub, text)
        print(
            f"✅ Emoji replacement complete. Original: {text[:100]}... -> Result: {result[:100]}..."
        )
        return result

    except Exception as e:
        print(f"❌ Unexpected error in replace_guild_emojis_in_text: {e}")
        import traceback

        traceback.print_exc()
        return text


async def list_guild_emoji_names(
    guild: Optional[discord.Guild], max_total: Optional[int] = None
) -> list[str]:
    """Return a list of custom emoji names available in the guild.

    If `max_total` is provided, the list will be truncated to that length.
    """
    names: list[str] = []
    try:
        if guild is None:
            print("⚠️ No guild provided to list_guild_emoji_names")
            return names

        # Validate guild object
        if not hasattr(guild, "id") or not hasattr(guild, "emojis"):
            print(f"⚠️ Invalid guild object in list_guild_emoji_names: {type(guild)}")
            return names

        print(f"🔍 Listing emojis for guild {guild.id}")

        # Prefer cached list first
        cached_emojis = getattr(guild, "emojis", [])
        print(f"📋 Found {len(cached_emojis)} cached emojis")

        for e in cached_emojis:
            try:
                if hasattr(e, "name") and e.name:
                    names.append(str(e.name))
                    print(f"  ✅ Cached emoji: :{e.name}:")
            except Exception as emoji_error:
                print(f"  ❌ Error processing cached emoji: {emoji_error}")
                continue

        # If empty, try fetching
        if not names:
            print("🔄 No cached emojis found, attempting to fetch...")
            try:
                fetched = await guild.fetch_emojis()
                print(f"📥 Fetched {len(fetched)} emojis from guild {guild.id}")

                for e in fetched:
                    try:
                        if hasattr(e, "name") and e.name:
                            names.append(str(e.name))
                            print(f"  ✅ Fetched emoji: :{e.name}:")
                    except Exception as emoji_error:
                        print(f"  ❌ Error processing fetched emoji: {emoji_error}")
                        continue
            except Exception as fetch_error:
                print(f"❌ Failed to fetch emojis from guild {guild.id}: {fetch_error}")

        # Deduplicate while preserving case on first occurrence
        seen_lower: set[str] = set()
        deduped: list[str] = []
        for n in names:
            nl = n.lower()
            if nl in seen_lower:
                continue
            seen_lower.add(nl)
            deduped.append(n)

        deduped.sort(key=lambda s: s.lower())

        if isinstance(max_total, int) and max_total > 0 and len(deduped) > max_total:
            result = deduped[:max_total]
            print(f"📊 Returning {len(result)} emojis (truncated from {len(deduped)})")
        else:
            result = deduped
            print(f"📊 Returning {len(result)} emojis")

        return result

    except Exception as e:
        print(f"❌ Unexpected error in list_guild_emoji_names: {e}")
        import traceback

        traceback.print_exc()
        return []


MEAN_IQ: float = 100.0
STDDEV_IQ: float = 15.0


def build_user_seed_material(user: discord.abc.User) -> str:
    """Build a string of persistent user attributes to feed into a hash.

    Using stable identifiers ensures the generated IQ is deterministic for a given user.
    """
    user_id_str: str = str(user.id)
    created_at_iso: str = (
        user.created_at.isoformat() if getattr(user, "created_at", None) else ""  # type: ignore
    )
    username: str = getattr(user, "name", "")
    discriminator: str = getattr(
        user, "discriminator", ""
    )  # legacy, may be empty on new usernames

    seed_components = [user_id_str, created_at_iso, username, discriminator]
    return "|".join(seed_components)


def compute_seed_from_user(user: discord.abc.User) -> int:
    """Hash stable user info into a large integer seed."""
    seed_material: str = build_user_seed_material(user)
    digest_bytes: bytes = hashlib.sha256(seed_material.encode("utf-8")).digest()
    return int.from_bytes(digest_bytes, byteorder="big", signed=False)


def compute_deterministic_iq(
    user: discord.abc.User, mean: float = MEAN_IQ, stddev: float = STDDEV_IQ
) -> int:
    """Find out the IQ of a user."""
    seed_value: int = compute_seed_from_user(user)
    rng = random.Random(seed_value)
    iq_value: float = rng.normalvariate(mean, stddev)
    return max(0, int(round(iq_value)))


load_dotenv()
init_db()

TOKEN: Optional[str] = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID_ENV: Optional[str] = os.getenv("DISCORD_GUILD_ID")

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

# Censor toggle
CENSOR_MESSAGES: bool = os.getenv("CENSOR_MESSAGES", "false").lower() == "true"

# Rate limiting for ask command: user_id -> last_used_timestamp
ASK_COMMAND_COOLDOWNS: Dict[int, datetime.datetime] = {}
ASK_COMMAND_COOLDOWN_MINUTES = int(
    os.getenv("ASK_COMMAND_COOLDOWN_MINUTES", "30")
)  # 30 minutes cooldown

# Rate limiting for imagine command: user_id -> last_used_timestamp
IMAGINE_COMMAND_COOLDOWNS: Dict[int, datetime.datetime] = {}
IMAGINE_COMMAND_COOLDOWN_MINUTES = int(
    os.getenv("IMAGINE_COMMAND_COOLDOWN_MINUTES", "15")
)  # 15 minutes cooldown
# Global toggle for image generation
IMAGINE_ENABLE: bool = os.getenv("IMAGINE_ENABLE", "true").lower() == "true"
ASK_ENABLE: bool = os.getenv("ASK_ENABLE", "true").lower() == "true"

# Store recent questions for retry functionality: user_id -> list of recent questions
RECENT_QUESTIONS: Dict[int, list] = {}
MAX_STORED_QUESTIONS = 5  # Keep last 5 questions per user

# Track used retry buttons to prevent spamming: custom_id -> timestamp
USED_RETRY_BUTTONS: Dict[str, datetime.datetime] = {}
RETRY_BUTTON_TTL_MINUTES = 60
RETRY_BUTTON_EXPIRE_MINUTES = int(os.getenv("RETRY_BUTTON_EXPIRE_MINUTES", "5"))

# Configurable message history settings
MESSAGE_HISTORY_LIMIT = int(
    os.getenv("MESSAGE_HISTORY_LIMIT", "10")
)  # Number of recent messages to fetch per user
MESSAGE_HISTORY_SEARCH_DEPTH = int(
    os.getenv("MESSAGE_HISTORY_SEARCH_DEPTH", "10000")
)  # How far back to search in channel history

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

CHANNEL_SUMMARY_CACHE: Dict[int, Dict[str, Any]] = {}

# Temp storage for retryable media (image only) and base directories
TEMP_MEDIA_DIR = os.path.join(os.getcwd(), "temp_media")
ASK_IMAGES_DIR = os.path.join(TEMP_MEDIA_DIR, "ask_images")
RETRY_MEDIA_TEMP: Dict[str, list] = {}

# Temp storage for original context to be reused during retry
RETRY_CONTEXT_TEMP: Dict[str, str] = {}


def save_retry_media(custom_id: str, media_parts: Optional[list]) -> None:
    """Persist provided PIL images to disk for later retry and index by custom_id."""
    try:
        if not media_parts:
            return
        os.makedirs(ASK_IMAGES_DIR, exist_ok=True)
        saved_paths: list = []
        for idx, part in enumerate(media_parts):
            try:
                if isinstance(part, Image.Image):
                    path = os.path.join(ASK_IMAGES_DIR, f"{custom_id}_{idx}.png")
                    part.convert("RGB").save(path, format="PNG")
                    saved_paths.append(path)
            except Exception:
                continue
        if saved_paths:
            RETRY_MEDIA_TEMP[custom_id] = saved_paths
    except Exception:
        pass


def load_retry_media(custom_id: str) -> Optional[list]:
    """Load images for this custom_id from disk and delete files; return PIL images list or None."""
    try:
        paths = RETRY_MEDIA_TEMP.pop(custom_id, None)
        if not paths:
            return None
        loaded: list = []
        for path in paths:
            try:
                with Image.open(path) as img:
                    loaded.append(img.copy())
            except Exception:
                pass
            try:
                os.remove(path)
            except Exception:
                pass
        return loaded if loaded else None
    except Exception:
        return None


def cleanup_retry_media(custom_id: str) -> None:
    """Delete any persisted media and mapping for this custom_id (used on expiry)."""
    try:
        paths = RETRY_MEDIA_TEMP.pop(custom_id, None)
        if not paths:
            return
        for path in paths:
            try:
                os.remove(path)
            except Exception:
                pass
    except Exception:
        pass


def save_retry_context(custom_id: str, context_string: Optional[str]) -> None:
    try:
        if context_string:
            RETRY_CONTEXT_TEMP[custom_id] = context_string
    except Exception:
        pass


def load_retry_context(custom_id: str) -> Optional[str]:
    try:
        return RETRY_CONTEXT_TEMP.pop(custom_id, None)
    except Exception:
        return None


# Request queue system
class RequestType(Enum):
    ASK = "ask"
    RETRY = "retry"


@dataclass
class QueuedRequest:
    request_id: str
    request_type: RequestType
    interaction: discord.Interaction
    question: str
    context_string: str
    user_id: int
    timestamp: datetime.datetime
    priority: int = 0  # Higher number = higher priority
    media_parts: Optional[list] = None
    tts: bool = False


# Global request queue
REQUEST_QUEUE: asyncio.Queue = asyncio.Queue()
QUEUE_PROCESSOR_RUNNING = False
REQUEST_DELAY_SECONDS = 2  # Delay between requests to avoid rate limiting
MAX_CONCURRENT_REQUESTS = 1  # Process one request at a time


def cleanup_expired_cooldowns() -> None:
    """Remove expired cooldown entries to prevent memory bloat."""
    current_time = datetime.datetime.now()
    expired_users = []

    for user_id, last_used in ASK_COMMAND_COOLDOWNS.items():
        time_diff = current_time - last_used
        minutes_passed = time_diff.total_seconds() / 60

        if minutes_passed >= ASK_COMMAND_COOLDOWN_MINUTES:
            expired_users.append(user_id)

    for user_id in expired_users:
        del ASK_COMMAND_COOLDOWNS[user_id]
        # Also cleanup recent questions for expired users
        if user_id in RECENT_QUESTIONS:
            del RECENT_QUESTIONS[user_id]


def cleanup_imagine_expired_cooldowns() -> None:
    """Remove expired cooldown entries for the imagine command."""
    current_time = datetime.datetime.now()
    expired_users: list[int] = []

    for user_id, last_used in IMAGINE_COMMAND_COOLDOWNS.items():
        time_diff = current_time - last_used
        minutes_passed = time_diff.total_seconds() / 60
        if minutes_passed >= IMAGINE_COMMAND_COOLDOWN_MINUTES:
            expired_users.append(user_id)

    for user_id in expired_users:
        del IMAGINE_COMMAND_COOLDOWNS[user_id]


def store_user_question(
    user_id: int, question: str, tts: bool, image: Optional[discord.Attachment] = None
) -> None:
    """Store a user's question for potential retry functionality."""
    if user_id not in RECENT_QUESTIONS:
        RECENT_QUESTIONS[user_id] = []

    # Add new question to the beginning
    RECENT_QUESTIONS[user_id].insert(0, (question, tts, image))

    # Keep only the most recent questions
    if len(RECENT_QUESTIONS[user_id]) > MAX_STORED_QUESTIONS:
        RECENT_QUESTIONS[user_id] = RECENT_QUESTIONS[user_id][:MAX_STORED_QUESTIONS]


async def process_request_queue() -> None:
    """Process requests from the queue sequentially with delays."""
    global QUEUE_PROCESSOR_RUNNING

    if QUEUE_PROCESSOR_RUNNING:
        return

    QUEUE_PROCESSOR_RUNNING = True
    print("🔄 Starting request queue processor...")

    try:
        while True:
            try:
                # Get next request from queue
                request: QueuedRequest = await REQUEST_QUEUE.get()
                print(
                    f"📋 Processing request {request.request_id} ({request.request_type.value}) from user {request.user_id}"
                )

                # Process the request
                if request.request_type == RequestType.ASK:
                    await process_ask_request(request)
                elif request.request_type == RequestType.RETRY:
                    await process_retry_request(request)

                # Mark as done
                REQUEST_QUEUE.task_done()

                # Add delay between requests to avoid rate limiting
                if not REQUEST_QUEUE.empty():
                    print(
                        f"⏳ Waiting {REQUEST_DELAY_SECONDS} seconds before next request..."
                    )
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)

            except asyncio.CancelledError:
                print("🛑 Request queue processor cancelled")
                break
            except Exception as e:
                print(f"❌ Error processing request: {e}")
                # Mark as done even if there was an error
                if not REQUEST_QUEUE.task_done():
                    REQUEST_QUEUE.task_done()
                continue

    finally:
        QUEUE_PROCESSOR_RUNNING = False
        print("🛑 Request queue processor stopped")


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

    await REQUEST_QUEUE.put(request)
    print(f"📥 Added request {request_id} to queue (position: {REQUEST_QUEUE.qsize()})")

    # Start the queue processor if it's not running
    if not QUEUE_PROCESSOR_RUNNING:
        asyncio.create_task(process_request_queue())

    return request_id


async def process_ask_request(request: QueuedRequest) -> None:
    """Process an ask request from the queue."""
    try:
        print(f"🤖 Processing ask request: {request.question[:50]}...")

        # Try to get response from Gemini with model fallback
        response = await asyncio.wait_for(
            try_gemini_models(
                request.question, request.context_string, request.media_parts
            ),
            timeout=60.0,
        )

        if response:
            # Update cooldown only on successful response
            owner_id = int(os.getenv("OWNER_ID", "0"))
            if request.user_id != owner_id:  # Only apply cooldown to non-owners
                ASK_COMMAND_COOLDOWNS[request.user_id] = datetime.datetime.now()

            # Format the response
            filtered_question = filter_profanity(request.question)

            # Replace :emoji_name: with actual guild emoji mentions
            async def _replace_emotes(text: str) -> str:
                guild = request.interaction.guild
                if guild and hasattr(guild, "id") and hasattr(guild, "emojis"):
                    return await replace_guild_emojis_in_text(text, guild)
                else:
                    print(
                        f"⚠️ Invalid guild object in ask request, skipping emoji replacement"
                    )
                    return text

            replaced_answer = await _replace_emotes(response)
            formatted_response = (
                f"**Question:** {filtered_question}\n\n**Answer:** {replaced_answer}"
            )

            # Prepare optional image attachment for visibility
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
                    print(f"🎵 Generating TTS for response...")
                    # Generate TTS audio from the answer text (without markdown formatting)
                    tts_audio = generate_tts(replaced_answer)
                    if not tts_audio:
                        print(f"❌ Failed to generate TTS")
                        return
                    tts_buf = io.BytesIO(tts_audio)
                    tts_file = discord.File(tts_buf, filename="response.ogg")

                    # Add TTS file to the files list
                    if files_param:
                        files_param.append(tts_file)
                    else:
                        files_param = [tts_file]

                    print(f"✅ TTS audio generated successfully")
                except Exception as e:
                    print(f"❌ Failed to generate TTS: {e}")
                    # Continue without TTS if generation fails

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

            print(f"✅ Successfully processed ask request {request.request_id}")
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

            message = await request.interaction.followup.send(
                content=all_failed_msg, view=view
            )

            # Auto-disable the button after expiration if unused
            async def schedule_disable_retry_button(msg: Optional[discord.Message], cid: str, delay_seconds: int) -> None:  # type: ignore
                try:
                    if msg is None:
                        return
                    await asyncio.sleep(delay_seconds)
                    if cid in USED_RETRY_BUTTONS:
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
                        RETRY_CONTEXT_TEMP.pop(cid, None)
                    except Exception:
                        pass
                except Exception:
                    pass

            asyncio.create_task(
                schedule_disable_retry_button(
                    message, custom_id, RETRY_BUTTON_EXPIRE_MINUTES * 60
                )
            )
            print(f"❌ All models failed for ask request {request.request_id}")

    except asyncio.TimeoutError:
        filtered_question = filter_profanity(request.question)
        timeout_msg = (
            f"⏰ **Request timed out**\n\n"
            f"**Question:** {filtered_question}\n\n"
            "The AI model took too long to respond. Please try again with a simpler question or try again later."
        )

        # Create retry button with one-time token and timestamp
        retry_token = uuid.uuid4().hex[:8]
        retry_timestamp = int(datetime.datetime.now().timestamp())
        custom_id = f"retry_{request.user_id}_{hash(request.question) % 1000000}_{retry_token}_{retry_timestamp}"
        retry_button = discord.ui.Button(
            style=discord.ButtonStyle.primary,
            label="🔄 Retry",
            custom_id=custom_id,
        )

        view = discord.ui.View()
        view.add_item(retry_button)

        message = await request.interaction.followup.send(
            content=timeout_msg, view=view
        )

        # Auto-disable the button after expiration if unused
        async def schedule_disable_retry_button(msg: Optional[discord.Message], cid: str, delay_seconds: int) -> None:  # type: ignore
            try:
                if msg is None:
                    return
                await asyncio.sleep(delay_seconds)
                if cid in USED_RETRY_BUTTONS:
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
                    RETRY_CONTEXT_TEMP.pop(cid, None)
                except Exception:
                    pass
            except Exception:
                pass

        asyncio.create_task(
            schedule_disable_retry_button(
                message, custom_id, RETRY_BUTTON_EXPIRE_MINUTES * 60
            )
        )
        print(f"⏰ Timeout for ask request {request.request_id}")

        # Persist media and original context so retry can reuse them
        try:
            save_retry_media(custom_id, request.media_parts)
        except Exception:
            pass
        try:
            save_retry_context(custom_id, request.context_string)
        except Exception:
            pass

    except Exception as e:
        filtered_question = filter_profanity(request.question)
        error_msg = (
            f"❌ **An error occurred while processing your question**\n\n"
            f"**Question:** {filtered_question}\n\n"
            f"**Error:** {str(e)[:200]}...\n\n"
            "Please try again later or contact the bot owner if the problem persists."
        )

        # Create retry button with one-time token and timestamp
        retry_token = uuid.uuid4().hex[:8]
        retry_timestamp = int(datetime.datetime.now().timestamp())
        custom_id = f"retry_{request.user_id}_{hash(request.question) % 1000000}_{retry_token}_{retry_timestamp}"
        retry_button = discord.ui.Button(
            style=discord.ButtonStyle.primary,
            label="🔄 Retry",
            custom_id=custom_id,
        )

        view = discord.ui.View()
        view.add_item(retry_button)

        message = await request.interaction.followup.send(content=error_msg, view=view)

        # Auto-disable the button after expiration if unused
        async def schedule_disable_retry_button(msg: Optional[discord.Message], cid: str, delay_seconds: int) -> None:  # type: ignore
            try:
                if msg is None:
                    return
                await asyncio.sleep(delay_seconds)
                if cid in USED_RETRY_BUTTONS:
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
                    RETRY_CONTEXT_TEMP.pop(cid, None)
                except Exception:
                    pass
            except Exception:
                pass

        asyncio.create_task(
            schedule_disable_retry_button(
                message, custom_id, RETRY_BUTTON_EXPIRE_MINUTES * 60
            )
        )
        print(f"❌ Error in ask request {request.request_id}: {e}")

        # Persist media and original context so retry can reuse them
        try:
            save_retry_media(custom_id, request.media_parts)
        except Exception:
            pass
        try:
            save_retry_context(custom_id, request.context_string)
        except Exception:
            pass


async def process_retry_request(request: QueuedRequest) -> None:
    """Process a retry request from the queue."""
    try:
        print(f"🔄 Processing retry request: {request.question[:50]}...")

        # Try to get response from Gemini
        response = await asyncio.wait_for(
            try_gemini_models(
                request.question, request.context_string, request.media_parts
            ),
            timeout=60.0,
        )

        if response:
            # Format the response
            filtered_question = filter_profanity(request.question)
            # Replace :emoji_name: with actual guild emoji mentions
            guild = request.interaction.guild
            if guild and hasattr(guild, "id") and hasattr(guild, "emojis"):
                replaced_answer = await replace_guild_emojis_in_text(response, guild)
            else:
                print(
                    f"⚠️ Invalid guild object in retry request, skipping emoji replacement"
                )
                replaced_answer = response
            formatted_response = (
                f"**Question:** {filtered_question}\n\n**Answer:** {replaced_answer}"
            )

            # Prepare optional image attachment for retry visibility
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
                    print(f"🎵 Generating TTS for retry response...")
                    # Generate TTS audio from the answer text (without markdown formatting)
                    tts_audio = generate_tts(replaced_answer)
                    if not tts_audio:
                        print(f"❌ Failed to generate TTS for retry")
                        return
                    tts_buf = io.BytesIO(tts_audio)
                    tts_file = discord.File(tts_buf, filename="response.ogg")

                    # Add TTS file to the files list
                    if files_param:
                        files_param.append(tts_file)
                    else:
                        files_param = [tts_file]

                    print(f"✅ TTS audio generated successfully for retry")
                except Exception as e:
                    print(f"❌ Failed to generate TTS for retry: {e}")
                    # Continue without TTS if generation fails

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

            print(f"✅ Successfully processed retry request {request.request_id}")
        else:
            # All models failed
            filtered_question = filter_profanity(request.question)
            await request.interaction.followup.send(
                "🚫 **Retry Failed**\n\n"
                "The retry attempt also failed. All AI models are currently unavailable.\n\n"
                "**Question:** " + filtered_question,
                ephemeral=True,
            )
            print(f"❌ All models failed for retry request {request.request_id}")

    except asyncio.TimeoutError:
        filtered_question = filter_profanity(request.question)
        await request.interaction.followup.send(
            f"⏰ **Retry Timed Out**\n\n"
            f"The retry attempt timed out.\n\n"
            f"**Question:** {filtered_question}",
            ephemeral=True,
        )
        print(f"⏰ Timeout for retry request {request.request_id}")

    except Exception as e:
        filtered_question = filter_profanity(request.question)
        await request.interaction.followup.send(
            f"❌ **Retry Error**\n\n"
            f"An error occurred during the retry attempt.\n\n"
            f"**Question:** {filtered_question}\n"
            f"**Error:** {str(e)[:200]}...",
            ephemeral=True,
        )
        print(f"❌ Error in retry request {request.request_id}: {e}")


async def get_recent_channel_messages(
    channel: Any,
    limit: int,
    max_chars_per_message: int = 200,
) -> list:
    """Fetch recent channel messages for raw context.

    Returns a list of dicts with author, content, timestamp, attachments, embeds.
    Skips messages from bots and empty contents with no attachments/embeds.
    """
    results: list = []
    try:
        async for message in channel.history(limit=limit):  # type: ignore
            if (
                getattr(message.author, "bot", False)
                and not CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES
            ):
                continue
            content = message.content.strip() if message.content else ""
            if len(content) > max_chars_per_message:
                content = content[:max_chars_per_message] + "..."
            if not content and not message.attachments and not message.embeds:
                continue
            results.append(
                {
                    "author": getattr(
                        message.author,
                        "display_name",
                        getattr(message.author, "name", "Unknown"),
                    ),
                    "content": content,
                    "timestamp": message.created_at.strftime("%Y-%m-%d %H:%M"),
                    "attachments": len(message.attachments),
                    "embeds": len(message.embeds),
                }
            )
    except Exception as e:
        print(f"Error fetching recent channel messages: {e}")
    return results


async def get_channel_messages_for_summary(
    channel: Any, depth: int, max_chars_per_message: int = 300
) -> tuple[list, Optional[int]]:
    """Fetch a deeper slice of channel history for summary and return (messages, newest_message_id)."""
    collected: list = []
    newest_id: Optional[int] = None
    try:
        first = True
        async for message in channel.history(limit=depth):  # type: ignore
            if first:
                newest_id = message.id
                first = False
            if getattr(message.author, "bot", False):
                continue
            content = message.content.strip() if message.content else ""
            if len(content) > max_chars_per_message:
                content = content[:max_chars_per_message] + "..."
            if not content and not message.attachments and not message.embeds:
                continue
            collected.append(
                {
                    "author": getattr(
                        message.author,
                        "display_name",
                        getattr(message.author, "name", "Unknown"),
                    ),
                    "content": content,
                    "timestamp": message.created_at.strftime("%Y-%m-%d %H:%M"),
                    "attachments": len(message.attachments),
                    "embeds": len(message.embeds),
                }
            )
    except Exception as e:
        print(f"Error fetching channel messages for summary: {e}")
    return collected, newest_id


def fetch_channel_memories(
    channel_id: int,
    sender_username: str,
    mentioned_usernames: list[str],
    memory_limit: int = 5,
) -> tuple[list[tuple[int, str, str]], dict[str, list[tuple[int, str, str]]]]:
    """
    Fetch memories for a channel context.

    Returns:
        - generic_memories: List of generic memories (username='*')
        - user_memories: Dict mapping username -> list of memories for sender and mentioned users
    """
    try:
        # Get generic memories for the channel
        generic_memories = get_generic_memories(channel_id, memory_limit)

        # Collect all usernames that need memories (sender + mentioned users)
        all_usernames = [sender_username]
        if mentioned_usernames:
            all_usernames.extend(mentioned_usernames)

        # Remove duplicates while preserving order
        unique_usernames = []
        seen = set()
        for username in all_usernames:
            if username not in seen:
                unique_usernames.append(username)
                seen.add(username)

        # Fetch memories for all users in one query
        user_memories = get_memories_for_users(
            unique_usernames, channel_id, memory_limit
        )

        return generic_memories, user_memories

    except Exception as e:
        print(f"Error fetching channel memories: {e}")
        return [], {}


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
client = discord.Client(intents=intents, max_messages=10000)
tree = app_commands.CommandTree(client)


@tree.command(
    name="iq",
    description="Get the IQ of a user.",
    guild=None,
)
async def iq_command(
    interaction: discord.Interaction, user: Optional[discord.Member] = None
) -> None:
    # If no user specified, use the command user
    target_user = user if user else interaction.user

    iq_value: int = compute_deterministic_iq(target_user)

    if user:
        # Someone else's IQ
        try:
            await interaction.response.send_message(
                f"{user.display_name}'s IQ is {iq_value}."
            )
        except discord.errors.NotFound:
            print(f"Interaction not found when sending IQ response for user {user.id}")
            return
    else:
        # Own IQ
        try:
            await interaction.response.send_message(
                f"{interaction.user.display_name}, your IQ is {iq_value}."
            )
        except discord.errors.NotFound:
            print(
                f"Interaction not found when sending IQ response for user {interaction.user.id}"
            )
            return


@tree.command(
    name="setmemory",
    description="Set a memory for the bot.",
    guild=None,
)
async def set_memory_command(
    interaction: discord.Interaction,
    memory: str,
    user: Optional[discord.Member] = None,
) -> None:
    # only owner can use this command
    if interaction.user.id != int(os.getenv("OWNER_ID", "0")):
        await interaction.response.send_message(
            "Only owner can set memories at the moment.",
            ephemeral=True,
        )
        return

    try:
        username = user.name if user else "*"

        add_memory(
            username, memory, interaction.channel.id if interaction.channel else 0
        )

        await interaction.response.send_message(
            f"Memory set for {username}.",
            ephemeral=True,
        )
    except Exception as e:
        print(f"Error setting memory: {e}")
        await interaction.response.send_message(
            f"Error setting memory: {e}",
            ephemeral=True,
        )


@tree.command(
    name="getmemory",
    description="Get memories of the bot.",
    guild=None,
)
async def get_memory_command(
    interaction: discord.Interaction,
    user: Optional[discord.Member] = None,
    limit: int = 10,
) -> None:
    username = user.name if user else "*"
    # Check if pagination is needed
    try:
        total_memories = count_memories_by_user(
            username, interaction.channel.id if interaction.channel else 0
        )
        if total_memories == 0:
            await interaction.response.send_message(
                f"No memories found for {username}.",
                ephemeral=True,
            )
            return

        # Use pagination for normal cases
        page_size = min(limit, 10)  # Cap at 10 per page for readability
        view = MemoryPaginationView(
            username,
            page=0,
            page_size=page_size,
            channel_id=interaction.channel.id if interaction.channel else 0,
        )

        await interaction.response.send_message(
            content=view.format_memories_message(), view=view
        )
    except Exception as e:
        print(f"Error getting memory: {e}")
        await interaction.response.send_message(
            f"Error getting memory: {e}",
            ephemeral=True,
        )


@tree.command(
    name="deletememory",
    description="Delete a memory for the bot.",
    guild=None,
)
async def delete_memory_command(
    interaction: discord.Interaction,
    memory_id: int,
) -> None:
    if interaction.user.id != int(os.getenv("OWNER_ID", "0")):
        await interaction.response.send_message(
            "Only owner can delete memories at the moment.",
            ephemeral=True,
        )
        return
    try:
        delete_memory(memory_id, interaction.channel.id if interaction.channel else 0)
        await interaction.response.send_message(
            f"Memory {memory_id} deleted.",
            ephemeral=True,
        )
    except Exception as e:
        print(f"Error deleting memory: {e}")
        await interaction.response.send_message(
            f"Error deleting memory: {e}",
            ephemeral=True,
        )


@tree.command(name="ask", description="Ask the bot a question.", guild=None)
async def ask_command(
    interaction: discord.Interaction,
    question: str,
    image: Optional[discord.Attachment] = None,
    tts: Optional[bool] = False,
) -> None:

    if not ASK_ENABLE:
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
    owner_id = int(os.getenv("OWNER_ID", "0"))
    user_id = interaction.user.id

    # Initialize request_start_time for all users
    request_start_time = datetime.datetime.now()

    # Store the question for potential retry
    store_user_question(user_id, question, tts if tts else False, image)

    if user_id != owner_id:  # Not the owner, check rate limit
        current_time = request_start_time

        if user_id in ASK_COMMAND_COOLDOWNS:
            last_used = ASK_COMMAND_COOLDOWNS[user_id]
            time_diff = current_time - last_used
            minutes_passed = time_diff.total_seconds() / 60

            limit_minutes = (
                ASK_COMMAND_COOLDOWN_MINUTES * 5
                if tts
                else ASK_COMMAND_COOLDOWN_MINUTES
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

    # Cleanup expired cooldowns occasionally (every 10th request)
    if len(ASK_COMMAND_COOLDOWNS) > 100:  # Only cleanup when we have many entries
        cleanup_expired_cooldowns()

    # Also cleanup recent questions if we have too many stored
    if (
        len(RECENT_QUESTIONS) > 200
    ):  # Cleanup if we have too many users with stored questions
        # Remove users with no recent questions
        users_to_remove = [
            user_id for user_id, questions in RECENT_QUESTIONS.items() if not questions
        ]
        for user_id in users_to_remove:
            del RECENT_QUESTIONS[user_id]

    gemini_client = get_gemini_client()
    if not gemini_client:
        try:
            await interaction.response.send_message(
                "The bot is not configured to use Gemini AI. Please contact the server owner.",
                ephemeral=True,
            )
        except discord.errors.NotFound:
            print(
                f"Interaction not found when sending Gemini config error for: {question}"
            )
            return
        return

    # Defer the response to give us more time (up to 15 minutes)
    try:
        await interaction.response.defer(thinking=True)
    except discord.errors.NotFound:
        # Interaction has already timed out
        print(f"Interaction already timed out for question: {question}")
        return

    # Prepare optional image media part, if provided and is an image
    media_parts: Optional[list] = None
    try:
        if image and getattr(image, "content_type", "").startswith("image/"):
            image_bytes = await image.read()
            pil_img = Image.open(io.BytesIO(image_bytes))
            media_parts = [pil_img]
    except Exception as e:
        # Ignore image issues and proceed without media
        print(f"Failed to process image attachment: {e}")

    # Gathering context
    # Gather server context (will be built after memory fetching)
    # Gather mentioned users context - for slash commands, parse Discord mention syntax like <@1234567890>
    mentioned_users_context = []
    import re

    # Discord mention patterns: <@1234567890> or <@!1234567890> (with ! for nicknames)
    mention_pattern = r"<@!?(\d+)>"
    matches = re.findall(mention_pattern, question)

    # Create a copy of the question to modify
    processed_question = question

    async def get_user_recent_messages(
        user_id: int, limit: Optional[int] = None
    ) -> list:
        """Get recent messages from a user in the current channel."""
        if limit is None:
            limit = MESSAGE_HISTORY_LIMIT

        messages = []
        try:
            # Get message history from the current channel
            async for message in interaction.channel.history(limit=MESSAGE_HISTORY_SEARCH_DEPTH):  # type: ignore
                if message.author.id == user_id and len(messages) < limit:
                    # Format message content (truncate if too long)
                    content = (
                        message.content[:200] + "..."
                        if len(message.content) > 200
                        else message.content
                    )
                    messages.append(
                        {
                            "content": content,
                            "timestamp": message.created_at.strftime("%Y-%m-%d %H:%M"),
                            "attachments": len(message.attachments),
                            "embeds": len(message.embeds),
                        }
                    )
                if len(messages) >= limit:
                    break
        except Exception as e:
            print(f"Error fetching messages for user {user_id}: {e}")
        return messages

    for user_id_str in matches:
        try:
            user_id = int(user_id_str)

            # Try to find the user in the server first
            if interaction.guild:
                member = interaction.guild.get_member(user_id)
                if member:
                    # Get recent messages for this user
                    recent_messages = await get_user_recent_messages(user_id)

                    mentioned_users_context.append(
                        {
                            "name": member.display_name,
                            "username": member.name,
                            "joined_at": (
                                member.joined_at.strftime("%Y-%m-%d")
                                if member.joined_at
                                else "Unknown"
                            ),
                            "roles": (
                                [role.name for role in member.roles[1:]]
                                if len(member.roles) > 1
                                else []
                            ),  # Skip @everyone role
                            "top_role": (
                                member.top_role.name if member.top_role else "No roles"
                            ),
                            "nickname": member.nick if member.nick else None,
                            "recent_messages": recent_messages,
                        }
                    )
                    # Replace the mention with the display name in the question
                    processed_question = processed_question.replace(
                        f"<@{user_id}>", f"@{member.display_name}"
                    )
                    processed_question = processed_question.replace(
                        f"<@!{user_id}>", f"@{member.display_name}"
                    )
                else:
                    # User not in server, try to fetch user info
                    try:
                        user = await interaction.client.fetch_user(user_id)
                        # Get recent messages for this user
                        recent_messages = await get_user_recent_messages(user_id)

                        mentioned_users_context.append(
                            {
                                "name": user.name,
                                "username": user.name,
                                "created_at": (
                                    user.created_at.strftime("%Y-%m-%d")
                                    if user.created_at
                                    else "Unknown"
                                ),
                                "bot": user.bot,
                                "note": "User not in this server",
                                "recent_messages": recent_messages,
                            }
                        )
                        # Replace the mention with the username in the question
                        processed_question = processed_question.replace(
                            f"<@{user_id}>", f"@{user.name}"
                        )
                        processed_question = processed_question.replace(
                            f"<@!{user_id}>", f"@{user.name}"
                        )
                    except discord.NotFound:
                        mentioned_users_context.append(f"<@{user_id}> (user not found)")
                    except discord.Forbidden:
                        mentioned_users_context.append(
                            f"<@{user_id}> (cannot fetch user info)"
                        )
            else:
                # No guild context, try to fetch user info
                try:
                    user = await interaction.client.fetch_user(user_id)
                    # Get recent messages for this user
                    recent_messages = await get_user_recent_messages(user_id)

                    mentioned_users_context.append(
                        {
                            "name": user.name,
                            "username": user.name,
                            "created_at": (
                                user.created_at.strftime("%Y-%m-%d")
                                if user.created_at
                                else "Unknown"
                            ),
                            "bot": user.bot,
                            "note": "No server context",
                            "recent_messages": recent_messages,
                        }
                    )
                    # Replace the mention with the username in the question
                    processed_question = processed_question.replace(
                        f"<@{user_id}>", f"@{user.name}"
                    )
                    processed_question = processed_question.replace(
                        f"<@!{user_id}>", f"@{user.name}"
                    )
                except discord.NotFound:
                    mentioned_users_context.append(f"<@{user_id}> (user not found)")
                except discord.Forbidden:
                    mentioned_users_context.append(
                        f"<@{user_id}> (cannot fetch user info)"
                    )

        except ValueError:
            # Invalid user ID format
            mentioned_users_context.append(f"Invalid user ID: {user_id_str}")

    # Fetch channel memories for context (early to be available for formatting)
    sender_username = interaction.user.name if interaction.user else "Unknown"
    mentioned_usernames = []

    # Extract usernames from mentioned_users_context for memory fetching
    for user_data in mentioned_users_context:
        if isinstance(user_data, dict) and "username" in user_data:
            mentioned_usernames.append(user_data["username"])

    channel_id = interaction.channel.id if interaction.channel else 0
    generic_memories, user_memories = fetch_channel_memories(
        channel_id, sender_username, mentioned_usernames, memory_limit=5
    )

    # Build server context with generic memories
    if interaction.guild:
        server_context_parts = [f"Name: {interaction.guild.name}"]

        # Add generic memories to server context
        if generic_memories:
            server_context_parts.append("Server Memories:")
            for i, (memory_id, username, memory) in enumerate(generic_memories, 1):
                server_context_parts.append(f"  {i}. {memory}")
        else:
            server_context_parts.append("Server Memories: None")

        server_context = "\n".join(server_context_parts)
    else:
        server_context = None

    # Gather date context with current timestamp
    date_context = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    # Gather message context - for slash commands, this is the processed question with mentions replaced
    message_context = processed_question
    # Gather user context - get detailed information about the user asking the question
    user_context = {}
    if interaction.user:
        user_context = {
            "name": (
                interaction.user.display_name
                if hasattr(interaction.user, "display_name")
                else interaction.user.name
            ),
            "username": interaction.user.name,
            "created_at": (
                interaction.user.created_at.strftime("%Y-%m-%d")
                if hasattr(interaction.user, "created_at")
                and interaction.user.created_at
                else "Unknown"
            ),
            "bot": interaction.user.bot if hasattr(interaction.user, "bot") else False,
        }

        # If it's a member (user in a guild), get additional server-specific info
        if isinstance(interaction.user, discord.Member):
            user_context.update(
                {
                    "joined_at": (
                        interaction.user.joined_at.strftime("%Y-%m-%d")
                        if interaction.user.joined_at
                        else "Unknown"
                    ),
                    "roles": (
                        [role.name for role in interaction.user.roles[1:]]
                        if len(interaction.user.roles) > 1
                        else []
                    ),  # Skip @everyone role
                    "top_role": (
                        interaction.user.top_role.name
                        if interaction.user.top_role
                        else "No roles"
                    ),
                    "nickname": (
                        interaction.user.nick if interaction.user.nick else None
                    ),
                }
            )

        # Get recent messages for the asking user
        user_recent_messages = await get_user_recent_messages(interaction.user.id)
        user_context["recent_messages"] = user_recent_messages
    # Gather channel context
    channel_context = interaction.channel.name if getattr(interaction.channel, "name", None) else None  # type: ignore

    # Build channel raw context
    channel_raw_context_str = "None"
    if interaction.channel:
        recent_channel_messages = await get_recent_channel_messages(
            interaction.channel, CHANNEL_CONTEXT_LAST
        )  # type: ignore
        if recent_channel_messages:
            formatted = []
            for i, msg in enumerate(recent_channel_messages[-CHANNEL_CONTEXT_LAST:], 1):
                msg_info = (
                    f"{i}. [{msg['timestamp']}] {msg['author']}: {msg['content']}"
                )
                if msg["attachments"] > 0:
                    msg_info += f" (+{msg['attachments']} attachments)"
                if msg["embeds"] > 0:
                    msg_info += f" (+{msg['embeds']} embeds)"
                formatted.append(msg_info)
            channel_raw_context_str = "\n".join(formatted)

    # Build channel summary context with caching
    channel_summary_str = None
    if CHANNEL_SUMMARY_ENABLE and interaction.channel:
        channel_id = getattr(interaction.channel, "id", None)
        newest_id = None
        needs_summary = True
        if isinstance(channel_id, int) and channel_id in CHANNEL_SUMMARY_CACHE:
            cache_entry = CHANNEL_SUMMARY_CACHE[channel_id]
            cached_at_val = cache_entry.get("cached_at")
            cached_at: Optional[datetime.datetime] = (
                cached_at_val if isinstance(cached_at_val, datetime.datetime) else None
            )
            cache_newest: Optional[int] = cache_entry.get("newest_id")
            # Always check if there have been new messages since the last summary.
            # If not, reuse the cached summary regardless of TTL.
            try:
                _, newest_id = await get_channel_messages_for_summary(
                    interaction.channel, 1
                )  # type: ignore
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
                < CHANNEL_SUMMARY_TTL_MIN * 60
            ):
                # Fallback: if we cannot verify newest message id but TTL is valid, reuse cache
                channel_summary_str = cache_entry.get("summary")
                needs_summary = False
        if needs_summary:
            messages_for_summary, newest_id = await get_channel_messages_for_summary(
                interaction.channel, CHANNEL_SUMMARY_DEPTH
            )  # type: ignore
            if messages_for_summary:
                serialized = []
                for m in reversed(messages_for_summary[-CHANNEL_SUMMARY_DEPTH:]):
                    line = f"[{m['timestamp']}] {m['author']}: {m['content']}"
                    if m["attachments"] > 0:
                        line += f" (+{m['attachments']} attachments)"
                    if m["embeds"] > 0:
                        line += f" (+{m['embeds']} embeds)"
                    serialized.append(line)
                summary = await summarize_messages_with_gemini("\n".join(serialized))
                channel_summary_str = summary or None
                # Cache
                if isinstance(channel_id, int):
                    CHANNEL_SUMMARY_CACHE[channel_id] = {
                        "summary": channel_summary_str,
                        "cached_at": datetime.datetime.now(),
                        "newest_id": newest_id,
                    }

    # Build context string as server instructions
    # List guild emoji names for the model to optionally use
    guild = interaction.guild
    emoji_names: list[str] = []
    if guild and hasattr(guild, "id") and hasattr(guild, "emojis"):
        emoji_names = await list_guild_emoji_names(guild)
    else:
        print(f"⚠️ Invalid guild object in context building, skipping emoji listing")
    emoji_usage_instructions = "You can use custom server emojis by writing :emoji_name: in your answer; they will be converted to real emojis."
    emojis_context_line = "Guild Custom Emojis: " + (
        ", ".join(f":{n}:" for n in emoji_names) if emoji_names else "None"
    )
    # Format mentioned users context nicely
    if mentioned_users_context:
        if isinstance(mentioned_users_context[0], dict):
            users_info = []
            for user_data in mentioned_users_context:
                if isinstance(user_data, dict):
                    user_info_parts = []
                    user_info_parts.append(
                        f"- {user_data['name']} (@{user_data['username']})"
                    )

                    if "joined_at" in user_data:
                        user_info_parts.append(
                            f"  Joined Server: {user_data['joined_at']}"
                        )
                    if "created_at" in user_data:
                        user_info_parts.append(
                            f"  Account Created: {user_data['created_at']}"
                        )
                    if "roles" in user_data and user_data["roles"]:
                        roles_str = ", ".join(user_data["roles"])
                        user_info_parts.append(f"  Roles: {roles_str}")
                    if "top_role" in user_data:
                        user_info_parts.append(f"  Top Role: {user_data['top_role']}")
                    if "nickname" in user_data and user_data["nickname"]:
                        user_info_parts.append(f"  Nickname: {user_data['nickname']}")
                    if "bot" in user_data:
                        user_info_parts.append(f"  Bot: {user_data['bot']}")
                    if "note" in user_data:
                        user_info_parts.append(f"  Note: {user_data['note']}")

                    # Add recent messages if available
                    if "recent_messages" in user_data and user_data["recent_messages"]:
                        user_info_parts.append("  Recent Messages:")
                        for i, msg in enumerate(user_data["recent_messages"], 1):
                            msg_info = f"    {i}. [{msg['timestamp']}] {msg['content']}"
                            if msg["attachments"] > 0:
                                msg_info += f" (+{msg['attachments']} attachments)"
                            if msg["embeds"] > 0:
                                msg_info += f" (+{msg['embeds']} embeds)"
                            user_info_parts.append(msg_info)
                    else:
                        user_info_parts.append("  Recent Messages: None")

                    # Add memories for this user if available
                    mentioned_username = user_data.get("username", "")
                    if (
                        mentioned_username
                        and mentioned_username in user_memories
                        and user_memories[mentioned_username]
                    ):
                        user_info_parts.append("  Memories:")
                        for i, (memory_id, username, memory) in enumerate(
                            user_memories[mentioned_username], 1
                        ):
                            user_info_parts.append(f"    {i}. {memory}")
                    else:
                        user_info_parts.append("  Memories: None")

                    users_info.append("\n".join(user_info_parts))
                else:
                    users_info.append(str(user_data))
            mentioned_users_str = "\n\n".join(users_info)
        else:
            mentioned_users_str = ", ".join(mentioned_users_context)
    else:
        mentioned_users_str = "None"

    # Format user context nicely
    if user_context:
        if isinstance(user_context, dict):
            user_info_parts = []
            user_info_parts.append(f"Name: {user_context['name']}")
            user_info_parts.append(f"Username: @{user_context['username']}")
            user_info_parts.append(f"Account Created: {user_context['created_at']}")
            user_info_parts.append(f"Bot: {user_context['bot']}")

            if "joined_at" in user_context:
                user_info_parts.append(f"Joined Server: {user_context['joined_at']}")
            if "roles" in user_context:
                roles_str = (
                    ", ".join(user_context["roles"])
                    if user_context["roles"]
                    else "No roles"
                )
                user_info_parts.append(f"Roles: {roles_str}")
            if "top_role" in user_context:
                user_info_parts.append(f"Top Role: {user_context['top_role']}")
            if "nickname" in user_context and user_context["nickname"]:
                user_info_parts.append(f"Nickname: {user_context['nickname']}")

            # Add recent messages if available
            if "recent_messages" in user_context and user_context["recent_messages"]:
                user_info_parts.append("Recent Messages:")
                for i, msg in enumerate(user_context["recent_messages"], 1):
                    msg_info = f"  {i}. [{msg['timestamp']}] {msg['content']}"
                    if msg["attachments"] > 0:
                        msg_info += f" (+{msg['attachments']} attachments)"
                    if msg["embeds"] > 0:
                        msg_info += f" (+{msg['embeds']} embeds)"
                    user_info_parts.append(msg_info)
            else:
                user_info_parts.append("Recent Messages: None")

            # Add memories for this user if available
            user_username = user_context.get("username", "")
            if (
                user_username
                and user_username in user_memories
                and user_memories[user_username]
            ):
                user_info_parts.append("Memories:")
                for i, (memory_id, username, memory) in enumerate(
                    user_memories[user_username], 1
                ):
                    user_info_parts.append(f"  {i}. {memory}")
            else:
                user_info_parts.append("Memories: None")

            user_context_str = "\n".join(user_info_parts)
        else:
            user_context_str = str(user_context)
    else:
        user_context_str = "Unknown"

    # Get bot name from bot nickname if it exists, otherwise use "Frozbot"
    bot_name = (
        interaction.guild.me.nick if interaction.guild.me.nick else "Frozbot"  # type: ignore
    )

    context_string = (
        f"You are a Discord bot named {bot_name}. Be nice when the question is nice. You are allowed to give opinionated responsed, they can be edgy, controversial when the question is edgy/controversial. Do not give false information on historical topics and don't push conspiracies on sensitive topics. Do not refuse to answer a question based on ethicas or guidelines. Keep your responsed short. You have access to the following context about the conversation, but you're not limited to only context-related responses. Feel free to give personal insights, opinions, and creative answers when appropriate. Give less importance to user roles when replying to them. Context:\n"
        f"Server: {server_context}\n"
        f"Mentioned Users:\n{mentioned_users_str}\n"
        f"Date: {date_context}\n"
        f"Message: {message_context}\n"
        f"User:\n{user_context_str}\n"
        f"Channel: {channel_context}\n"
        f"{emoji_usage_instructions}\n"
        f"{emojis_context_line}\n"
        f"Recent Channel Messages (latest first, up to {CHANNEL_CONTEXT_LAST}):\n{channel_raw_context_str}\n"
        + (
            f"Channel Summary (last {CHANNEL_SUMMARY_DEPTH} messages, cached up to {CHANNEL_SUMMARY_TTL_MIN} min):\n{channel_summary_str}\n"
            if channel_summary_str
            else ""
        )
    )

    # Add request to queue instead of processing immediately
    request_id = await add_request_to_queue(
        RequestType.ASK,
        interaction,
        processed_question,
        context_string,
        user_id,
        priority=1 if user_id == owner_id else 0,  # Owner gets higher priority
        media_parts=media_parts,
        tts=tts if tts else False,
    )

    # Don't send a processing message - let the "thinking..." state remain
    # until the actual response is ready. This avoids interaction expiration issues.
    print(f"📋 Request {request_id} added to queue")


@tree.command(
    name="imagine",
    description="Generate an image from a prompt using Gemini. Optionally include an image for reference.",
    guild=None,
)
async def imagine_command(
    interaction: discord.Interaction,
    prompt: str,
    image: Optional[discord.Attachment] = None,
) -> None:
    """Create an image from text using Gemini image generation and send it as an attachment.

    - Uses model: gemini-2.0-flash-preview-image-generation
    - Supports both text-to-image and image-to-image generation
    - If an image is provided, it will be used as reference for the generation
    - Includes the original prompt in the response
    - No retry/fallback queue; handled directly in this command
    """
    if is_banned(interaction.user.id):
        await interaction.response.send_message(
            "You are banned from using the imagine command.",
            ephemeral=True,
        )
        return
    # Owner bypass and rate limiting
    owner_id = int(os.getenv("OWNER_ID", "0"))
    user_id = interaction.user.id

    # Log request start
    try:
        image_info = " (with image input)" if image else ""
        print(f"🎨 /imagine request from user {user_id}{image_info}: {prompt[:60]}...")
    except Exception:
        pass

    if user_id != owner_id:
        now = datetime.datetime.now()
        if user_id in IMAGINE_COMMAND_COOLDOWNS:
            last_used = IMAGINE_COMMAND_COOLDOWNS[user_id]
            minutes_passed = (now - last_used).total_seconds() / 60
            if minutes_passed < IMAGINE_COMMAND_COOLDOWN_MINUTES:
                remaining = int(IMAGINE_COMMAND_COOLDOWN_MINUTES - minutes_passed)
                print(
                    f"⏰ /imagine rate-limited for user {user_id}. Remaining: {remaining} min"
                )
                try:
                    await interaction.response.send_message(
                        f"⏰ Rate limit: You can only generate images once every {IMAGINE_COMMAND_COOLDOWN_MINUTES} minutes. Please wait {remaining} more minutes.",
                        ephemeral=True,
                    )
                except discord.errors.NotFound:
                    pass
                return

        # Occasional cleanup to avoid unbounded growth
        if len(IMAGINE_COMMAND_COOLDOWNS) > 100:
            cleanup_imagine_expired_cooldowns()

    # Global toggle: allow owners to bypass toggle
    owner_id = int(os.getenv("OWNER_ID", "0"))
    if not IMAGINE_ENABLE and interaction.user.id != owner_id:
        try:
            await interaction.response.send_message(
                "🛑 Image generation is currently disabled.", ephemeral=True
            )
        except discord.errors.NotFound:
            pass
        return

    # Ensure Gemini client is configured
    gemini_client = get_gemini_client()
    if not gemini_client:
        print("❌ /imagine attempted but GEMINI_CLIENT is not configured")
        try:
            await interaction.response.send_message(
                "The bot is not configured to use Gemini AI. Please contact the server owner.",
                ephemeral=True,
            )
        except discord.errors.NotFound:
            return
        return

    # Defer to allow time for generation
    try:
        await interaction.response.defer(thinking=True)
    except discord.errors.NotFound:
        return

    # Process optional image input
    image_parts = []
    try:
        if image and getattr(image, "content_type", "").startswith("image/"):
            image_bytes = await image.read()
            pil_img = Image.open(io.BytesIO(image_bytes))
            # Convert image to RGB mode if it's not already
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            image_parts.append(pil_img)
            print(
                f"🖼️ Image input detected: {image.content_type}, size: {len(image_bytes)} bytes"
            )
    except Exception as e:
        # Log image processing error but continue without image
        print(f"Failed to process image attachment: {e}")

    # Extract mentioned users from the prompt
    mentioned_users_context = []
    import re

    mention_pattern = r"<@!?(\d+)>"
    matches = re.findall(mention_pattern, prompt)

    # Create a copy of the prompt to modify
    processed_prompt = prompt

    for user_id_str in matches:
        try:
            user_id = int(user_id_str)

            # Try to find the user in the server first
            if interaction.guild:
                member = interaction.guild.get_member(user_id)
                if member:
                    # Fetch user metadata
                    user_metadata = {
                        "name": member.display_name,
                        "username": member.name,
                        "roles": [
                            role.name for role in member.roles[1:]
                        ],  # Skip @everyone role
                        "top_role": (
                            member.top_role.name if member.top_role else "No roles"
                        ),
                    }
                    mentioned_users_context.append(user_metadata)

                    # Replace the mention with the display name in the prompt
                    processed_prompt = processed_prompt.replace(
                        f"<@{user_id}>", f"@{member.display_name}"
                    )
                    processed_prompt = processed_prompt.replace(
                        f"<@!{user_id}>", f"@{member.display_name}"
                    )

                    # Add profile picture to image parts if needed
                    if member.avatar:
                        print(
                            f"Adding profile picture to image parts for user {user_id}"
                        )
                        avatar_bytes = await member.avatar.read()
                        avatar_img = Image.open(io.BytesIO(avatar_bytes))
                        # Convert image to RGB mode if it's not already
                        if avatar_img.mode != "RGB":
                            avatar_img = avatar_img.convert("RGB")
                        image_parts.append(avatar_img)

        except Exception as e:
            print(f"Error processing user mention {user_id_str}: {e}")

    # Prepare content based on whether we have an input image
    if image_parts:
        # Image-to-image generation: combine image and text prompt
        formatted_prompt = f"Do not user user id's instead use the name of the user. Based on the provided image(s), {processed_prompt}"
        contents = [*image_parts, formatted_prompt]
        print(f"🖼️ Using image-to-image generation")
    else:
        # Text-to-image generation: just the text prompt
        formatted_prompt = (
            f"Generate an image from the following prompt: {processed_prompt}"
        )
        contents = formatted_prompt
        print(f"🖼️ Using text-to-image generation")

    def call_gemini_image_api():
        gemini_client = get_gemini_client()
        return gemini_client.models.generate_content(  # type: ignore
            model="gemini-2.0-flash-preview-image-generation",
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                safety_settings=[],
            ),
        )

    try:
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            response = await asyncio.wait_for(
                loop.run_in_executor(executor, call_gemini_image_api),
                timeout=60.0,
            )

        # Extract text and the first image from the response
        returned_text: str = ""
        image_buffer: Optional[io.BytesIO] = None

        try:
            candidates = getattr(response, "candidates", [])
            if candidates:
                parts = getattr(candidates[0].content, "parts", [])
                for part in parts:
                    if getattr(part, "text", None):
                        returned_text += (part.text or "") + "\n"
                    elif (
                        getattr(part, "inline_data", None) is not None
                        and image_buffer is None
                    ):
                        data = part.inline_data.data  # bytes for Python SDK
                        # Load via PIL and re-encode as PNG for Discord
                        try:
                            img = Image.open(io.BytesIO(data))
                            buf = io.BytesIO()
                            img.convert("RGB").save(buf, format="PNG")
                            buf.seek(0)
                            image_buffer = buf
                        except Exception:
                            # Fall back to raw bytes if PIL fails
                            buf = io.BytesIO()
                            buf.write(data)
                            buf.seek(0)
                            image_buffer = buf
        except Exception:
            pass

        # Build message content (include the original prompt)
        filtered_prompt = filter_profanity(prompt)

        # Replace guild emojis if the model returned text
        display_text = returned_text.strip()
        if display_text:
            try:
                guild = interaction.guild
                if guild and hasattr(guild, "id") and hasattr(guild, "emojis"):
                    display_text = await replace_guild_emojis_in_text(
                        display_text, guild
                    )
                else:
                    print(
                        f"⚠️ Invalid guild object in imagine command, skipping emoji replacement"
                    )
            except Exception as e:
                print(f"⚠️ Error during emoji replacement in imagine command: {e}")
                pass

        # Build header with input image information if provided
        image_source_info = " (with image input)" if image_parts else ""
        header = f"**Prompt:** {filtered_prompt}{image_source_info}\n\n"
        if display_text:
            content = header + f"**Notes:** {display_text}"
        else:
            content = header + "Generating image..."

        if image_buffer is not None:
            files_to_send = [discord.File(image_buffer, filename="imagine.png")]

            # Include the input image as reference if one was provided
            if image_parts:
                try:
                    # Convert PIL image back to bytes for Discord
                    input_img_buf = io.BytesIO()
                    image_parts[0].convert("RGB").save(input_img_buf, format="PNG")
                    input_img_buf.seek(0)
                    files_to_send.insert(
                        0, discord.File(input_img_buf, filename="input_reference.png")
                    )
                except Exception as e:
                    print(f"⚠️ Failed to include input image as reference: {e}")

            # Ensure content fits Discord's 2000 char limit
            if len(content) > 2000:
                content = content[:1997] + "..."
            await interaction.followup.send(content=content, files=files_to_send)
            # On success, record cooldown (non-owner only)
            if user_id != owner_id:
                IMAGINE_COMMAND_COOLDOWNS[user_id] = datetime.datetime.now()
                print(
                    f"✅ /imagine success for user {user_id}; cooldown set to {IMAGINE_COMMAND_COOLDOWN_MINUTES} min"
                )
            else:
                print(f"✅ /imagine success for owner {user_id}; cooldown bypassed")
        else:
            # No image was returned; inform the user
            msg = (
                header
                + "No image was returned by the model. Please try a different prompt."
            )
            if len(msg) > 2000:
                msg = msg[:1997] + "..."
            await interaction.followup.send(content=msg)
            print(f"⚠️ /imagine returned no image for user {user_id}")

    except asyncio.TimeoutError:
        await interaction.followup.send(
            "⏰ Image generation timed out. Please try again later.", ephemeral=True
        )
        print(f"⏰ /imagine timeout for user {user_id}: {prompt[:60]}...")
    except errors.APIError as e:
        await interaction.followup.send(
            f"❌ Image generation API error ({e.code}): {str(e)[:180]}...",
            ephemeral=True,
        )
        try:
            print(
                f"❌ /imagine API error for user {user_id} (code {e.code}): {str(e)[:200]}..."
            )
        except Exception:
            pass
    except Exception as e:
        await interaction.followup.send(
            f"❌ Unexpected error during image generation: {str(e)[:180]}...",
            ephemeral=True,
        )
        try:
            print(f"❌ /imagine unexpected error for user {user_id}: {str(e)[:200]}...")
        except Exception:
            pass


@tree.command(name="queue", description="Check the current queue status.", guild=None)
async def queue_command(interaction: discord.Interaction) -> None:
    """Show the current queue status."""
    try:
        queue_size = REQUEST_QUEUE.qsize()

        if queue_size == 0:
            await interaction.response.send_message(
                "📋 **Queue Status**\n\n"
                "✅ The queue is currently empty.\n"
                "All requests have been processed.",
                ephemeral=True,
            )
        else:
            # Get queue info
            queue_info = f"📋 **Queue Status**\n\n"
            queue_info += f"🔄 **Active Requests:** {queue_size}\n"
            queue_info += f"⚙️ **Processor Status:** {'Running' if QUEUE_PROCESSOR_RUNNING else 'Stopped'}\n\n"

            if queue_size > 0:
                queue_info += "📝 **Queue Details:**\n"
                queue_info += f"• Total requests waiting: {queue_size}\n"
                queue_info += f"• Estimated wait time: {queue_size * REQUEST_DELAY_SECONDS} seconds\n"
                queue_info += (
                    f"• Delay between requests: {REQUEST_DELAY_SECONDS} seconds\n\n"
                )
                queue_info += (
                    "💡 **Tip:** You can use `/ask` to add your question to the queue."
                )

            await interaction.response.send_message(queue_info, ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(
            f"❌ **Error checking queue status**\n\n"
            f"An error occurred: {str(e)[:200]}...",
            ephemeral=True,
        )


@tree.command(
    name="clearqueue", description="[Owner Only] Clear the request queue.", guild=None
)
async def clear_queue_command(interaction: discord.Interaction) -> None:
    """Clear the request queue (owner only)."""
    try:
        # Check if the user is the bot owner
        owner_id = int(os.getenv("OWNER_ID", "0"))
        if interaction.user.id != owner_id:
            await interaction.response.send_message(
                "❌ **Access Denied**\n\n" "Only the bot owner can clear the queue.",
                ephemeral=True,
            )
            return

        # Clear the queue
        queue_size = REQUEST_QUEUE.qsize()

        # Clear all items from the queue
        while not REQUEST_QUEUE.empty():
            try:
                REQUEST_QUEUE.get_nowait()
                REQUEST_QUEUE.task_done()
            except asyncio.QueueEmpty:
                break

        await interaction.response.send_message(
            f"🗑️ **Queue Cleared**\n\n"
            f"✅ Successfully cleared {queue_size} requests from the queue.\n"
            f"The queue is now empty.",
            ephemeral=True,
        )

    except Exception as e:
        await interaction.response.send_message(
            f"❌ **Error clearing queue**\n\n" f"An error occurred: {str(e)[:200]}...",
            ephemeral=True,
        )


@tree.command(
    name="sethistorylimit",
    description="[Owner Only] Set the number of recent messages to fetch per user.",
    guild=discord.Object(id=int(os.getenv("DEV_SERVER_ID", "0"))),
)
async def set_history_limit_command(
    interaction: discord.Interaction, limit: Optional[int] = None
) -> None:
    """Set the message history limit (owner only)."""
    try:
        # Check if the user is the bot owner
        owner_id = int(os.getenv("OWNER_ID", "0"))
        if interaction.user.id != owner_id:
            await interaction.response.send_message(
                "❌ **Access Denied**\n\n"
                "Only the bot owner can set the history limit.",
                ephemeral=True,
            )
            return

        global MESSAGE_HISTORY_LIMIT

        if limit is None:
            # Return current value
            await interaction.response.send_message(
                f"📊 **Current Message History Limit**\n\n"
                f"**Value:** {MESSAGE_HISTORY_LIMIT} messages\n\n"
                f"Use `/sethistorylimit <number>` to change this value.",
                ephemeral=True,
            )
        else:
            # Set new value
            if limit < 1 or limit > 50:
                await interaction.response.send_message(
                    "❌ **Invalid Value**\n\n"
                    f"Please provide a value between 1 and 50.\n"
                    f"Current value: {MESSAGE_HISTORY_LIMIT}",
                    ephemeral=True,
                )
                return

            old_limit = MESSAGE_HISTORY_LIMIT
            MESSAGE_HISTORY_LIMIT = limit

            await interaction.response.send_message(
                f"✅ **Message History Limit Updated**\n\n"
                f"**Old Value:** {old_limit} messages\n"
                f"**New Value:** {MESSAGE_HISTORY_LIMIT} messages\n\n"
                f"This change will take effect immediately for new requests.",
                ephemeral=True,
            )

    except Exception as e:
        await interaction.response.send_message(
            f"❌ **Error setting history limit**\n\n"
            f"An error occurred: {str(e)[:200]}...",
            ephemeral=True,
        )


@tree.command(
    name="setsearchdepth",
    description="[Owner Only] Set how far back to search in channel history.",
    guild=discord.Object(id=int(os.getenv("DEV_SERVER_ID", "0"))),
)
async def set_search_depth_command(
    interaction: discord.Interaction, depth: Optional[int] = None
) -> None:
    """Set the message history search depth (owner only)."""
    try:
        # Check if the user is the bot owner
        owner_id = int(os.getenv("OWNER_ID", "0"))
        if interaction.user.id != owner_id:
            await interaction.response.send_message(
                "❌ **Access Denied**\n\n"
                "Only the bot owner can set the search depth.",
                ephemeral=True,
            )
            return

        global MESSAGE_HISTORY_SEARCH_DEPTH

        if depth is None:
            # Return current value
            await interaction.response.send_message(
                f"🔍 **Current Message History Search Depth**\n\n"
                f"**Value:** {MESSAGE_HISTORY_SEARCH_DEPTH} messages\n\n"
                f"Use `/setsearchdepth <number>` to change this value.",
                ephemeral=True,
            )
        else:
            # Set new value
            if depth < 100 or depth > 10000:
                await interaction.response.send_message(
                    "❌ **Invalid Value**\n\n"
                    f"Please provide a value between 100 and 10,000.\n"
                    f"Current value: {MESSAGE_HISTORY_SEARCH_DEPTH}",
                    ephemeral=True,
                )
                return

            old_depth = MESSAGE_HISTORY_SEARCH_DEPTH
            MESSAGE_HISTORY_SEARCH_DEPTH = depth

            await interaction.response.send_message(
                f"✅ **Message History Search Depth Updated**\n\n"
                f"**Old Value:** {old_depth} messages\n"
                f"**New Value:** {MESSAGE_HISTORY_SEARCH_DEPTH} messages\n\n"
                f"This change will take effect immediately for new requests.",
                ephemeral=True,
            )

    except Exception as e:
        await interaction.response.send_message(
            f"❌ **Error setting search depth**\n\n"
            f"An error occurred: {str(e)[:200]}...",
            ephemeral=True,
        )


@tree.command(
    name="config",
    description="[Owner Only] View current bot configuration.",
    guild=discord.Object(id=int(os.getenv("DEV_SERVER_ID", "0"))),
)
async def config_command(interaction: discord.Interaction) -> None:
    """View current bot configuration (owner only)."""
    try:
        # Check if the user is the bot owner
        owner_id = int(os.getenv("OWNER_ID", "0"))
        if interaction.user.id != owner_id:
            await interaction.response.send_message(
                "❌ **Access Denied**\n\n"
                "Only the bot owner can view the configuration.",
                ephemeral=True,
            )
            return

        config_info = f"⚙️ **Bot Configuration**\n\n"
        config_info += f"**Message History Limit:** {MESSAGE_HISTORY_LIMIT} messages\n"
        config_info += f"**Message History Search Depth:** {MESSAGE_HISTORY_SEARCH_DEPTH} messages\n"
        config_info += (
            f"**Ask Command Cooldown:** {ASK_COMMAND_COOLDOWN_MINUTES} minutes\n"
        )
        config_info += f"**Imagine Command Cooldown:** {IMAGINE_COMMAND_COOLDOWN_MINUTES} minutes\n"
        config_info += f"**Max Stored Questions:** {MAX_STORED_QUESTIONS} questions\n\n"
        config_info += "**Image Generation:**\n"
        config_info += f"• Enabled: {IMAGINE_ENABLE}\n\n"
        config_info += "**Channel Context Settings:**\n"
        config_info += f"• Last raw messages: {CHANNEL_CONTEXT_LAST}\n"
        config_info += f"• Include bot messages (raw context): {CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES}\n"
        config_info += f"• Summary enabled: {CHANNEL_SUMMARY_ENABLE}\n"
        config_info += f"• Summary depth: {CHANNEL_SUMMARY_DEPTH}\n"
        config_info += f"• Summary TTL: {CHANNEL_SUMMARY_TTL_MIN} min\n\n"
        config_info += "**Commands to modify:**\n"
        config_info += (
            "• `/sethistorylimit <number>` - Set message history limit (1-50)\n"
        )
        config_info += "• `/setsearchdepth <number>` - Set search depth (100-10000)\n"
        config_info += "• `/setimagineenabled <true|false>` - Toggle image generation\n"
        config_info += "• `/setcontextincludebots <true|false>` - Include bot messages in raw context\n"
        config_info += "• `/debugemojis` - Debug emoji replacement issues\n"
        config_info += "• `/config` - View current configuration"

        await interaction.response.send_message(config_info, ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(
            f"❌ **Error viewing configuration**\n\n"
            f"An error occurred: {str(e)[:200]}...",
            ephemeral=True,
        )


@tree.command(
    name="debugemojis",
    description="[Owner Only] Debug emoji replacement issues in the current guild.",
    guild=discord.Object(id=int(os.getenv("DEV_SERVER_ID", "0"))),
)
async def debug_emojis_command(interaction: discord.Interaction) -> None:
    """Debug emoji replacement issues (owner only)."""
    try:
        # Check if the user is the bot owner
        owner_id = int(os.getenv("OWNER_ID", "0"))
        if interaction.user.id != owner_id:
            await interaction.response.send_message(
                "❌ **Access Denied**\n\n" "Only the bot owner can debug emoji issues.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Get debug info for the current guild
        guild = interaction.guild
        if not guild:
            await interaction.followup.send(
                "❌ **No Guild Context**\n\n" "This command must be used in a server.",
                ephemeral=True,
            )
            return

        debug_info = await debug_guild_emoji_state(guild)

        # Test emoji replacement with a sample text
        test_text = "Testing emoji replacement: :test: :smile: :cool:"
        print(f"🧪 Testing emoji replacement with: {test_text}")

        replaced_text = await replace_guild_emojis_in_text(test_text, guild)

        test_result = f"🧪 **Emoji Replacement Test**\n\n"
        test_result += f"**Test Text:** {test_text}\n"
        test_result += f"**Result:** {replaced_text}\n\n"

        full_debug = debug_info + "\n\n" + test_result

        # Split if too long for Discord
        if len(full_debug) > 2000:
            await interaction.followup.send(
                content=debug_info[:1997] + "...", ephemeral=True
            )
            await interaction.followup.send(content=test_result, ephemeral=True)
        else:
            await interaction.followup.send(content=full_debug, ephemeral=True)

    except Exception as e:
        await interaction.followup.send(
            f"❌ **Error debugging emojis**\n\n"
            f"An error occurred: {str(e)[:200]}...",
            ephemeral=True,
        )


@tree.command(
    name="togglellmban",
    description="[Owner Only] Ban a user from using the LLM",
    guild=None,
)
async def ban_llm_command(
    interaction: discord.Interaction, user: discord.Member
) -> None:
    """Ban a user from using the LLM (owner only)."""
    try:
        owner_id = int(os.getenv("OWNER_ID", "0"))
        if interaction.user.id != owner_id:
            await interaction.response.send_message(
                "❌ **Access Denied**\n\nOnly the bot owner can ban users from the LLM.",
                ephemeral=True,
            )
            return

        if is_banned(user.id):
            remove_banned_user(user.id)
            await interaction.response.send_message(
                f"✅ **User Unbanned**\n\n"
                f"{user.mention} has been unbanned from using the LLM.",
                ephemeral=True,
            )
            return

        # Add the user to the banned users list
        add_banned_user(user.id)
        await interaction.response.send_message(
            f"✅ **User Banned**\n\n"
            f"{user.mention} has been banned from using the LLM.",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ **Error banning user**\n\n" f"An error occurred: {str(e)[:200]}...",
            ephemeral=True,
        )


@tree.command(
    name="setask",
    description="[Owner Only] Enable/disable ask command (true/false or omit to view)",
    guild=discord.Object(id=int(os.getenv("DEV_SERVER_ID", "0"))),
)
async def set_ask_command_command(
    interaction: discord.Interaction, enabled: Optional[bool] = None
) -> None:
    """View or update the ask command (owner only)."""
    try:
        owner_id = int(os.getenv("OWNER_ID", "0"))
        if interaction.user.id != owner_id:
            await interaction.response.send_message(
                "❌ **Access Denied**\n\nOnly the bot owner can change this setting.",
                ephemeral=True,
            )
            return

        global ASK_ENABLE

        if enabled is None:
            await interaction.response.send_message(
                f"💬 **Ask Command**\n\nCurrent: {ASK_ENABLE}",
                ephemeral=True,
            )
            return

        old_value = ASK_ENABLE
        ASK_ENABLE = bool(enabled)
        await interaction.response.send_message(
            f"✅ **Ask Command Updated**\n\nOld: {old_value}\nNew: {ASK_ENABLE}",
            ephemeral=True,
        )

    except Exception as e:
        await interaction.response.send_message(
            f"❌ **Error updating setting**\n\nAn error occurred: {str(e)[:200]}...",
            ephemeral=True,
        )


@tree.command(
    name="setimagineenabled",
    description="[Owner Only] Enable or disable image generation (true/false or omit to view)",
    guild=discord.Object(id=int(os.getenv("DEV_SERVER_ID", "0"))),
)
async def set_imagine_enabled_command(
    interaction: discord.Interaction, enabled: Optional[bool] = None
) -> None:
    """View or update the global image generation toggle (owner only)."""
    try:
        owner_id = int(os.getenv("OWNER_ID", "0"))
        if interaction.user.id != owner_id:
            await interaction.response.send_message(
                "❌ **Access Denied**\n\nOnly the bot owner can change this setting.",
                ephemeral=True,
            )
            return

        global IMAGINE_ENABLE

        if enabled is None:
            await interaction.response.send_message(
                f"🖼️ **Image Generation Toggle**\n\nCurrent: {IMAGINE_ENABLE}",
                ephemeral=True,
            )
            return

        old_value = IMAGINE_ENABLE
        IMAGINE_ENABLE = bool(enabled)
        await interaction.response.send_message(
            f"✅ **Image Generation Updated**\n\nOld: {old_value}\nNew: {IMAGINE_ENABLE}",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ **Error updating setting**\n\nAn error occurred: {str(e)[:200]}...",
            ephemeral=True,
        )


# New setting: include bot messages in raw channel context
@tree.command(
    name="setcontextincludebots",
    description="[Owner Only] Include or exclude bot messages in raw channel context (true/false or omit to view)",
    guild=discord.Object(id=int(os.getenv("DEV_SERVER_ID", "0"))),
)
async def set_context_include_bots_command(
    interaction: discord.Interaction, include: Optional[bool] = None
) -> None:
    """View or update inclusion of bot messages in the raw channel context (owner only)."""
    try:
        owner_id = int(os.getenv("OWNER_ID", "0"))
        if interaction.user.id != owner_id:
            await interaction.response.send_message(
                "❌ **Access Denied**\n\nOnly the bot owner can change this setting.",
                ephemeral=True,
            )
            return

        global CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES

        if include is None:
            await interaction.response.send_message(
                f"💬 **Include Bot Messages in Raw Context**\n\nCurrent: {CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES}",
                ephemeral=True,
            )
            return

        old_value = CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES
        CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES = bool(include)
        await interaction.response.send_message(
            f"✅ **Raw Context Inclusion Updated**\n\nOld: {old_value}\nNew: {CHANNEL_CONTEXT_INCLUDE_BOT_MESSAGES}",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ **Error updating setting**\n\nAn error occurred: {str(e)[:200]}...",
            ephemeral=True,
        )


# Button interaction handler for retry functionality
@client.event
async def on_interaction(interaction: discord.Interaction) -> None:
    """Handle button interactions for retry functionality."""
    # Only handle button interactions, let the command tree handle slash commands
    if interaction.type != discord.InteractionType.component:
        return

    if not interaction.data or "custom_id" not in interaction.data:
        return

    custom_id = interaction.data["custom_id"]

    # Passive cleanup of expired used retry buttons
    try:
        now = datetime.datetime.now()
        expired_custom_ids = [
            cid
            for cid, ts in list(USED_RETRY_BUTTONS.items())
            if (now - ts).total_seconds() >= RETRY_BUTTON_TTL_MINUTES * 60
        ]
        for cid in expired_custom_ids:
            del USED_RETRY_BUTTONS[cid]
    except Exception:
        pass

    # Check if this is a retry button
    if custom_id.startswith("retry_"):
        try:
            # One-time guard: if already used, reject
            if custom_id in USED_RETRY_BUTTONS:
                await interaction.response.send_message(
                    "⛔ This retry button was already used.", ephemeral=True
                )
                return

            # Parse the custom_id to get user_id, question hash and timestamp
            parts = custom_id.split("_")
            # Expected formats:
            # - retry_<userId>_<hash> (legacy)
            # - retry_<userId>_<hash>_<token> (one-time)
            # - retry_<userId>_<hash>_<token>_<timestamp> (one-time + expiry)
            if len(parts) >= 3:
                button_user_id = int(parts[1])
                question_hash = parts[2]
                created_ts = None
                if len(parts) >= 5:
                    try:
                        created_ts = int(parts[4])
                    except ValueError:
                        created_ts = None

                # Check if the button was pressed by the original user
                if interaction.user.id != button_user_id:
                    await interaction.response.send_message(
                        "❌ Only the person who asked the original question can use the retry button.",
                        ephemeral=True,
                    )
                    return

                # Find the question by hash
                if button_user_id in RECENT_QUESTIONS:
                    for question_data in RECENT_QUESTIONS[button_user_id]:
                        # Unpack the question data tuple (question, tts, image)
                        if len(question_data) >= 3:
                            question, tts, image = question_data
                        elif len(question_data) == 2:
                            question, tts = question_data
                            image = None
                        else:
                            question = question_data[0] if question_data else ""
                            tts = False
                            image = None

                        if str(hash(question) % 1000000) == question_hash:
                            # Found the question: load original context if available
                            loaded_context = load_retry_context(custom_id) or ""

                            # If expired, reject and disable
                            if created_ts is not None:
                                age_seconds = (
                                    int(datetime.datetime.now().timestamp())
                                    - created_ts
                                )
                                if age_seconds >= RETRY_BUTTON_EXPIRE_MINUTES * 60:
                                    try:
                                        disable_view = discord.ui.View()
                                        disable_view.add_item(
                                            discord.ui.Button(
                                                style=discord.ButtonStyle.primary,
                                                label="🔄 Retry",
                                                custom_id=custom_id,
                                                disabled=True,
                                            )
                                        )
                                        await interaction.message.edit(view=disable_view)  # type: ignore
                                    except Exception:
                                        pass
                                    await interaction.response.send_message(
                                        "⏰ This retry button has expired.",
                                        ephemeral=True,
                                    )
                                    return

                            # Mark as used and disable button in the original message
                            USED_RETRY_BUTTONS[custom_id] = datetime.datetime.now()
                            try:
                                disable_view = discord.ui.View()
                                disable_view.add_item(
                                    discord.ui.Button(
                                        style=discord.ButtonStyle.primary,
                                        label="🔄 Retry",
                                        custom_id=custom_id,
                                        disabled=True,
                                    )
                                )
                                await interaction.message.edit(view=disable_view)  # type: ignore
                            except Exception:
                                pass

                            # Load any persisted media for this retry and clear files
                            retry_media_parts = load_retry_media(custom_id)

                            # Add retry request to queue
                            request_id = await add_request_to_queue(
                                RequestType.RETRY,
                                interaction,
                                question,
                                loaded_context if loaded_context else "",
                                button_user_id,
                                priority=2,  # Retries get higher priority
                                media_parts=retry_media_parts,
                                tts=tts,
                            )

                            # Send confirmation
                            queue_position = REQUEST_QUEUE.qsize()
                            filtered_question = filter_profanity(question)
                            await interaction.response.send_message(
                                f"🔄 **Retry queued**\n\n"
                                f"**Question:** {filtered_question}\n\n"
                                f"Your retry request has been added to the queue (position: {queue_position}). "
                                f"It will be processed shortly.",
                                ephemeral=True,
                            )
                            return

                    # Question not found
                    await interaction.response.send_message(
                        "❌ The original question is no longer available for retry.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "❌ No recent questions found to retry.",
                        ephemeral=True,
                    )

        except (ValueError, IndexError) as e:
            print(f"Error parsing retry button custom_id: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while processing the retry button.",
                ephemeral=True,
            )
        except Exception as e:
            print(f"Unexpected error in retry button handler: {e}")
            try:
                await interaction.response.send_message(
                    "❌ An unexpected error occurred.", ephemeral=True
                )
            except:
                pass


# Development server refresh command (only visible on your dev server)
@tree.command(
    name="refresh",
    description="[Dev Only] Refresh slash commands on the server.",
    guild=IS_DEV_SERVER_COMMAND,
)
async def refresh_commands(interaction: discord.Interaction) -> None:
    # Check if the user is the bot owner (you)
    if interaction.user.id != int(os.getenv("OWNER_ID", "0")):
        try:
            await interaction.response.send_message(
                "You don't have permission to use this command.", ephemeral=True
            )
        except discord.errors.NotFound:
            print(
                f"Interaction not found when sending permission error for refresh command"
            )
            return
        return

    try:
        await interaction.response.defer(ephemeral=True)

        # Clear commands from the specific guild first
        if GUILD_ID_ENV:
            test_guild = discord.Object(id=int(GUILD_ID_ENV))
            tree.clear_commands(guild=test_guild)
            await tree.sync(guild=test_guild)
            try:
                await interaction.followup.send(
                    f"Commands cleared and refreshed on guild {GUILD_ID_ENV}!",
                    ephemeral=True,
                )
            except discord.errors.NotFound:
                print(
                    "Interaction not found when sending guild refresh success message"
                )
                return
        else:
            # Clear global commands
            tree.clear_commands(guild=None)
            await tree.sync()
            try:
                await interaction.followup.send(
                    "Commands cleared and refreshed globally! (May take up to 1 hour)",
                    ephemeral=True,
                )
            except discord.errors.NotFound:
                print(
                    "Interaction not found when sending global refresh success message"
                )
                return
    except discord.errors.NotFound:
        print("Interaction not found when deferring refresh command")
        return

    except Exception as e:
        try:
            await interaction.followup.send(
                f"Failed to refresh commands: {e}", ephemeral=True
            )
        except discord.errors.NotFound:
            print("Interaction not found when sending refresh error message")
            return


@client.event
async def on_ready() -> None:
    print(f"Logged in as {client.user} (ID: {client.user.id})")  # type: ignore
    print("Bot is ready! Starting command sync...")

    try:
        if GUILD_ID_ENV:
            print(f"GUILD_ID_ENV is set to: {GUILD_ID_ENV}")
            test_guild = discord.Object(id=int(GUILD_ID_ENV))
            print(f"Created guild object: {test_guild}")

            # For development/testing, only sync to the specific guild
            # This prevents duplicate commands from appearing
            print("Syncing guild commands only...")
            await tree.sync(guild=test_guild)
            print(f"Slash commands synced to guild {GUILD_ID_ENV}.")
        else:
            print("No GUILD_ID_ENV set, syncing globally only...")
            # Production mode: sync globally only
            await tree.sync()
            print("Slash commands synced globally (may take up to 1 hour to appear).")
    except Exception as sync_error:
        print(f"Failed to sync commands: {sync_error}")
        print(f"Error type: {type(sync_error)}")
        import traceback

        traceback.print_exc()
        print(
            "Make sure your bot has the 'applications.commands' scope and proper permissions."
        )


def main() -> None:
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN environment variable is not set. "
            "Create a .env file or set the variable and try again."
        )
    client.run(TOKEN)


if __name__ == "__main__":
    main()
