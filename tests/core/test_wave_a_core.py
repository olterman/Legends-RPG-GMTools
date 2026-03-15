from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.contracts import build_record, validate_record
from app.core.storage import FileRecordStore


class WaveACoreTests(unittest.TestCase):
    def test_validate_record_normalizes_context_and_source(self) -> None:
        record = build_record(
            record_type="lore_entry",
            title="The Red Gate",
            slug="The Red Gate",
            system_id="None",
            setting_id="Lands of Legends",
            source={"kind": "local", "origin": "user"},
            metadata={"summary": "Ancient gate ruin", "tags": ["gate", "ruins"]},
            content={"body": "A shattered gate stands on the ridge."},
        )

        validated = validate_record(record)

        self.assertEqual(validated["slug"], "the_red_gate")
        self.assertEqual(validated["context"]["system_id"], "none")
        self.assertEqual(validated["context"]["setting_id"], "lands_of_legends")
        self.assertEqual(validated["source"]["kind"], "local")
        self.assertEqual(validated["metadata"]["summary"], "Ancient gate ruin")

    def test_validate_record_rejects_unknown_top_level_keys(self) -> None:
        record = build_record(record_type="generic_note", title="Hello")
        record["environment"] = "fenmir"
        with self.assertRaisesRegex(ValueError, "unsupported top-level record keys"):
            validate_record(record)

    def test_validate_record_requires_setting_if_campaign_present(self) -> None:
        record = build_record(
            record_type="generic_note",
            title="Bad Context",
            campaign_id="campaign_alpha",
        )
        with self.assertRaisesRegex(ValueError, "campaign_id requires"):
            validate_record(record)

    def test_file_record_store_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = FileRecordStore(Path(td))
            created = store.create(
                build_record(
                    record_type="lore_entry",
                    title="Fenmir Watchtower",
                    system_id="none",
                    setting_id="lands_of_legends",
                    metadata={"summary": "A lonely tower in the north", "tags": ["tower", "fenmir"]},
                    content={"body": "It watches the old road."},
                )
            )

            fetched = store.get(created["id"])
            self.assertEqual(fetched["title"], "Fenmir Watchtower")

            updated_payload = dict(fetched)
            updated_payload["metadata"] = dict(fetched["metadata"])
            updated_payload["metadata"]["summary"] = "An old tower guarding the road"
            updated = store.update(created["id"], updated_payload)
            self.assertEqual(updated["metadata"]["summary"], "An old tower guarding the road")

            listed = store.list(filters={"setting_id": "lands_of_legends"})
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["id"], created["id"])

            searched = store.search("guarding the road", filters={"type": "lore_entry"})
            self.assertEqual(len(searched), 1)
            self.assertEqual(searched[0]["id"], created["id"])

            deleted = store.delete(created["id"])
            self.assertEqual(deleted["status"], "trashed")
            self.assertEqual(store.list(), [])

            restored = store.restore(created["id"])
            self.assertEqual(restored["status"], "active")
            self.assertEqual(len(store.list()), 1)

            store.delete(created["id"])
            expunged = store.expunge(created["id"])
            self.assertEqual(expunged["status"], "expunged")
            with self.assertRaises(FileNotFoundError):
                store.get(created["id"])

    def test_file_record_store_rejects_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = FileRecordStore(Path(td))
            record = build_record(record_type="generic_note", title="One", record_id="rec_fixed")
            store.create(record)
            with self.assertRaises(FileExistsError):
                store.create(record)


if __name__ == "__main__":
    unittest.main()
