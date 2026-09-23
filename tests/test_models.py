from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from domain.models import Message, Session


class DomainModelTests(unittest.TestCase):
    def test_message_requires_utc_timestamp(self) -> None:
        with self.assertRaisesRegex(ValueError, "created_at"):
            Message(
                id="message-1",
                channel_id="channel-1",
                sender_id="user-1",
                body="hello",
                created_at=datetime.now(),
                client_request_id="request-1",
            )

    def test_session_expiry_must_follow_creation(self) -> None:
        created_at = datetime.now(UTC)
        with self.assertRaisesRegex(ValueError, "expires_at"):
            Session(
                id="session-1",
                user_id="user-1",
                token_hash="not-a-plain-token",
                created_at=created_at,
                expires_at=created_at - timedelta(seconds=1),
            )


if __name__ == "__main__":
    unittest.main()

