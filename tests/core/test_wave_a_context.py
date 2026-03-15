from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import (
    MANIFEST_FILENAME,
    build_context_catalog,
    build_default_context_from_catalog,
    load_context_manifests,
)
from app.core.context import ContextService, build_context


class WaveAContextTests(unittest.TestCase):
    def test_context_service_defaults_to_none_system_when_no_systems_exist(self) -> None:
        service = ContextService()
        resolved = service.resolve()
        self.assertEqual(
            resolved,
            {
                "system_id": "none",
                "setting_id": "",
                "campaign_id": "",
            },
        )

    def test_context_service_resolves_precedence(self) -> None:
        service = ContextService(default_context=build_context(system_id="none"))
        resolved = service.resolve(
            system_defaults={"system_id": "cypher"},
            setting_defaults={"setting_id": "lands_of_legends"},
            session={"campaign_id": "session_campaign"},
            requested={"campaign_id": "requested_campaign"},
        )
        self.assertEqual(
            resolved,
            {
                "system_id": "cypher",
                "setting_id": "lands_of_legends",
                "campaign_id": "requested_campaign",
            },
        )

    def test_context_service_clear_to_level(self) -> None:
        service = ContextService(default_context=build_context(system_id="cypher"))
        context = build_context(
            system_id="cypher",
            setting_id="lands_of_legends",
            campaign_id="campaign_alpha",
        )
        self.assertEqual(
            service.clear_to_level(context, level="setting"),
            {
                "system_id": "cypher",
                "setting_id": "lands_of_legends",
                "campaign_id": "",
            },
        )
        self.assertEqual(
            service.clear_to_level(context, level="system"),
            {
                "system_id": "cypher",
                "setting_id": "",
                "campaign_id": "",
            },
        )

    def test_build_context_catalog_and_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            campaign_dir = root / "cypher" / "lands_of_legends" / "campaign_alpha"
            campaign_dir.mkdir(parents=True, exist_ok=True)

            (root / "cypher" / MANIFEST_FILENAME).write_text(
                json.dumps({"label": "Cypher System"}),
                encoding="utf-8",
            )
            (root / "cypher" / "lands_of_legends" / MANIFEST_FILENAME).write_text(
                json.dumps({"label": "Lands of Legends"}),
                encoding="utf-8",
            )
            (campaign_dir / MANIFEST_FILENAME).write_text(
                json.dumps({"label": "Campaign Alpha"}),
                encoding="utf-8",
            )

            catalog = build_context_catalog(root)
            self.assertEqual(
                catalog,
                {
                    "systems": {
                        "cypher": {
                            "settings": {
                                "lands_of_legends": {
                                    "campaigns": ["campaign_alpha"]
                                }
                            }
                        }
                    }
                },
            )

            default_context = build_default_context_from_catalog(catalog)
            self.assertEqual(
                default_context,
                {
                    "system_id": "cypher",
                    "setting_id": "lands_of_legends",
                    "campaign_id": "campaign_alpha",
                },
            )

            manifests = load_context_manifests(root, default_context)
            self.assertEqual(sorted(manifests.keys()), ["campaign", "setting", "system"])
            self.assertEqual(manifests["setting"]["label"], "Lands of Legends")


if __name__ == "__main__":
    unittest.main()
