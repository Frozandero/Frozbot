# Basic sqlite database for various long term storage

import os
import sqlite3
from contextlib import contextmanager


DB_PATH = os.getenv("FROZBOT_DB_PATH", "database.db")


def get_db_path() -> str:
    """Return the configured SQLite database path."""
    return os.getenv("FROZBOT_DB_PATH", DB_PATH)


@contextmanager
def connect_db():
    """Open a SQLite connection and always close it."""
    conn = sqlite3.connect(get_db_path())
    try:
        yield conn
    finally:
        conn.close()


def clear_db():
    with connect_db() as conn:
        c = conn.cursor()
        c.execute("DROP TABLE IF EXISTS banned_users")
        c.execute("DROP TABLE IF EXISTS memories")
        conn.commit()


def init_db():
    with connect_db() as conn:
        c = conn.cursor()

        # Create banned_users table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id INTEGER PRIMARY KEY
            )
        """
        )

        # Create memories table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                memory TEXT,
                channel_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        conn.commit()


def add_banned_user(user_id: int):
    with connect_db() as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id,))
        conn.commit()


def remove_banned_user(user_id: int):
    with connect_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
        conn.commit()


def is_banned(user_id: int) -> bool:
    with connect_db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM banned_users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
    return result is not None


def get_banned_users() -> list[int]:
    with connect_db() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM banned_users")
        result = c.fetchall()
    return [user[0] for user in result]


def add_memory(username: str, memory: str, channel_id: int):
    with connect_db() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO memories (username, memory, channel_id) VALUES (?, ?, ?)",
            (username, memory, channel_id),
        )
        conn.commit()


def get_memories_by_user(
    username: str, channel_id: int, limit: int = 10, offset: int = 0
) -> list[tuple[int, str, str]]:
    with connect_db() as conn:
        c = conn.cursor()
        if limit == -1:
            c.execute(
                "SELECT id, username, memory FROM memories WHERE username = ? AND channel_id = ? ORDER BY created_at DESC",
                (username, channel_id),
            )
        else:
            c.execute(
                "SELECT id, username, memory FROM memories WHERE username = ? AND channel_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (username, channel_id, limit, offset),
            )
        result = c.fetchall()
    return result


def get_memories(
    channel_id: int, limit: int = 10, offset: int = 0
) -> list[tuple[int, str, str]]:
    with connect_db() as conn:
        c = conn.cursor()
        if limit == -1:
            c.execute(
                "SELECT id, username, memory FROM memories WHERE channel_id = ? ORDER BY created_at DESC",
                (channel_id,),
            )
        else:
            c.execute(
                "SELECT id, username, memory FROM memories WHERE channel_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (channel_id, limit, offset),
            )
        result = c.fetchall()
    return result


def count_memories_by_user(username: str, channel_id: int) -> int:
    with connect_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM memories WHERE username = ? AND channel_id = ?",
            (username, channel_id),
        )
        result = c.fetchone()
    return result[0] if result else 0


def count_memories(channel_id: int) -> int:
    with connect_db() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM memories WHERE channel_id = ?", (channel_id,))
        result = c.fetchone()
    return result[0] if result else 0


def delete_memory(id: int, channel_id: int) -> bool:
    with connect_db() as conn:
        c = conn.cursor()
        c.execute(
            "DELETE FROM memories WHERE id = ? AND channel_id = ?",
            (id, channel_id),
        )
        deleted = c.rowcount > 0
        conn.commit()
    return deleted


def get_memories_for_users(
    usernames: list[str], channel_id: int, limit: int = 10
) -> dict[str, list[tuple[int, str, str]]]:
    """
    Get memories for multiple users in a single query.
    Returns a dict mapping username -> list of memories.
    """
    if not usernames:
        return {}

    # Create placeholders for the IN clause
    placeholders = ",".join("?" for _ in usernames)

    if limit == -1:
        query = f"""
            SELECT id, username, memory FROM memories 
            WHERE username IN ({placeholders}) AND channel_id = ? 
            ORDER BY created_at DESC
        """
        params = usernames + [channel_id]
    else:
        # For limited results, we need to use a more complex query to limit per user
        # This approach gets all memories for the users and we'll limit in Python
        query = f"""
            SELECT id, username, memory FROM memories 
            WHERE username IN ({placeholders}) AND channel_id = ? 
            ORDER BY username, created_at DESC
        """
        params = usernames + [channel_id]

    with connect_db() as conn:
        c = conn.cursor()
        c.execute(query, params)
        results = c.fetchall()

    # Group by username and apply limit if needed
    memories_by_user = {}
    for username in usernames:
        memories_by_user[username] = []

    for memory_id, username, memory in results:
        if username in memories_by_user and (
            limit == -1 or len(memories_by_user[username]) < limit
        ):
            memories_by_user[username].append((memory_id, username, memory))

    return memories_by_user


def get_generic_memories(
    channel_id: int, limit: int = 10
) -> list[tuple[int, str, str]]:
    """
    Get generic memories (username='*') for a channel.
    """
    return get_memories_by_user("*", channel_id, limit)
