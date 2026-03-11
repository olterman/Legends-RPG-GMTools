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


def load_config_dir(config_dir: Path) -> dict[str, Any]:
    merged: dict[str, Any] = {}

    for path in sorted(config_dir.glob("*.yaml")):
        data = load_yaml_file(path)
        for key, value in data.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key].update(value)
            elif key in merged:
                raise ValueError(f"Duplicate top-level config key '{key}' in {path}")
            else:
                merged[key] = value

    return merged 