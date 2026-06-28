"""Emoji handling functions for Frozbot."""

import logging
import re
from typing import Dict, Any, Optional

import discord

EMOJI_NAME_PATTERN = r"[A-Za-z0-9_]{2,32}"
GUILD_EMOJI_TOKEN_RE = re.compile(rf"(?<!<)(?<!<a)\\?:({EMOJI_NAME_PATTERN})\\?:")
logger = logging.getLogger(__name__)


def _log(message: str) -> None:
    logger.debug("emoji_debug", extra={"detail": message[:300]})


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
        _log(
            f"[WARN] Invalid guild object passed to replace_guild_emojis_in_text: {type(guild)}"
        )
        return text

    # Additional validation: ensure guild is in a valid state
    try:
        guild_id = getattr(guild, "id", None)
        if not guild_id:
            _log("[WARN] Guild object has no valid ID")
            return text
    except Exception as e:
        _log(f"[WARN] Error accessing guild ID: {e}")
        return text

    # Pre-process: Normalize Unicode colon variants to ASCII colons
    unicode_colon_variants = ["：", "﹕", "︓", "꞉", "∶"]
    for variant in unicode_colon_variants:
        if variant in text:
            _log(f"[emoji] Normalizing Unicode colon variant '{variant}' to ASCII ':'")
            text = text.replace(variant, ":")

    # Pre-process: Fix malformed Discord emoji patterns like <:name:> or <a:name:> (missing ID)
    malformed_emoji_pattern = re.compile(rf"<(a?):({EMOJI_NAME_PATTERN}):>")
    malformed_matches = malformed_emoji_pattern.findall(text)
    if malformed_matches:
        _log(f"[emoji] Found malformed emoji patterns (missing ID): {malformed_matches}")
        text = malformed_emoji_pattern.sub(r":\2:", text)
        _log(f"[emoji] Fixed malformed emojis, text now: {text[:100]}...")

    # Match :name: and LLM-escaped \:name\: tokens, but not existing
    # Discord custom emoji mentions such as <:name:id> or <a:name:id>.
    names_in_text = set(GUILD_EMOJI_TOKEN_RE.findall(text))
    if not names_in_text:
        return text

    _log(f"[emoji] Found emoji names in text: {names_in_text}")

    # Build name -> emoji mapping (case-insensitive by name)
    name_to_emoji: Dict[str, Any] = {}
    try:
        # First try to get emojis from cache
        cached_emojis = getattr(guild, "emojis", [])
        _log(f"[DEBUG] Found {len(cached_emojis)} cached emojis in guild {guild_id}")

        for e in cached_emojis:
            try:
                if hasattr(e, "name") and e.name:
                    name_to_emoji[str(e.name).lower()] = e
            except Exception as emoji_error:
                _log(f"  [WARN] Error processing cached emoji: {emoji_error}")
                continue

        # Check which emojis are missing from cache
        missing = {n for n in names_in_text if n.lower() not in name_to_emoji}
        if missing:
            _log(f"[emoji] Fetching missing emojis: {missing}")
            try:
                fetched = await guild.fetch_emojis()
                _log(f"[emoji] Fetched {len(fetched)} emojis from guild {guild_id}")

                for e in fetched:
                    try:
                        if hasattr(e, "name") and e.name:
                            name_to_emoji[str(e.name).lower()] = e
                    except Exception as emoji_error:
                        _log(f"  [WARN] Error processing fetched emoji: {emoji_error}")
                        continue
            except Exception as fetch_error:
                _log(f"[WARN] Failed to fetch emojis from guild {guild_id}: {fetch_error}")
                # Continue with cached emojis only

        # Show final mapping
        _log(f"[emoji] Final emoji mapping: {len(name_to_emoji)} emojis available")

        def _sub(m: re.Match) -> str:
            name = m.group(1)
            emoji = name_to_emoji.get(name.lower())
            if emoji:
                try:
                    emoji_str = str(emoji)
                    return emoji_str
                except Exception as e:
                    _log(f"[WARN] Error converting emoji {emoji} to string: {e}")
                    # Strip colons if conversion fails - shows just the name
                    return name
            else:
                _log(f"[WARN] No emoji found for :{name}:, stripping colons")
                # Strip the colons to make text readable instead of showing :name:
                return name

        result = GUILD_EMOJI_TOKEN_RE.sub(_sub, text)
        _log(
            f"[emoji] Emoji replacement complete. Original: {text[:100]}... -> Result: {result[:100]}..."
        )
        return result

    except Exception as e:
        _log(f"[ERROR] Unexpected error in replace_guild_emojis_in_text: {e}")
        logger.exception(
            "emoji_replacement_unexpected_error",
            extra={"error_type": type(e).__name__},
        )
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
            logger.warning("emoji_list_no_guild")
            return names

        # Validate guild object
        if not hasattr(guild, "id") or not hasattr(guild, "emojis"):
            logger.warning(
                "emoji_list_invalid_guild",
                extra={"guild_type": type(guild).__name__},
            )
            return names

        logger.debug("emoji_list_started", extra={"guild_id": guild.id})

        # Prefer cached list first
        cached_emojis = getattr(guild, "emojis", [])
        logger.debug(
            "emoji_cached_count",
            extra={"guild_id": guild.id, "emoji_count": len(cached_emojis)},
        )

        for e in cached_emojis:
            try:
                if hasattr(e, "name") and e.name:
                    names.append(str(e.name))
                    logger.debug(
                        "emoji_cached_name",
                        extra={"guild_id": guild.id, "emoji_name": e.name},
                    )
            except Exception as emoji_error:
                logger.debug(
                    "emoji_cached_processing_error",
                    extra={
                        "guild_id": guild.id,
                        "error_type": type(emoji_error).__name__,
                    },
                )
                continue

        # If empty, try fetching
        if not names:
            logger.debug("emoji_fetch_started", extra={"guild_id": guild.id})
            try:
                fetched = await guild.fetch_emojis()
                logger.debug(
                    "emoji_fetch_completed",
                    extra={"guild_id": guild.id, "emoji_count": len(fetched)},
                )

                for e in fetched:
                    try:
                        if hasattr(e, "name") and e.name:
                            names.append(str(e.name))
                            logger.debug(
                                "emoji_fetched_name",
                                extra={"guild_id": guild.id, "emoji_name": e.name},
                            )
                    except Exception as emoji_error:
                        logger.debug(
                            "emoji_fetched_processing_error",
                            extra={
                                "guild_id": guild.id,
                                "error_type": type(emoji_error).__name__,
                            },
                        )
                        continue
            except Exception as fetch_error:
                logger.warning(
                    "emoji_fetch_failed",
                    extra={
                        "guild_id": guild.id,
                        "error_type": type(fetch_error).__name__,
                    },
                    exc_info=True,
                )

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
            logger.debug(
                "emoji_list_returning_truncated",
                extra={"returned": len(result), "total": len(deduped)},
            )
        else:
            result = deduped
            logger.debug("emoji_list_returning", extra={"returned": len(result)})

        return result

    except Exception as e:
        logger.exception(
            "emoji_list_unexpected_error",
            extra={"error_type": type(e).__name__},
        )
        return []
