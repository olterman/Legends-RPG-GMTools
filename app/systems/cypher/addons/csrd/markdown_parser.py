from __future__ import annotations

import re
from pathlib import Path

DESCRIPTOR_START_MARKER = "DESCRIPTORS"
DESCRIPTOR_END_MARKER = "CUSTOMIZING DESCRIPTORS"
ALL_CAPS_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9'&()\- ,/]+$")
SAMPLE_DESCRIPTOR_HEADING_RE = re.compile(r"^##\s+Descriptor:\s+(?P<title>.+?)\s*$", re.MULTILINE)
SECTION_BREAKS = {
    "DESCRIPTORS",
    "CUSTOMIZING DESCRIPTORS",
    "SPECIES AS DESCRIPTOR",
}


def load_markdown(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _title_from_heading(heading: str) -> str:
    parts = []
    for token in heading.strip().split():
        if "-" in token:
            parts.append("-".join(piece.capitalize() for piece in token.split("-")))
        else:
            parts.append(token.capitalize())
    return " ".join(parts)


def _descriptor_chapter_lines(markdown_text: str) -> list[str]:
    lines = markdown_text.splitlines()
    start = None
    end = None
    for index, line in enumerate(lines):
        if line.strip() == DESCRIPTOR_START_MARKER and start is None:
            start = index + 1
            continue
        if start is not None and line.strip() == DESCRIPTOR_END_MARKER:
            end = index
            break
    if start is None:
        return []
    return lines[start:end]


def split_descriptor_sections(markdown_text: str) -> list[tuple[str, str]]:
    lines = _descriptor_chapter_lines(markdown_text)
    if not lines:
        matches = list(SAMPLE_DESCRIPTOR_HEADING_RE.finditer(markdown_text))
        sections: list[tuple[str, str]] = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
            title = match.group("title").strip()
            body = markdown_text[start:end].strip()
            if title and body:
                sections.append((title, body))
        return sections

    headings: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped in SECTION_BREAKS:
            continue
        if ALL_CAPS_HEADING_RE.fullmatch(stripped) and len(stripped) < 60:
            headings.append((index, stripped))

    sections: list[tuple[str, str]] = []
    for index, (line_number, heading) in enumerate(headings):
        if heading in SECTION_BREAKS:
            continue
        start = line_number + 1
        end = headings[index + 1][0] if index + 1 < len(headings) else len(lines)
        title = _title_from_heading(heading)
        body = "\n".join(lines[start:end]).strip()
        if title and body:
            sections.append((title, body))
    return sections


def descriptor_slug(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", title.strip().lower())
    return normalized.strip("_")


def descriptor_summary(body: str, *, max_length: int = 240) -> str:
    collapsed = " ".join(body.split())
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 3].rstrip() + "..."


def parse_descriptor_markdown(markdown_text: str) -> list[dict[str, str]]:
    descriptors: list[dict[str, str]] = []
    for title, body in split_descriptor_sections(markdown_text):
        descriptors.append(
            {
                "title": title,
                "slug": descriptor_slug(title),
                "summary": descriptor_summary(body),
                "text": body,
                "type": "descriptor",
            }
        )
    return descriptors
