from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lol_api.config_loader import load_config_dir
from lol_api.settings import attach_settings_metadata


def compute_defaults(config: dict[str, Any]) -> tuple[list[str], str | None]:
    seed = attach_settings_metadata({"metadata": {}}, {}, config).get("metadata", {})
    settings = seed.get("settings", []) if isinstance(seed, dict) else []
    setting = seed.get("setting") if isinstance(seed, dict) else None
    return list(settings or []), (str(setting) if setting else None)


def with_lore_settings(item: dict[str, Any], settings: list[str], setting: str | None) -> dict[str, Any]:
    out = dict(item)
    out["settings"] = settings
    if setting:
        out["setting"] = setting
    return out


def migrate(lore_dir: Path, config: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    updated = 0
    skipped = 0
    errors = 0
    details: list[str] = []

    defaults, primary = compute_defaults(config)

    entries_dir = lore_dir / "entries"
    for path in sorted(entries_dir.glob("*.json")):
        rel = str(path.relative_to(lore_dir)).replace("\\", "/")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                skipped += 1
                details.append(f"skip {rel}: root is not an object")
                continue
            before = json.dumps(data, ensure_ascii=False, sort_keys=True)
            after_obj = with_lore_settings(data, defaults, primary)
            after = json.dumps(after_obj, ensure_ascii=False, sort_keys=True)
            if before == after:
                skipped += 1
                continue
            if dry_run:
                updated += 1
                details.append(f"DRY-RUN update {rel}")
                continue
            path.write_text(json.dumps(after_obj, indent=2, ensure_ascii=False), encoding="utf-8")
            updated += 1
            details.append(f"updated {rel}")
        except Exception as exc:
            errors += 1
            details.append(f"error {rel}: {exc}")

    index_path = lore_dir / "index.json"
    if index_path.exists():
        rel = "index.json"
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            if not isinstance(index, dict):
                skipped += 1
                details.append(f"skip {rel}: root is not an object")
            else:
                items = index.get("items", [])
                if not isinstance(items, list):
                    skipped += 1
                    details.append(f"skip {rel}: items is not a list")
                else:
                    before = json.dumps(index, ensure_ascii=False, sort_keys=True)
                    index["items"] = [
                        with_lore_settings(item, defaults, primary)
                        for item in items
                        if isinstance(item, dict)
                    ]
                    index["count"] = len(index["items"])
                    after = json.dumps(index, ensure_ascii=False, sort_keys=True)
                    if before == after:
                        skipped += 1
                    elif dry_run:
                        updated += 1
                        details.append(f"DRY-RUN update {rel}")
                    else:
                        index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
                        updated += 1
                        details.append(f"updated {rel}")
        except Exception as exc:
            errors += 1
            details.append(f"error {rel}: {exc}")

    prompts_path = lore_dir / "prompts_index.json"
    if prompts_path.exists():
        rel = "prompts_index.json"
        try:
            prompts_doc = json.loads(prompts_path.read_text(encoding="utf-8"))
            if not isinstance(prompts_doc, dict):
                skipped += 1
                details.append(f"skip {rel}: root is not an object")
            else:
                items = prompts_doc.get("items", [])
                if not isinstance(items, list):
                    skipped += 1
                    details.append(f"skip {rel}: items is not a list")
                else:
                    before = json.dumps(prompts_doc, ensure_ascii=False, sort_keys=True)
                    prompts_doc["items"] = [
                        with_lore_settings(item, defaults, primary)
                        for item in items
                        if isinstance(item, dict)
                    ]
                    prompts_doc["count"] = len(prompts_doc["items"])
                    after = json.dumps(prompts_doc, ensure_ascii=False, sort_keys=True)
                    if before == after:
                        skipped += 1
                    elif dry_run:
                        updated += 1
                        details.append(f"DRY-RUN update {rel}")
                    else:
                        prompts_path.write_text(json.dumps(prompts_doc, indent=2, ensure_ascii=False), encoding="utf-8")
                        updated += 1
                        details.append(f"updated {rel}")
        except Exception as exc:
            errors += 1
            details.append(f"error {rel}: {exc}")

    return {"updated": updated, "skipped": skipped, "errors": errors, "details": details}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill lore entries/index with setting tags.")
    parser.add_argument("--lore-dir", default="lore", help="Lore directory path")
    parser.add_argument("--config-dir", default="config", help="Config directory path")
    parser.add_argument("--dry-run", action="store_true", help="Show planned updates without writing files")
    args = parser.parse_args()

    lore_dir = Path(args.lore_dir)
    config_dir = Path(args.config_dir)
    if not lore_dir.exists():
        raise FileNotFoundError(f"Lore directory not found: {lore_dir}")
    if not config_dir.exists():
        raise FileNotFoundError(f"Config directory not found: {config_dir}")

    config = load_config_dir(config_dir)
    result = migrate(lore_dir, config, dry_run=args.dry_run)
    for line in result["details"]:
        print(line)
    print(
        f"Summary: updated={result['updated']} skipped={result['skipped']} errors={result['errors']}"
    )


if __name__ == "__main__":
    main()
