"""Generic rulebook helpers for markdown-backed addon documents."""

from .service import (
    RulebookDocument,
    RulebookHeading,
    build_rulebook_toc,
    extract_markdown_headings,
    load_rulebook_document,
    render_rulebook_html,
    slugify_heading,
)

__all__ = [
    "RulebookDocument",
    "RulebookHeading",
    "build_rulebook_toc",
    "extract_markdown_headings",
    "load_rulebook_document",
    "render_rulebook_html",
    "slugify_heading",
]
