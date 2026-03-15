from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path


HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
SETEXT_UNDERLINE_RE = re.compile(r"^(=+|-+)\s*$")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'()-]*")
INLINE_IMAGE_BLOB_RE = re.compile(r"!\[[^\]]*\]\(\s*data:image/[^)]+\)", re.IGNORECASE)


@dataclass(frozen=True)
class RulebookHeading:
    level: int
    title: str
    anchor: str
    line_number: int


@dataclass(frozen=True)
class RulebookDocument:
    title: str
    markdown_path: str
    markdown_text: str
    headings: list[RulebookHeading]


def slugify_heading(title: str) -> str:
    normalized = NON_ALNUM_RE.sub("-", title.strip().lower()).strip("-")
    return normalized or "section"


def _looks_like_plain_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 90:
        return False
    if stripped.startswith(("-", "*", "|", ">")):
        return False
    if stripped.endswith((".", ":", ";", "!", "?")):
        return False
    words = WORD_RE.findall(stripped)
    if not words or len(words) > 12:
        return False
    if stripped == stripped.upper():
        return True
    capitalized = sum(1 for word in words if word[:1].isupper())
    return capitalized >= max(1, len(words) // 2)


def _next_non_empty_line(lines: list[str], start_index: int) -> tuple[int, str] | None:
    for index in range(start_index, len(lines)):
        stripped = lines[index].strip()
        if stripped:
            return index, stripped
    return None


def extract_markdown_headings(markdown_text: str) -> list[RulebookHeading]:
    lines = markdown_text.splitlines()
    headings: list[RulebookHeading] = []
    used_anchors: dict[str, int] = {}

    def add_heading(*, level: int, title: str, line_number: int) -> None:
        anchor = slugify_heading(title)
        seen = used_anchors.get(anchor, 0)
        used_anchors[anchor] = seen + 1
        if seen:
            anchor = f"{anchor}-{seen + 1}"
        headings.append(
            RulebookHeading(
                level=level,
                title=title.strip(),
                anchor=anchor,
                line_number=line_number,
            )
        )

    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match:
            add_heading(
                level=len(match.group("hashes")),
                title=match.group("title"),
                line_number=index + 1,
            )
            continue
        if index + 1 >= len(lines):
            continue
        stripped = line.strip()
        if not stripped:
            continue
        underline = lines[index + 1].strip()
        if SETEXT_UNDERLINE_RE.fullmatch(underline):
            level = 1 if underline.startswith("=") else 2
            add_heading(level=level, title=stripped, line_number=index + 1)
            continue
        if not _looks_like_plain_heading(stripped):
            continue
        previous_line_blank = index == 0 or not lines[index - 1].strip()
        next_line_blank = index + 1 < len(lines) and not lines[index + 1].strip()
        if not previous_line_blank or not next_line_blank:
            continue
        next_item = _next_non_empty_line(lines, index + 1)
        if next_item is None:
            continue
        _, next_line = next_item
        if _looks_like_plain_heading(next_line):
            continue
        add_heading(level=2, title=stripped, line_number=index + 1)
    return headings


def load_rulebook_document(markdown_path: Path, *, title: str = "") -> RulebookDocument:
    resolved = markdown_path.resolve()
    markdown_text = resolved.read_text(encoding="utf-8", errors="replace")
    headings = extract_markdown_headings(markdown_text)
    first_non_empty = next((line.strip() for line in markdown_text.splitlines() if line.strip()), "")
    document_title = title.strip() or first_non_empty or (headings[0].title if headings else resolved.stem)
    return RulebookDocument(
        title=document_title,
        markdown_path=str(resolved),
        markdown_text=markdown_text,
        headings=headings,
    )


def build_rulebook_toc(document: RulebookDocument, *, max_level: int = 3) -> list[RulebookHeading]:
    return [heading for heading in document.headings if heading.level <= max_level]


def render_rulebook_html(document: RulebookDocument) -> str:
    heading_by_line = {heading.line_number: heading for heading in document.headings}
    lines = document.markdown_text.splitlines()
    html_parts: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        text = " ".join(item.strip() for item in paragraph if item.strip())
        if text:
            html_parts.append(f"<p>{escape(text)}</p>")
        paragraph.clear()

    def flush_list(items: list[str], *, ordered: bool) -> None:
        if not items:
            return
        tag = "ol" if ordered else "ul"
        html_parts.append(f"<{tag}>")
        for item in items:
            html_parts.append(f"<li>{escape(item)}</li>")
        html_parts.append(f"</{tag}>")

    def strip_inline_image_blobs(text: str) -> str:
        return INLINE_IMAGE_BLOB_RE.sub("", text).strip()

    index = 0
    while index < len(lines):
        line_number = index + 1
        raw_line = lines[index]
        stripped = raw_line.strip()
        stripped = strip_inline_image_blobs(stripped)

        heading = heading_by_line.get(line_number)
        if heading is not None:
            flush_paragraph()
            html_parts.append(
                f'<h{heading.level} id="{escape(heading.anchor)}">{escape(heading.title)}</h{heading.level}>'
            )
            index += 1
            if index < len(lines) and SETEXT_UNDERLINE_RE.fullmatch(lines[index].strip()):
                index += 1
            continue

        if not stripped:
            flush_paragraph()
            index += 1
            continue

        if stripped.startswith("|"):
            flush_paragraph()
            table_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index])
                index += 1
            html_parts.append(f"<pre>{escape(chr(10).join(table_lines))}</pre>")
            continue

        if stripped.startswith(("- ", "* ")):
            flush_paragraph()
            items: list[str] = []
            while index < len(lines):
                candidate = strip_inline_image_blobs(lines[index].strip())
                if not candidate.startswith(("- ", "* ")):
                    break
                items.append(candidate[2:].strip())
                index += 1
            flush_list(items, ordered=False)
            continue

        numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if numbered:
            flush_paragraph()
            items = []
            while index < len(lines):
                candidate = strip_inline_image_blobs(lines[index].strip())
                match = re.match(r"^\d+\.\s+(.*)$", candidate)
                if not match:
                    break
                items.append(match.group(1).strip())
                index += 1
            flush_list(items, ordered=True)
            continue

        paragraph.append(stripped)
        index += 1

    flush_paragraph()
    return "\n".join(html_parts)
