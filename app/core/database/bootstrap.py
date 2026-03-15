from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CURRENT_SCHEMA_VERSION = 2


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row["name"]) == column_name for row in rows)


def _ensure_meta_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def _apply_migration_v1(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL DEFAULT '',
            display_name TEXT NOT NULL,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """
    )


def _apply_migration_v2(conn: sqlite3.Connection) -> None:
    if not _column_exists(conn, "users", "email"):
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            actor_user_id TEXT,
            action_type TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            system_id TEXT NOT NULL DEFAULT 'none',
            setting_id TEXT NOT NULL DEFAULT '',
            campaign_id TEXT NOT NULL DEFAULT '',
            request_kind TEXT NOT NULL DEFAULT '',
            provider_id TEXT NOT NULL DEFAULT '',
            prompt_text TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(actor_user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tags (
            id TEXT PRIMARY KEY,
            tag_key TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity_tags (
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            tag_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (entity_type, entity_id, tag_id),
            FOREIGN KEY(tag_id) REFERENCES tags(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity_links (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            link_type TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


MIGRATIONS: list[tuple[int, str, Any]] = [
    (1, "initial_platform_schema", _apply_migration_v1),
    (2, "users_email_column", _apply_migration_v2),
]


@dataclass
class DatabaseBootstrapResult:
    path: str
    created: bool
    current_version: int
    applied_versions: list[int]


class DatabaseManager:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def ensure(self) -> DatabaseBootstrapResult:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        created = not self.db_path.exists()
        conn = _connect(self.db_path)
        try:
            _ensure_meta_tables(conn)
            applied = self._applied_versions(conn)
            applied_now: list[int] = []
            for version, name, migration in MIGRATIONS:
                if version in applied:
                    continue
                migration(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                    (version, name),
                )
                applied_now.append(version)
            conn.execute(
                """
                INSERT INTO platform_metadata(key, value)
                VALUES ('current_schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(CURRENT_SCHEMA_VERSION),),
            )
            conn.commit()
            final_versions = self._applied_versions(conn)
            return DatabaseBootstrapResult(
                path=str(self.db_path),
                created=created,
                current_version=CURRENT_SCHEMA_VERSION,
                applied_versions=final_versions if applied_now or final_versions else [],
            )
        finally:
            conn.close()

    def _applied_versions(self, conn: sqlite3.Connection) -> list[int]:
        if not _table_exists(conn, "schema_migrations"):
            return []
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version ASC").fetchall()
        return [int(row["version"]) for row in rows]

    def inspect(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return {
                "path": str(self.db_path),
                "exists": False,
                "current_version": 0,
                "tables": [],
            }
        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name ASC"
            ).fetchall()
            tables = [str(row["name"]) for row in rows]
            current_version = 0
            if _table_exists(conn, "platform_metadata"):
                row = conn.execute(
                    "SELECT value FROM platform_metadata WHERE key = 'current_schema_version'"
                ).fetchone()
                if row is not None:
                    current_version = int(str(row["value"]))
            return {
                "path": str(self.db_path),
                "exists": True,
                "current_version": current_version,
                "tables": tables,
            }
        finally:
            conn.close()


def ensure_database(db_path: Path) -> DatabaseBootstrapResult:
    return DatabaseManager(db_path).ensure()
