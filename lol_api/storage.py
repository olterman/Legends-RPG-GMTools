from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import normalize_settings_values

STORAGE_SCHEMA_VERSION = "1.0"


def _normalize_image_refs(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    refs: list[str] = []
    for value in values:
        text = str(value or "").strip().replace("\\", "/")
        if text.lower().startswith(("http://", "https://", "data:")):
            if text not in refs:
                refs.append(text)
            continue
        if text.startswith("/images/"):
            text = text[len("/images/"):]
        if text.startswith("images/"):
            text = text[len("images/"):]
        elif text.startswith("/"):
            if text not in refs:
                refs.append(text)
            continue
        text = text.strip("/")
        if not text:
            continue
        if text not in refs:
            refs.append(text)
    return refs


def safe_slug(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "unnamed"


def storage_subdir_for_result(result: dict[str, Any]) -> str:
    """
    Store records by high-level type to keep storage manageable.
    """
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    item_type = safe_slug(str(
        result.get("primarycategory")
        or metadata.get("primarycategory")
        or result.get("type", "item")
    ))
    source_raw = str(metadata.get("source") or "").strip().lower()
    source_norm = re.sub(r"[^a-z0-9]+", "", source_raw)
    if source_norm == "foundryvtt":
        settings = normalize_settings_values(metadata.get("settings"))
        if not settings:
            settings = normalize_settings_values(metadata.get("setting"))
        setting_slug = safe_slug(settings[0]) if settings else "unsorted"
        return f"foundryvtt/{setting_slug}/{item_type}"
    return item_type


def effective_seed(payload: dict[str, Any]) -> str:
    seed = str(payload.get("seed", "")).strip()
    if seed:
        return seed

    return "random-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_storage_filename(result: dict[str, Any], payload: dict[str, Any]) -> str:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    item_type = safe_slug(str(
        result.get("primarycategory")
        or metadata.get("primarycategory")
        or result.get("type", "item")
    ))
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
    subdir = storage_subdir_for_result(result)
    target_dir = storage_dir / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename

    path = ensure_unique_path(path)

    record = {
        "schema_version": STORAGE_SCHEMA_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "filename": str(path.relative_to(storage_dir)).replace("\\", "/"),
        "payload": payload,
        "result": result,
    }

    path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    return path


