# Basic sqlite database for various long term storage

import sqlite3


def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS banned_users (
        user_id INTEGER PRIMARY KEY
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
