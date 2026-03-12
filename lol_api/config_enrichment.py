from __future__ import annotations

from pathlib import Path
from typing import Any

import json
import yaml


DEFAULT_EXCLUDED_RACE_KEYS = {
    "daelgast",
    "alfirin_tribes",
    "human_tribes",
    "uruk_tribes",
    "small_folk",
}


def load_candidates(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"summary": {}, "races": [], "areas": []}
    return json.loads(path.read_text(encoding="utf-8"))


def curated_candidates(data: dict[str, Any]) -> dict[str, Any]:
    races = data.get("races", []) or []
    envs = data.get("areas", []) or data.get("environments", []) or []

    curated_races = [
        item for item in races
        if str(item.get("key", "")).strip() not in DEFAULT_EXCLUDED_RACE_KEYS
    ]
    # Keep place additions explicit; avoid broad basin-level Fenmir catch-all.
    curated_envs = [
        item for item in envs
        if str(item.get("key", "")).strip() != "fenmir"
    ]

    race_defaults = [str(item.get("key", "")).strip() for item in curated_races if item.get("key")]
    env_defaults = [str(item.get("key", "")).strip() for item in curated_envs if item.get("key")]

    return {
        "summary": data.get("summary", {}),
        "races": curated_races,
        "areas": curated_envs,
        "defaults": {
            "race_keys": race_defaults,
            "area_keys": env_defaults,
            "environment_keys": env_defaults,
        },
        "excluded_race_keys": sorted(DEFAULT_EXCLUDED_RACE_KEYS),
    }


def load_generated_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return data


def select_yaml_sections(
    generated_doc: dict[str, Any],
    race_keys: list[str],
    area_keys: list[str],
) -> dict[str, Any]:
    race_keys_set = {k.strip() for k in race_keys if k and str(k).strip()}
    env_keys_set = {k.strip() for k in area_keys if k and str(k).strip()}

    races = {
        k: v
        for k, v in (generated_doc.get("races", {}) or {}).items()
        if k in race_keys_set
    }
    areas = {
        k: v
        for k, v in ((generated_doc.get("areas", {}) or generated_doc.get("environments", {})) or {}).items()
        if k in env_keys_set
    }
    settlements = {
        k: v
        for k, v in (generated_doc.get("settlements", {}) or {}).items()
        if k in env_keys_set
    }
    encounters = {
        k: v
        for k, v in (generated_doc.get("encounters", {}) or {}).items()
        if k in env_keys_set
    }

    return {
        "races": races,
        "areas": areas,
        "environments": areas,
        "settlements": settlements,
        "encounters": encounters,
    }


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