def list_saved_results(
    storage_dir: Path,
    *,
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not storage_dir.exists():
        return []

    items: list[dict[str, Any]] = []

    for path in sorted(storage_dir.rglob("*.json"), reverse=True):
        if ".locks" in path.parts:
            continue
        if ".trash" in path.parts:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rel = str(path.relative_to(storage_dir)).replace("\\", "/")
            metadata = data.get("result", {}).get("metadata", {}) or {}
            settings = normalize_settings_values(metadata.get("settings"))
            if not settings:
                settings = normalize_settings_values(metadata.get("setting"))
            if not settings:
                settings = normalize_settings_values(default_settings or [])

            normalized_metadata = dict(metadata)
            if normalized_metadata.get("environment") and not normalized_metadata.get("area"):
                normalized_metadata["area"] = normalized_metadata.get("environment")
            if normalized_metadata.get("area") and not normalized_metadata.get("environment"):
                normalized_metadata["environment"] = normalized_metadata.get("area")
            if settings:
                normalized_metadata["settings"] = settings
                normalized_metadata.setdefault("setting", settings[0])
            normalized_metadata["images"] = _normalize_image_refs(normalized_metadata.get("images"))
            result_obj = data.get("result", {}) or {}
            sections = result_obj.get("sections", {}) or {}
            sheet = result_obj.get("sheet", {}) or {}
            description = ""
            for candidate in (
                result_obj.get("description"),
                normalized_metadata.get("description"),
                sections.get("description"),
                sections.get("summary"),
                sections.get("effect"),
                sections.get("use"),
                result_obj.get("excerpt"),
                sheet.get("notes"),
                result_obj.get("text"),
            ):
                text = " ".join(str(candidate or "").strip().split())
                if text:
                    description = text
                    break

            items.append({
                "filename": rel,
                "saved_at": data.get("saved_at"),
                "type": result_obj.get("type"),
                "name": result_obj.get("name"),
                "description": description,
                "settlement_type": result_obj.get("settlement_type") or sections.get("settlement_type"),
                "sections": sections if isinstance(sections, dict) else {},
                "metadata": normalized_metadata,
            })

        except Exception:
            rel = str(path.relative_to(storage_dir)).replace("\\", "/")
            items.append({
                "filename": rel,
                "saved_at": None,
                "type": "unknown",
                "name": None,
                "description": "",
                "metadata": {},
            })

    return items


def trash_saved_result(storage_dir: Path, filename: str) -> dict[str, str]:
    source_path = (storage_dir / filename).resolve()
    root = storage_dir.resolve()

    if not str(source_path).startswith(str(root) + "/") and source_path != root:
        raise FileNotFoundError(f"No saved result named '{filename}'")
    if not source_path.exists():
        raise FileNotFoundError(f"No saved result named '{filename}'")
    if ".trash" in source_path.parts:
        raise FileNotFoundError(f"No saved result named '{filename}'")

    trash_root = storage_dir / ".trash"
    target_path = trash_root / filename
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path = ensure_unique_path(target_path)
    source_path.rename(target_path)

    return {
        "filename": filename,
        "trash_filename": str(target_path.relative_to(trash_root)).replace("\\", "/"),
    }


def list_trashed_results(storage_dir: Path) -> list[dict[str, Any]]:
    trash_root = storage_dir / ".trash"
    if not trash_root.exists():
        return []

    items: list[dict[str, Any]] = []
    for path in sorted(trash_root.rglob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rel = str(path.relative_to(trash_root)).replace("\\", "/")
            result = data.get("result", {}) if isinstance(data, dict) else {}
            items.append({
                "filename": rel,
                "saved_at": data.get("saved_at"),
                "type": result.get("type"),
                "name": result.get("name"),
            })
        except Exception:
            rel = str(path.relative_to(trash_root)).replace("\\", "/")
            items.append({
                "filename": rel,
                "saved_at": None,
                "type": "unknown",
                "name": None,
            })
    return items


def load_trashed_result(storage_dir: Path, trash_filename: str) -> dict[str, Any]:
    trash_root = (storage_dir / ".trash").resolve()
    path = (trash_root / trash_filename).resolve()

    if not str(path).startswith(str(trash_root) + "/") and path != trash_root:
        raise FileNotFoundError(f"No trashed result named '{trash_filename}'")
    if not path.exists():
        raise FileNotFoundError(f"No trashed result named '{trash_filename}'")

    return json.loads(path.read_text(encoding="utf-8"))


def restore_trashed_result(storage_dir: Path, trash_filename: str) -> dict[str, str]:
    trash_root = (storage_dir / ".trash").resolve()
    source_path = (trash_root / trash_filename).resolve()
    root = storage_dir.resolve()

    if not str(source_path).startswith(str(trash_root) + "/") and source_path != trash_root:
        raise FileNotFoundError(f"No trashed result named '{trash_filename}'")
    if not source_path.exists():
        raise FileNotFoundError(f"No trashed result named '{trash_filename}'")

    target_path = root / trash_filename
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path = ensure_unique_path(target_path)
    source_path.rename(target_path)

    # Clean up empty folders in trash tree.
    parent = source_path.parent
    while parent != trash_root and parent.exists():
        if any(parent.iterdir()):
            break
        parent.rmdir()
        parent = parent.parent

    return {
        "trash_filename": trash_filename,
        "filename": str(target_path.relative_to(root)).replace("\\", "/"),
    }


def expunge_trashed_result(storage_dir: Path, trash_filename: str) -> dict[str, str]:
    trash_root = (storage_dir / ".trash").resolve()
    target = (trash_root / trash_filename).resolve()

    if not str(target).startswith(str(trash_root) + "/") and target != trash_root:
        raise FileNotFoundError(f"No trashed result named '{trash_filename}'")
    if not target.exists():
        raise FileNotFoundError(f"No trashed result named '{trash_filename}'")

    target.unlink()

    parent = target.parent
    while parent != trash_root and parent.exists():
        if any(parent.iterdir()):
            break
        parent.rmdir()
        parent = parent.parent

    return {"trash_filename": trash_filename}


def update_saved_result(storage_dir: Path, filename: str, record: dict[str, Any]) -> dict[str, Any]:
    path = (storage_dir / filename).resolve()
    root = storage_dir.resolve()

    if not str(path).startswith(str(root) + "/") and path != root:
        raise FileNotFoundError(f"No saved result named '{filename}'")
    if not path.exists():
        raise FileNotFoundError(f"No saved result named '{filename}'")

    to_write = dict(record)
    to_write.setdefault("schema_version", STORAGE_SCHEMA_VERSION)
    to_write["filename"] = filename
    to_write.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
    path.write_text(json.dumps(to_write, indent=2, ensure_ascii=False), encoding="utf-8")
    return to_write


def load_saved_result(
    storage_dir: Path,
    filename: str,
    *,
    default_settings: list[str] | None = None,
) -> dict[str, Any]:
    path = (storage_dir / filename).resolve()
    root = storage_dir.resolve()

    if not str(path).startswith(str(root) + "/") and path != root:
        raise FileNotFoundError(f"No saved result named '{filename}'")

    if not path.exists():
        raise FileNotFoundError(f"No saved result named '{filename}'")

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data.setdefault("schema_version", STORAGE_SCHEMA_VERSION)
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    settings = normalize_settings_values(metadata.get("settings"))
    if not settings:
        settings = normalize_settings_values(metadata.get("setting"))
    if not settings:
        settings = normalize_settings_values(default_settings or [])
    if settings:
        metadata = dict(metadata)
        metadata["settings"] = settings
        metadata.setdefault("setting", settings[0])
    metadata["images"] = _normalize_image_refs(metadata.get("images"))
    if metadata:
        result = dict(result)
        result["metadata"] = metadata
        data = dict(data)
        data["result"] = result
    return data

def search_saved_results(
    storage_dir: Path,
    *,
    item_type: str | None = None,
    setting: str | None = None,
    area: str | None = None,
    location: str | None = None,
    environment: str | None = None,
    race: str | None = None,
    profession: str | None = None,
    name_contains: str | None = None,
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    items = list_saved_results(storage_dir, default_settings=default_settings)

    def norm(value: str | None) -> str:
        return (value or "").strip().lower()

    def norm_search_text(value: str | None) -> str:
        text = norm(value)
        text = text.replace("_", " ").replace("-", " ")
        return " ".join(text.split())

    item_type = norm(item_type)
    setting = norm(setting)
    area = norm(area)
    location = norm(location)
    environment = norm(environment)
    race = norm(race)
    profession = norm(profession)
    name_contains = norm_search_text(name_contains)

    filtered: list[dict[str, Any]] = []

    for item in items:
        metadata = item.get("metadata", {}) or {}
        name = norm(item.get("name"))
        current_type = norm(item.get("type"))
        current_settings = [norm(value) for value in metadata.get("settings", [])]
        if not current_settings and metadata.get("setting"):
            current_settings = [norm(metadata.get("setting"))]
        current_area = norm(metadata.get("area") or metadata.get("environment"))
        current_location = norm(metadata.get("location"))
        current_race = norm(metadata.get("race"))
        current_profession = norm(metadata.get("profession"))
        current_subtype = norm(metadata.get("subtype") or metadata.get("location_category_type"))
        current_primarycategory = norm(metadata.get("primarycategory") or current_subtype)
        sections = item.get("sections") if isinstance(item.get("sections"), dict) else {}
        current_settlement_type = norm(
            item.get("settlement_type")
            or metadata.get("settlement_type")
            or sections.get("settlement_type")
        )
        description = norm_search_text(item.get("description"))
        text_haystack = " ".join(
            value for value in [
                norm_search_text(name),
                description,
                norm_search_text(current_type),
                norm_search_text(current_subtype),
                norm_search_text(current_primarycategory),
                norm_search_text(current_area),
                norm_search_text(current_location),
                norm_search_text(current_race),
                norm_search_text(current_profession),
                norm_search_text(current_settlement_type),
                norm_search_text(" ".join(current_settings)),
            ] if value
        )

        if item_type:
            if item_type == "landmark":
                if current_type != "location" or current_subtype != "landmark":
                    continue
            elif item_type == "city":
                if current_subtype != "city" and "city" not in current_settlement_type:
                    continue
            elif item_type == "village":
                if current_subtype != "village" and "village" not in current_settlement_type:
                    continue
            elif item_type == "player_character":
                if current_type not in {"character", "character_sheet"}:
                    continue
            elif item_type == "rollable_table":
                if current_type != "rollable_table" and current_primarycategory != "rollable_table":
                    continue
            elif current_type != item_type:
                continue
        if setting and setting not in current_settings:
            continue
        # Legacy alias support: `environment` behaves like `area`.
        area_filter = area or environment
        if area_filter and current_area != area_filter:
            continue
        if location and location not in current_location:
            continue
        if race and current_race != race:
            continue
        if profession and current_profession != profession:
            continue
        if name_contains and name_contains not in text_haystack:
            continue

        filtered.append(item)

    return filtered
