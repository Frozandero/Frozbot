"""Utility functions for Frozbot."""

import datetime
from typing import Optional

from better_profanity import profanity

import config

# Initialize profanity filter
profanity.load_censor_words()


def filter_profanity(text: str) -> str:
    """Filter profanity from text, replacing it with block characters."""
    return profanity.censor(text, "■") if config.CENSOR_MESSAGES else text


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


def check_rate_limit(user_id: int, cooldown_minutes: int, cooldowns_dict: dict) -> tuple[bool, int]:
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

