"""Command-line entry point for applying SQLite migrations."""

from __future__ import annotations

from common.config import ConfigurationError, load_settings
from common.logging import configure_logging
from server.database import Database, apply_migrations


def main() -> int:
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        raise SystemExit(f"configuration error: {exc}") from exc
    logger = configure_logging(
        service="database-migrate",
        node_id=settings.chat_node_id,
        level=settings.log_level,
    )
    applied = apply_migrations(Database(settings.chat_database_path))
    logger.info(
        "migrations_complete",
        extra={
            "database_path": str(settings.chat_database_path),
            "applied_migrations": applied,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

