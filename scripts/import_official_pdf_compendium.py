#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SUPPORTED_TYPES = {
    "npc",
    "creature",
    "monster",
    "ability",
    "focus",
    "descriptor",
    "character_type",
    "flavor",
    "skill",
    "cypher",
    "artifact",
    "equipment",
}

TYPE_TO_FOLDER = {
    "npc": "npcs",
    "creature": "creatures",
    "monster": "monsters",
    "ability": "abilities",
    "focus": "foci",
    "descriptor": "descriptors",
    "character_type": "types",
    "flavor": "flavors",
    "skill": "skills",
    "cypher": "cyphers",
    "artifact": "artifacts",
    "equipment": "equipment",
}

WHITE_BOOK_SETTINGS = {
    "godforsaken": ["fantasy"],
    "claim_the_sky": ["superhero"],
    "stay_alive": ["horror"],
    "the_stars_are_fire": ["science_fiction"],
    "its_only_magic": ["fantasy"],
    "it_s_only_magic": ["fantasy"],
    "high_noon_at_midnight": ["western"],
    "neon_rain": ["cyberpunk"],
    "we_are_all_mad_here": ["fairytale"],
    "rust_and_redemption": ["post_apocalypse"],
}

_IGNORE_HEADINGS = {
    "CHAPTER",
    "GODFORSAKEN",
    "FANTASY CYPHERS",
    "FANTASY ARTIFACTS",
    "EXAMPLE FANTASY CYPHERS",
    "EXAMPLE FANTASY ARTIFACTS",
    "FANTASY CYPHERS TABLE",
    "MAJOR FANTASY ARTIFACTS TABLE",
    "MINOR FANTASY ARTIFACTS TABLE",
    "TYPES OF CYPHERS",
    "MANIFEST",
    "FANTASTIC",
    "CHARACTER ABILITIES AS CYPHERS",
}

_NPC_HINT_TOKENS = {
    "berserker",
    "druid",
    "thief",
    "paladin",
    "priest",
    "wizard",
    "sorcerer",
    "cultist",
    "guard",
    "soldier",
    "merchant",
    "noble",
    "captain",
    "assassin",
    "hunter",
    "ranger",
    "barbarian",
    "bard",
    "cleric",
    "monk",
    "warrior",
    "halfling",
    "elf",
    "dwarf",
}

_CREATURE_HINT_TOKENS = {
    "dragon",
    "basilisk",
    "chimera",
    "beast",
    "wolf",
    "spider",
    "serpent",
    "hound",
    "demon",
    "devil",
    "undead",
    "ooze",
    "golem",
    "hydra",
    "wyvern",
    "griffin",
    "gryphon",
    "elemental",
    "ghost",
    "wraith",
    "zombie",
    "skeleton",
}


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "untitled"


def title_case_heading(value: str) -> str:
    parts = re.split(r"(\s+)", str(value or "").strip())
    out: list[str] = []
    for part in parts:
        if not part or part.isspace():
            out.append(part)
            continue
        if part.isupper() and len(part) <= 3:
            out.append(part)
            continue
        out.append(part.capitalize())
    return "".join(out).strip()


def extract_pages(pdf_path: Path) -> list[str]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError("pypdf is required for PDF extraction commands") from exc
    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(str(page.extract_text() or ""))
    return pages


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def build_index(out_dir: Path) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    counts_by_type: dict[str, int] = {}
    for item_type, folder_name in TYPE_TO_FOLDER.items():
        folder = out_dir / folder_name
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            items.append({
                "slug": data.get("slug"),
                "title": data.get("title"),
                "type": data.get("type"),
                "book": data.get("book"),
                "pages": data.get("pages"),
                "settings": data.get("settings"),
                "path": str(path.relative_to(out_dir)).replace("\\", "/"),
            })
            counts_by_type[item_type] = counts_by_type.get(item_type, 0) + 1
    index = {"count": len(items), "counts_by_type": counts_by_type, "items": items}
    write_json(out_dir / "index.json", index)
    return index


