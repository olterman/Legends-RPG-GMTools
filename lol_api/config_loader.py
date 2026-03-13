from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a top-level mapping.")
    return data


def _merge_top_level(merged: dict[str, Any], data: dict[str, Any], source: Path) -> None:
    for key, value in data.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key].update(value)
        elif key in merged:
            raise ValueError(f"Duplicate top-level config key '{key}' in {source}")
        else:
            merged[key] = value


def list_world_ids(config_dir: Path) -> list[str]:
    worlds_dir = config_dir / "worlds"
    if not worlds_dir.exists():
        return []
    ids = [
        p.name
        for p in sorted(worlds_dir.iterdir())
        if p.is_dir() and not p.name.startswith(".")
    ]
    return ids


def list_setting_ids(config_dir: Path) -> list[str]:
    return list_world_ids(config_dir)


def load_world_layer(config_dir: Path, world_id: str) -> dict[str, Any]:
    world_dir = config_dir / "worlds" / world_id
    if not world_dir.exists():
        raise FileNotFoundError(f"World config folder not found: {world_dir}")

    merged_world: dict[str, Any] = {}
    for path in sorted(world_dir.glob("*.yaml")):
        data = load_yaml_file(path)
        _merge_top_level(merged_world, data, path)
    return merged_world


def load_setting_layer(config_dir: Path, setting_id: str) -> dict[str, Any]:
    return load_world_layer(config_dir, setting_id)


def infer_default_world_id(config_dir: Path) -> str | None:
    world_ids = set(list_world_ids(config_dir))
    if not world_ids:
        return None

    settings_file = config_dir / "02_settings.yaml"
    if settings_file.exists():
        try:
            data = load_yaml_file(settings_file)
            settings = (
                data.get("genres")
                if isinstance(data, dict) and isinstance(data.get("genres"), dict)
                else data.get("settings", {}) if isinstance(data, dict) else {}
            )
            defaults = settings.get("defaults", []) if isinstance(settings, dict) else []
            if isinstance(defaults, list):
                for value in defaults:
                    token = str(value or "").strip()
                    if token in world_ids:
                        return token
        except Exception:
            pass

    if len(world_ids) == 1:
        return next(iter(world_ids))
    return None


def infer_default_setting_id(config_dir: Path) -> str | None:
    return infer_default_world_id(config_dir)


def infer_core_setting_for_world(config_dir: Path, world_id: str) -> str | None:
    try:
        merged_world = load_world_layer(config_dir, world_id)
    except FileNotFoundError:
        return None

    world_block = merged_world.get("world", {}) if isinstance(merged_world, dict) else {}
    core_setting = None
    if isinstance(world_block, dict):
        core_setting = world_block.get("core_genre") or world_block.get("core_setting")
    token = str(core_setting or "").strip()
    return token or None


def infer_core_genre_for_setting(config_dir: Path, setting_id: str) -> str | None:
    return infer_core_setting_for_world(config_dir, setting_id)


def describe_world(config_dir: Path, world_id: str) -> dict[str, Any]:
    merged_world = load_world_layer(config_dir, world_id)
    world_block = merged_world.get("world", {}) if isinstance(merged_world, dict) else {}

    core_value = None
    if isinstance(world_block, dict):
        core_value = world_block.get("core_genre") or world_block.get("core_setting")

    return {
        "id": world_id,
        "label": str(world_block.get("label") or world_id).strip(),
        "core_setting": str(core_value or "").strip() or None,
        "core_genre": str(core_value or "").strip() or None,
        "description": str(world_block.get("description") or "").strip() or None,
    }


def describe_setting(config_dir: Path, setting_id: str) -> dict[str, Any]:
    return describe_world(config_dir, setting_id)


def list_world_descriptors(config_dir: Path) -> list[dict[str, Any]]:
    worlds: list[dict[str, Any]] = []
    for world_id in list_world_ids(config_dir):
        try:
            worlds.append(describe_world(config_dir, world_id))
        except Exception:
            worlds.append({
                "id": world_id,
                "label": world_id,
                "core_setting": None,
                "description": None,
            })
    return worlds


def list_setting_descriptors(config_dir: Path) -> list[dict[str, Any]]:
    return list_world_descriptors(config_dir)


def load_config_dir(
    config_dir: Path,
    *,
    world_id: str | None = None,
    setting_id: str | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}

    # Legacy flat config remains supported during migration.
    for path in sorted(config_dir.glob("*.yaml")):
        data = load_yaml_file(path)
        _merge_top_level(merged, data, path)

    # Optional core layer for shared, cross-world config.
    core_dir = config_dir / "core"
    if core_dir.exists():
        for path in sorted(core_dir.glob("*.yaml")):
            data = load_yaml_file(path)
            _merge_top_level(merged, data, path)

    # Optional genre layer (legacy name: setting), selected via world.core_genre / world.core_setting.
    active_world = (setting_id or world_id or "").strip()
    active_core_setting: str | None = None
    if active_world:
        active_core_setting = infer_core_setting_for_world(config_dir, active_world)

    if active_core_setting:
        setting_dir = config_dir / "settings" / active_core_setting
        if setting_dir.exists():
            for path in sorted(setting_dir.glob("*.yaml")):
                data = load_yaml_file(path)
                _merge_top_level(merged, data, path)

    # Optional world-specific layer (highest precedence).
    if active_world:
        world_dir = config_dir / "worlds" / active_world
        if not world_dir.exists():
            raise FileNotFoundError(f"World config folder not found: {world_dir}")
        for path in sorted(world_dir.glob("*.yaml")):
            data = load_yaml_file(path)
            _merge_top_level(merged, data, path)

    # Backward-compatible aliasing while refactoring "environment" -> "area".
    if "areas" not in merged and "environments" in merged:
        merged["areas"] = merged.get("environments", {})
    if "environments" not in merged and "areas" in merged:
        merged["environments"] = merged.get("areas", {})

    # Nested aliasing for monster maps.
    monster_traits = merged.get("monster_traits")
    if isinstance(monster_traits, dict):
        if "areas" not in monster_traits and "environments" in monster_traits:
            monster_traits["areas"] = monster_traits.get("environments", {})
        if "environments" not in monster_traits and "areas" in monster_traits:
            monster_traits["environments"] = monster_traits.get("areas", {})

    monster_names = merged.get("monster_names")
    if isinstance(monster_names, dict):
        if "areas" not in monster_names and "environments" in monster_names:
            monster_names["areas"] = monster_names.get("environments", {})
        if "environments" not in monster_names and "areas" in monster_names:
            monster_names["environments"] = monster_names.get("areas", {})

    return merged
