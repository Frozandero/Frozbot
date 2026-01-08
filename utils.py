"""Utility functions for Frozbot."""

import datetime
import re
from typing import Optional

from better_profanity import profanity

import config

# Initialize profanity filter
profanity.load_censor_words()

# Comprehensive list of extreme slurs that should never appear in system prompts
# This prevents the bot from learning or repeating these terms through context
EXTREME_SLURS = [
    # Racial slurs (common variants)
    r"\bn[i1l!|]+[e3][g6]+[e3]r\w*\b",
    r"\bk[i1l!|]+[e3]y\w*\b",
    r"\bs[p]+[i1l!|]+c\w*\b",
    r"\bc[o0]+[o0]n\w*\b",
    r"\bg[o0]+[o0]k\w*\b",
    r"\bj[a4@]+[p]+[a4@]+n\w*\b",
    r"\bc[h]+[i1l!|]+n[k]+\w*\b",
    r"\bt[o0]+w[e3]+l[h]+\w*\b",
    r"\bs[a4@]+nd\s*n[i1l!|]+[g6]+\w*\b",
    r"\bn[i1l!|]+[g6]+[a4@]+\w*\b",
    # Homophobic slurs
    r"\bf[a4@]+[g6]+\w*\b",
    r"\bd[i1l!|]+k[e3]+\w*\b",
    r"\bq[u]+[e3]+e[e3]+r\w*\b",
    # Other extreme slurs
    r"\br[e3]+t[a4@]+rd\w*\b",
    r"\bs[l!|]+[u]+t\w*\b",
    r"\bc[u]+nt\w*\b",
    r"\bwh[o0]+r[e3]+\w*\b",
    r"\bb[i1l!|]+tch\w*\b",
    r"\bc[u]+ck\w*\b",
    r"\bp[u]+ss[y]+\w*\b",
    r"\btw[a4@]+t\w*\b",
    r"\btr[a4@]+nn[y]+\w*\b",
    r"\bs[h]+[e3]+m[a4@]+l[e3]+\w*\b",
    r"\bh[i1l!|]+[j]+[a4@]+d[i1l!|]+\w*\b",
    r"\bt[e3]+rr[o0]+r[i1l!|]+st\w*\b",
    r"\bk[i1l!|]+[l!|]\s*[a4@]+ll\w*\b",
    r"\br[a4@]+p[e3]+\w*\b",
    r"\bm[o0]+l[e3]+st\w*\b",
    r"\bp[e3]+d[o0]+\w*\b",
]

# Compile regex patterns for performance
EXTREME_SLUR_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in EXTREME_SLURS
]


def filter_profanity(text: str) -> str:
    """Filter profanity from text, replacing it with block characters."""
    return profanity.censor(text, "■") if config.CENSOR_MESSAGES else text


def sanitize_system_prompt(text: str) -> str:
    """
    Remove extreme slurs from system prompts to prevent the bot from learning or repeating them.
    This is always applied regardless of CENSOR_MESSAGES setting.

    Args:
        text: The system prompt/context string to sanitize

    Returns:
        Sanitized text with extreme slurs removed/replaced
    """
    sanitized = text
    for pattern in EXTREME_SLUR_PATTERNS:
        sanitized = pattern.sub("[removed]", sanitized)
    return sanitized


def cleanup_expired_cooldowns() -> None:
    """Remove expired cooldown entries to prevent memory bloat."""
    current_time = datetime.datetime.now()
    expired_users = []

    for user_id, last_used in config.ASK_COMMAND_COOLDOWNS.items():
        time_diff = current_time - last_used
        minutes_passed = time_diff.total_seconds() / 60

        if minutes_passed >= config.ASK_COMMAND_COOLDOWN_MINUTES:
            expired_users.append(user_id)

    for user_id in expired_users:
        del config.ASK_COMMAND_COOLDOWNS[user_id]
        # Also cleanup recent questions for expired users
        if user_id in config.RECENT_QUESTIONS:
            del config.RECENT_QUESTIONS[user_id]


def cleanup_imagine_expired_cooldowns() -> None:
    """Remove expired cooldown entries for the imagine command."""
    current_time = datetime.datetime.now()
    expired_users: list[int] = []

    for user_id, last_used in config.IMAGINE_COMMAND_COOLDOWNS.items():
        time_diff = current_time - last_used
        minutes_passed = time_diff.total_seconds() / 60
        if minutes_passed >= config.IMAGINE_COMMAND_COOLDOWN_MINUTES:
            expired_users.append(user_id)

    for user_id in expired_users:
        del config.IMAGINE_COMMAND_COOLDOWNS[user_id]


def store_user_question(
    user_id: int, question: str, tts: bool, image: Optional[object] = None
) -> None:
    """Store a user's question for potential retry functionality."""
    if user_id not in config.RECENT_QUESTIONS:
        config.RECENT_QUESTIONS[user_id] = []

    # Add new question to the beginning
    config.RECENT_QUESTIONS[user_id].insert(0, (question, tts, image))

    # Keep only the most recent questions
    if len(config.RECENT_QUESTIONS[user_id]) > config.MAX_STORED_QUESTIONS:
        config.RECENT_QUESTIONS[user_id] = config.RECENT_QUESTIONS[user_id][
            : config.MAX_STORED_QUESTIONS
        ]


def check_rate_limit(
    user_id: int, cooldown_minutes: int, cooldowns_dict: dict
) -> tuple[bool, int]:
    """
    Check if a user is rate limited.

    Returns:
        Tuple of (is_rate_limited, remaining_minutes)
    """
    if config.is_owner(user_id):
        return False, 0

    current_time = datetime.datetime.now()

    if user_id in cooldowns_dict:
        last_used = cooldowns_dict[user_id]
        time_diff = current_time - last_used
        minutes_passed = time_diff.total_seconds() / 60

        if minutes_passed < cooldown_minutes:
            remaining_minutes = int(cooldown_minutes - minutes_passed)
            return True, remaining_minutes

    return False, 0


def truncate_text(text: str, max_length: int = 2000) -> str:
    """Truncate text to a maximum length, adding ellipsis if truncated."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
