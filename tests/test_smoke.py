from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lol_api.lore import (
    expunge_trashed_lore_item,
    list_trashed_lore_items,
    load_lore_index,
    restore_trashed_lore_item,
    trash_lore_item,
    update_lore_item,
)
from lol_api.storage import (
    expunge_trashed_result,
    list_saved_results,
    list_trashed_results,
    restore_trashed_result,
    save_generated_result,
    search_saved_results,
    trash_saved_result,
    update_saved_result,
)


class SmokeTests(unittest.TestCase):
    def test_setting_world_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save_generated_result(
                root,
                {
                    "type": "npc",
                    "name": "Fenmir Scout",
                    "metadata": {
                        "settings": ["fantasy", "lands_of_legends"],
                        "area": "fenmir_highlands",
                    },
                },
                {},
            )
            save_generated_result(
                root,
                {
                    "type": "npc",
                    "name": "Neon Agent",
                    "metadata": {
                        "settings": ["cyberpunk"],
                        "area": "neon_district",
                    },
                },
                {},
            )

            filtered = search_saved_results(
                root,
                setting="fantasy",
                area="fenmir_highlands",
            )
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0]["name"], "Fenmir Scout")

            legacy_alias = search_saved_results(
                root,
                setting="fantasy",
                environment="fenmir_highlands",
            )
            self.assertEqual(len(legacy_alias), 1)
            self.assertEqual(legacy_alias[0]["name"], "Fenmir Scout")

    def test_storage_edit_delete_trash_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            saved_path = save_generated_result(
                root,
                {
                    "type": "monster",
                    "name": "Ash Warden",
                    "metadata": {"settings": ["fantasy"], "area": "caldor"},
                },
                {"seed": "abc"},
            )
            filename = str(saved_path.relative_to(root)).replace("\\", "/")

            record = json.loads(saved_path.read_text(encoding="utf-8"))
            record["result"]["name"] = "Ash Warden Prime"
            update_saved_result(root, filename, record)

            listed = list_saved_results(root)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["name"], "Ash Warden Prime")

            moved = trash_saved_result(root, filename)
            self.assertTrue(moved["trash_filename"].endswith(".json"))
            self.assertEqual(len(list_saved_results(root)), 0)
            self.assertEqual(len(list_trashed_results(root)), 1)

            restore_trashed_result(root, moved["trash_filename"])
            self.assertEqual(len(list_saved_results(root)), 1)

            moved_again = trash_saved_result(root, filename)
            expunge_trashed_result(root, moved_again["trash_filename"])
            self.assertEqual(len(list_trashed_results(root)), 0)

    def test_lore_index_consistency_after_edits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lore_root = Path(td)
            entries_dir = lore_root / "entries"
            entries_dir.mkdir(parents=True, exist_ok=True)

            entry = {
                "type": "lore",
                "title": "Ancient Gate",
                "slug": "ancient_gate",
                "source": "local",
                "source_path": "logseq/pages/Ancient Gate.md",
                "excerpt": "Old and mysterious.",
                "categories": ["area"],
                "mentions_total": 1,
                "content_markdown": "# Ancient Gate",
                "settings": ["fantasy", "lands_of_legends"],
                "setting": "lands_of_legends",
            }
            (entries_dir / "ancient_gate.json").write_text(
                json.dumps(entry, indent=2),
                encoding="utf-8",
            )
            (lore_root / "index.json").write_text(
                json.dumps(
                    {
                        "count": 1,
                        "items": [
                            {
                                "title": entry["title"],
                                "slug": entry["slug"],
                                "source_path": entry["source_path"],
                                "excerpt": entry["excerpt"],
                                "categories": entry["categories"],
                                "mentions_total": entry["mentions_total"],
                                "settings": entry["settings"],
                                "setting": entry["setting"],
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            updated = update_lore_item(lore_root, "ancient_gate", {**entry, "title": "Ancient Gate Revised"})
            self.assertEqual(updated["title"], "Ancient Gate Revised")
            idx = load_lore_index(lore_root)
            self.assertEqual(idx["count"], 1)
            self.assertEqual(idx["items"][0]["title"], "Ancient Gate Revised")

            trash_lore_item(lore_root, "ancient_gate")
            self.assertEqual(load_lore_index(lore_root)["count"], 0)
            self.assertEqual(len(list_trashed_lore_items(lore_root)), 1)

            restore_trashed_lore_item(lore_root, "ancient_gate")
            self.assertEqual(load_lore_index(lore_root)["count"], 1)

            trash_lore_item(lore_root, "ancient_gate")
            expunge_trashed_lore_item(lore_root, "ancient_gate")
            self.assertEqual(len(list_trashed_lore_items(lore_root)), 0)

    def test_location_lore_requires_area(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lore_root = Path(td)
            entries_dir = lore_root / "entries"
            entries_dir.mkdir(parents=True, exist_ok=True)
            entry = {
                "type": "lore",
                "title": "Starfall Keep",
                "slug": "starfall_keep",
                "categories": ["city", "location"],
                "content_markdown": "# Starfall Keep",
            }
            (entries_dir / "starfall_keep.json").write_text(
                json.dumps(entry, indent=2),
                encoding="utf-8",
            )
            (lore_root / "index.json").write_text(json.dumps({"count": 0, "items": []}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "location entries require area"):
                update_lore_item(lore_root, "starfall_keep", entry)


if __name__ == "__main__":
    unittest.main()
