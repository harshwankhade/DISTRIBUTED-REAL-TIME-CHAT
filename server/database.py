"""SQLite connection and migration management for the chat server."""

from __future__ import annotations

import sqlite3
from pathlib import Path


MIGRATIONS_DIRECTORY = Path(__file__).resolve().parent / "migrations"


class Database:
    """Open configured SQLite connections with consistent safety settings."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        if str(self.path) != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
        return connection


def apply_migrations(database: Database) -> list[str]:
    """Apply each ordered SQL migration once and return newly applied names."""

    connection = database.connect()
    applied_now: list[str] = []
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied = {
            row["name"]
            for row in connection.execute("SELECT name FROM schema_migrations")
        }
        for migration_path in sorted(MIGRATIONS_DIRECTORY.glob("*.sql")):
            if migration_path.name in applied:
                continue
            with connection:
                connection.executescript(migration_path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(name) VALUES (?)",
                    (migration_path.name,),
                )
            applied_now.append(migration_path.name)
    finally:
        connection.close()
    return applied_now

