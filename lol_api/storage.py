from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def safe_slug(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "unnamed"


def effective_seed(payload: dict[str, Any]) -> str:
    seed = str(payload.get("seed", "")).strip()
    if seed:
        return seed

    return "random-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_storage_filename(result: dict[str, Any], payload: dict[str, Any]) -> str:
    item_type = safe_slug(str(result.get("type", "item")))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    return f"{item_type}_{timestamp}.json"

  


def ensure_unique_path(path: Path) -> Path:
    """
    If a file already exists, append a timestamp to avoid overwriting.
    """

    if not path.exists():
        return path

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    stem = path.stem
    suffix = path.suffix

    return path.with_name(f"{stem}_{timestamp}{suffix}")


def save_generated_result(storage_dir: Path, result: dict[str, Any], payload: dict[str, Any]) -> Path:
    storage_dir.mkdir(parents=True, exist_ok=True)

    filename = build_storage_filename(result, payload)
    path = storage_dir / filename

    path = ensure_unique_path(path)

    record = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "filename": path.name,
        "payload": payload,
        "result": result,
    }

    path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    return path


def list_saved_results(storage_dir: Path) -> list[dict[str, Any]]:
    if not storage_dir.exists():
        return []

    items: list[dict[str, Any]] = []

    for path in sorted(storage_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))

            items.append({
                "filename": path.name,
                "saved_at": data.get("saved_at"),
                "type": data.get("result", {}).get("type"),
                "name": data.get("result", {}).get("name"),
                "metadata": data.get("result", {}).get("metadata", {}),
            })

        except Exception:
            items.append({
                "filename": path.name,
                "saved_at": None,
                "type": "unknown",
                "name": None,
                "metadata": {},
            })

    return items


def load_saved_result(storage_dir: Path, filename: str) -> dict[str, Any]:
    path = storage_dir / filename

    if not path.exists():
        raise FileNotFoundError(f"No saved result named '{filename}'")

    return json.loads(path.read_text(encoding="utf-8"))

def search_saved_results(
    storage_dir: Path,
    *,
    item_type: str | None = None,
    environment: str | None = None,
    race: str | None = None,
    profession: str | None = None,
    name_contains: str | None = None,
) -> list[dict[str, Any]]:
    items = list_saved_results(storage_dir)

    def norm(value: str | None) -> str:
        return (value or "").strip().lower()

    item_type = norm(item_type)
    environment = norm(environment)
    race = norm(race)
    profession = norm(profession)
    name_contains = norm(name_contains)

    filtered: list[dict[str, Any]] = []

    for item in items:
        metadata = item.get("metadata", {}) or {}
        name = norm(item.get("name"))
        current_type = norm(item.get("type"))
        current_environment = norm(metadata.get("environment"))
        current_race = norm(metadata.get("race"))
        current_profession = norm(metadata.get("profession"))

        if item_type and current_type != item_type:
            continue
        if environment and current_environment != environment:
            continue
        if race and current_race != race:
            continue
        if profession and current_profession != profession:
            continue
        if name_contains and name_contains not in name:
            continue

        filtered.append(item)

    return filtered

