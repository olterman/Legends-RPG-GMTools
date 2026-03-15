from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.core.search import VectorIndexService


class VectorIndexServiceTests(unittest.TestCase):
    def test_build_and_query_indexes_new_hierarchy_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lore_root = root / "app" / "systems" / "cypher" / "addons" / "godforsaken" / "modules" / "land_of_legends" / "lore"
            lore_root.mkdir(parents=True, exist_ok=True)
            (lore_root / "overview.md").write_text(
                "# Land of Legends\n\nThe Whisper Salt Oath binds speakers to truth before the old waters.",
                encoding="utf-8",
            )
            manifest_root = root / "app" / "systems" / "cypher" / "addons" / "godforsaken" / "modules" / "land_of_legends" / "regions" / "caldor_island"
            manifest_root.mkdir(parents=True, exist_ok=True)
            (manifest_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "caldor_island",
                        "label": "Caldor Island",
                        "kind": "top_level_region",
                        "summary": "A mountainous island realm of high valleys and hidden roads.",
                    }
                ),
                encoding="utf-8",
            )
            legacy_root = root / "lore" / "entries"
            legacy_root.mkdir(parents=True, exist_ok=True)
            (legacy_root / "legacy_only.md").write_text("This should never be indexed.", encoding="utf-8")

            service = VectorIndexService(project_root=root)
            stats = service.build()

            self.assertTrue(stats["exists"])
            self.assertGreaterEqual(stats["document_count"], 2)
            self.assertIn("module_lore", stats["source_counts"])
            self.assertIn("module_manifest", stats["source_counts"])

            items = service.query(q="Whisper Salt Oath", filters={"system_id": "cypher", "module_id": "land_of_legends"})
            self.assertTrue(items)
            self.assertTrue(any(item["source_kind"] == "module_lore" for item in items))
            self.assertFalse(any("legacy_only" in item["source_path"] for item in items))
