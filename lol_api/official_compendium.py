from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SUPPORTED_OFFICIAL_COMPENDIUM_TYPES = {
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

_TYPE_TO_FOLDER = {
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


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "untitled"


def official_folder_for_type(item_type: str) -> str:
    if item_type not in SUPPORTED_OFFICIAL_COMPENDIUM_TYPES:
        raise ValueError(f"Unsupported official compendium type '{item_type}'")
    return _TYPE_TO_FOLDER[item_type]


def load_official_compendium_index(official_dir: Path) -> dict[str, Any]:
    index_path = official_dir / "index.json"
    if not index_path.exists():
        return {"count": 0, "counts_by_type": {}, "items": []}
    return json.loads(index_path.read_text(encoding="utf-8"))


def list_official_items(official_dir: Path, item_type: str) -> list[dict[str, Any]]:
    folder = official_dir / official_folder_for_type(item_type)
    if not folder.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        items.append({
            "title": data.get("title"),
            "slug": data.get("slug"),
            "type": data.get("type"),
            "book": data.get("book"),
            "pages": data.get("pages"),
            "setting": data.get("setting"),
            "settings": data.get("settings"),
            "description": data.get("description"),
            "path": path.name,
        })
    return items


def load_official_item(official_dir: Path, item_type: str, slug: str) -> dict[str, Any]:
    path = official_dir / official_folder_for_type(item_type) / f"{_slugify(slug)}.json"
    if not path.exists():
        raise FileNotFoundError(f"No official {item_type} named '{slug}'")
    return json.loads(path.read_text(encoding="utf-8"))


def search_official_compendium(
    official_dir: Path,
    *,
    item_type: str | None = None,
    setting: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    query_lc = str(query or "").strip().lower()
    setting_lc = str(setting or "").strip().lower()
    if item_type in SUPPORTED_OFFICIAL_COMPENDIUM_TYPES:
        types = [str(item_type)]
    else:
        types = sorted(SUPPORTED_OFFICIAL_COMPENDIUM_TYPES)

    results: list[dict[str, Any]] = []
    for t in types:
        for item in list_official_items(official_dir, t):
            item_settings = [
                str(x or "").strip().lower()
                for x in (item.get("settings") or [])
                if str(x or "").strip()
            ]
            if setting_lc and item_settings and setting_lc not in item_settings and "all_settings" not in item_settings:
                continue
            hay = " ".join([
                str(item.get("title") or ""),
                str(item.get("slug") or ""),
                str(item.get("type") or ""),
                str(item.get("book") or ""),
                str(item.get("description") or ""),
                " ".join(item.get("settings") or []),
            ]).lower()
            if query_lc and query_lc not in hay:
                continue
            results.append(item)
    return results

