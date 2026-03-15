from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.contracts.context import NONE_SYSTEM_ID, normalize_token
from app.core.contracts.ids import new_record_id
from app.core.database.bootstrap import ensure_database


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return {}


@dataclass
class AuditEvent:
    id: str
    actor_user_id: str
    action_type: str
    target_type: str
    target_id: str
    system_id: str
    setting_id: str
    campaign_id: str
    request_kind: str
    provider_id: str
    prompt_text: str
    payload: dict[str, Any]
    result: dict[str, Any]
    created_at: str


class AuditService:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        ensure_database(self.db_path)

    def log_event(
        self,
        *,
        action_type: str,
        target_type: str,
        target_id: str,
        actor_user_id: str = "",
        system_id: str = NONE_SYSTEM_ID,
        setting_id: str = "",
        campaign_id: str = "",
        request_kind: str = "",
        provider_id: str = "",
        prompt_text: str = "",
        payload: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
    ) -> AuditEvent:
        clean_action = normalize_token(action_type)
        clean_target_type = normalize_token(target_type)
        clean_target_id = str(target_id or "").strip()
        if not clean_action:
            raise ValueError("action_type is required")
        if not clean_target_type:
            raise ValueError("target_type is required")
        if not clean_target_id:
            raise ValueError("target_id is required")

        event_id = new_record_id().replace("rec_", "evt_", 1)
        actor = str(actor_user_id or "").strip()
        clean_system = normalize_token(system_id) or NONE_SYSTEM_ID
        clean_setting = normalize_token(setting_id)
        clean_campaign = normalize_token(campaign_id)
        clean_request_kind = normalize_token(request_kind)
        clean_provider_id = normalize_token(provider_id)
        prompt = str(prompt_text or "").strip()
        payload_obj = dict(payload or {})
        result_obj = dict(result or {})

        conn = _connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO audit_events(
                    id, actor_user_id, action_type, target_type, target_id,
                    system_id, setting_id, campaign_id, request_kind,
                    provider_id, prompt_text, payload_json, result_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    actor or None,
                    clean_action,
                    clean_target_type,
                    clean_target_id,
                    clean_system,
                    clean_setting,
                    clean_campaign,
                    clean_request_kind,
                    clean_provider_id,
                    prompt,
                    _json_dumps(payload_obj),
                    _json_dumps(result_obj),
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT id, actor_user_id, action_type, target_type, target_id,
                       system_id, setting_id, campaign_id, request_kind,
                       provider_id, prompt_text, payload_json, result_json, created_at
                FROM audit_events
                WHERE id = ?
                """,
                (event_id,),
            ).fetchone()
            return self._row_to_event(row)
        finally:
            conn.close()

    def list_events(
        self,
        *,
        actor_user_id: str = "",
        action_type: str = "",
        target_type: str = "",
        target_id: str = "",
        system_id: str = "",
        setting_id: str = "",
        campaign_id: str = "",
        provider_id: str = "",
        limit: int = 100,
    ) -> list[AuditEvent]:
        conditions: list[str] = []
        params: list[Any] = []

        def add_equal(column: str, raw_value: str, *, normalize: bool = False) -> None:
            text = str(raw_value or "").strip()
            if not text:
                return
            if normalize:
                text = normalize_token(text)
            conditions.append(f"{column} = ?")
            params.append(text)

        add_equal("actor_user_id", actor_user_id)
        add_equal("action_type", action_type, normalize=True)
        add_equal("target_type", target_type, normalize=True)
        add_equal("target_id", target_id)
        add_equal("system_id", system_id, normalize=True)
        add_equal("setting_id", setting_id, normalize=True)
        add_equal("campaign_id", campaign_id, normalize=True)
        add_equal("provider_id", provider_id, normalize=True)

        sql = """
            SELECT id, actor_user_id, action_type, target_type, target_id,
                   system_id, setting_id, campaign_id, request_kind,
                   provider_id, prompt_text, payload_json, result_json, created_at
            FROM audit_events
        """
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit or 1)))

        conn = _connect(self.db_path)
        try:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_event(row) for row in rows]
        finally:
            conn.close()

    def get_event(self, event_id: str) -> AuditEvent | None:
        clean_id = str(event_id or "").strip()
        if not clean_id:
            return None
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT id, actor_user_id, action_type, target_type, target_id,
                       system_id, setting_id, campaign_id, request_kind,
                       provider_id, prompt_text, payload_json, result_json, created_at
                FROM audit_events
                WHERE id = ?
                """,
                (clean_id,),
            ).fetchone()
            return self._row_to_event(row) if row is not None else None
        finally:
            conn.close()

    def _row_to_event(self, row: sqlite3.Row | None) -> AuditEvent:
        if row is None:
            raise ValueError("audit row is required")
        return AuditEvent(
            id=str(row["id"]),
            actor_user_id=str(row["actor_user_id"] or ""),
            action_type=str(row["action_type"]),
            target_type=str(row["target_type"]),
            target_id=str(row["target_id"]),
            system_id=str(row["system_id"] or NONE_SYSTEM_ID),
            setting_id=str(row["setting_id"] or ""),
            campaign_id=str(row["campaign_id"] or ""),
            request_kind=str(row["request_kind"] or ""),
            provider_id=str(row["provider_id"] or ""),
            prompt_text=str(row["prompt_text"] or ""),
            payload=_json_loads(str(row["payload_json"] or "{}")),
            result=_json_loads(str(row["result_json"] or "{}")),
            created_at=str(row["created_at"]),
        )
