from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.generation import GenerationRequest, GenerationService
from app.core.plugins import PluginService
from app.core.search import VectorIndexService


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class GenerationServiceTests(unittest.TestCase):
    def test_plugin_service_merges_secret_settings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app" / "plugins" / "openai_remote").mkdir(parents=True, exist_ok=True)
            (root / "app" / "plugins" / "openai_remote" / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "openai_remote",
                        "name": "OpenAI Remote",
                        "status": "active",
                        "bundled": True,
                        "enabled_by_default": True,
                    }
                ),
                encoding="utf-8",
            )
            (root / "config").mkdir(parents=True, exist_ok=True)
            (root / "config" / "plugins_settings.json").write_text(
                json.dumps({"openai_remote": {"base_url": "https://api.openai.com"}}),
                encoding="utf-8",
            )
            (root / "data" / "plugins").mkdir(parents=True, exist_ok=True)
            (root / "data" / "plugins" / "plugin_secrets.json").write_text(
                json.dumps({"openai_remote": {"api_key": "secret-token"}}),
                encoding="utf-8",
            )
            plugin_service = PluginService(project_root=root)

            settings = plugin_service.load_plugin_settings("openai_remote")

            self.assertEqual(settings["base_url"], "https://api.openai.com")
            self.assertEqual(settings["api_key"], "secret-token")

    def test_plugin_providers_are_loaded(self) -> None:
        service = GenerationService(
            vector_service=VectorIndexService(project_root=PROJECT_ROOT, index_root=PROJECT_ROOT / "data" / "vector_index"),
            plugin_service=PluginService(project_root=PROJECT_ROOT),
        )

        provider_ids = {item["id"] for item in service.list_providers()}

        self.assertIn("local_structured_draft", provider_ids)
        self.assertIn("openai_remote", provider_ids)
        self.assertIn("ollama_local", provider_ids)

    @patch.dict(
        "os.environ",
        {"OPENAI_API_KEY": "test-key"},
        clear=False,
    )
    @patch("app.plugins.openai_remote.provider.urllib_request.urlopen")
    def test_openai_provider_builds_generated_body(self, mock_urlopen) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "# Black Reed Ford\n\n## Overview\nA river village shaped by reeds and hard trade."
                        }
                    }
                ]
            }
        )
        service = GenerationService(
            vector_service=VectorIndexService(project_root=PROJECT_ROOT, index_root=PROJECT_ROOT / "data" / "vector_index"),
            plugin_service=PluginService(project_root=PROJECT_ROOT),
        )

        result = service.build_draft(
            GenerationRequest(
                title="Black Reed Ford",
                record_type="village",
                system_id="cypher",
                addon_id="godforsaken",
                setting_id="land_of_legends",
                campaign_id="",
                focus_query="new village in fenmir lowlands",
                notes="poor frontier river village",
                source_kind="module_lore",
                provider_id="openai_remote",
            )
        )

        self.assertEqual(result["provider_id"], "openai_remote")
        self.assertIn("Black Reed Ford", result["proposed_record"]["body"])
        self.assertTrue(mock_urlopen.called)

    @patch("app.plugins.ollama_local.provider.urllib_request.urlopen")
    def test_ollama_provider_builds_generated_body(self, mock_urlopen) -> None:
        mock_urlopen.return_value = _FakeHTTPResponse(
            {
                "response": "# Mirewatch\n\n## Overview\nA sodden Fenmir settlement built on raised timber and river superstition."
            }
        )
        service = GenerationService(
            vector_service=VectorIndexService(project_root=PROJECT_ROOT, index_root=PROJECT_ROOT / "data" / "vector_index"),
            plugin_service=PluginService(project_root=PROJECT_ROOT),
        )

        result = service.build_draft(
            GenerationRequest(
                title="Mirewatch",
                record_type="village",
                system_id="cypher",
                addon_id="godforsaken",
                setting_id="land_of_legends",
                campaign_id="",
                focus_query="new village in fenmir lowlands",
                notes="muddy river crossing",
                source_kind="module_lore",
                provider_id="ollama_local",
            )
        )

        self.assertEqual(result["provider_id"], "ollama_local")
        self.assertIn("Mirewatch", result["proposed_record"]["body"])
        self.assertTrue(mock_urlopen.called)
