from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from common.metadata import utc_now
from domain.models import Channel, ChannelMember, Session, User, UserRole, UserStatus
from server.database import Database, apply_migrations
from server.repositories.sqlite import SQLiteUnitOfWorkFactory


class SQLiteRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "chat.db"
        self.database = Database(self.database_path)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_migration_is_repeatable(self) -> None:
        self.assertEqual(apply_migrations(self.database), ["001_initial.sql"])
        self.assertEqual(apply_migrations(self.database), [])
        connection = self.database.connect()
        try:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            connection.close()
        self.assertTrue(
            {"schema_migrations", "users", "sessions", "channels", "channel_members"}
            <= tables
        )

    def test_users_sessions_channels_and_memberships_survive_reopen(self) -> None:
        apply_migrations(self.database)
        factory = SQLiteUnitOfWorkFactory(self.database)
        now = utc_now()
        user = User("user-1", "alice", UserRole.USER, UserStatus.ACTIVE, now)
        channel = Channel("channel-1", "general", user.id, now)
        session = Session(
            "session-1",
            user.id,
            "hashed-token",
            now,
            now + timedelta(hours=1),
        )
        with factory() as unit_of_work:
            unit_of_work.users.add(user, "encoded-password")
            unit_of_work.sessions.add(session)
            unit_of_work.channels.add(channel)
            unit_of_work.channels.add_member(ChannelMember(channel.id, user.id, now))
            unit_of_work.commit()

        reopened_factory = SQLiteUnitOfWorkFactory(Database(self.database_path))
        with reopened_factory() as unit_of_work:
            self.assertEqual(unit_of_work.users.get(user.id).user, user)
            self.assertEqual(
                unit_of_work.sessions.get_by_token_hash("hashed-token"), session
            )
            self.assertEqual(unit_of_work.channels.get(channel.id), channel)
            self.assertTrue(unit_of_work.channels.is_member(channel.id, user.id))


if __name__ == "__main__":
    unittest.main()

