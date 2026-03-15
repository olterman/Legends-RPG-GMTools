from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.contracts import (
    CAMPAIGN_LORE_FILE_ORDER,
    MODULE_LORE_FILE_ORDER,
    build_inn_manifest,
    build_region_manifest,
    build_settlement_manifest,
    build_subregion_manifest,
    lore_sort_key,
    validate_authored_manifest,
    validate_inn_manifest,
    validate_settlement_manifest,
)


class ContentSchemaTests(unittest.TestCase):
    def test_region_manifest_normalizes_core_fields(self) -> None:
        manifest = build_region_manifest(
            manifest_id="Caldor Island",
            label="Caldor Island",
            status="Planned",
            summary="Island realm",
            notes="Base authored region",
        )

        validated = validate_authored_manifest(manifest)

        self.assertEqual(validated["id"], "caldor_island")
        self.assertEqual(validated["kind"], "top_level_region")
        self.assertEqual(validated["status"], "planned")

    def test_subregion_manifest_dispatches_cleanly(self) -> None:
        manifest = build_subregion_manifest(
            manifest_id="The Vale",
            label="The Vale",
            summary="Hidden basin",
        )

        validated = validate_authored_manifest(manifest)

        self.assertEqual(validated["kind"], "subregion")
        self.assertEqual(validated["label"], "The Vale")

    def test_settlement_manifest_rejects_unknown_detail_keys(self) -> None:
        manifest = build_settlement_manifest(
            manifest_id="Lake Home",
            label="Lake Home",
            details={"notable_inn": "The Sizzling Trout", "proprietor": "Nope"},
        )

        with self.assertRaisesRegex(ValueError, "unsupported settlement detail keys"):
            validate_settlement_manifest(manifest)

    def test_settlement_manifest_normalizes_canonical_detail_keys(self) -> None:
        manifest = build_settlement_manifest(
            manifest_id="Mountain Home",
            label="Mountain Home",
            details={
                "notable_inn": "The Lucky Pick",
                "economy": "Mining and herding",
                "culture": "Old mountain customs",
            },
        )

        validated = validate_settlement_manifest(manifest)

        self.assertEqual(
            set(validated["details"].keys()),
            {"notable_inn", "economy", "culture"},
        )

    def test_inn_manifest_normalizes_canonical_detail_keys(self) -> None:
        manifest = build_inn_manifest(
            manifest_id="The Sizzling Trout",
            label="The Sizzling Trout",
            details={
                "proprietor": "Amelia Greenheart",
                "atmosphere": "Warm and lively",
                "clientele": "Fishers and farmers",
                "notable_feature": "Grilled trout",
                "rumor_or_hook": "Wish fish tale",
            },
            source_refs=["storage/inn/inn_20260314T162854.json"],
        )

        validated = validate_inn_manifest(manifest)

        self.assertEqual(validated["id"], "the_sizzling_trout")
        self.assertEqual(
            set(validated["details"].keys()),
            {"proprietor", "atmosphere", "clientele", "notable_feature", "rumor_or_hook"},
        )
        self.assertEqual(validated["source_refs"], ["storage/inn/inn_20260314T162854.json"])

    def test_inn_manifest_rejects_unknown_detail_keys(self) -> None:
        manifest = build_inn_manifest(
            manifest_id="The Lucky Pick",
            label="The Lucky Pick",
            details={"proprietor": "Kirk", "reputation": "Wrong schema"},
        )

        with self.assertRaisesRegex(ValueError, "unsupported inn detail keys"):
            validate_inn_manifest(manifest)

    def test_lore_layout_contract_exposes_expected_file_orders(self) -> None:
        self.assertEqual(
            MODULE_LORE_FILE_ORDER,
            [
                "overview.md",
                "history.md",
                "culture.md",
                "religion.md",
                "politics.md",
                "relationships.md",
                "secrets.md",
            ],
        )
        self.assertEqual(
            CAMPAIGN_LORE_FILE_ORDER,
            [
                "overview.md",
                "gm_notes.md",
                "adventure_hooks.md",
                "session_notes.md",
                "reveals.md",
                "changes.md",
            ],
        )

    def test_lore_sort_key_prefers_canonical_module_order(self) -> None:
        ordered = sorted(
            ["secrets.md", "culture.md", "overview.md", "notes.md"],
            key=lore_sort_key,
        )
        self.assertEqual(
            ordered,
            ["overview.md", "culture.md", "secrets.md", "notes.md"],
        )


if __name__ == "__main__":
    unittest.main()
