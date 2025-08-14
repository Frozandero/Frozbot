# Basic sqlite database for various long term storage

import sqlite3


def clear_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS banned_users")
    c.execute("DROP TABLE IF EXISTS memories")
    conn.commit()
    conn.close()


def init_db():
    conn = sqlite3.connect("database.db")
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
    conn.close()


def add_banned_user(user_id: int):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("INSERT INTO banned_users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def remove_banned_user(user_id: int):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def is_banned(user_id: int) -> bool:
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT * FROM banned_users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None


def get_banned_users() -> list[int]:
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM banned_users")
    result = c.fetchall()
    conn.close()
    return [user[0] for user in result]


def add_memory(username: str, memory: str, channel_id: int):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO memories (username, memory, channel_id) VALUES (?, ?, ?)",
        (username, memory, channel_id),
    )
    conn.commit()
    conn.close()


def get_memories_by_user(
    username: str, channel_id: int, limit: int = 10, offset: int = 0
) -> list[tuple[int, str, str]]:
    conn = sqlite3.connect("database.db")
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
    conn.close()
    return result


def get_memories(
    channel_id: int, limit: int = 10, offset: int = 0
) -> list[tuple[int, str, str]]:
    conn = sqlite3.connect("database.db")
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
    conn.close()
    return result


def count_memories_by_user(username: str, channel_id: int) -> int:
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM memories WHERE username = ?", (username,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0


def count_memories(channel_id: int) -> int:
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM memories")
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0


def delete_memory(id: int, channel_id: int):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("DELETE FROM memories WHERE id = ?", (id,))
    conn.commit()
