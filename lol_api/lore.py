from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .settings import normalize_settings_values

LORE_ENTRY_SCHEMA_VERSION = "1.0"
LOCATION_CATEGORY_TYPES = {
    "city",
    "forest",
    "mountain",
    "lake",
    "inn",
    "settlement",
    "cave",
    "dungeon",
    "landmark",
}
LOCATION_CATEGORY_PRIORITY = [
    "city",
    "settlement",
    "inn",
    "landmark",
    "dungeon",
    "cave",
    "mountain",
    "forest",
    "lake",
]


def _normalize_image_refs(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    refs: list[str] = []
    for value in values:
        text = str(value or "").strip().replace("\\", "/")
        if text.startswith("/images/"):
            text = text[len("/images/"):]
        if text.startswith("images/"):
            text = text[len("images/"):]
        text = text.strip("/")
        if not text:
            continue
        if text not in refs:
            refs.append(text)
    return refs


def _normalized_categories(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        key = str(value or "").strip().lower().replace(" ", "_")
        if key:
            out.append(key)
    return sorted(set(out))


def _pick_location_type(categories: list[str]) -> str:
    for key in LOCATION_CATEGORY_PRIORITY:
        if key in categories:
            return key
    return ""


def _is_location_entry(categories: list[str]) -> bool:
    return any(category in LOCATION_CATEGORY_TYPES for category in categories)


def _normalize_lore_item(item: dict[str, Any], default_settings: list[str] | None = None) -> dict[str, Any]:
    normalized = dict(item)
    categories = _normalized_categories(normalized.get("categories"))
    if categories:
        normalized["categories"] = categories

    if normalized.get("environment") and not normalized.get("area"):
        normalized["area"] = normalized.get("environment")
    if normalized.get("area") and not normalized.get("environment"):
        normalized["environment"] = normalized.get("area")

    if _is_location_entry(categories):
        normalized.setdefault("location", normalized.get("title") or normalized.get("slug") or "Unnamed Location")
        location_type = _pick_location_type(categories)
        if location_type:
            normalized["location_type"] = location_type
        if "location" not in categories:
            normalized["categories"] = sorted(set(categories + ["location"]))

    settings = normalize_settings_values(normalized.get("settings"))
    if not settings:
        settings = normalize_settings_values(normalized.get("setting"))
    if not settings:
        settings = normalize_settings_values(default_settings or [])
    if settings:
        normalized["settings"] = settings
        normalized["setting"] = normalized.get("setting") or settings[0]
    description = str(normalized.get("description") or "").strip()
    if not description:
        description = str(normalized.get("excerpt") or "").strip()
    if description:
        normalized["description"] = description
        normalized.setdefault("excerpt", description)
    normalized["images"] = _normalize_image_refs(normalized.get("images"))
    return normalized


def load_lore_index(
    lore_dir: Path,
    *,
    default_settings: list[str] | None = None,
) -> dict[str, Any]:
    path = lore_dir / "index.json"
    if not path.exists():
        return {"count": 0, "items": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else []
    if isinstance(items, list):
        data["items"] = [
            _normalize_lore_item(item, default_settings=default_settings)
            for item in items
            if isinstance(item, dict)
        ]
        data["count"] = len(data["items"])
    return data


def list_lore_items(
    lore_dir: Path,
    *,
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    data = load_lore_index(lore_dir, default_settings=default_settings)
    return data.get("items", []) or []


def load_lore_item(
    lore_dir: Path,
    slug: str,
    *,
    default_settings: list[str] | None = None,
) -> dict[str, Any]:
    path = lore_dir / "entries" / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(f"No lore entry named '{slug}'")
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data.setdefault("schema_version", LORE_ENTRY_SCHEMA_VERSION)
        return _normalize_lore_item(data, default_settings=default_settings)
    return data


def search_lore(
    lore_dir: Path,
    query: str | None = None,
    *,
    setting: str | None = None,
    location: str | None = None,
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    query_lc = (query or "").strip().lower()
    setting_lc = (setting or "").strip().lower()
    location_lc = (location or "").strip().lower()
    results: list[dict[str, Any]] = []
    for item in list_lore_items(lore_dir, default_settings=default_settings):
        item_settings = [
            str(value or "").strip().lower()
            for value in (item.get("settings") or [])
            if str(value or "").strip()
        ]
        if setting_lc and setting_lc not in item_settings:
            continue
        item_location = str(item.get("location") or item.get("title") or "").strip().lower()
        if location_lc and location_lc not in item_location:
            continue
        if not query_lc:
            results.append(item)
            continue
        hay = " ".join([
            str(item.get("title", "")),
            str(item.get("description", "")),
            str(item.get("excerpt", "")),
            " ".join(item.get("categories", []) or []),
            " ".join(item.get("settings", []) or []),
            str(item.get("location", "")),
            str(item.get("location_type", "")),
            str(item.get("area", "")),
            str(item.get("source_path", "")),
        ]).lower()
        if query_lc in hay:
            results.append(item)
    return results


def _index_path(lore_dir: Path) -> Path:
    return lore_dir / "index.json"


def _entries_dir(lore_dir: Path) -> Path:
    return lore_dir / "entries"


def _trash_entries_dir(lore_dir: Path) -> Path:
    return lore_dir / ".trash" / "entries"


def _slugify(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _load_index(lore_dir: Path) -> dict[str, Any]:
    path = _index_path(lore_dir)
    if not path.exists():
        return {"count": 0, "items": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"count": 0, "items": []}
    items = data.get("items")
    if not isinstance(items, list):
        data["items"] = []
    return data


def _write_index(lore_dir: Path, data: dict[str, Any]) -> None:
    items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
    data = dict(data)
    data["items"] = items
    data["count"] = len(items)
    _index_path(lore_dir).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _index_item_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    categories = _normalized_categories(entry.get("categories"))
    settings = normalize_settings_values(entry.get("settings"))
    if not settings:
        settings = normalize_settings_values(entry.get("setting"))
    area = str(entry.get("area") or entry.get("environment") or "").strip()
    location = str(entry.get("location") or entry.get("title") or "").strip()
    location_type = str(entry.get("location_type") or _pick_location_type(categories) or "").strip()
    return {
        "title": str(entry.get("title") or "Untitled"),
        "slug": str(entry.get("slug") or ""),
        "source_path": str(entry.get("source_path") or ""),
        "description": str(entry.get("description") or entry.get("excerpt") or ""),
        "excerpt": str(entry.get("excerpt") or entry.get("description") or ""),
        "categories": [str(x) for x in categories if str(x).strip()],
        "mentions_total": int(entry.get("mentions_total") or 0),
        "settings": settings,
        "setting": settings[0] if settings else "",
        "area": area,
        "environment": area,
        "location": location,
        "location_type": location_type,
        "images": _normalize_image_refs(entry.get("images")),
    }


def _upsert_index_item(lore_dir: Path, entry: dict[str, Any]) -> None:
    index_data = _load_index(lore_dir)
    items = [item for item in (index_data.get("items") or []) if isinstance(item, dict)]
    slug = str(entry.get("slug") or "").strip()
    if not slug:
        raise ValueError("lore entry slug is required")
    summary = _index_item_from_entry(entry)
    replaced = False
    next_items: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("slug") or "").strip() == slug:
            next_items.append(summary)
            replaced = True
        else:
            next_items.append(item)
    if not replaced:
        next_items.append(summary)
    index_data["items"] = next_items
    _write_index(lore_dir, index_data)


def _remove_index_slug(lore_dir: Path, slug: str) -> None:
    index_data = _load_index(lore_dir)
    items = [item for item in (index_data.get("items") or []) if isinstance(item, dict)]
    keep = [item for item in items if str(item.get("slug") or "").strip() != slug]
    index_data["items"] = keep
    _write_index(lore_dir, index_data)


def update_lore_item(lore_dir: Path, slug: str, item: dict[str, Any]) -> dict[str, Any]:
    slug_clean = _slugify(slug)
    if not slug_clean:
        raise ValueError("invalid lore slug")
    path = _entries_dir(lore_dir) / f"{slug_clean}.json"
    if not path.exists():
        raise FileNotFoundError(f"No lore entry named '{slug_clean}'")

    payload = dict(item)
    payload["slug"] = slug_clean
    payload.setdefault("type", "lore")
    payload.setdefault("title", "Untitled")
    payload.setdefault("source", "local")
    payload.setdefault("schema_version", LORE_ENTRY_SCHEMA_VERSION)
    categories = _normalized_categories(payload.get("categories"))
    if categories:
        payload["categories"] = categories

    area = str(payload.get("area") or payload.get("environment") or "").strip()
    if _is_location_entry(categories) or str(payload.get("location") or "").strip():
        if not area:
            raise ValueError("location entries require area")
        payload["area"] = area
        payload["environment"] = area
        payload["location"] = str(payload.get("location") or payload.get("title") or "Unnamed Location").strip()
        location_type = str(payload.get("location_type") or _pick_location_type(categories)).strip()
        if location_type:
            payload["location_type"] = location_type
        if "location" not in categories:
            payload["categories"] = sorted(set(categories + ["location"]))
    settings = normalize_settings_values(payload.get("settings"))
    if settings:
        payload["settings"] = settings
        payload["setting"] = payload.get("setting") or settings[0]
    payload["images"] = _normalize_image_refs(payload.get("images"))

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _upsert_index_item(lore_dir, payload)
    return payload


def list_trashed_lore_items(lore_dir: Path) -> list[dict[str, Any]]:
    root = _trash_entries_dir(lore_dir)
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), reverse=True):
        slug = path.stem
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append({
                "slug": slug,
                "title": data.get("title"),
                "source_path": data.get("source_path"),
            })
        except Exception:
            items.append({"slug": slug, "title": slug, "source_path": ""})
    return items


def load_trashed_lore_item(lore_dir: Path, slug: str) -> dict[str, Any]:
    slug_clean = _slugify(slug)
    if not slug_clean:
        raise FileNotFoundError(f"No trashed lore entry named '{slug}'")
    path = _trash_entries_dir(lore_dir) / f"{slug_clean}.json"
    if not path.exists():
        raise FileNotFoundError(f"No trashed lore entry named '{slug_clean}'")
    return json.loads(path.read_text(encoding="utf-8"))


def trash_lore_item(lore_dir: Path, slug: str) -> dict[str, str]:
    slug_clean = _slugify(slug)
    if not slug_clean:
        raise FileNotFoundError(f"No lore entry named '{slug}'")
    source = _entries_dir(lore_dir) / f"{slug_clean}.json"
    if not source.exists():
        raise FileNotFoundError(f"No lore entry named '{slug_clean}'")
    trash_dir = _trash_entries_dir(lore_dir)
    trash_dir.mkdir(parents=True, exist_ok=True)
    target = trash_dir / f"{slug_clean}.json"
    source.rename(target)
    _remove_index_slug(lore_dir, slug_clean)
    return {"slug": slug_clean}


def restore_trashed_lore_item(lore_dir: Path, slug: str) -> dict[str, str]:
    slug_clean = _slugify(slug)
    if not slug_clean:
        raise FileNotFoundError(f"No trashed lore entry named '{slug}'")
    source = _trash_entries_dir(lore_dir) / f"{slug_clean}.json"
    if not source.exists():
        raise FileNotFoundError(f"No trashed lore entry named '{slug_clean}'")
    entries_dir = _entries_dir(lore_dir)
    entries_dir.mkdir(parents=True, exist_ok=True)
    target = entries_dir / f"{slug_clean}.json"
    source.rename(target)
    data = json.loads(target.read_text(encoding="utf-8"))
    data["slug"] = slug_clean
    _upsert_index_item(lore_dir, data)
    return {"slug": slug_clean}


def expunge_trashed_lore_item(lore_dir: Path, slug: str) -> dict[str, str]:
    slug_clean = _slugify(slug)
    if not slug_clean:
        raise FileNotFoundError(f"No trashed lore entry named '{slug}'")
    target = _trash_entries_dir(lore_dir) / f"{slug_clean}.json"
    if not target.exists():
        raise FileNotFoundError(f"No trashed lore entry named '{slug_clean}'")
    target.unlink()
    return {"slug": slug_clean}
