from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SUPPORTED_COMPENDIUM_TYPES = {
    "cypher",
    "creature",
    "character_type",
    "flavor",
    "descriptor",
    "focus",
    "ability",
    "skill",
}

_TYPE_TO_FOLDER = {
    "cypher": "cyphers",
    "creature": "creatures",
    "character_type": "types",
    "flavor": "flavors",
    "descriptor": "descriptors",
    "focus": "foci",
    "ability": "abilities",
    "skill": "skills",
}


def compendium_folder_for_type(item_type: str) -> str:
    if item_type not in SUPPORTED_COMPENDIUM_TYPES:
        raise ValueError(f"Unsupported compendium type '{item_type}'")
    return _TYPE_TO_FOLDER[item_type]


def load_compendium_index(compendium_dir: Path) -> dict[str, Any]:
    index_path = compendium_dir / "index.json"
    if not index_path.exists():
        return {
            "cyphers": 0,
            "creatures": 0,
            "types": 0,
            "flavors": 0,
            "descriptors": 0,
            "foci": 0,
            "abilities": 0,
            "skills": 0,
        }
    return json.loads(index_path.read_text(encoding="utf-8"))


def list_compendium_items(compendium_dir: Path, item_type: str) -> list[dict[str, Any]]:
    folder = compendium_dir / compendium_folder_for_type(item_type)
    if not folder.exists():
        return []

    items = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append({
                "title": data.get("title"),
                "slug": data.get("slug"),
                "type": data.get("type"),
                "category": data.get("category"),
                "level": data.get("level"),
                "environment": data.get("environment"),
                "summary": data.get("summary"),
                "cost": data.get("cost"),
                "alpha_section": data.get("alpha_section"),
                "path": path.name,
            })
        except Exception:
            continue
    return items


def load_compendium_item(compendium_dir: Path, item_type: str, slug: str) -> dict[str, Any]:
    path = compendium_dir / compendium_folder_for_type(item_type) / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(f"No {item_type} named '{slug}'")
    return json.loads(path.read_text(encoding="utf-8"))


def search_compendium(
    compendium_dir: Path,
    *,
    item_type: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    query = (query or "").strip().lower()
    if item_type in SUPPORTED_COMPENDIUM_TYPES:
        types = [item_type]
    else:
        types = sorted(SUPPORTED_COMPENDIUM_TYPES)

    results: list[dict[str, Any]] = []

    for t in types:
        # Abilities often contain nested named options in effect/details text.
        # For those, include full-file text in the searchable haystack.
        if t == "ability" and query:
            folder = compendium_dir / compendium_folder_for_type(t)
            if not folder.exists():
                continue

            for path in sorted(folder.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue

                details_text = " ".join(str(x) for x in (data.get("details") or []))
                haystack = " ".join([
                    str(data.get("title", "")),
                    str(data.get("slug", "")),
                    str(data.get("type", "")),
                    str(data.get("cost", "")),
                    str(data.get("alpha_section", "")),
                    str(data.get("effect", "")),
                    details_text,
                ]).lower()

                if query and query not in haystack:
                    continue

                results.append({
                    "title": data.get("title"),
                    "slug": data.get("slug"),
                    "type": data.get("type"),
                    "category": data.get("category"),
                    "level": data.get("level"),
                    "environment": data.get("environment"),
                    "summary": data.get("summary"),
                    "cost": data.get("cost"),
                    "alpha_section": data.get("alpha_section"),
                    "path": path.name,
                })
            continue

        for item in list_compendium_items(compendium_dir, t):
            haystack = " ".join(
                str(item.get(k, "")) for k in ["title", "slug", "category", "environment", "level", "type"]
            ).lower()
            if query and query not in haystack:
                continue
            results.append(item)

    return results
