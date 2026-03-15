from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.contracts import lore_sort_key
from app.core.rulebooks import extract_markdown_headings, render_rulebook_html, RulebookDocument


@dataclass(frozen=True)
class LoreDocument:
    id: str
    title: str
    path: str
    markdown_text: str
    rendered_html: str


def _title_from_markdown(markdown_text: str, *, fallback: str) -> str:
    headings = extract_markdown_headings(markdown_text)
    if headings:
        return headings[0].title
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped.lstrip("#").strip() or fallback
    return fallback


def _resolve_central_lore_root(item_root: Path, module_root: Path | None) -> Path | None:
    if module_root is None:
        return None
    try:
        relative_root = item_root.relative_to(module_root)
    except ValueError:
        return None
    if str(relative_root) == ".":
        return module_root / "lore"
    if relative_root.parts and relative_root.parts[0] == "lore":
        return item_root
    return module_root / "lore" / relative_root


def load_lore_documents(item_root: Path, *, module_root: Path | None = None) -> list[LoreDocument]:
    lore_root = _resolve_central_lore_root(item_root, module_root)
    if lore_root is None or not lore_root.exists() or not lore_root.is_dir():
        lore_root = item_root / "lore"
    if not lore_root.exists() or not lore_root.is_dir():
        return []

    documents: list[LoreDocument] = []
    for path in sorted(lore_root.glob("*.md"), key=lambda candidate: lore_sort_key(candidate.name)):
        markdown_text = path.read_text(encoding="utf-8", errors="replace")
        title = _title_from_markdown(markdown_text, fallback=path.stem.replace("_", " ").title())
        rendered_html = render_rulebook_html(
            RulebookDocument(
                title=title,
                markdown_path=str(path.resolve()),
                markdown_text=markdown_text,
                headings=extract_markdown_headings(markdown_text),
            )
        )
        documents.append(
            LoreDocument(
                id=path.stem,
                title=title,
                path=str(path),
                markdown_text=markdown_text,
                rendered_html=rendered_html,
            )
        )
    return documents
