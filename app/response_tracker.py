"""Local SQLite store for Gmail venue responses."""

import sqlite3
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATABASE_PATH = DATA_DIR / "responses.db"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS venue_responses (
            thread_id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            sender_name TEXT NOT NULL,
            sender_email TEXT NOT NULL,
            subject TEXT NOT NULL,
            received_at TEXT NOT NULL,
            snippet TEXT NOT NULL,
            tracking_status TEXT NOT NULL DEFAULT 'new',
            first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return connection


def upsert_response(response: dict[str, str]) -> bool:
    """Insert or refresh one thread response; return whether it was new."""
    with _connect() as connection:
        exists = connection.execute(
            "SELECT 1 FROM venue_responses WHERE thread_id = ?",
            (response["thread_id"],),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO venue_responses (
                thread_id, message_id, sender_name, sender_email,
                subject, received_at, snippet
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                message_id = excluded.message_id,
                sender_name = excluded.sender_name,
                sender_email = excluded.sender_email,
                subject = excluded.subject,
                received_at = excluded.received_at,
                snippet = excluded.snippet,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                response["thread_id"],
                response["message_id"],
                response["sender_name"],
                response["sender_email"],
                response["subject"],
                response["received_at"],
                response["snippet"],
            ),
        )
    return exists is None


def list_responses() -> list[dict[str, Any]]:
    """Return tracked responses newest first."""
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT thread_id, message_id, sender_name, sender_email,
                   subject, received_at, snippet, tracking_status
            FROM venue_responses
            ORDER BY received_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]
