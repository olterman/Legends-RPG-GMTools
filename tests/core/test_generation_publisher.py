from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.generation import GenerationPublisher


class GenerationPublisherTests(unittest.TestCase):
    def _module_root(self, root: Path) -> Path:
        return root / "app" / "systems" / "cypher" / "addons" / "godforsaken" / "modules" / "land_of_legends"

    def _seed_region(self, module_root: Path, region_id: str, label: str) -> None:
        (module_root / "regions" / region_id).mkdir(parents=True, exist_ok=True)
        (module_root / "regions" / region_id / "manifest.json").write_text(
            json.dumps({"id": region_id, "label": label, "kind": "top_level_region", "status": "active"}),
            encoding="utf-8",
        )

    def test_publish_village_writes_manifest_and_central_lore(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module_root = self._module_root(root)
            self._seed_region(module_root, "fenmir_lowlands", "Fenmir Lowlands")
            publisher = GenerationPublisher(project_root=root)

            result = publisher.publish_settlement_like(
                kind="village",
                system_id="cypher",
                addon_id="godforsaken",
                module_id="land_of_legends",
                region_id="fenmir_lowlands",
                subregion_id="",
                title="Black Reed Ford",
                summary="A muddy river village shaped by wary trade and old scars.",
                markdown_body="## Overview\nBlack Reed Ford watches the ford and mistrusts easy promises.",
                provider_id="ollama_local",
            )

            self.assertTrue(result.manifest_path.exists())
            self.assertTrue(result.lore_path.exists())
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["id"], "black_reed_ford")
            self.assertEqual(manifest["kind"], "village")
            self.assertEqual(manifest["summary"], "A muddy river village shaped by wary trade and old scars.")
            self.assertEqual(manifest["source_refs"], ["generated:ollama_local"])
            lore_text = result.lore_path.read_text(encoding="utf-8")
            self.assertIn("# Black Reed Ford", lore_text)
            self.assertIn("Black Reed Ford watches the ford", lore_text)
            self.assertIn("/regions/fenmir_lowlands/villages/black_reed_ford", result.ui_url)

    def test_publish_region_and_subregion_work(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module_root = self._module_root(root)
            module_root.mkdir(parents=True, exist_ok=True)
            publisher = GenerationPublisher(project_root=root)

            region = publisher.publish_region(
                system_id="cypher",
                addon_id="godforsaken",
                module_id="land_of_legends",
                title="Ash Coast",
                summary="A bleak wind-battered coast.",
                markdown_body="## Overview\nAsh Coast is bleak and salt-bitten.",
                provider_id="ollama_local",
            )
            self.assertTrue(region.manifest_path.exists())
            self.assertIn("/regions/ash_coast", region.ui_url)

            subregion = publisher.publish_subregion(
                system_id="cypher",
                addon_id="godforsaken",
                module_id="land_of_legends",
                region_id="ash_coast",
                title="The Black Reach",
                summary="A hard reach under cinder skies.",
                markdown_body="## Overview\nThe Black Reach gathers smoke and old fear.",
                provider_id="ollama_local",
            )
            self.assertTrue(subregion.manifest_path.exists())
            self.assertIn("/regions/ash_coast/subregions/the_black_reach", subregion.ui_url)

    def test_publish_city_and_inn_work(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module_root = self._module_root(root)
            self._seed_region(module_root, "fenmir_free_cities", "Fenmir Free Cities")
            publisher = GenerationPublisher(project_root=root)

            city = publisher.publish_settlement_like(
                kind="city",
                system_id="cypher",
                addon_id="godforsaken",
                module_id="land_of_legends",
                region_id="fenmir_free_cities",
                subregion_id="",
                title="Greyhaven",
                summary="A port city of rope, contracts, and grudges.",
                markdown_body="## Overview\nGreyhaven lives by tides and bargains.",
                provider_id="ollama_local",
            )
            self.assertTrue(city.manifest_path.exists())

            inn = publisher.publish_inn(
                system_id="cypher",
                addon_id="godforsaken",
                module_id="land_of_legends",
                region_id="fenmir_free_cities",
                subregion_id="",
                parent_collection="cities",
                parent_id="greyhaven",
                title="The Rope And Lantern",
                summary="A harborside inn for captains and liars.",
                markdown_body="## Overview\nThe Rope and Lantern never truly sleeps.",
                provider_id="ollama_local",
            )
            self.assertTrue(inn.manifest_path.exists())
            self.assertIn("/cities/greyhaven/inns/the_rope_and_lantern", inn.ui_url)
