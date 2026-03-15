from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.auth import (
    DEFAULT_ROLE,
    AuthService,
    hash_password,
    normalize_email,
    normalize_role,
    verify_password,
)


class AuthServiceTests(unittest.TestCase):
    def test_password_hash_roundtrip(self) -> None:
        encoded = hash_password("correct horse battery staple")
        self.assertNotEqual(encoded, "correct horse battery staple")
        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("wrong password", encoded))

    def test_normalize_role_defaults_and_validates(self) -> None:
        self.assertEqual(normalize_role("GM"), "gm")
        self.assertEqual(normalize_role("OWNER"), "owner")
        self.assertEqual(normalize_role(""), DEFAULT_ROLE)
        with self.assertRaisesRegex(ValueError, "unsupported role"):
            normalize_role("admin")

    def test_normalize_email_requires_at_symbol(self) -> None:
        self.assertEqual(normalize_email("Patrik@Olterman.se "), "patrik@olterman.se")
        with self.assertRaisesRegex(ValueError, "valid email is required"):
            normalize_email("not-an-email")

    def test_create_user_and_authenticate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            service = AuthService(Path(td) / "gmforge.db")
            user = service.create_user(
                username="Game Master",
                email="gm@example.com",
                display_name="Game Master",
                password="correct horse battery staple",
                role="gm",
            )

            self.assertEqual(user.username, "game_master")
            self.assertEqual(user.email, "gm@example.com")
            self.assertEqual(user.role, "gm")

            fetched = service.get_user_by_username("game master")
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.id, user.id)

            authed = service.authenticate(
                username="game_master",
                password="correct horse battery staple",
            )
            self.assertIsNotNone(authed)
            self.assertEqual(authed.id, user.id)

            denied = service.authenticate(username="game_master", password="wrong password")
            self.assertIsNone(denied)

    def test_create_user_rejects_duplicate_username(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            service = AuthService(Path(td) / "gmforge.db")
            service.create_user(
                username="player_one",
                email="player@example.com",
                display_name="Player One",
                password="verysecurepass",
            )
            with self.assertRaisesRegex(ValueError, "user already exists"):
                service.create_user(
                    username="player one",
                    email="other@example.com",
                    display_name="Duplicate",
                    password="verysecurepass",
                )

    def test_ensure_user_returns_existing_seed_user(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            service = AuthService(Path(td) / "gmforge.db")
            first = service.ensure_user(
                username="olterman",
                email="patrik@olterman.se",
                display_name="Patrik Olterman",
                password="changeme",
                role="owner",
            )
            second = service.ensure_user(
                username="olterman",
                email="someone@example.com",
                display_name="Different Name",
                password="differentpass",
                role="player",
            )
            self.assertEqual(first.id, second.id)
            self.assertEqual(second.role, "owner")
            self.assertEqual(second.email, "patrik@olterman.se")

    def test_session_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            service = AuthService(Path(td) / "gmforge.db")
            user = service.create_user(
                username="player_one",
                email="player@example.com",
                display_name="Player One",
                password="verysecurepass",
                role="player",
            )
            session = service.create_session(user_id=user.id, ttl_hours=1)
            self.assertEqual(session.user_id, user.id)

            loaded = service.get_session(session.id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.id, session.id)

            revoked = service.revoke_session(session.id)
            self.assertEqual(revoked["id"], session.id)
            self.assertIsNone(service.get_session(session.id))


if __name__ == "__main__":
    unittest.main()
