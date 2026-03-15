from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.contracts.records import summarize_record, utc_now_iso, validate_record


class FileRecordStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.records_dir = self.root / "records"
        self.indexes_dir = self.root / "indexes"
        self.trash_dir = self.root / "trash"
        self.summary_path = self.indexes_dir / "records_summary.json"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.indexes_dir.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)

    def _record_path(self, record_id: str) -> Path:
        return self.records_dir / f"{record_id}.json"

    def _trash_path(self, record_id: str) -> Path:
        return self.trash_dir / f"{record_id}.json"

    def _load_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_summaries(self) -> list[dict[str, Any]]:
        if not self.summary_path.exists():
            return []
        data = self._load_json(self.summary_path)
        items = data.get("items", []) if isinstance(data, dict) else []
        return [item for item in items if isinstance(item, dict)]

    def _write_summaries(self, items: list[dict[str, Any]]) -> None:
        payload = {"count": len(items), "items": items}
        self._write_json(self.summary_path, payload)

    def _upsert_summary(self, summary: dict[str, Any]) -> None:
        items = self._load_summaries()
        next_items = [item for item in items if str(item.get("id") or "") != summary["id"]]
        next_items.append(summary)
        next_items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        self._write_summaries(next_items)

    def _remove_summary(self, record_id: str) -> None:
        items = self._load_summaries()
        next_items = [item for item in items if str(item.get("id") or "") != record_id]
        self._write_summaries(next_items)

    def create(self, record: dict[str, Any]) -> dict[str, Any]:
        validated = validate_record(record)
        path = self._record_path(validated["id"])
        trash_path = self._trash_path(validated["id"])
        if path.exists() or trash_path.exists():
            raise FileExistsError(f"record already exists: {validated['id']}")
        self._write_json(path, validated)
        self._upsert_summary(summarize_record(validated))
        return validated

    def get(self, record_id: str) -> dict[str, Any]:
        path = self._record_path(record_id)
        if not path.exists():
            raise FileNotFoundError(f"record not found: {record_id}")
        return validate_record(self._load_json(path))

    def update(self, record_id: str, record: dict[str, Any]) -> dict[str, Any]:
        current = self.get(record_id)
        merged = dict(record)
        merged["id"] = record_id
        if "audit" not in merged or not isinstance(merged["audit"], dict):
            merged["audit"] = dict(current.get("audit") or {})
        merged["audit"] = dict(merged["audit"])
        merged["audit"]["created_at"] = current["audit"]["created_at"]
        merged["audit"]["created_by"] = current["audit"]["created_by"]
        merged["audit"]["updated_at"] = utc_now_iso()
        if not str(merged["audit"].get("updated_by") or "").strip():
            merged["audit"]["updated_by"] = current["audit"]["updated_by"]
        validated = validate_record(merged)
        self._write_json(self._record_path(record_id), validated)
        self._upsert_summary(summarize_record(validated))
        return validated

    def delete(self, record_id: str) -> dict[str, Any]:
        record = self.get(record_id)
        trashed = dict(record)
        trashed["metadata"] = dict(record["metadata"])
        trashed["metadata"]["status"] = "trashed"
        trashed["audit"] = dict(record["audit"])
        trashed["audit"]["updated_at"] = utc_now_iso()
        source = self._record_path(record_id)
        target = self._trash_path(record_id)
        source.rename(target)
        self._write_json(target, validate_record(trashed))
        self._remove_summary(record_id)
        return {"id": record_id, "status": "trashed"}

    def restore(self, record_id: str) -> dict[str, Any]:
        source = self._trash_path(record_id)
        if not source.exists():
            raise FileNotFoundError(f"trashed record not found: {record_id}")
        record = validate_record(self._load_json(source))
        record["metadata"] = dict(record["metadata"])
        record["metadata"]["status"] = "active"
        record["audit"] = dict(record["audit"])
        record["audit"]["updated_at"] = utc_now_iso()
        target = self._record_path(record_id)
        source.rename(target)
        self._write_json(target, validate_record(record))
        self._upsert_summary(summarize_record(record))
        return {"id": record_id, "status": "active"}

    def expunge(self, record_id: str) -> dict[str, Any]:
        target = self._trash_path(record_id)
        if not target.exists():
            raise FileNotFoundError(f"trashed record not found: {record_id}")
        target.unlink()
        return {"id": record_id, "status": "expunged"}

    def list(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        items = self._load_summaries()
        return self._apply_filters(items, filters or {})

    def search(self, query: str = "", filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        query_lc = str(query or "").strip().lower()
        items = self.list(filters=filters)
        if not query_lc:
            return items
        results: list[dict[str, Any]] = []
        for item in items:
            haystack = " ".join([
                str(item.get("title") or ""),
                str(item.get("type") or ""),
                str(item.get("summary") or ""),
                " ".join(str(x) for x in (item.get("tags") or [])),
                str(item.get("system_id") or ""),
                str(item.get("addon_id") or ""),
                str(item.get("setting_id") or ""),
                str(item.get("campaign_id") or ""),
            ]).lower()
            if query_lc in haystack:
                results.append(item)
        return results

    def summarize(self, record: dict[str, Any]) -> dict[str, Any]:
        return summarize_record(record)

    def _apply_filters(self, items: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
        if not filters:
            return items
        results: list[dict[str, Any]] = []
        for item in items:
            if filters.get("type") and str(item.get("type") or "") != str(filters["type"]):
                continue
            if filters.get("system_id") and str(item.get("system_id") or "") != str(filters["system_id"]):
                continue
            if filters.get("addon_id") and str(item.get("addon_id") or "") != str(filters["addon_id"]):
                continue
            if filters.get("setting_id") and str(item.get("setting_id") or "") != str(filters["setting_id"]):
                continue
            if filters.get("campaign_id") and str(item.get("campaign_id") or "") != str(filters["campaign_id"]):
                continue
            if filters.get("status") and str(item.get("status") or "") != str(filters["status"]):
                continue
            if filters.get("tag"):
                tag = str(filters["tag"])
                if tag not in [str(value) for value in (item.get("tags") or [])]:
                    continue
            results.append(item)
        return results
