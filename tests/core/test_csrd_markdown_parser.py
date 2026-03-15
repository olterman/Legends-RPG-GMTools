from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.systems.cypher.addons.csrd import parse_descriptor_markdown


class CsrdMarkdownParserTests(unittest.TestCase):
    def test_parse_descriptor_markdown_extracts_descriptor_sections(self) -> None:
        markdown = """
# Cypher System Reference Document

## Descriptor: Charming

You have a pleasant manner and an easy smile.

- Pool: +2 Intellect
- Skill: Persuasion

## Descriptor: Stealthy

You move quietly and avoid notice.
"""

        parsed = parse_descriptor_markdown(markdown)

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["title"], "Charming")
        self.assertEqual(parsed[0]["slug"], "charming")
        self.assertEqual(parsed[0]["type"], "descriptor")
        self.assertIn("pleasant manner", parsed[0]["text"])
        self.assertEqual(parsed[1]["slug"], "stealthy")

    def test_parser_stays_in_addon_layer(self) -> None:
        addon_parser = PROJECT_ROOT / "app" / "systems" / "cypher" / "addons" / "csrd" / "markdown_parser.py"
        core_parser = PROJECT_ROOT / "app" / "core" / "content" / "markdown_parser.py"
        self.assertTrue(addon_parser.exists())
        self.assertFalse(core_parser.exists())

    def test_parse_real_csrd_descriptor_chapter(self) -> None:
        markdown_path = (
            PROJECT_ROOT
            / "app"
            / "systems"
            / "cypher"
            / "addons"
            / "csrd"
            / "source_markdown"
            / "Cypher-System-Reference-Document-2025-08-22.md"
        )
        parsed = parse_descriptor_markdown(markdown_path.read_text(encoding="utf-8", errors="replace"))

        self.assertEqual(len(parsed), 50)
        by_slug = {item["slug"]: item for item in parsed}
        self.assertIn("charming", by_slug)
        self.assertIn("stealthy", by_slug)
        self.assertIn("risk_taking", by_slug)
        self.assertTrue(by_slug["charming"]["text"].startswith("You’re a smooth talker and a charmer."))


if __name__ == "__main__":
    unittest.main()
