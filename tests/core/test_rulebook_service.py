from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.rulebooks import (
    build_rulebook_toc,
    extract_markdown_headings,
    load_rulebook_document,
    render_rulebook_html,
)


class RulebookServiceTests(unittest.TestCase):
    def test_extract_markdown_headings_supports_atx_and_setext(self) -> None:
        markdown = """
GMForge Guide
=============

## Introduction

### Welcome

Section Two
-----------
"""
        headings = extract_markdown_headings(markdown)
        self.assertEqual(
            [(item.level, item.title, item.anchor) for item in headings],
            [
                (1, "GMForge Guide", "gmforge-guide"),
                (2, "Introduction", "introduction"),
                (3, "Welcome", "welcome"),
                (2, "Section Two", "section-two"),
            ],
        )

    def test_load_rulebook_document_reads_real_csrd_markdown(self) -> None:
        path = (
            PROJECT_ROOT
            / "app"
            / "systems"
            / "cypher"
            / "addons"
            / "csrd"
            / "source_markdown"
            / "Cypher-System-Reference-Document-2025-08-22.md"
        )
        document = load_rulebook_document(path)
        self.assertEqual(document.title, "CYPHER SYSTEM REFERENCE DOCUMENT 2025-08-22")
        self.assertGreater(len(document.headings), 10)
        titles = [item.title for item in document.headings[:8]]
        self.assertIn("How to Play the Cypher System", titles)
        descriptor_heading = next(item for item in document.headings if item.title == "Descriptor")
        self.assertEqual(descriptor_heading.anchor, "descriptor")
        toc = build_rulebook_toc(document, max_level=2)
        self.assertGreater(len(toc), 10)
        self.assertLessEqual(len(toc), len(document.headings))

    def test_render_rulebook_html_filters_inline_image_blobs(self) -> None:
        markdown = """
# Godforsaken

![page image](data:image/png;base64,AAAAABBBBBCCCCCDDDD)

Intro text after image.
"""
        document = load_rulebook_document(Path(__file__), title="Godforsaken")
        object.__setattr__(document, "markdown_text", markdown)
        object.__setattr__(document, "headings", extract_markdown_headings(markdown))

        html = render_rulebook_html(document)

        self.assertIn("Godforsaken", html)
        self.assertIn("Intro text after image.", html)
        self.assertNotIn("data:image/png;base64", html)


if __name__ == "__main__":
    unittest.main()
