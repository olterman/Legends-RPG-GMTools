from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.app import discover_systems


class SystemLoaderTests(unittest.TestCase):
    def test_discover_systems_returns_empty_list_for_empty_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            systems = discover_systems(Path(td))
            self.assertEqual(systems, [])

    def test_discover_systems_reads_system_and_addon_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            system_dir = root / "mist_engine"
            addon_dir = system_dir / "addons" / "city_of_mist"
            content_types_dir = system_dir / "content_types"
            addon_dir.mkdir(parents=True, exist_ok=True)
            content_types_dir.mkdir(parents=True, exist_ok=True)

            (system_dir / "system.json").write_text(
                json.dumps(
                    {
                        "id": "mist_engine",
                        "name": "Mist Engine",
                        "engine": "mist_engine",
                        "status": "planned",
                        "summary": "System shell",
                        "content_roots": ["core_rules", "addons"],
                        "default_types": ["character_record"],
                        "supports_addons": True,
                    }
                ),
                encoding="utf-8",
            )
            (content_types_dir / "content_types.json").write_text(
                json.dumps(
                    {
                        "system_id": "mist_engine",
                        "types": [
                            {
                                "id": "theme_record",
                                "label": "Theme",
                                "category": "rules",
                                "summary": "Theme record",
                                "supports_generation": False,
                                "supports_search": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (addon_dir / "addon.json").write_text(
                json.dumps(
                    {
                        "id": "city_of_mist",
                        "system_id": "mist_engine",
                        "name": "City of Mist",
                        "status": "planned",
                        "summary": "Addon shell",
                        "kind": "title",
                    }
                ),
                encoding="utf-8",
            )
            (addon_dir / "rulebook.json").write_text(
                json.dumps(
                    {
                        "id": "city_of_mist_core",
                        "system_id": "mist_engine",
                        "addon_id": "city_of_mist",
                        "title": "City of Mist Core",
                        "markdown_path": "source_markdown/city-of-mist.md",
                        "html_path": "source_html/city-of-mist.html",
                        "source_path": "source/city-of-mist.pdf",
                        "format": "markdown",
                        "generated_toc": True,
                    }
                ),
                encoding="utf-8",
            )

            systems = discover_systems(root)
            self.assertEqual(len(systems), 1)
            self.assertEqual(systems[0]["id"], "mist_engine")
            self.assertEqual(systems[0]["content_types"][0]["id"], "theme_record")
            self.assertEqual(len(systems[0]["addons"]), 1)
            self.assertEqual(systems[0]["addons"][0]["id"], "city_of_mist")
            self.assertEqual(systems[0]["addons"][0]["rulebooks"][0]["id"], "city_of_mist_core")
            self.assertEqual(
                systems[0]["addons"][0]["rulebooks"][0]["html_path"],
                "source_html/city-of-mist.html",
            )

    def test_discover_systems_reads_repo_scaffold(self) -> None:
        systems = discover_systems(PROJECT_ROOT / "app" / "systems")
        by_id = {item["id"]: item for item in systems}

        self.assertIn("cypher", by_id)
        self.assertIn("mist_engine", by_id)
        self.assertIn("savage_worlds", by_id)
        self.assertIn("outgunned", by_id)
        self.assertIn("daggerheart", by_id)

        self.assertEqual(
            sorted(item["id"] for item in by_id["cypher"]["content_types"]),
            [
                "ability_record",
                "artifact_record",
                "character_sheet",
                "creature_record",
                "cypher_record",
                "descriptor_record",
                "focus_record",
                "npc_record",
                "type_record",
            ],
        )
        self.assertEqual(
            sorted(addon["id"] for addon in by_id["cypher"]["addons"]),
            ["csrd"],
        )
        self.assertEqual(
            by_id["cypher"]["addons"][0]["rulebooks"][0]["id"],
            "cypher_system_reference_document",
        )

        self.assertEqual(
            sorted(addon["id"] for addon in by_id["mist_engine"]["addons"]),
            ["city_of_mist", "legends_in_the_mist", "otherscape"],
        )
        self.assertEqual(
            sorted(addon["id"] for addon in by_id["savage_worlds"]["addons"]),
            ["savage_pathfinder", "savage_rifts", "secret_world", "starbreaker"],
        )
        self.assertEqual(
            sorted(addon["id"] for addon in by_id["outgunned"]["addons"]),
            ["action_flicks_80s", "action_flicks_hong_kong", "adventure", "superheroes"],
        )


if __name__ == "__main__":
    unittest.main()
