from __future__ import annotations

import unittest

from server.security.passwords import hash_password, verify_password
from server.security.tokens import generate_session_token, hash_session_token


class PasswordSecurityTests(unittest.TestCase):
    def test_password_hashes_are_salted_and_verifiable(self) -> None:
        password = "correct-horse-battery-staple"
        first = hash_password(password)
        second = hash_password(password)
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password(password, first))
        self.assertFalse(verify_password("wrong-password", first))

    def test_short_password_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 12"):
            hash_password("short")

    def test_session_tokens_are_random_and_stored_as_hashes(self) -> None:
        first = generate_session_token()
        second = generate_session_token()
        self.assertNotEqual(first, second)
        self.assertNotEqual(hash_session_token(first), first)
        self.assertEqual(len(hash_session_token(first)), 64)


if __name__ == "__main__":
    unittest.main()

