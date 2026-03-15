from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _promote_foundry_helper_record(path: Path, storage_root: Path) -> tuple[bool, str | None]:
    data = _load_json(path)
    if not isinstance(data, dict):
        return False, None
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    item_type = str(result.get("type") or "").strip().lower()
    source = str(metadata.get("source") or "").strip().lower()
    origin = str(metadata.get("origin") or "").strip().lower()

    if item_type not in {"cypher", "attack"}:
        return False, None
    if source not in {"foundryvtt", "foundry_vtt"}:
        return False, None
    if origin != "foundry_import":
        return False, None
    if not metadata.get("owner_character_filename"):
        return False, None

    rel = path.relative_to(storage_root).as_posix()
    target = storage_root / item_type / path.name

    metadata = dict(metadata)
    metadata["source"] = "storage"
    metadata["origin"] = "foundry_item_extracted"
    result = dict(result)
    result["metadata"] = metadata
    data = dict(data)
    data["result"] = result
    data["filename"] = target.relative_to(storage_root).as_posix()

    _write_json(target, data)
    if target.resolve() != path.resolve():
        path.unlink()
    return True, rel


def cleanup_foundry_legacy_records(storage_root: Path, *, write: bool = False) -> dict[str, Any]:
    changed: list[str] = []
    for path in sorted((storage_root / "foundryvtt").rglob("*.json")) if (storage_root / "foundryvtt").exists() else []:
        changed_flag, rel = _promote_foundry_helper_record(path, storage_root) if write else (False, path.relative_to(storage_root).as_posix() if _would_promote(path) else None)
        if rel:
            changed.append(rel)
    return {"changed_files": changed, "count": len(changed), "write": write}


def _would_promote(path: Path) -> bool:
    data = _load_json(path)
    if not isinstance(data, dict):
        return False
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    return (
        str(result.get("type") or "").strip().lower() in {"cypher", "attack"}
        and str(metadata.get("source") or "").strip().lower() in {"foundryvtt", "foundry_vtt"}
        and str(metadata.get("origin") or "").strip().lower() == "foundry_import"
        and bool(metadata.get("owner_character_filename"))
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote legacy Foundry-extracted helper records into normal local storage.")
    parser.add_argument("--storage-root", type=Path, default=Path(__file__).resolve().parents[1] / "storage")
    parser.add_argument("--write", action="store_true", help="Apply changes in place. Default is dry-run.")
    args = parser.parse_args()

    result = cleanup_foundry_legacy_records(args.storage_root, write=args.write)
    mode = "Applied" if args.write else "Would update"
    print(f"{mode} {result['count']} file(s).")
    for rel in result["changed_files"]:
        print(rel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
