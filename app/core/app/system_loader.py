from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.contracts.context import normalize_token

SYSTEM_MANIFEST_FILENAME = "system.json"
ADDON_MANIFEST_FILENAME = "addon.json"
CONTENT_TYPE_MANIFEST_FILENAME = "content_types.json"
RULEBOOK_MANIFEST_FILENAME = "rulebook.json"
MODULE_MANIFEST_FILENAME = "module.json"


def _load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a top-level object")
    return data


def _sorted_child_dirs(path: Path) -> list[Path]:
    if not path.exists() or not path.is_dir():
        return []
    return [child for child in sorted(path.iterdir()) if child.is_dir() and not child.name.startswith(".")]


def validate_system_manifest(manifest: dict[str, Any], *, expected_id: str | None = None) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("system manifest must be an object")
    system_id = normalize_token(manifest.get("id"))
    if not system_id:
        raise ValueError("system manifest id is required")
    if expected_id and system_id != normalize_token(expected_id):
        raise ValueError(f"system manifest id '{system_id}' does not match folder '{expected_id}'")
    name = str(manifest.get("name") or "").strip()
    if not name:
        raise ValueError("system manifest name is required")
    return {
        "id": system_id,
        "name": name,
        "engine": str(manifest.get("engine") or "").strip(),
        "status": str(manifest.get("status") or "planned").strip().lower() or "planned",
        "summary": str(manifest.get("summary") or "").strip(),
        "content_roots": list(manifest.get("content_roots") or []),
        "default_types": list(manifest.get("default_types") or []),
        "supports_addons": bool(manifest.get("supports_addons", True)),
    }


def validate_content_types_manifest(manifest: dict[str, Any], *, expected_system_id: str) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("content types manifest must be an object")
    system_id = normalize_token(manifest.get("system_id"))
    if system_id != normalize_token(expected_system_id):
        raise ValueError(
            f"content types manifest system_id '{system_id}' does not match '{expected_system_id}'"
        )
    raw_types = manifest.get("types")
    if not isinstance(raw_types, list):
        raise ValueError("content types manifest types must be a list")
    types: list[dict[str, Any]] = []
    for item in raw_types:
        if not isinstance(item, dict):
            raise ValueError("content type entry must be an object")
        type_id = normalize_token(item.get("id"))
        if not type_id:
            raise ValueError("content type id is required")
        label = str(item.get("label") or "").strip()
        if not label:
            raise ValueError(f"content type '{type_id}' label is required")
        types.append(
            {
                "id": type_id,
                "label": label,
                "category": normalize_token(item.get("category")) or "record",
                "summary": str(item.get("summary") or "").strip(),
                "supports_generation": bool(item.get("supports_generation", False)),
                "supports_search": bool(item.get("supports_search", True)),
            }
        )
    return {"system_id": system_id, "types": types}


