from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.auth import AuthService
from app.core.content import ContentService
from app.systems.cypher.addons.csrd import (
    import_csrd_descriptor_file,
    import_csrd_descriptor_markdown_file,
    import_csrd_descriptors,
)


class CsrdDescriptorImporterTests(unittest.TestCase):
    def test_import_single_descriptor_file_creates_core_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "gmforge.db"
            data_root = root / "data"
            auth = AuthService(db_path)
            user = auth.create_user(
                username="gm_one",
                email="gm@example.com",
                display_name="GM One",
                password="verysecurepass",
                role="gm",
            )
            content = ContentService(data_root=data_root, db_path=db_path)

            result = import_csrd_descriptor_file(
                PROJECT_ROOT / "CSRD" / "compendium" / "descriptors" / "charming.json",
                content_service=content,
                actor_user_id=user.id,
            )

            self.assertEqual(result["id"], "cypher_csrd_descriptor_charming")
            self.assertEqual(result["type"], "descriptor_record")
            self.assertEqual(result["system"]["id"], "cypher")
            self.assertEqual(result["system"]["addon_id"], "csrd")
            self.assertEqual(result["source"]["kind"], "addon_pack")
            self.assertEqual(result["source"]["origin"], "csrd")
            self.assertIn("descriptor", result["metadata"]["tags"])
            self.assertEqual(result["slug"], "charming")

            stored = content.get_record(result["id"])
            self.assertEqual(stored["title"], "Charming")

            by_tag = content.list_records_for_tag(tag="descriptor")
            self.assertEqual(len(by_tag), 1)
            self.assertEqual(by_tag[0]["id"], result["id"])

            events = content.audit.list_events(target_id=result["id"])
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].request_kind, "system_import")
            self.assertEqual(events[0].provider_id, "csrd")

    def test_import_descriptors_bulk_imports_multiple_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            content = ContentService(data_root=root / "data", db_path=root / "gmforge.db")

            imported = import_csrd_descriptors(
                PROJECT_ROOT / "CSRD" / "compendium" / "descriptors",
                content_service=content,
            )

            self.assertGreater(len(imported), 10)
            ids = {item["id"] for item in imported}
            self.assertIn("cypher_csrd_descriptor_charming", ids)

    def test_importer_is_system_addon_code_not_core_api(self) -> None:
        module_path = PROJECT_ROOT / "app" / "systems" / "cypher" / "addons" / "csrd" / "importer.py"
        self.assertTrue(module_path.exists())
        self.assertFalse((PROJECT_ROOT / "app" / "core" / "content" / "csrd_importer.py").exists())

    def test_import_descriptor_markdown_file_creates_records_through_core_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            content = ContentService(data_root=root / "data", db_path=root / "gmforge.db")
            markdown_path = root / "descriptors.md"
            markdown_path.write_text(
                """
# CSRD

## Descriptor: Charming

You have a pleasant manner and an easy smile.

## Descriptor: Stealthy

You move quietly and avoid notice.
""".strip()
                + "\n",
                encoding="utf-8",
            )

            imported = import_csrd_descriptor_markdown_file(
                markdown_path,
                content_service=content,
            )

            self.assertEqual(len(imported), 2)
            self.assertEqual(imported[0]["source"]["kind"], "addon_pack")
            self.assertEqual(imported[0]["source"]["origin"], "csrd_markdown")
            self.assertEqual(imported[0]["system"]["addon_id"], "csrd")
            self.assertEqual(imported[0]["slug"], "charming")
            events = content.audit.list_events(target_id=imported[0]["id"])
            self.assertEqual(events[0].provider_id, "csrd_markdown")


if __name__ == "__main__":
    unittest.main()
