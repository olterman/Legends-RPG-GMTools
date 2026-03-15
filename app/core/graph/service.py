from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.contracts.context import normalize_token
from app.core.contracts.ids import new_record_id
from app.core.database.bootstrap import ensure_database


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_label(value: Any) -> str:
    return str(value or "").strip()


@dataclass
class TagRecord:
    id: str
    tag_key: str
    label: str
    created_at: str


@dataclass
class EntityTagRecord:
    entity_type: str
    entity_id: str
    tag_id: str
    created_at: str


@dataclass
class EntityLinkRecord:
    id: str
    source_type: str
    source_id: str
    link_type: str
    target_type: str
    target_id: str
    created_at: str


class GraphService:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        ensure_database(self.db_path)

    def upsert_tag(self, *, tag: str, label: str = "") -> TagRecord:
        tag_key = normalize_token(tag)
        if not tag_key:
            raise ValueError("tag is required")
        clean_label = _normalize_label(label) or tag_key.replace("_", " ").title()

        existing = self.get_tag(tag_key)
        if existing is not None:
            if existing.label != clean_label:
                conn = _connect(self.db_path)
                try:
                    conn.execute(
                        "UPDATE tags SET label = ? WHERE id = ?",
                        (clean_label, existing.id),
                    )
                    conn.commit()
                finally:
                    conn.close()
                return self.get_tag(tag_key)  # type: ignore[return-value]
            return existing

        tag_id = new_record_id().replace("rec_", "tag_", 1)
        conn = _connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO tags(id, tag_key, label) VALUES (?, ?, ?)",
                (tag_id, tag_key, clean_label),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_tag(tag_key)  # type: ignore[return-value]

    def get_tag(self, tag: str) -> TagRecord | None:
        tag_key = normalize_token(tag)
        if not tag_key:
            return None
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT id, tag_key, label, created_at FROM tags WHERE tag_key = ?",
                (tag_key,),
            ).fetchone()
            return self._row_to_tag(row) if row is not None else None
        finally:
            conn.close()

    def list_tags(self, *, query: str = "", limit: int = 100) -> list[TagRecord]:
        clean_query = str(query or "").strip().lower()
        conn = _connect(self.db_path)
        try:
            if clean_query:
                rows = conn.execute(
                    """
                    SELECT id, tag_key, label, created_at
                    FROM tags
                    WHERE lower(tag_key) LIKE ? OR lower(label) LIKE ?
                    ORDER BY label ASC
                    LIMIT ?
                    """,
                    (f"%{clean_query}%", f"%{clean_query}%", max(1, int(limit or 1))),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, tag_key, label, created_at
                    FROM tags
                    ORDER BY label ASC
                    LIMIT ?
                    """,
                    (max(1, int(limit or 1)),),
                ).fetchall()
            return [self._row_to_tag(row) for row in rows]
        finally:
            conn.close()

    def tag_entity(self, *, entity_type: str, entity_id: str, tag: str, label: str = "") -> EntityTagRecord:
        clean_entity_type = normalize_token(entity_type)
        clean_entity_id = str(entity_id or "").strip()
        if not clean_entity_type:
            raise ValueError("entity_type is required")
        if not clean_entity_id:
            raise ValueError("entity_id is required")
        tag_record = self.upsert_tag(tag=tag, label=label)

        conn = _connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO entity_tags(entity_type, entity_id, tag_id)
                VALUES (?, ?, ?)
                """,
                (clean_entity_type, clean_entity_id, tag_record.id),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT entity_type, entity_id, tag_id, created_at
                FROM entity_tags
                WHERE entity_type = ? AND entity_id = ? AND tag_id = ?
                """,
                (clean_entity_type, clean_entity_id, tag_record.id),
            ).fetchone()
            return self._row_to_entity_tag(row)
        finally:
            conn.close()

    def list_entities_for_tag(self, *, tag: str, entity_type: str = "", limit: int = 200) -> list[EntityTagRecord]:
        tag_record = self.get_tag(tag)
        if tag_record is None:
            return []
        clean_entity_type = normalize_token(entity_type)
        conn = _connect(self.db_path)
        try:
            if clean_entity_type:
                rows = conn.execute(
                    """
                    SELECT entity_type, entity_id, tag_id, created_at
                    FROM entity_tags
                    WHERE tag_id = ? AND entity_type = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (tag_record.id, clean_entity_type, max(1, int(limit or 1))),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT entity_type, entity_id, tag_id, created_at
                    FROM entity_tags
                    WHERE tag_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (tag_record.id, max(1, int(limit or 1))),
                ).fetchall()
            return [self._row_to_entity_tag(row) for row in rows]
        finally:
            conn.close()

    def list_tags_for_entity(self, *, entity_type: str, entity_id: str) -> list[TagRecord]:
        clean_entity_type = normalize_token(entity_type)
        clean_entity_id = str(entity_id or "").strip()
        if not clean_entity_type or not clean_entity_id:
            return []
        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT t.id, t.tag_key, t.label, t.created_at
                FROM tags t
                JOIN entity_tags et ON et.tag_id = t.id
                WHERE et.entity_type = ? AND et.entity_id = ?
                ORDER BY t.label ASC
                """,
                (clean_entity_type, clean_entity_id),
            ).fetchall()
            return [self._row_to_tag(row) for row in rows]
        finally:
            conn.close()

    def clear_tags_for_entity(self, *, entity_type: str, entity_id: str) -> int:
        clean_entity_type = normalize_token(entity_type)
        clean_entity_id = str(entity_id or "").strip()
        if not clean_entity_type or not clean_entity_id:
            return 0
        conn = _connect(self.db_path)
        try:
            cursor = conn.execute(
                "DELETE FROM entity_tags WHERE entity_type = ? AND entity_id = ?",
                (clean_entity_type, clean_entity_id),
            )
            conn.commit()
            return int(cursor.rowcount or 0)
        finally:
            conn.close()

    def link_entities(
        self,
        *,
        source_type: str,
        source_id: str,
        link_type: str,
        target_type: str,
        target_id: str,
    ) -> EntityLinkRecord:
        clean_source_type = normalize_token(source_type)
        clean_source_id = str(source_id or "").strip()
        clean_link_type = normalize_token(link_type)
        clean_target_type = normalize_token(target_type)
        clean_target_id = str(target_id or "").strip()
        if not clean_source_type:
            raise ValueError("source_type is required")
        if not clean_source_id:
            raise ValueError("source_id is required")
        if not clean_link_type:
            raise ValueError("link_type is required")
        if not clean_target_type:
            raise ValueError("target_type is required")
        if not clean_target_id:
            raise ValueError("target_id is required")

        link_id = new_record_id().replace("rec_", "lnk_", 1)
        conn = _connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO entity_links(id, source_type, source_id, link_type, target_type, target_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    link_id,
                    clean_source_type,
                    clean_source_id,
                    clean_link_type,
                    clean_target_type,
                    clean_target_id,
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT id, source_type, source_id, link_type, target_type, target_id, created_at
                FROM entity_links
                WHERE id = ?
                """,
                (link_id,),
            ).fetchone()
            return self._row_to_link(row)
        finally:
            conn.close()

    def list_links_from(
        self,
        *,
        source_type: str,
        source_id: str,
        link_type: str = "",
        limit: int = 200,
    ) -> list[EntityLinkRecord]:
        clean_source_type = normalize_token(source_type)
        clean_source_id = str(source_id or "").strip()
        clean_link_type = normalize_token(link_type)
        if not clean_source_type or not clean_source_id:
            return []
        conn = _connect(self.db_path)
        try:
            if clean_link_type:
                rows = conn.execute(
                    """
                    SELECT id, source_type, source_id, link_type, target_type, target_id, created_at
                    FROM entity_links
                    WHERE source_type = ? AND source_id = ? AND link_type = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (clean_source_type, clean_source_id, clean_link_type, max(1, int(limit or 1))),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, source_type, source_id, link_type, target_type, target_id, created_at
                    FROM entity_links
                    WHERE source_type = ? AND source_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (clean_source_type, clean_source_id, max(1, int(limit or 1))),
                ).fetchall()
            return [self._row_to_link(row) for row in rows]
        finally:
            conn.close()

    def list_backlinks_for(
        self,
        *,
        target_type: str,
        target_id: str,
        link_type: str = "",
        limit: int = 200,
    ) -> list[EntityLinkRecord]:
        clean_target_type = normalize_token(target_type)
        clean_target_id = str(target_id or "").strip()
        clean_link_type = normalize_token(link_type)
        if not clean_target_type or not clean_target_id:
            return []
        conn = _connect(self.db_path)
        try:
            if clean_link_type:
                rows = conn.execute(
                    """
                    SELECT id, source_type, source_id, link_type, target_type, target_id, created_at
                    FROM entity_links
                    WHERE target_type = ? AND target_id = ? AND link_type = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (clean_target_type, clean_target_id, clean_link_type, max(1, int(limit or 1))),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, source_type, source_id, link_type, target_type, target_id, created_at
                    FROM entity_links
                    WHERE target_type = ? AND target_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (clean_target_type, clean_target_id, max(1, int(limit or 1))),
                ).fetchall()
            return [self._row_to_link(row) for row in rows]
        finally:
            conn.close()

    def clear_links_from(self, *, source_type: str, source_id: str) -> int:
        clean_source_type = normalize_token(source_type)
        clean_source_id = str(source_id or "").strip()
        if not clean_source_type or not clean_source_id:
            return 0
        conn = _connect(self.db_path)
        try:
            cursor = conn.execute(
                "DELETE FROM entity_links WHERE source_type = ? AND source_id = ?",
                (clean_source_type, clean_source_id),
            )
            conn.commit()
            return int(cursor.rowcount or 0)
        finally:
            conn.close()

    def _row_to_tag(self, row: sqlite3.Row | None) -> TagRecord:
        if row is None:
            raise ValueError("tag row is required")
        return TagRecord(
            id=str(row["id"]),
            tag_key=str(row["tag_key"]),
            label=str(row["label"]),
            created_at=str(row["created_at"]),
        )

    def _row_to_entity_tag(self, row: sqlite3.Row | None) -> EntityTagRecord:
        if row is None:
            raise ValueError("entity tag row is required")
        return EntityTagRecord(
            entity_type=str(row["entity_type"]),
            entity_id=str(row["entity_id"]),
            tag_id=str(row["tag_id"]),
            created_at=str(row["created_at"]),
        )

    def _row_to_link(self, row: sqlite3.Row | None) -> EntityLinkRecord:
        if row is None:
            raise ValueError("entity link row is required")
        return EntityLinkRecord(
            id=str(row["id"]),
            source_type=str(row["source_type"]),
            source_id=str(row["source_id"]),
            link_type=str(row["link_type"]),
            target_type=str(row["target_type"]),
            target_id=str(row["target_id"]),
            created_at=str(row["created_at"]),
        )
