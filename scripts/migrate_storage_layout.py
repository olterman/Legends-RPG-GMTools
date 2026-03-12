from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from lol_api.storage import safe_slug, storage_subdir_for_result


def infer_subdir_from_filename(path: Path) -> str:
    stem = path.stem
    prefix = stem.split("_", 1)[0] if "_" in stem else stem
    return safe_slug(prefix or "item")


def migrate(storage_dir: Path, dry_run: bool = False) -> dict:
    moved = 0
    skipped = 0
    errors = 0
    details: list[str] = []

    for path in sorted(storage_dir.glob("*.json")):
        if path.name.startswith("."):
            skipped += 1
            continue

        try:
            subdir: str
            record = json.loads(path.read_text(encoding="utf-8"))
            result = record.get("result", {}) if isinstance(record, dict) else {}
            if isinstance(result, dict) and result:
                subdir = storage_subdir_for_result(result)
            else:
                subdir = infer_subdir_from_filename(path)

            target_dir = storage_dir / subdir
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / path.name

            # Ensure unique destination.
            if target_path.exists():
                base = target_path.stem
                suffix = target_path.suffix
                idx = 1
                while True:
                    candidate = target_dir / f"{base}_{idx}{suffix}"
                    if not candidate.exists():
                        target_path = candidate
                        break
                    idx += 1

            rel = str(target_path.relative_to(storage_dir)).replace("\\", "/")
            if isinstance(record, dict):
                record["filename"] = rel

            if dry_run:
                details.append(f"DRY-RUN move {path.name} -> {rel}")
                moved += 1
                continue

            # Write updated record first to destination, then remove source.
            target_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            path.unlink()
            details.append(f"moved {path.name} -> {rel}")
            moved += 1
        except Exception as exc:
            errors += 1
            details.append(f"error {path.name}: {exc}")

    return {
        "moved": moved,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate storage/*.json to storage/<type>/")
    parser.add_argument("--storage-dir", default="storage", help="Storage directory path")
    parser.add_argument("--dry-run", action="store_true", help="Show planned moves without changing files")
    args = parser.parse_args()

    storage_dir = Path(args.storage_dir)
    if not storage_dir.exists():
        raise FileNotFoundError(f"Storage directory not found: {storage_dir}")

    result = migrate(storage_dir, dry_run=args.dry_run)
    for line in result["details"]:
        print(line)
    print(
        f"Summary: moved={result['moved']} skipped={result['skipped']} errors={result['errors']}"
    )


if __name__ == "__main__":
    main()
