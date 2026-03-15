from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


TOKEN_ALIASES = {
    "lands_of_legends": "lands_of_legend",
    "land_of_legends": "lands_of_legend",
    "land_of_legend": "lands_of_legend",
}

TAG_ALIASES = {
    "lands_of_legends": "lands_of_legend",
    "land_of_legends": "lands_of_legend",
    "land_of_legend": "lands_of_legend",
    "highland_urukculture": "culture",
    "alfirin": "alfir",
    "alfir_sombra": "duathrim",
    "alfir_sylvani": "galadhrim",
    "alfir_sky_children": "kalaquendi",
    "sky_children": "kalaquendi",
    "alfir_wave_riders": "falthrim",
    "faltrim": "falthrim",
    "race_alfir": "alfir",
    "cyfer": "cypher",
    "cyphers_artifacts": "",
    "human_highlanders": "highland_fenmir",
    "the_other_human_tribes": "",
    "the_dead": "gurthim",
    "dangers_undead": "gurthim",
    "dangers_monsters": "monster",
    "liilim": "lilim",
    "Lands of Legends": "Lands of Legend",
    "Land of Legends": "Lands of Legend",
}

DISPLAY_ALIASES = {
    "Lands of Legends": "Lands of Legend",
    "Land of Legends": "Lands of Legend",
    "liilim": "lilim",
}

TARGET_FILES = (
    "config/02_settings.yaml",
    "config/worlds/lands_of_legends/00_world.yaml",
    "lore/index.json",
    "lore/prompts_index.json",
    "images/_index.json",
)

TARGET_DIRS = (
    "lore/entries",
    "storage",
)


def _normalize_scalar(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped in TOKEN_ALIASES:
        replacement = TOKEN_ALIASES[stripped]
        return replacement if value == stripped else value.replace(stripped, replacement)
    if stripped in DISPLAY_ALIASES:
        replacement = DISPLAY_ALIASES[stripped]
        return replacement if value == stripped else value.replace(stripped, replacement)
    out = value
    for wrong, right in DISPLAY_ALIASES.items():
        if wrong in out:
            out = out.replace(wrong, right)
    return out


def _normalize_tags(raw: Any) -> Any:
    if not isinstance(raw, list):
        return raw
    values: list[str] = []
    for item in raw:
        tag = str(item or "").strip()
        if not tag:
            continue
        normalized = TAG_ALIASES.get(tag, tag)
        if not normalized:
            continue
        if normalized not in values:
            values.append(normalized)
    return values


def _normalize_data(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key == "tags":
                normalized[key] = _normalize_tags(item)
            else:
                normalized[key] = _normalize_data(item)
        return normalized
    if isinstance(value, list):
        return [_normalize_data(item) for item in value]
    return _normalize_scalar(value)


def _load_structured(path: Path) -> Any:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _dump_structured(path: Path, data: Any) -> str:
    if path.suffix.lower() == ".json":
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def iter_target_paths(project_root: Path) -> list[Path]:
    paths: list[Path] = []
    for rel in TARGET_FILES:
        path = project_root / rel
        if path.exists():
            paths.append(path)
    for rel in TARGET_DIRS:
        root = project_root / rel
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
                continue
            if path.is_file():
                paths.append(path)
    return paths


def harmonize_project(project_root: Path, *, write: bool = False) -> dict[str, Any]:
    changed: list[str] = []
    for path in iter_target_paths(project_root):
        try:
            original = _load_structured(path)
        except Exception:
            continue
        normalized = _normalize_data(original)
        if normalized == original:
            continue
        changed.append(str(path.relative_to(project_root)))
        if write:
            path.write_text(_dump_structured(path, normalized), encoding="utf-8")
    return {"changed_files": changed, "count": len(changed), "write": write}


def harmonize_paths(project_root: Path, rel_paths: list[str], *, write: bool = False) -> dict[str, Any]:
    changed: list[str] = []
    for rel in rel_paths:
        path = (project_root / rel).resolve()
        try:
            path.relative_to(project_root.resolve())
        except ValueError:
            continue
        if not path.exists() or not path.is_file() or path.suffix.lower() not in {".json", ".yaml", ".yml"}:
            continue
        try:
            original = _load_structured(path)
        except Exception:
            continue
        normalized = _normalize_data(original)
        if normalized == original:
            continue
        changed.append(str(path.relative_to(project_root)))
        if write:
            path.write_text(_dump_structured(path, normalized), encoding="utf-8")
    return {"changed_files": changed, "count": len(changed), "write": write}


def main() -> int:
    parser = argparse.ArgumentParser(description="Harmonize Lands of Legend taxonomy aliases in structured project data.")
    parser.add_argument("--project-root", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument("--path", action="append", default=[], help="Project-relative structured file path to harmonize. Repeatable.")
    parser.add_argument("--write", action="store_true", help="Apply changes in place. Default is dry-run.")
    args = parser.parse_args()

    if args.path:
        result = harmonize_paths(args.project_root, args.path, write=args.write)
    else:
        result = harmonize_project(args.project_root, write=args.write)
    mode = "Applied" if args.write else "Would update"
    print(f"{mode} {result['count']} file(s).")
    for rel in result["changed_files"]:
        print(rel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
