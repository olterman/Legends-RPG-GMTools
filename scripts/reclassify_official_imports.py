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

BOOK_HEADINGS = {
    "godforsaken",
    "claim the sky",
    "stay alive",
    "the stars are fire",
    "its only magic",
    "it's only magic",
    "high noon at midnight",
    "neon rain",
    "rust and redemption",
    "we are all mad here",
}

CREATURE_KEYWORDS = {
    "beast",
    "bear",
    "rat",
    "snake",
    "wraith",
    "troll",
    "zombie",
    "steed",
    "fiend",
    "goblin",
}

HUMANOID_KEYWORDS = {
    "officer",
    "captain",
    "doctor",
    "dr",
    "priest",
    "hunter",
    "aristocrat",
    "merchant",
    "guard",
    "knight",
    "paladin",
    "sorcerer",
}


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "untitled"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def looks_like_section_noise(title: str) -> bool:
    t = " ".join(str(title or "").strip().lower().split())
    if not t:
        return True
    if t in {"artifacts", "cyphers"}:
        return True
    if "cyphers and artifacts" in t:
        return True
    if t in BOOK_HEADINGS:
        return True
    return False


def detect_text_markers(text: str) -> dict[str, bool]:
    return {
        "depletion": bool(re.search(r"(?im)^\s*depletion\s*:", text)),
        "effect": bool(re.search(r"(?im)^\s*effect\s*:", text)),
        "manifestation": bool(re.search(r"(?im)^\s*manifestation\s*:", text)),
        "limitation": bool(re.search(r"(?im)^\s*limitation\s*:", text)),
        "motive": bool(re.search(r"(?im)^\s*motive\s*:", text)),
        "combat": bool(re.search(r"(?im)^\s*combat\s*:", text)),
        "gm_intrusion": bool(re.search(r"(?im)^\s*gm intrusion\s*:", text)),
    }


def infer_creature_from_title(title: str) -> bool:
    words = re.findall(r"[a-z]+", str(title or "").lower())
    if not words:
        return False
    if any(w in HUMANOID_KEYWORDS for w in words):
        return False
    return any(w in CREATURE_KEYWORDS for w in words)


def decide_type(item: dict[str, Any]) -> str:
    current_type = str(item.get("type") or "").strip().lower()
    title = str(item.get("title") or "")
    text = str(item.get("text") or "")
    markers = detect_text_markers(text)

    if current_type in {"cypher", "artifact"}:
        if markers["depletion"]:
            return "artifact"
        text_lc = text.lower()
        # Only flip artifact -> cypher with explicit cypher language.
        has_explicit_cypher_lang = (
            "this cypher" in text_lc
            or "cypher's level" in text_lc
            or "cypher’s level" in text_lc
        )
        if current_type == "artifact" and has_explicit_cypher_lang and not markers["depletion"]:
            return "cypher"
        if current_type == "cypher" and (markers["effect"] or markers["manifestation"] or markers["limitation"]):
            return "cypher"
        return current_type

    if current_type == "npc":
        if infer_creature_from_title(title):
            return "creature"
    return current_type


def build_index(out_dir: Path) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    counts_by_type: dict[str, int] = {}
    for item_type, folder_name in TYPE_TO_FOLDER.items():
        folder = out_dir / folder_name
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                data = load_json(path)
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


def process(out_dir: Path, apply: bool) -> dict[str, Any]:
    report: dict[str, Any] = {
        "changed": [],
        "excluded": [],
        "counts": {"scanned": 0, "changed": 0, "excluded": 0},
    }

    scan_folders = ["npcs", "cyphers", "artifacts", "creatures", "monsters"]
    for folder_name in scan_folders:
        folder = out_dir / folder_name
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            report["counts"]["scanned"] += 1
            try:
                data = load_json(path)
            except Exception:
                continue

            current_type = str(data.get("type") or "").strip().lower()
            title = str(data.get("title") or "").strip()
            if current_type not in SUPPORTED_TYPES:
                continue

            if looks_like_section_noise(title):
                excluded_rel = Path("_excluded") / folder_name / path.name
                report["excluded"].append({
                    "path": str(path.relative_to(out_dir)).replace("\\", "/"),
                    "title": title,
                    "reason": "section_heading_noise",
                    "target": str(excluded_rel).replace("\\", "/"),
                })
                report["counts"]["excluded"] += 1
                if apply:
                    target = out_dir / excluded_rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        target.unlink()
                    path.rename(target)
                continue

            new_type = decide_type(data)
            if new_type == current_type:
                continue
            target_folder = TYPE_TO_FOLDER[new_type]
            target_path = out_dir / target_folder / path.name
            if slugify(path.stem) != slugify(str(data.get("slug") or path.stem)):
                data["slug"] = slugify(path.stem)
            data["type"] = new_type
            metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
            metadata["reclassified_from"] = current_type
            metadata["reclassified_to"] = new_type
            data["metadata"] = metadata

            report["changed"].append({
                "path": str(path.relative_to(out_dir)).replace("\\", "/"),
                "title": title,
                "from": current_type,
                "to": new_type,
                "target": str(target_path.relative_to(out_dir)).replace("\\", "/"),
            })
            report["counts"]["changed"] += 1
            if apply:
                write_json(path, data)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if target_path.exists():
                    target_path.unlink()
                path.rename(target_path)

    if apply:
        index = build_index(out_dir)
        report["index_count"] = index.get("count", 0)
        report["index_counts_by_type"] = index.get("counts_by_type", {})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and reclassify imported official compendium entries.")
    parser.add_argument(
        "--out-dir",
        default="PDF_Repository/private_compendium",
        help="Private compendium output directory (default: PDF_Repository/private_compendium)",
    )
    parser.add_argument("--apply", action="store_true", help="Apply file moves/updates. Default is dry-run.")
    parser.add_argument(
        "--report",
        default="PDF_Repository/private_compendium/reclassification_report.json",
        help="Path to write JSON report.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    report = process(out_dir, apply=bool(args.apply))
    report_path = Path(args.report).resolve()
    write_json(report_path, report)

    print(f"Scanned: {report['counts']['scanned']}")
    print(f"Changed: {report['counts']['changed']}")
    print(f"Excluded: {report['counts']['excluded']}")
    print(f"Report: {report_path}")
    if args.apply:
        print(f"Index count: {report.get('index_count', 0)}")
        print(f"Index counts by type: {report.get('index_counts_by_type', {})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
