from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.lore_docs import load_lore_documents


class LoreDocsServiceTests(unittest.TestCase):
    def test_load_lore_documents_reads_markdown_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            item_root = Path(td) / "node"
            lore_root = item_root / "lore"
            lore_root.mkdir(parents=True)
            (lore_root / "overview.md").write_text(
                "# Mountain Home\n\nA quiet ridge village.\n",
                encoding="utf-8",
            )

            docs = load_lore_documents(item_root)

            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0].id, "overview")
            self.assertEqual(docs[0].title, "Mountain Home")
            self.assertIn("<h1", docs[0].rendered_html)
            self.assertIn("quiet ridge village", docs[0].rendered_html)

    def test_load_lore_documents_prefers_central_module_lore(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            module_root = Path(td) / "module"
            item_root = module_root / "peoples" / "alfir"
            (item_root / "lore").mkdir(parents=True)
            (item_root / "lore" / "overview.md").write_text(
                "# Local\n\nLocal sibling lore.\n",
                encoding="utf-8",
            )
            central_root = module_root / "lore" / "peoples" / "alfir"
            central_root.mkdir(parents=True)
            (central_root / "overview.md").write_text(
                "# Central\n\nCentral module lore.\n",
                encoding="utf-8",
            )

            docs = load_lore_documents(item_root, module_root=module_root)

            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0].title, "Central")
            self.assertIn("Central module lore", docs[0].rendered_html)


if __name__ == "__main__":
    unittest.main()
