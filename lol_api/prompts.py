from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_prompts_index(prompts_file: Path) -> dict[str, Any]:
    if not prompts_file.exists():
        return {"count": 0, "items": []}
    return json.loads(prompts_file.read_text(encoding="utf-8"))


def search_prompts(
    prompts_file: Path,
    query: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    data = load_prompts_index(prompts_file)
    items = data.get("items", []) or []
    query_lc = (query or "").strip().lower()
    category_lc = (category or "").strip().lower()

    out: list[dict[str, Any]] = []
    for item in items:
        item_category = str(item.get("category", "")).strip().lower()
        if category_lc and item_category != category_lc:
            continue

        if query_lc:
            hay = " ".join(
                [
                    str(item.get("title", "")),
                    str(item.get("source_title", "")),
                    str(item.get("source_slug", "")),
                    str(item.get("text", "")),
                ]
            ).lower()
            if query_lc not in hay:
                continue

        out.append(item)
    return out
