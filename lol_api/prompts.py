from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import normalize_settings_values


def _build_lore_settings_map(prompts_file: Path) -> dict[str, list[str]]:
    lore_index = prompts_file.parent / "index.json"
    if not lore_index.exists():
        return {}
    try:
        data = json.loads(lore_index.read_text(encoding="utf-8"))
    except Exception:
        return {}

    items = data.get("items", []) if isinstance(data, dict) else []
    out: dict[str, list[str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug", "")).strip()
        if not slug:
            continue
        settings = normalize_settings_values(item.get("settings"))
        if not settings:
            settings = normalize_settings_values(item.get("setting"))
        out[slug] = settings
    return out


def _normalize_prompt_item(
    item: dict[str, Any],
    *,
    lore_settings_map: dict[str, list[str]],
    default_settings: list[str] | None = None,
) -> dict[str, Any]:
    out = dict(item)
    settings = normalize_settings_values(out.get("settings"))
    if not settings:
        settings = normalize_settings_values(out.get("setting"))
    if not settings:
        settings = lore_settings_map.get(str(out.get("source_slug", "")).strip(), [])
    if not settings:
        settings = normalize_settings_values(default_settings or [])
    if settings:
        out["settings"] = settings
        out["setting"] = out.get("setting") or settings[0]
    return out


def load_prompts_index(
    prompts_file: Path,
    *,
    default_settings: list[str] | None = None,
) -> dict[str, Any]:
    if not prompts_file.exists():
        return {"count": 0, "items": []}
    data = json.loads(prompts_file.read_text(encoding="utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else []
    lore_settings_map = _build_lore_settings_map(prompts_file)
    if isinstance(items, list):
        data["items"] = [
            _normalize_prompt_item(
                item,
                lore_settings_map=lore_settings_map,
                default_settings=default_settings,
            )
            for item in items
            if isinstance(item, dict)
        ]
        data["count"] = len(data["items"])
    return data


def search_prompts(
    prompts_file: Path,
    query: str | None = None,
    category: str | None = None,
    setting: str | None = None,
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    data = load_prompts_index(prompts_file, default_settings=default_settings)
    items = data.get("items", []) or []
    query_lc = (query or "").strip().lower()
    category_lc = (category or "").strip().lower()
    setting_lc = (setting or "").strip().lower()

    out: list[dict[str, Any]] = []
    for item in items:
        item_category = str(item.get("category", "")).strip().lower()
        if category_lc and item_category != category_lc:
            continue
        item_settings = [
            str(value or "").strip().lower()
            for value in (item.get("settings") or [])
            if str(value or "").strip()
        ]
        if setting_lc and setting_lc not in item_settings:
            continue

        if query_lc:
            hay = " ".join(
                [
                    str(item.get("title", "")),
                    str(item.get("source_title", "")),
                    str(item.get("source_slug", "")),
                    " ".join(item.get("settings", []) or []),
                    str(item.get("text", "")),
                ]
            ).lower()
            if query_lc not in hay:
                continue

        out.append(item)
    return out


def _recount_by_category(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        category = str(item.get("category") or "unknown").strip().lower() or "unknown"
        counts[category] = counts.get(category, 0) + 1
    return counts


def _write_prompts_index(prompts_file: Path, items: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "count": len(items),
        "counts_by_category": _recount_by_category(items),
        "items": items,
    }
    prompts_file.parent.mkdir(parents=True, exist_ok=True)
    prompts_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def update_prompt(
    prompts_file: Path,
    prompt_id: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    prompt_id = str(prompt_id or "").strip()
    if not prompt_id:
        raise ValueError("prompt id is required")

    data = load_prompts_index(prompts_file)
    items = list(data.get("items") or [])
    index = next((i for i, existing in enumerate(items) if str(existing.get("id") or "").strip() == prompt_id), -1)
    if index < 0:
        raise FileNotFoundError(f"No prompt with id '{prompt_id}'")

    updated = dict(item)
    updated["id"] = prompt_id
    updated.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
    items[index] = updated
    _write_prompts_index(prompts_file, items)
    return updated


def trash_prompt(prompts_file: Path, prompt_id: str) -> dict[str, Any]:
    prompt_id = str(prompt_id or "").strip()
    if not prompt_id:
        raise ValueError("prompt id is required")

    data = load_prompts_index(prompts_file)
    items = list(data.get("items") or [])
    index = next((i for i, existing in enumerate(items) if str(existing.get("id") or "").strip() == prompt_id), -1)
    if index < 0:
        raise FileNotFoundError(f"No prompt with id '{prompt_id}'")

    removed = items.pop(index)
    _write_prompts_index(prompts_file, items)

    trash_dir = prompts_file.parent / ".trash" / "prompts"
    trash_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    trash_name = f"{prompt_id}_{ts}.json"
    (trash_dir / trash_name).write_text(
        json.dumps({"id": prompt_id, "trashed_at": datetime.now(timezone.utc).isoformat(), "item": removed}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"id": prompt_id, "trash_file": trash_name, "item": removed}
