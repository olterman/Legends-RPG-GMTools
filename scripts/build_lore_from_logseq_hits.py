from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote


def slugify(text: str) -> str:
    text = unquote(text).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "untitled"


def title_from_path(path: str) -> str:
    name = Path(path).stem
    name = unquote(name)
    name = name.replace("_", " ").strip()
    return name or "Untitled"


def first_excerpt(markdown_text: str, max_len: int = 260) -> str:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("tags::", "title::", "id::", "- id::")):
            continue
        if stripped.startswith("#"):
            continue
        if stripped == "---":
            continue
        if stripped.startswith("```"):
            continue
        excerpt = re.sub(r"\s+", " ", stripped)
        return excerpt[:max_len]
    return ""


def clean_logseq_markdown(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    cleaned: list[str] = []
    in_code_fence = False
    in_quote_block = False
    references_started = False

    def normalize_line(line: str) -> str:
        stripped = line.strip()
        if not stripped:
            return ""
        stripped = re.sub(r"`{2,}$", "", stripped)

        # Logseq uses "- " blocks for almost everything. Convert to narrative
        # markdown by unwrapping leading bullets and indentation.
        while stripped.startswith("- "):
            stripped = stripped[2:].strip()

        return stripped

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            cleaned.append(line)
            continue

        if in_code_fence:
            cleaned.append(line)
            continue

        normalized = normalize_line(line)
        if not normalized:
            cleaned.append("")
            continue

        # Drop Logseq property lines.
        if re.match(r"^[A-Za-z0-9_-]+::\s*", normalized):
            continue
        if normalized.startswith("id::"):
            continue

        # Convert Logseq quote blocks to Markdown blockquotes.
        if normalized.upper() in {"#+BEGIN_QUOTE", "#+BEGINQUOTE"}:
            in_quote_block = True
            continue
        if normalized.upper() in {"#+END_QUOTE", "#+ENDQUOTE"}:
            in_quote_block = False
            cleaned.append("")
            continue

        if in_quote_block:
            cleaned.append(f"> {normalized}")
            continue

        # Group bare URLs under a References heading to reduce visual noise.
        if re.match(r"^https?://", normalized):
            if not references_started:
                cleaned.append("### References")
                references_started = True
            cleaned.append(f"- {normalized}")
            continue

        cleaned.append(normalized)

    # Collapse excessive empty lines.
    compact: list[str] = []
    blank_run = 0
    for line in cleaned:
        if line.strip():
            blank_run = 0
            compact.append(line)
        else:
            blank_run += 1
            if blank_run <= 1:
                compact.append("")

    return "\n".join(infer_markdown_lists(compact)).strip()


def infer_markdown_lists(lines: list[str]) -> list[str]:
    def is_heading(line: str) -> bool:
        return bool(re.match(r"^#{1,6}\s+", line))

    def is_separator(line: str) -> bool:
        return line.strip() == "---"

    def is_code_fence(line: str) -> bool:
        return line.strip().startswith("```")

    def is_candidate_item(line: str) -> bool:
        s = line.strip()
        if not s:
            return False
        if is_heading(s) or is_separator(s):
            return False
        if s.startswith(("- ", "* ", "> ", "### ")):
            return False
        if re.match(r"^https?://", s):
            return False
        # Keep inferred bullets to concise fragments, not full prose.
        if len(s) > 100:
            return False
        if re.search(r"[.!?]$", s):
            return False
        return True

    result: list[str] = []
    i = 0
    in_code_fence = False

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        if is_code_fence(line):
            in_code_fence = not in_code_fence
            result.append(raw)
            i += 1
            continue

        if in_code_fence:
            result.append(raw)
            i += 1
            continue

        if line.endswith(":") and not is_heading(line):
            j = i + 1
            candidates: list[str] = []
            while j < len(lines):
                nxt = lines[j].strip()
                if not nxt:
                    break
                if is_heading(nxt) or is_separator(nxt) or is_code_fence(nxt):
                    break
                if not is_candidate_item(nxt):
                    break
                candidates.append(nxt)
                j += 1

            if len(candidates) >= 2:
                result.append(raw)
                for c in candidates:
                    result.append(f"- {c}")
                i = j
                continue

        result.append(raw)
        i += 1

    return result


def classify_prompt_text(text: str, hint: str = "") -> str:
    low = (hint + "\n" + text).lower()
    art_terms = [
        "style",
        "lighting",
        "camera",
        "render",
        "artstation",
        "midjourney",
        "stable diffusion",
        "sdxl",
        "illustration",
        "portrait",
        "concept art",
    ]
    return "art" if any(term in low for term in art_terms) else "lore"


def split_prompts_from_markdown(
    markdown_text: str,
    *,
    source_slug: str,
    source_title: str,
    source_path: str,
    id_start: int = 1,
) -> tuple[str, list[dict], int]:
    prompt_heading_hints = {
        "prompt",
        "output guidelines",
        "drift test",
        "drift",
        "green flags",
        "final litmus",
        "core world truths",
        "races (quick context)",
        "cultural themes to emphasize",
        "prompt focus",
        "begin prompt",
        "checksum",
    }

    lines = markdown_text.splitlines()
    out_lines: list[str] = []
    prompts: list[dict] = []
    i = 0
    next_id = id_start

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        heading_probe = re.sub(r"^[-*]\s+", "", stripped)

        heading = re.match(r"^(#{1,6})\s+(.+)$", heading_probe)
        if heading:
            heading_text = heading.group(2).strip()
            heading_lc = heading_text.lower()
            if any(h in heading_lc for h in prompt_heading_hints):
                j = i + 1
                block: list[str] = []
                capture_to_end = any(
                    h in heading_lc
                    for h in [
                        "drift test",
                        "green flags",
                        "final litmus",
                        "output guidelines",
                        "core world truths",
                        "races (quick context)",
                        "cultural themes to emphasize",
                        "checksum",
                    ]
                )
                while j < len(lines):
                    nxt = lines[j].strip()
                    nxt_probe = re.sub(r"^[-*]\s+", "", nxt)
                    if not capture_to_end and re.match(r"^#{1,6}\s+", nxt_probe):
                        break
                    block.append(lines[j])
                    j += 1
                text = "\n".join(x for x in block if x.strip()).strip()
                if text:
                    category = classify_prompt_text(text, heading_text)
                    prompts.append(
                        {
                            "id": f"prompt_{next_id:04d}",
                            "title": heading_text,
                            "category": category,
                            "text": text,
                            "source_slug": source_slug,
                            "source_title": source_title,
                            "source_path": source_path,
                        }
                    )
                    next_id += 1
                i = j
                continue

        if stripped.startswith("```"):
            lang = stripped[3:].strip().lower()
            j = i + 1
            block: list[str] = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                block.append(lines[j])
                j += 1

            has_end = j < len(lines) and lines[j].strip().startswith("```")
            block_text = "\n".join(block).strip()
            prompt_like = True

            if prompt_like and block_text:
                category = classify_prompt_text(block_text, lang)
                prompts.append(
                    {
                        "id": f"prompt_{next_id:04d}",
                        "title": f"Code Prompt ({lang or 'block'})",
                        "category": category,
                        "text": block_text,
                        "source_slug": source_slug,
                        "source_title": source_title,
                        "source_path": source_path,
                    }
                )
                next_id += 1
                i = j + 1 if has_end else j
                continue

            out_lines.append(line)
            out_lines.extend(block)
            if has_end:
                out_lines.append(lines[j])
                i = j + 1
            else:
                i = j
            continue

        inline_prompt = re.match(
            r"^(ai\s+prompt|art\s+prompt|lore\s+prompt|negative\s+prompt|prompt)\s*:\s*(.+)$",
            stripped,
            flags=re.IGNORECASE,
        )
        if inline_prompt:
            hint = inline_prompt.group(1)
            text = inline_prompt.group(2).strip()
            category = classify_prompt_text(text, hint)
            prompts.append(
                {
                    "id": f"prompt_{next_id:04d}",
                    "title": hint.title(),
                    "category": category,
                    "text": text,
                    "source_slug": source_slug,
                    "source_title": source_title,
                    "source_path": source_path,
                }
            )
            next_id += 1
            i += 1
            continue

        out_lines.append(line)
        i += 1

    return "\n".join(out_lines).strip(), prompts, next_id


def build_lore() -> None:
    root = Path(__file__).resolve().parents[1]
    hits_path = root / "docs" / "logseq_config_term_hits.json"
    if not hits_path.exists():
        raise FileNotFoundError(f"Missing scan report: {hits_path}")

    report = json.loads(hits_path.read_text(encoding="utf-8"))
    hits_by_file = report.get("hits_by_file", {}) or {}

    out_dir = root / "lore"
    entries_dir = out_dir / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)
    prompts: list[dict] = []
    prompt_id = 1

    # Clean previously generated entries.
    for path in entries_dir.glob("*.json"):
        path.unlink()

    index_items: list[dict] = []

    for source_path, term_entries in sorted(hits_by_file.items()):
        path_obj = root / source_path
        if not path_obj.exists():
            # Skip stale paths gracefully.
            continue

        raw_text = path_obj.read_text(encoding="utf-8", errors="ignore")
        clean_text = clean_logseq_markdown(raw_text)
        title = title_from_path(source_path)
        slug = slugify(title)
        clean_text, entry_prompts, prompt_id = split_prompts_from_markdown(
            clean_text,
            source_slug=slug,
            source_title=title,
            source_path=source_path,
            id_start=prompt_id,
        )
        prompts.extend(entry_prompts)
        excerpt = first_excerpt(clean_text)

        terms = sorted({str(t.get("term", "")).strip() for t in term_entries if str(t.get("term", "")).strip()})
        categories = sorted({str(t.get("category", "")).strip() for t in term_entries if str(t.get("category", "")).strip()})
        mentions_total = int(sum(int(t.get("mentions", 0)) for t in term_entries))

        entry = {
            "type": "lore",
            "title": title,
            "slug": slug,
            "source": "logseq",
            "source_path": source_path,
            "excerpt": excerpt,
            "categories": categories,
            "terms": terms,
            "mentions_total": mentions_total,
            "content_markdown": clean_text,
            "prompt_counts": {
                "lore": len([p for p in entry_prompts if p["category"] == "lore"]),
                "art": len([p for p in entry_prompts if p["category"] == "art"]),
            },
        }
        (entries_dir / f"{slug}.json").write_text(
            json.dumps(entry, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        index_items.append({
            "title": title,
            "slug": slug,
            "source_path": source_path,
            "excerpt": excerpt,
            "categories": categories,
            "mentions_total": mentions_total,
        })

    index = {
        "count": len(index_items),
        "items": sorted(index_items, key=lambda x: x["title"].lower()),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "prompts_index.json").write_text(
        json.dumps(
            {
                "count": len(prompts),
                "counts_by_category": {
                    "lore": len([p for p in prompts if p["category"] == "lore"]),
                    "art": len([p for p in prompts if p["category"] == "art"]),
                },
                "items": prompts,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"Built {len(index_items)} lore entries at {out_dir}")
    print(f"Extracted {len(prompts)} prompts to {out_dir / 'prompts_index.json'}")


if __name__ == "__main__":
    build_lore()