def validate_addon_manifest(
    manifest: dict[str, Any],
    *,
    expected_system_id: str,
    expected_addon_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("addon manifest must be an object")
    addon_id = normalize_token(manifest.get("id"))
    if not addon_id:
        raise ValueError("addon manifest id is required")
    if expected_addon_id and addon_id != normalize_token(expected_addon_id):
        raise ValueError(f"addon manifest id '{addon_id}' does not match folder '{expected_addon_id}'")
    system_id = normalize_token(manifest.get("system_id"))
    if system_id != normalize_token(expected_system_id):
        raise ValueError(f"addon manifest system_id '{system_id}' does not match '{expected_system_id}'")
    name = str(manifest.get("name") or "").strip()
    if not name:
        raise ValueError("addon manifest name is required")
    return {
        "id": addon_id,
        "system_id": system_id,
        "name": name,
        "status": str(manifest.get("status") or "planned").strip().lower() or "planned",
        "summary": str(manifest.get("summary") or "").strip(),
        "kind": str(manifest.get("kind") or "sourcebook").strip().lower() or "sourcebook",
    }


def validate_rulebook_manifest(
    manifest: dict[str, Any],
    *,
    expected_system_id: str,
    expected_addon_id: str,
) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("rulebook manifest must be an object")
    rulebook_id = normalize_token(manifest.get("id"))
    if not rulebook_id:
        raise ValueError("rulebook manifest id is required")
    system_id = normalize_token(manifest.get("system_id"))
    addon_id = normalize_token(manifest.get("addon_id"))
    if system_id != normalize_token(expected_system_id):
        raise ValueError(f"rulebook manifest system_id '{system_id}' does not match '{expected_system_id}'")
    if addon_id != normalize_token(expected_addon_id):
        raise ValueError(f"rulebook manifest addon_id '{addon_id}' does not match '{expected_addon_id}'")
    title = str(manifest.get("title") or "").strip()
    if not title:
        raise ValueError("rulebook manifest title is required")
    markdown_path = str(manifest.get("markdown_path") or "").strip()
    if not markdown_path:
        raise ValueError("rulebook manifest markdown_path is required")
    return {
        "id": rulebook_id,
        "system_id": system_id,
        "addon_id": addon_id,
        "title": title,
        "markdown_path": markdown_path,
        "html_path": str(manifest.get("html_path") or "").strip(),
        "source_path": str(manifest.get("source_path") or "").strip(),
        "format": str(manifest.get("format") or "markdown").strip().lower() or "markdown",
        "generated_toc": bool(manifest.get("generated_toc", True)),
        "summary": str(manifest.get("summary") or "").strip(),
    }


def validate_module_manifest(
    manifest: dict[str, Any],
    *,
    expected_system_id: str,
    expected_addon_id: str,
    expected_module_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("module manifest must be an object")
    module_id = normalize_token(manifest.get("id"))
    if not module_id:
        raise ValueError("module manifest id is required")
    if expected_module_id and module_id != normalize_token(expected_module_id):
        raise ValueError(f"module manifest id '{module_id}' does not match folder '{expected_module_id}'")
    system_id = normalize_token(manifest.get("system_id"))
    addon_id = normalize_token(manifest.get("addon_id"))
    if system_id != normalize_token(expected_system_id):
        raise ValueError(f"module manifest system_id '{system_id}' does not match '{expected_system_id}'")
    if addon_id != normalize_token(expected_addon_id):
        raise ValueError(f"module manifest addon_id '{addon_id}' does not match '{expected_addon_id}'")
    label = str(manifest.get("label") or manifest.get("name") or "").strip()
    if not label:
        raise ValueError("module manifest label is required")
    return {
        "id": module_id,
        "system_id": system_id,
        "addon_id": addon_id,
        "label": label,
        "status": str(manifest.get("status") or "planned").strip().lower() or "planned",
        "summary": str(manifest.get("summary") or "").strip(),
        "kind": str(manifest.get("kind") or "setting_module").strip().lower() or "setting_module",
        "theme": str(manifest.get("theme") or "").strip(),
        "scope": str(manifest.get("scope") or "").strip().lower() or "setting",
        "default_campaign_style": str(manifest.get("default_campaign_style") or "").strip(),
        "tags": [str(tag).strip() for tag in list(manifest.get("tags") or []) if str(tag).strip()],
        "feature_flags": dict(manifest.get("feature_flags") or {}),
    }


def discover_systems(systems_root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for system_dir in _sorted_child_dirs(systems_root):
        manifest_path = system_dir / SYSTEM_MANIFEST_FILENAME
        if not manifest_path.exists():
            continue
        system = validate_system_manifest(_load_json_object(manifest_path), expected_id=system_dir.name)
        content_types_path = system_dir / "content_types" / CONTENT_TYPE_MANIFEST_FILENAME
        content_types: list[dict[str, Any]] = []
        if content_types_path.exists():
            content_types = validate_content_types_manifest(
                _load_json_object(content_types_path),
                expected_system_id=system["id"],
            )["types"]

        addons_dir = system_dir / "addons"
        addons: list[dict[str, Any]] = []
        for addon_dir in _sorted_child_dirs(addons_dir):
            addon_path = addon_dir / ADDON_MANIFEST_FILENAME
            if not addon_path.exists():
                continue
            addon = validate_addon_manifest(
                    _load_json_object(addon_path),
                    expected_system_id=system["id"],
                    expected_addon_id=addon_dir.name,
                )
            rulebooks: list[dict[str, Any]] = []
            rulebook_path = addon_dir / RULEBOOK_MANIFEST_FILENAME
            if rulebook_path.exists():
                rulebooks.append(
                    validate_rulebook_manifest(
                        _load_json_object(rulebook_path),
                        expected_system_id=system["id"],
                        expected_addon_id=addon["id"],
                    )
                )
            modules: list[dict[str, Any]] = []
            modules_dir = addon_dir / "modules"
            for module_dir in _sorted_child_dirs(modules_dir):
                module_path = module_dir / MODULE_MANIFEST_FILENAME
                if not module_path.exists():
                    continue
                modules.append(
                    validate_module_manifest(
                        _load_json_object(module_path),
                        expected_system_id=system["id"],
                        expected_addon_id=addon["id"],
                        expected_module_id=module_dir.name,
                    )
                )
            addon["rulebooks"] = rulebooks
            addon["modules"] = modules
            addons.append(addon)

        item = dict(system)
        item["content_types"] = content_types
        item["addons"] = addons
        items.append(item)
    return items
