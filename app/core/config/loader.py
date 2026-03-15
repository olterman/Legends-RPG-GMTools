from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.contracts.context import NONE_SYSTEM_ID, build_context, normalize_token, validate_context

MANIFEST_FILENAME = "manifest.json"


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a top-level object")
    return data


def _child_dirs(path: Path) -> list[Path]:
    if not path.exists() or not path.is_dir():
        return []
    return [child for child in sorted(path.iterdir()) if child.is_dir() and not child.name.startswith(".")]


def discover_system_ids(content_root: Path) -> list[str]:
    ids: list[str] = []
    for child in _child_dirs(content_root):
        token = normalize_token(child.name)
        if token and token not in ids:
            ids.append(token)
    return ids


def discover_setting_ids(content_root: Path, *, system_id: str) -> list[str]:
    root = content_root / normalize_token(system_id)
    ids: list[str] = []
    for child in _child_dirs(root):
        token = normalize_token(child.name)
        if token and token not in ids:
            ids.append(token)
    return ids


def discover_campaign_ids(
    content_root: Path,
    *,
    system_id: str,
    setting_id: str,
) -> list[str]:
    root = (
        content_root
        / normalize_token(system_id)
        / normalize_token(setting_id)
    )
    ids: list[str] = []
    for child in _child_dirs(root):
        token = normalize_token(child.name)
        if token and token not in ids:
            ids.append(token)
    return ids


def build_context_catalog(content_root: Path) -> dict[str, Any]:
    catalog: dict[str, Any] = {"systems": {}}
    for system_id in discover_system_ids(content_root):
        system_block: dict[str, Any] = {"settings": {}}
        for setting_id in discover_setting_ids(content_root, system_id=system_id):
            system_block["settings"][setting_id] = {
                "campaigns": discover_campaign_ids(
                    content_root,
                    system_id=system_id,
                    setting_id=setting_id,
                )
            }
        catalog["systems"][system_id] = system_block
    return catalog


def manifest_path_for_context(content_root: Path, context: dict[str, Any], *, level: str) -> Path | None:
    ctx = validate_context(context)
    system_id = ctx["system_id"]
    setting_id = ctx["setting_id"]
    campaign_id = ctx["campaign_id"]

    if level == "system":
        if system_id == NONE_SYSTEM_ID:
            return None
        return content_root / system_id / MANIFEST_FILENAME
    if level == "setting":
        if system_id == NONE_SYSTEM_ID or not setting_id:
            return None
        return content_root / system_id / setting_id / MANIFEST_FILENAME
    if level == "campaign":
        if system_id == NONE_SYSTEM_ID or not setting_id or not campaign_id:
            return None
        return content_root / system_id / setting_id / campaign_id / MANIFEST_FILENAME
    raise ValueError(f"unsupported manifest level '{level}'")


def load_context_manifests(content_root: Path, context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for level in ("system", "setting", "campaign"):
        path = manifest_path_for_context(content_root, context, level=level)
        if path is None or not path.exists():
            continue
        manifests[level] = load_json_object(path)
    return manifests


def build_default_context_from_catalog(catalog: dict[str, Any]) -> dict[str, str]:
    systems = catalog.get("systems", {}) if isinstance(catalog, dict) else {}
    if not isinstance(systems, dict) or not systems:
        return build_context(system_id=NONE_SYSTEM_ID)

    system_id = next(iter(systems.keys()))
    settings = (systems.get(system_id) or {}).get("settings", {})
    if not isinstance(settings, dict) or not settings:
        return build_context(system_id=system_id)

    setting_id = next(iter(settings.keys()))
    campaigns = ((settings.get(setting_id) or {}).get("campaigns") or [])
    campaign_id = campaigns[0] if campaigns else ""
    return build_context(
        system_id=system_id,
        setting_id=setting_id,
        campaign_id=campaign_id,
    )
