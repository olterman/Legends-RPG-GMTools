from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.audit import AuditService
from app.core.contracts.records import validate_record
from app.core.graph import GraphService
from app.core.storage import FileRecordStore


class ContentService:
    def __init__(self, *, data_root: Path, db_path: Path) -> None:
        self.store = FileRecordStore(data_root)
        self.audit = AuditService(db_path)
        self.graph = GraphService(db_path)

    def create_record(
        self,
        record: dict[str, Any],
        *,
        actor_user_id: str = "",
        request_kind: str = "manual",
        provider_id: str = "",
        prompt_text: str = "",
    ) -> dict[str, Any]:
        created = self.store.create(record)
        self._sync_record_relationships(created)
        self._log_event(
            action_type="create_record",
            record=created,
            actor_user_id=actor_user_id,
            request_kind=request_kind,
            provider_id=provider_id,
            prompt_text=prompt_text,
        )
        return created

    def update_record(
        self,
        record_id: str,
        record: dict[str, Any],
        *,
        actor_user_id: str = "",
        request_kind: str = "manual",
        provider_id: str = "",
        prompt_text: str = "",
    ) -> dict[str, Any]:
        updated = self.store.update(record_id, record)
        self._sync_record_relationships(updated)
        self._log_event(
            action_type="update_record",
            record=updated,
            actor_user_id=actor_user_id,
            request_kind=request_kind,
            provider_id=provider_id,
            prompt_text=prompt_text,
        )
        return updated

    def delete_record(self, record_id: str, *, actor_user_id: str = "", request_kind: str = "manual") -> dict[str, Any]:
        record = self.store.get(record_id)
        result = self.store.delete(record_id)
        self._log_event(
            action_type="delete_record",
            record=record,
            actor_user_id=actor_user_id,
            request_kind=request_kind,
        )
        return result

    def restore_record(self, record_id: str, *, actor_user_id: str = "", request_kind: str = "manual") -> dict[str, Any]:
        result = self.store.restore(record_id)
        record = self.store.get(record_id)
        self._sync_record_relationships(record)
        self._log_event(
            action_type="restore_record",
            record=record,
            actor_user_id=actor_user_id,
            request_kind=request_kind,
        )
        return result

    def get_record(self, record_id: str) -> dict[str, Any]:
        return self.store.get(record_id)

    def list_records(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.store.list(filters=filters)

    def search_records(self, query: str = "", filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.store.search(query=query, filters=filters)

    def list_records_for_tag(self, *, tag: str, entity_type: str = "") -> list[dict[str, Any]]:
        entity_tags = self.graph.list_entities_for_tag(tag=tag, entity_type=entity_type)
        items: list[dict[str, Any]] = []
        for relation in entity_tags:
            try:
                record = self.store.get(relation.entity_id)
            except FileNotFoundError:
                continue
            items.append(record)
        return items

    def list_backlinks(self, *, record_id: str, target_type: str = "record") -> list[dict[str, Any]]:
        links = self.graph.list_backlinks_for(target_type=target_type, target_id=record_id)
        items: list[dict[str, Any]] = []
        for link in links:
            try:
                source = self.store.get(link.source_id)
            except FileNotFoundError:
                continue
            items.append({"link": link, "record": source})
        return items

    def _sync_record_relationships(self, record: dict[str, Any]) -> None:
        validated = validate_record(record)
        entity_type = "record"
        entity_id = validated["id"]

        self.graph.clear_tags_for_entity(entity_type=entity_type, entity_id=entity_id)
        for tag in validated["metadata"].get("tags") or []:
            self.graph.tag_entity(entity_type=entity_type, entity_id=entity_id, tag=str(tag))

        self.graph.clear_links_from(source_type=entity_type, source_id=entity_id)
        for link in validated.get("links") or []:
            if not isinstance(link, dict):
                continue
            link_type = str(link.get("link_type") or "").strip()
            target_type = str(link.get("target_type") or "").strip() or "record"
            target_id = str(link.get("target_id") or "").strip()
            if not link_type or not target_id:
                continue
            self.graph.link_entities(
                source_type=entity_type,
                source_id=entity_id,
                link_type=link_type,
                target_type=target_type,
                target_id=target_id,
            )

    def _log_event(
        self,
        *,
        action_type: str,
        record: dict[str, Any],
        actor_user_id: str,
        request_kind: str,
        provider_id: str = "",
        prompt_text: str = "",
    ) -> None:
        self.audit.log_event(
            actor_user_id=actor_user_id,
            action_type=action_type,
            target_type="record",
            target_id=str(record["id"]),
            system_id=str((record.get("context") or {}).get("system_id") or "none"),
            setting_id=str((record.get("context") or {}).get("setting_id") or ""),
            campaign_id=str((record.get("context") or {}).get("campaign_id") or ""),
            request_kind=request_kind,
            provider_id=provider_id,
            prompt_text=prompt_text,
            payload={"record_type": record.get("type"), "title": record.get("title")},
            result={"record_id": record.get("id")},
        )
