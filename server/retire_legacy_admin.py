"""One-time, recoverable removal of the old global administrator account."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from common.config import load_settings
from server.database import Database, apply_migrations


def retire_legacy_admin(database_path: Path) -> tuple[int, int, Path | None]:
    database = Database(database_path)
    apply_migrations(database)
    source = database.connect()
    try:
        admins = [row["id"] for row in source.execute(
            "SELECT id FROM users WHERE role='admin'"
        )]
        if not admins:
            return 0, 0, None
        placeholders = ",".join("?" for _ in admins)
        owned = source.execute(
            f"SELECT id FROM channels WHERE created_by IN ({placeholders})", admins
        ).fetchall()
        owned_ids = [row["id"] for row in owned]
        # Do not discard data in a channel owned by an ordinary user.
        other_channels = source.execute(
            f"""SELECT COUNT(1) FROM channels WHERE created_by NOT IN ({placeholders})
                AND (id IN (SELECT channel_id FROM messages WHERE sender_id IN ({placeholders}))
                OR id IN (SELECT channel_id FROM files WHERE uploader_id IN ({placeholders})))""",
            (*admins, *admins, *admins),
        ).fetchone()[0]
        if other_channels:
            raise RuntimeError("legacy admin has content in another user's channel; manual review required")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = database_path.with_name(f"{database_path.stem}.before-owner-change-{stamp}.bak")
        suffix = 1
        while backup.exists():
            backup = database_path.with_name(
                f"{database_path.stem}.before-owner-change-{stamp}-{suffix}.bak"
            )
            suffix += 1
        with closing(sqlite3.connect(backup)) as target:
            source.backup(target)
        try:
            source.execute("BEGIN IMMEDIATE")
            for channel_id in owned_ids:
                source.execute("DELETE FROM channels WHERE id=?", (channel_id,))
            for admin_id in admins:
                source.execute("DELETE FROM channel_members WHERE user_id=?", (admin_id,))
                source.execute("DELETE FROM sessions WHERE user_id=?", (admin_id,))
                source.execute("DELETE FROM users WHERE id=?", (admin_id,))
            source.commit()
        except Exception:
            source.rollback()
            raise
        return len(admins), len(owned_ids), backup
    finally:
        source.close()


def main() -> int:
    settings = load_settings()
    admins, channels, backup = retire_legacy_admin(settings.chat_database_path)
    if backup:
        print(f"Retired {admins} legacy admin account(s) and {channels} owned channel(s).")
        print(f"Recoverable database backup: {backup}")
        print("Old uploaded bytes remain on disk but are no longer listed or accessible through the app.")
    else:
        print("No legacy admin account found; nothing to retire.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
