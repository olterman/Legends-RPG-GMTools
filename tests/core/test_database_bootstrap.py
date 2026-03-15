from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import CURRENT_SCHEMA_VERSION, DatabaseManager, ensure_database


class DatabaseBootstrapTests(unittest.TestCase):
    def test_ensure_database_creates_schema_and_tracks_version(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "gmforge.db"
            result = ensure_database(db_path)

            self.assertTrue(db_path.exists())
            self.assertTrue(result.created)
            self.assertEqual(result.current_version, CURRENT_SCHEMA_VERSION)
            self.assertEqual(result.applied_versions, [1, 2])

            inspection = DatabaseManager(db_path).inspect()
            self.assertTrue(inspection["exists"])
            self.assertEqual(inspection["current_version"], CURRENT_SCHEMA_VERSION)
            self.assertIn("users", inspection["tables"])
            self.assertIn("auth_sessions", inspection["tables"])
            self.assertIn("audit_events", inspection["tables"])
            self.assertIn("tags", inspection["tables"])
            self.assertIn("entity_tags", inspection["tables"])
            self.assertIn("entity_links", inspection["tables"])
            self.assertIn("schema_migrations", inspection["tables"])

    def test_ensure_database_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "gmforge.db"
            first = ensure_database(db_path)
            second = ensure_database(db_path)

            self.assertEqual(first.current_version, CURRENT_SCHEMA_VERSION)
            self.assertEqual(second.current_version, CURRENT_SCHEMA_VERSION)
            self.assertFalse(second.created)
            self.assertEqual(second.applied_versions, [1, 2])


if __name__ == "__main__":
    unittest.main()
