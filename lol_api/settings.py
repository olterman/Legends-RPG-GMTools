from __future__ import annotations

import re
from typing import Any


def normalize_setting_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def normalize_settings_values(raw: Any) -> list[str]:
    values: list[str] = []

    def push(value: Any) -> None:
        token = normalize_setting_token(value)
        if token and token not in values:
            values.append(token)

    if raw is None:
        return values

    if isinstance(raw, str):
        # Allow either a single token or comma-delimited lists in query/payload values.
        for part in raw.split(","):
            push(part)
        return values

    if isinstance(raw, (list, tuple, set)):
        for item in raw:
            push(item)
        return values

    if isinstance(raw, dict):
        # Accept {"fantasy": true, "modern": false}-style maps.
        for key, enabled in raw.items():
            if enabled:
                push(key)
        return values

    push(raw)
    return values


def settings_catalog(config: dict[str, Any]) -> list[str]:
    catalog: list[str] = []

    def add_many(raw: Any) -> None:
        for token in normalize_settings_values(raw):
            if token not in catalog:
                catalog.append(token)

    raw = config.get("settings")
    if isinstance(raw, list):
        add_many(raw)
    elif isinstance(raw, dict):
        if isinstance(raw.get("core"), list):
            add_many(raw.get("core"))
        if isinstance(raw.get("catalog"), list):
            add_many(raw.get("catalog"))
        if isinstance(raw.get("catalog"), dict):
            add_many(list(raw.get("catalog").keys()))
        # Fallback: a direct mapping keyed by setting ids.
        if not catalog:
            add_many(list(raw.keys()))

    setting_cfg = config.get("setting", {}) or {}
    add_many(setting_cfg.get("id"))
    add_many(setting_cfg.get("name"))

    return catalog


def settings_worlds_map(config: dict[str, Any]) -> dict[str, list[str]]:
    settings_cfg = config.get("settings", {}) or {}
    catalog = settings_cfg.get("catalog", {}) if isinstance(settings_cfg, dict) else {}
    worlds_map: dict[str, list[str]] = {}
    if not isinstance(catalog, dict):
        return worlds_map

    for core_key, details in catalog.items():
        core = normalize_setting_token(core_key)
        if not core:
            continue
        worlds = normalize_settings_values((details or {}).get("worlds") if isinstance(details, dict) else None)
        worlds_map[core] = worlds

    return worlds_map


def core_settings(config: dict[str, Any]) -> list[str]:
    settings_cfg = config.get("settings", {}) or {}
    if isinstance(settings_cfg, dict) and isinstance(settings_cfg.get("core"), list):
        return normalize_settings_values(settings_cfg.get("core"))
    return [k for k in settings_worlds_map(config).keys()]


def settings_nav_model(config: dict[str, Any]) -> dict[str, Any]:
    settings_cfg = config.get("settings", {}) or {}
    catalog = settings_cfg.get("catalog", {}) if isinstance(settings_cfg, dict) else {}
    worlds_map = settings_worlds_map(config)

    options: list[dict[str, str]] = [
        {"value": "all_settings", "label": "All Settings"},
    ]

    for core in core_settings(config):
        label = core.replace("_", " ").title()
        if isinstance(catalog, dict):
            details = catalog.get(core) or catalog.get(core.replace("_", " "))
            if isinstance(details, dict) and str(details.get("label", "")).strip():
                label = str(details.get("label")).strip()
        options.append({"value": core, "label": label})

    worlds_by_core = {
        core: [{"value": world, "label": world.replace("_", " ").title()} for world in worlds]
        for core, worlds in worlds_map.items()
        if worlds
    }

    return {
        "core_options": options,
        "worlds_by_core": worlds_by_core,
    }


def default_settings(config: dict[str, Any]) -> list[str]:
    values: list[str] = []
    settings_cfg = config.get("settings", {}) or {}

    raw_defaults = settings_cfg.get("defaults") if isinstance(settings_cfg, dict) else None
    for token in normalize_settings_values(raw_defaults):
        if token not in values:
            values.append(token)

    # Backward-compatible fallback for projects without explicit settings defaults.
    if not values:
        for token in normalize_settings_values((config.get("setting", {}) or {}).get("id")):
            if token not in values:
                values.append(token)
        for token in normalize_settings_values((config.get("setting", {}) or {}).get("name")):
            if token not in values:
                values.append(token)

    if not values:
        catalog = settings_catalog(config)
        if catalog:
            values.append(catalog[0])

    return values


def expand_related_settings(base_settings: list[str], config: dict[str, Any]) -> list[str]:
    values = list(base_settings)
    settings_cfg = config.get("settings", {}) or {}
    catalog = settings_cfg.get("catalog", {}) if isinstance(settings_cfg, dict) else {}
    if not isinstance(catalog, dict):
        return values

    world_to_core: dict[str, str] = {}
    for core_key, details in catalog.items():
        core = normalize_setting_token(core_key)
        for world in normalize_settings_values((details or {}).get("worlds") if isinstance(details, dict) else None):
            if world and core:
                world_to_core[world] = core

    for token in list(values):
        core = world_to_core.get(token)
        if core and core not in values:
            values.insert(0, core)

    return values


def resolve_item_settings(
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    config: dict[str, Any],
) -> list[str]:
    values: list[str] = []

    def add_many(raw: Any) -> None:
        for token in normalize_settings_values(raw):
            if token not in values:
                values.append(token)

    payload = payload or {}
    metadata = metadata or {}

    add_many(payload.get("settings"))
    add_many(payload.get("setting"))
    add_many(metadata.get("settings"))
    add_many(metadata.get("setting"))

    # Ensure every item is tied to at least one setting tag.
    if not values:
        add_many(default_settings(config))

    values = expand_related_settings(values, config)

    return values


def attach_settings_metadata(
    result: dict[str, Any],
    payload: dict[str, Any] | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    settings = resolve_item_settings(payload, metadata, config)
    preferred_primary = normalize_setting_token(metadata.get("setting"))
    settings_cfg = config.get("settings", {}) or {}
    catalog = settings_cfg.get("catalog", {}) if isinstance(settings_cfg, dict) else {}
    world_tags: set[str] = set()
    if isinstance(catalog, dict):
        for details in catalog.values():
            if isinstance(details, dict):
                world_tags.update(normalize_settings_values(details.get("worlds")))

    if settings:
        metadata["settings"] = settings
        primary: str | None = None

        if preferred_primary and preferred_primary in settings:
            if preferred_primary in world_tags:
                primary = preferred_primary
            else:
                # Prefer a specific world tag over a broad genre tag when available.
                primary = next((tag for tag in settings if tag in world_tags), preferred_primary)
        else:
            primary = next((tag for tag in settings if tag in world_tags), settings[0])

        metadata["setting"] = primary or settings[0]

    result["metadata"] = metadata
    return result
