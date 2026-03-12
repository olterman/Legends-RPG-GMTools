from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_lore_index(lore_dir: Path) -> dict[str, Any]:
    path = lore_dir / "index.json"
    if not path.exists():
        return {"count": 0, "items": []}
    return json.loads(path.read_text(encoding="utf-8"))


def list_lore_items(lore_dir: Path) -> list[dict[str, Any]]:
    data = load_lore_index(lore_dir)
    return data.get("items", []) or []


def load_lore_item(lore_dir: Path, slug: str) -> dict[str, Any]:
    path = lore_dir / "entries" / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(f"No lore entry named '{slug}'")
    return json.loads(path.read_text(encoding="utf-8"))


def search_lore(lore_dir: Path, query: str | None = None) -> list[dict[str, Any]]:
    query_lc = (query or "").strip().lower()
    results: list[dict[str, Any]] = []
    for item in list_lore_items(lore_dir):
        if not query_lc:
            results.append(item)
            continue
        hay = " ".join([
            str(item.get("title", "")),
            str(item.get("excerpt", "")),
            " ".join(item.get("categories", []) or []),
            str(item.get("source_path", "")),
        ]).lower()
        if query_lc in hay:
            results.append(item)
    return results
