from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from common.errors import ApplicationError, ErrorCode
from server.application.auth import AuthApplication
from server.database import Database
from server.repositories.sqlite import SQLiteUnitOfWorkFactory
from server.seed import seed_users


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class AuthApplicationTests(unittest.TestCase):
    def test_expired_token_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "chat.db")
            seed_users(
                database,
                admin_username="admin",
                admin_password="admin-password-123",
                sample_usernames=["alice"],
                sample_password="sample-password-123",
            )
            clock = MutableClock(datetime(2026, 1, 1, tzinfo=UTC))
            auth = AuthApplication(
                SQLiteUnitOfWorkFactory(database),
                session_ttl_seconds=60,
                clock=clock,
                token_generator=lambda: "deterministic-test-token",
            )
            login = auth.login(
                "alice", "sample-password-123", request_id="login-request"
            )
            self.assertEqual(auth.authenticate(login.token, request_id="auth-1").username, "alice")
            clock.value += timedelta(seconds=61)
            with self.assertRaises(ApplicationError) as captured:
                auth.authenticate(login.token, request_id="auth-2")
            self.assertEqual(captured.exception.code, ErrorCode.UNAUTHENTICATED)
            self.assertIn("expired", captured.exception.message)


if __name__ == "__main__":
    unittest.main()

