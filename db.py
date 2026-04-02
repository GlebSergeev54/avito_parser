import sqlite3
from sqlite3 import Connection

from config import DB_PATH


def get_connection() -> Connection:
    """
    Создает и возвращает подключение к SQLite.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables(conn: Connection) -> None:
    """
    Создает таблицу кеша, если ее еще нет.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            avito_id TEXT NOT NULL,
            query_text TEXT NOT NULL,
            title TEXT,
            price TEXT,
            address TEXT,
            description TEXT,
            published_at TEXT,
            views_count TEXT,
            url TEXT,
            status TEXT NOT NULL,
            created_at_cache TEXT NOT NULL,
            updated_at_cache TEXT NOT NULL,
            UNIQUE(avito_id, query_text)
        )
        """
    )
    conn.commit()