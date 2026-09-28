"""The owner transition preserves ordinary accounts and makes a backup."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from server.database import Database
from server.retire_legacy_admin import retire_legacy_admin
from server.seed import seed_users


class RetireLegacyAdminTests(unittest.TestCase):
    def test_admin_owned_channel_is_backed_up_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat.db"
            database = Database(path)
            seed_users(database, admin_username="admin", admin_password="password123",
                       sample_usernames=["alice"], sample_password="password123")
            with closing(database.connect()) as connection, connection:
                admin_id = connection.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
                alice_id = connection.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
                connection.execute(
                    "INSERT INTO channels(id,name,created_by,created_at) VALUES(?,?,?,?)",
                    ("old", "old-channel", admin_id, "2026-01-01T00:00:00+00:00"),
                )
                connection.execute(
                    "INSERT INTO channel_members(channel_id,user_id,joined_at) VALUES(?,?,?)",
                    ("old", alice_id, "2026-01-01T00:00:00+00:00"),
                )
                connection.execute(
                    """INSERT INTO messages(id,channel_id,sender_id,body,created_at,client_request_id)
                       VALUES(?,?,?,?,?,?)""",
                    ("old-message", "old", alice_id, "discardable", "2026-01-01T00:00:00+00:00", "old-request"),
                )
                connection.execute(
                    """INSERT INTO files(id,channel_id,uploader_id,original_name,storage_reference,
                       content_type,size_bytes,checksum_sha256,created_at,client_request_id)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    ("old-file", "old", alice_id, "old.txt", "old-storage", "text/plain", 1,
                     "0" * 64, "2026-01-01T00:00:00+00:00", "old-upload"),
                )
            admins, channels, backup = retire_legacy_admin(path)
            self.assertEqual((admins, channels), (1, 1))
            self.assertIsNotNone(backup)
            self.assertTrue(backup.exists())
            with closing(database.connect()) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM channels").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM files").fetchone()[0], 0)
            with closing(Database(backup).connect()) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM channels").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM files").fetchone()[0], 1)
            self.assertEqual(retire_legacy_admin(path)[:2], (0, 0))


if __name__ == "__main__":
    unittest.main()
