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


def migrate(
    storage_dir: Path,
    config: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    scanned = 0
    updated = 0
    skipped = 0
    errors = 0
    details: list[str] = []

    for path in sorted(storage_dir.rglob("*.json")):
        if ".locks" in path.parts or path.name.startswith("."):
            skipped += 1
            continue

        scanned += 1
        rel = str(path.relative_to(storage_dir)).replace("\\", "/")

        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                skipped += 1
                details.append(f"skip {rel}: root is not an object")
                continue

            result = record.get("result")
            if not isinstance(result, dict):
                skipped += 1
                details.append(f"skip {rel}: missing result object")
                continue

            payload = record.get("payload")
            payload_obj = payload if isinstance(payload, dict) else {}
            before = json.dumps(result, ensure_ascii=False, sort_keys=True)
            after_result = attach_settings_metadata(dict(result), payload_obj, config)
            after = json.dumps(after_result, ensure_ascii=False, sort_keys=True)

            if before == after:
                skipped += 1
                continue

            if dry_run:
                updated += 1
                details.append(f"DRY-RUN update {rel}")
                continue

            record["result"] = after_result
            path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            updated += 1
            details.append(f"updated {rel}")
        except Exception as exc:
            errors += 1
            details.append(f"error {rel}: {exc}")

    return {
        "scanned": scanned,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill storage metadata.settings from payload/result/config defaults."
    )
    parser.add_argument("--storage-dir", default="storage", help="Storage directory path")
    parser.add_argument("--config-dir", default="config", help="Config directory path")
    parser.add_argument("--dry-run", action="store_true", help="Show planned updates without writing files")
    args = parser.parse_args()

    storage_dir = Path(args.storage_dir)
    if not storage_dir.exists():
        raise FileNotFoundError(f"Storage directory not found: {storage_dir}")

    config_dir = Path(args.config_dir)
    if not config_dir.exists():
        raise FileNotFoundError(f"Config directory not found: {config_dir}")

    config = load_config_dir(config_dir)
    result = migrate(storage_dir, config, dry_run=args.dry_run)
    for line in result["details"]:
        print(line)
    print(
        f"Summary: scanned={result['scanned']} updated={result['updated']} "
        f"skipped={result['skipped']} errors={result['errors']}"
    )


if __name__ == "__main__":
    main()