def _write_entry(out_dir: Path, payload: dict[str, Any], *, overwrite: bool) -> bool:
    item_type = str(payload.get("type") or "").strip().lower()
    if item_type not in SUPPORTED_TYPES:
        raise ValueError(f"Unsupported type '{item_type}'")
    folder = out_dir / TYPE_TO_FOLDER[item_type]
    slug = slugify(str(payload.get("slug") or payload.get("title") or "untitled"))
    payload["slug"] = slug
    path = folder / f"{slug}.json"
    if path.exists() and not overwrite:
        return False
    write_json(path, payload)
    return True


def cmd_dump_pages(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf).resolve()
    out_dir = Path(args.out_dir).resolve()
    pages = extract_pages(pdf_path)
    raw_dir = out_dir / "_raw_pages" / slugify(pdf_path.stem)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for i, text in enumerate(pages, start=1):
        (raw_dir / f"page_{i:04d}.txt").write_text(text, encoding="utf-8")
    print(f"Dumped {len(pages)} pages to {raw_dir}")
    return 0


def _entry_payload(
    *,
    item_type: str,
    title: str,
    slug: str,
    book: str,
    page_start: int,
    page_end: int,
    chunk: str,
    description: str,
    settings: list[str],
    pdf_path: Path,
    metadata_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "copyright_restricted": True,
        "do_not_sync": True,
        "pdf_path": str(pdf_path),
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    pages_value = ""
    if int(page_start or 0) > 0:
        pages_value = f"{page_start}-{page_end}" if page_end != page_start else f"{page_start}"
    return {
        "slug": slugify(slug),
        "title": title,
        "type": item_type,
        "source": "official_pdf",
        "book": book,
        "pages": pages_value,
        "description": description,
        "text": chunk,
        "settings": settings,
        "setting": settings[0] if settings else "",
        "metadata": metadata,
    }


def cmd_import_catalog(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf).resolve()
    out_dir = Path(args.out_dir).resolve()
    catalog_path = Path(args.catalog).resolve()

    pages = extract_pages(pdf_path)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entries = catalog.get("entries") or []
    if not isinstance(entries, list):
        raise ValueError("catalog.entries must be a list")

    default_settings = catalog.get("settings") or []
    default_book = str(catalog.get("book") or pdf_path.stem)
    created = 0

    for row in entries:
        if not isinstance(row, dict):
            continue
        item_type = str(row.get("type") or "").strip().lower()
        if item_type not in SUPPORTED_TYPES:
            raise ValueError(f"Unsupported type '{item_type}' in catalog")
        title = str(row.get("title") or "").strip()
        if not title:
            raise ValueError("Catalog entry is missing title")
        slug = slugify(str(row.get("slug") or title))
        page_start = int(row.get("page_start") or 0)
        page_end = int(row.get("page_end") or page_start)
        if page_start <= 0 or page_end <= 0 or page_end < page_start:
            raise ValueError(f"Invalid page range for '{title}'")
        if page_end > len(pages):
            raise ValueError(f"Page range for '{title}' exceeds PDF page count")

        chunk = "\n\n".join(pages[page_start - 1 : page_end]).strip()
        description = str(row.get("description") or "").strip()
        if not description:
            first_para = next((p.strip() for p in chunk.split("\n\n") if p.strip()), "")
            description = first_para[:500]

        settings = row.get("settings") if isinstance(row.get("settings"), list) else default_settings
        settings = [str(x).strip() for x in settings if str(x).strip()]
        book = str(row.get("book") or default_book).strip()
        payload = _entry_payload(
            item_type=item_type,
            title=title,
            slug=slug,
            book=book,
            page_start=page_start,
            page_end=page_end,
            chunk=chunk,
            description=description,
            settings=settings,
            pdf_path=pdf_path,
            metadata_extra={"import_mode": "catalog"},
        )
        if _write_entry(out_dir, payload, overwrite=bool(args.overwrite)):
            created += 1

    index = build_index(out_dir)
    print(f"Imported {created} entries from catalog '{catalog_path.name}'.")
    print(f"Official private compendium index count: {index['count']}")
    return 0


def _normalize_lines(page_text: str) -> list[str]:
    lines = []
    for line in str(page_text or "").replace("\r\n", "\n").split("\n"):
        clean = re.sub(r"\s+", " ", line).strip()
        lines.append(clean)
    return lines


def _looks_like_heading(line: str) -> bool:
    s = str(line or "").strip()
    if not s:
        return False
    if ":" in s:
        return False
    if re.fullmatch(r"\d{1,4}", s):
        return False
    if len(s) < 3 or len(s) > 72:
        return False
    upper_ratio = sum(1 for c in s if c.isupper()) / max(1, sum(1 for c in s if c.isalpha()))
    if upper_ratio < 0.75:
        return False
    upper_clean = re.sub(r"[^A-Z ]+", "", s.upper()).strip()
    for ignored in _IGNORE_HEADINGS:
        if upper_clean == ignored or upper_clean.startswith(f"{ignored} "):
            return False
    if re.match(r"^(D\d+|PAGE \d+|TABLE)", s.upper()):
        return False
    return True


def _infer_context(page_text: str) -> str:
    up = str(page_text or "").upper()
    if "ARTIFACT" in up:
        return "artifact"
    if "CYPHER" in up:
        return "cypher"
    if "NPC" in up or "CREATURES AND NPC" in up:
        return "npc"
    return ""


def _extract_auto_entries(
    pages: list[str],
    *,
    book: str,
    settings: list[str],
    pdf_path: Path,
    start_page: int,
    end_page: int,
    slug_prefix: str,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for pno in range(start_page, end_page + 1):
        page_text = pages[pno - 1]
        lines = _normalize_lines(page_text)
        context = _infer_context(page_text)
        heading_positions: list[tuple[int, str, str]] = []

        for i, line in enumerate(lines):
            npc_match = re.match(r"^([A-Z][A-Z'’\-\s]+?)\s+(\d+)\s+\((\d+)\)$", line)
            if npc_match:
                title = title_case_heading(npc_match.group(1))
                heading_positions.append((i, title, "npc"))
                continue

            if not _looks_like_heading(line):
                continue

            lookahead = "\n".join(lines[i + 1 : i + 12])
            has_level = bool(re.search(r"(?im)^\s*Level:\s*", lookahead))
            if not has_level:
                continue

            entry_type = ""
            if context == "artifact" or re.search(r"(?im)^\s*Depletion:\s*", lookahead):
                entry_type = "artifact"
            elif context == "cypher" or re.search(r"(?im)^\s*Effect:\s*", lookahead):
                entry_type = "cypher"
            elif context == "npc":
                entry_type = "npc"
            else:
                continue

            title = title_case_heading(line)
            heading_positions.append((i, title, entry_type))

        for idx, (start_idx, title, item_type) in enumerate(heading_positions):
            end_idx = heading_positions[idx + 1][0] if idx + 1 < len(heading_positions) else len(lines)
            chunk_lines = lines[start_idx:end_idx]
            chunk = "\n".join([x for x in chunk_lines if x]).strip()
            if len(chunk) < 40:
                continue

            description = ""
            for row in chunk_lines[1:]:
                if not row:
                    continue
                if re.match(r"^[A-Za-z][A-Za-z ]{1,40}:\s*", row):
                    description = re.sub(r"\s+", " ", row).strip()
                    break
                if not _looks_like_heading(row):
                    description = re.sub(r"\s+", " ", row).strip()
                    break
            if not description:
                description = re.sub(r"\s+", " ", chunk_lines[1] if len(chunk_lines) > 1 else chunk).strip()
            description = description[:520]

            base_slug = slugify(title)
            full_slug = f"{slug_prefix}_{base_slug}" if slug_prefix else base_slug
            key = (item_type, full_slug, pno)
            if key in seen:
                continue
            seen.add(key)

            entries.append(_entry_payload(
                item_type=item_type,
                title=title,
                slug=full_slug,
                book=book,
                page_start=pno,
                page_end=pno,
                chunk=chunk,
                description=description,
                settings=settings,
                pdf_path=pdf_path,
                metadata_extra={"import_mode": "auto_heading"},
            ))

    return entries


def cmd_auto_import(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf).resolve()
    out_dir = Path(args.out_dir).resolve()
    pages = extract_pages(pdf_path)
    book = str(args.book or pdf_path.stem).strip()
    settings = [str(x).strip() for x in str(args.settings or "").split(",") if str(x).strip()]
    start_page = max(1, int(args.start_page or 1))
    end_page = min(len(pages), int(args.end_page or len(pages)))
    if end_page < start_page:
        raise ValueError("end_page must be >= start_page")
    slug_prefix = slugify(str(args.slug_prefix or book))

    entries = _extract_auto_entries(
        pages,
        book=book,
        settings=settings,
        pdf_path=pdf_path,
        start_page=start_page,
        end_page=end_page,
        slug_prefix=slug_prefix if args.prefix_slug_with_book else "",
    )
    written = 0
    for payload in entries:
        if _write_entry(out_dir, payload, overwrite=bool(args.overwrite)):
            written += 1

    index = build_index(out_dir)
    by_type: dict[str, int] = {}
    for item in entries:
        t = str(item.get("type") or "")
        by_type[t] = by_type.get(t, 0) + 1
    print(f"AUTO import: parsed {len(entries)} candidate entries from '{pdf_path.name}' pages {start_page}-{end_page}.")
    print(f"AUTO import: wrote {written} entries (overwrite={bool(args.overwrite)}).")
    print(f"AUTO import: parsed by type: {by_type}")
    print(f"Official private compendium index count: {index['count']}")
    return 0


def cmd_auto_import_white_books(args: argparse.Namespace) -> int:
    books_dir = Path(args.books_dir).resolve()
    if not books_dir.exists():
        legacy_dir = Path("PDF_Repository/Setting_Books").resolve()
        if legacy_dir.exists():
            books_dir = legacy_dir
    out_dir = Path(args.out_dir).resolve()
    pdf_paths = sorted(books_dir.glob("*.pdf"))
    if not pdf_paths:
        raise ValueError(f"No PDF files found under: {books_dir}")

    total_written = 0
    total_candidates = 0
    for pdf_path in pdf_paths:
        stem_slug = slugify(pdf_path.stem)
        settings = WHITE_BOOK_SETTINGS.get(stem_slug, [str(args.default_setting or "all_settings").strip()])
        pages = extract_pages(pdf_path)
        entries = _extract_auto_entries(
            pages,
            book=pdf_path.stem,
            settings=settings,
            pdf_path=pdf_path,
            start_page=1,
            end_page=len(pages),
            slug_prefix=stem_slug if args.prefix_slug_with_book else "",
        )
        written_for_book = 0
        for payload in entries:
            if _write_entry(out_dir, payload, overwrite=bool(args.overwrite)):
                written_for_book += 1
        total_candidates += len(entries)
        total_written += written_for_book
        print(f"[{pdf_path.name}] candidates={len(entries)} written={written_for_book} settings={settings}")

    index = build_index(out_dir)
    print(f"AUTO white-books import complete: candidates={total_candidates}, written={total_written}")
    print(f"Official private compendium index count: {index['count']}")
    return 0


def _normalize_label_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _extract_labeled_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_key = ""
    for raw_line in lines:
        line = re.sub(r"\s+", " ", str(raw_line or "").strip())
        if not line:
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9 '’\-/]{1,48}):\s*(.*)$", line)
        if m:
            key = _normalize_label_key(m.group(1))
            value = str(m.group(2) or "").strip()
            current_key = key
            if key in fields and value:
                fields[key] = f"{fields[key]} {value}".strip()
            else:
                fields[key] = value
            continue
        if current_key:
            fields[current_key] = f"{fields.get(current_key, '')} {line}".strip()
    return {k: v.strip() for k, v in fields.items() if str(v).strip()}


def _extract_page_hint(text: str) -> int:
    source = str(text or "")
    patterns = [
        r"(?im)\bpage\s+(\d{1,4})\b",
        r"(?im)\bp\.\s*(\d{1,4})\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, source)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return 0


def _classify_docling_entry(title: str, heading_path: str, fields: dict[str, str]) -> str:
    title_lc = str(title or "").strip().lower()
    path_lc = str(heading_path or "").strip().lower()
    combined_lc = " ".join([
        title_lc,
        path_lc,
        str(fields.get("description") or "").strip().lower(),
        str(fields.get("combat") or "").strip().lower(),
    ])
    keys = set(fields.keys())
    looks_like_creature = any(tok in combined_lc for tok in _CREATURE_HINT_TOKENS) or any(
        tok in path_lc for tok in ("creature", "monster", "beast")
    )
    looks_like_npc = any(tok in combined_lc for tok in _NPC_HINT_TOKENS) or any(
        tok in path_lc for tok in ("npc", "humanoid", "people", "folk", "villain", "ally")
    )

    if "depletion" in keys and ("effect" in keys or "level" in keys):
        return "artifact"
    if "effect" in keys and ("level" in keys or "form" in keys or "manifestation" in keys or "limitation" in keys):
        return "cypher"
    if any(k.startswith("tier ") for k in keys):
        return "focus"
    if "motive" in keys and "health" in keys:
        if looks_like_creature:
            return "creature"
        if looks_like_npc:
            return "npc"
        if "npc" in path_lc:
            return "npc"
        if "creature" in path_lc or "monster" in path_lc:
            return "creature"
        return "creature"
    if "health" in keys and ("damage inflicted" in keys or "combat" in keys):
        if looks_like_creature:
            return "creature"
        if looks_like_npc:
            return "npc"
        if "creature" in path_lc or "monster" in path_lc:
            return "creature"
        if "npc" in path_lc:
            return "npc"
        return "creature"
    if "player intrusion" in keys and "stat pools" in keys:
        return "character_type"
    if "special abilities" in keys and ("health" in keys or "armor" in keys):
        return "npc"
    return ""


def _split_docling_blocks(markdown_text: str) -> list[dict[str, Any]]:
    lines = str(markdown_text or "").replace("\r\n", "\n").split("\n")
    heading_stack: list[tuple[int, str]] = []
    blocks: list[dict[str, Any]] = []
    current_title = ""
    current_level = 0
    current_path = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        if not current_title:
            current_lines = []
            return
        payload_lines = [re.sub(r"\s+", " ", x).strip() for x in current_lines if str(x or "").strip()]
        if payload_lines:
            blocks.append({
                "title": current_title,
                "level": current_level,
                "heading_path": current_path,
                "lines": payload_lines,
                "text": "\n".join(payload_lines).strip(),
            })
        current_lines = []

    for line in lines:
        m = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
        if m:
            flush()
            level = len(m.group(1))
            title = str(m.group(2) or "").strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            path_titles = [x[1] for x in heading_stack]
            current_title = title
            current_level = level
            current_path = " > ".join(path_titles)
            current_lines = []
            continue
        current_lines.append(line)
    flush()
    return blocks


def _derive_title_from_text(title: str, lines: list[str]) -> str:
    base = str(title or "").strip()
    if base and not re.fullmatch(r"\d+\s*\(\d+\)", base):
        # Docling headings can be sentence-like ("A Berserker Is A Fierce Warrior...").
        # Trim to the likely name phrase so downstream type heuristics can work.
        m_phrase = re.match(r"^(?:a|an|the|some)\s+([A-Za-z][A-Za-z'’\- ]{1,80}?)\s+(?:are|is|can|have|has)\b", base, flags=re.IGNORECASE)
        if m_phrase:
            phrase = str(m_phrase.group(1) or "").strip()
            return title_case_heading(phrase)
        m_head = re.match(r"^([A-Za-z][A-Za-z'’\- ]{1,64}?)(?:[.:;]|$)", base)
        if m_head:
            return title_case_heading(str(m_head.group(1) or "").strip())
        return title_case_heading(base)
    first = re.sub(r"\s+", " ", str(lines[0] if lines else "").strip())
    if not first:
        return base or "Untitled"
    candidate = ""
    m = re.match(r"^([A-Za-z][A-Za-z'’\- ]{1,48})\s+(?:are|is|can|have|has)\b", first)
    if m:
        candidate = str(m.group(1) or "").strip()
    else:
        # fallback: first 1-4 words
        words = re.findall(r"[A-Za-z][A-Za-z'’\-]*", first)
        candidate = " ".join(words[:4]).strip()
    if candidate.endswith("s") and len(candidate) > 4 and " " not in candidate:
        candidate = candidate[:-1]
    return title_case_heading(candidate or base or "Untitled")


def _extract_docling_entries(
    markdown_text: str,
    *,
    book: str,
    settings: list[str],
    source_name: str,
    slug_prefix: str,
    min_text_len: int = 90,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for block in _split_docling_blocks(markdown_text):
        raw_title = str(block.get("title") or "").strip()
        if not raw_title:
            continue
        if _looks_like_heading(raw_title):
            # This heading style is often all-caps section noise in docling output.
            if raw_title.upper() in _IGNORE_HEADINGS:
                continue
        lines = list(block.get("lines") or [])
        title = _derive_title_from_text(raw_title, lines)
        text = str(block.get("text") or "").strip()
        if len(text) < min_text_len:
            continue
        fields = _extract_labeled_fields(lines)
        item_type = _classify_docling_entry(title, str(block.get("heading_path") or ""), fields)
        if not item_type:
            continue
        if item_type not in SUPPORTED_TYPES:
            continue
        page_hint = _extract_page_hint(text)
        desc = ""
        for key in ("description", "effect", "combat", "motive", "interaction", "use"):
            value = str(fields.get(key) or "").strip()
            if value:
                desc = value
                break
        if not desc:
            desc = re.sub(r"\s+", " ", text).strip()
        desc = desc[:520]
        base_slug = slugify(title)
        full_slug = f"{slug_prefix}_{base_slug}" if slug_prefix else base_slug
        uniq = (item_type, full_slug)
        if uniq in seen:
            continue
        seen.add(uniq)
        out.append(_entry_payload(
            item_type=item_type,
            title=title_case_heading(title),
            slug=full_slug,
            book=book,
            page_start=page_hint,
            page_end=page_hint,
            chunk=text,
            description=desc,
            settings=settings,
            pdf_path=Path(source_name),
            metadata_extra={
                "import_mode": "docling_auto",
                "docling_source": source_name,
                "heading_path": str(block.get("heading_path") or ""),
            },
        ))
    return out


def cmd_auto_import_docling(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).resolve()
    markdown_paths = [Path(x).resolve() for x in (args.markdown or []) if str(x or "").strip()]
    if not markdown_paths:
        raise ValueError("at least one --markdown path is required")
    explicit_settings = [str(x).strip() for x in str(args.settings or "").split(",") if str(x).strip()]
    written = 0
    candidates = 0
    by_type: dict[str, int] = {}
    for markdown_path in markdown_paths:
        if not markdown_path.exists() or not markdown_path.is_file():
            continue
        text = markdown_path.read_text(encoding="utf-8", errors="replace")
        book = str(args.book or markdown_path.stem).strip()
        settings = list(explicit_settings)
        if not settings:
            settings = WHITE_BOOK_SETTINGS.get(slugify(book), [])
        prefix = slugify(str(args.slug_prefix or book)) if args.prefix_slug_with_book else ""
        entries = _extract_docling_entries(
            text,
            book=book,
            settings=settings,
            source_name=str(markdown_path),
            slug_prefix=prefix,
            min_text_len=max(20, int(args.min_text_len or 90)),
        )
        candidates += len(entries)
        for item in entries:
            t = str(item.get("type") or "").strip().lower()
            by_type[t] = by_type.get(t, 0) + 1
            if _write_entry(out_dir, item, overwrite=bool(args.overwrite)):
                written += 1
        print(f"[docling:{markdown_path.name}] candidates={len(entries)}")

    index = build_index(out_dir)
    print(f"AUTO docling import: candidates={candidates}, wrote={written}, by_type={by_type}")
    print(f"Official private compendium index count: {index['count']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import legally-restricted official PDF material into private compendium storage (git-ignored)."
    )
    parser.add_argument(
        "--out-dir",
        default="PDF_Repository/private_compendium",
        help="Output directory for private official compendium data (default: PDF_Repository/private_compendium)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    dump_pages = sub.add_parser("dump-pages", help="Extract page text files from a PDF for catalog preparation.")
    dump_pages.add_argument("--pdf", required=True, help="Path to official PDF file.")
    dump_pages.set_defaults(func=cmd_dump_pages)

    import_catalog = sub.add_parser("import-catalog", help="Import entries from a catalog JSON with page ranges.")
    import_catalog.add_argument("--pdf", required=True, help="Path to official PDF file.")
    import_catalog.add_argument("--catalog", required=True, help="Path to catalog JSON.")
    import_catalog.add_argument("--overwrite", action="store_true", help="Overwrite existing slug file if present.")
    import_catalog.set_defaults(func=cmd_import_catalog)

    auto_import = sub.add_parser("auto-import", help="Auto-extract heading-based entries (cyphers/artifacts/npcs) from one PDF.")
    auto_import.add_argument("--pdf", required=True, help="Path to official PDF file.")
    auto_import.add_argument("--book", default="", help="Book title override (default: PDF stem).")
    auto_import.add_argument("--settings", default="", help="Comma-separated settings tags, e.g. 'fantasy'.")
    auto_import.add_argument("--start-page", type=int, default=1, help="1-based first page to scan.")
    auto_import.add_argument("--end-page", type=int, default=0, help="1-based last page to scan (default: last page).")
    auto_import.add_argument("--slug-prefix", default="", help="Slug prefix (default: book slug).")
    auto_import.add_argument("--prefix-slug-with-book", action="store_true", default=True, help="Prefix slugs with book slug (default: on).")
    auto_import.add_argument("--overwrite", action="store_true", help="Overwrite existing slug file if present.")
    auto_import.set_defaults(func=cmd_auto_import)

    auto_import_white = sub.add_parser(
        "auto-import-white-books",
        help="Auto-extract heading-based entries across all PDFs in Genre_Books.",
    )
    auto_import_white.add_argument(
        "--books-dir",
        default="PDF_Repository/Genre_Books",
        help="Directory containing white book PDFs (default: PDF_Repository/Genre_Books; legacy fallback: PDF_Repository/Setting_Books).",
    )
    auto_import_white.add_argument(
        "--default-setting",
        default="all_settings",
        help="Fallback setting tag for unknown books (default: all_settings).",
    )
    auto_import_white.add_argument("--prefix-slug-with-book", action="store_true", default=True, help="Prefix slugs with book slug (default: on).")
    auto_import_white.add_argument("--overwrite", action="store_true", help="Overwrite existing slug file if present.")
    auto_import_white.set_defaults(func=cmd_auto_import_white_books)

    auto_import_docling = sub.add_parser(
        "auto-import-docling",
        help="Auto-extract entries from one or more Docling markdown files.",
    )
    auto_import_docling.add_argument(
        "--markdown",
        action="append",
        default=[],
        help="Path to Docling markdown file (can be provided multiple times).",
    )
    auto_import_docling.add_argument("--book", default="", help="Book title override (default: markdown stem).")
    auto_import_docling.add_argument("--settings", default="", help="Comma-separated settings tags, e.g. 'fantasy'.")
    auto_import_docling.add_argument("--slug-prefix", default="", help="Slug prefix (default: book slug).")
    auto_import_docling.add_argument("--prefix-slug-with-book", action="store_true", default=True, help="Prefix slugs with book slug (default: on).")
    auto_import_docling.add_argument("--min-text-len", type=int, default=90, help="Minimum block text length for candidate extraction.")
    auto_import_docling.add_argument("--overwrite", action="store_true", help="Overwrite existing slug file if present.")
    auto_import_docling.set_defaults(func=cmd_auto_import_docling)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
