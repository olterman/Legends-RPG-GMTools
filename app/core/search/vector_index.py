from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DB_NAME = "vector_index.sqlite"
DEFAULT_DIM = 768
SCHEMA_VERSION = 1
EMBEDDING_MODEL_VERSION = "hashed-bow-v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_token(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or ""))
    while "__" in clean:
        clean = clean.replace("__", "_")
    return clean.strip("_")


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9'\-]{0,63}", str(text or "").lower())


def _hash_index(token: str, dim: int) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=False) % dim


def _hash_sign(token: str) -> float:
    digest = hashlib.md5(token.encode("utf-8")).digest()  # noqa: S324 - deterministic sign bit only
    return 1.0 if (digest[0] & 1) else -1.0


def embed_sparse(text: str, *, dim: int = DEFAULT_DIM) -> dict[int, float]:
    vec: dict[int, float] = {}
    for token in _tokenize(text):
        index = _hash_index(token, dim)
        vec[index] = vec.get(index, 0.0) + _hash_sign(token)
    norm = math.sqrt(sum(value * value for value in vec.values()))
    if norm <= 0:
        return {}
    return {key: value / norm for key, value in vec.items() if abs(value) > 1e-9}


def _cosine_sparse(a: dict[int, float], b: dict[int, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return float(sum(value * b.get(key, 0.0) for key, value in a.items()))


def _sanitize_text(text: str) -> str:
    raw = str(text or "").replace("\r\n", "\n")
    raw = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", raw)
    raw = re.sub(r"<img\b[^>]*>", " ", raw, flags=re.IGNORECASE)
    cleaned_lines: list[str] = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue
        if "data:image/" in stripped.lower():
            continue
        if len(stripped) >= 140 and " " not in stripped:
            continue
        letters = sum(ch.isalpha() for ch in stripped)
        digits = sum(ch.isdigit() for ch in stripped)
        punct = sum((not ch.isalnum() and not ch.isspace()) for ch in stripped)
        total = max(1, len(stripped))
        if len(stripped) >= 100 and (letters / total) < 0.25 and ((digits + punct) / total) > 0.6:
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _split_markdown(text: str, *, max_chars: int = 900, overlap_chars: int = 180) -> list[tuple[str, str]]:
    raw = _sanitize_text(text)
    if not raw:
        return []
    sections: list[tuple[str, list[str]]] = []
    current_heading = "Document"
    current_lines: list[str] = []
    for line in raw.split("\n"):
        if re.match(r"^\s{0,3}#{1,6}\s+\S+", line):
            if current_lines:
                sections.append((current_heading, current_lines))
            current_heading = re.sub(r"^\s{0,3}#{1,6}\s+", "", line).strip() or "Section"
            current_lines = []
            continue
        current_lines.append(line)
    if current_lines:
        sections.append((current_heading, current_lines))

    chunks: list[tuple[str, str]] = []
    for heading, body_lines in sections:
        block = "\n".join(body_lines).strip()
        if not block:
            continue
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", block) if part.strip()]
        cursor = ""
        for paragraph in paragraphs:
            candidate = f"{cursor}\n\n{paragraph}".strip() if cursor else paragraph
            if len(candidate) <= max_chars:
                cursor = candidate
                continue
            if cursor:
                chunks.append((heading, cursor.strip()))
                tail = cursor[-overlap_chars:].strip()
                cursor = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
                continue
            start = 0
            step = max(120, max_chars - overlap_chars)
            while start < len(paragraph):
                end = min(len(paragraph), start + max_chars)
                piece = paragraph[start:end].strip()
                if piece:
                    chunks.append((heading, piece))
                if end >= len(paragraph):
                    break
                start += step
            cursor = ""
        if cursor:
            chunks.append((heading, cursor.strip()))
    return chunks


@dataclass(frozen=True)
class VectorChunk:
    doc_id: str
    scope_key: str
    owner_layer: str
    system_id: str
    addon_id: str
    module_id: str
    setting_id: str
    campaign_id: str
    source_kind: str
    content_type: str
    title: str
    heading: str
    source_path: str
    ui_url: str
    chunk_index: int
    text: str
    sha256: str
    updated_at: str


class VectorIndexService:
    def __init__(self, *, project_root: Path, index_root: Path | None = None, dim: int = DEFAULT_DIM) -> None:
        self.project_root = Path(project_root).resolve()
        self.systems_root = self.project_root / "app" / "systems"
        self.content_root = self.project_root / "content"
        self.data_root = self.project_root / "data"
        self.index_root = (index_root or (self.data_root / "vector_index")).resolve()
        self.index_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.index_root / DEFAULT_DB_NAME
        self.dim = dim

    def build(self) -> dict[str, Any]:
        chunks = list(self._discover_chunks())
        with sqlite3.connect(self.db_path) as conn:
            self._ensure_schema(conn)
            conn.execute("DELETE FROM vectors")
            conn.execute("DELETE FROM documents")
            for chunk in chunks:
                cursor = conn.execute(
                    """
                    INSERT INTO documents (
                        doc_id,
                        scope_key,
                        owner_layer,
                        system_id,
                        addon_id,
                        module_id,
                        setting_id,
                        campaign_id,
                        source_kind,
                        content_type,
                        title,
                        heading,
                        source_path,
                        ui_url,
                        chunk_index,
                        text,
                        sha256,
                        token_count,
                        char_count,
                        updated_at,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.doc_id,
                        chunk.scope_key,
                        chunk.owner_layer,
                        chunk.system_id,
                        chunk.addon_id,
                        chunk.module_id,
                        chunk.setting_id,
                        chunk.campaign_id,
                        chunk.source_kind,
                        chunk.content_type,
                        chunk.title,
                        chunk.heading,
                        chunk.source_path,
                        chunk.ui_url,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.sha256,
                        len(_tokenize(chunk.text)),
                        len(chunk.text),
                        chunk.updated_at,
                        _utc_now_iso(),
                    ),
                )
                vector = embed_sparse(chunk.text, dim=self.dim)
                conn.execute(
                    "INSERT INTO vectors (document_id, dim, sparse_json) VALUES (?, ?, ?)",
                    (int(cursor.lastrowid), self.dim, json.dumps(vector, sort_keys=True)),
                )
            conn.execute(
                "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
                ("last_built_at", _utc_now_iso()),
            )
            conn.commit()
        return self.stats()

    def stats(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return {
                "db_path": str(self.db_path),
                "exists": False,
                "document_count": 0,
                "source_counts": {},
                "scope_counts": {"systems": 0, "addons": 0, "modules": 0, "campaigns": 0},
            }
        with sqlite3.connect(self.db_path) as conn:
            self._ensure_schema(conn)
            document_count = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
            source_counts = {
                row[0]: int(row[1])
                for row in conn.execute(
                    "SELECT source_kind, COUNT(*) FROM documents GROUP BY source_kind ORDER BY source_kind"
                ).fetchall()
            }
            scope_counts = {
                "systems": int(conn.execute("SELECT COUNT(DISTINCT system_id) FROM documents WHERE system_id != ''").fetchone()[0]),
                "addons": int(conn.execute("SELECT COUNT(DISTINCT addon_id) FROM documents WHERE addon_id != ''").fetchone()[0]),
                "modules": int(conn.execute("SELECT COUNT(DISTINCT module_id) FROM documents WHERE module_id != ''").fetchone()[0]),
                "campaigns": int(conn.execute("SELECT COUNT(DISTINCT campaign_id) FROM documents WHERE campaign_id != ''").fetchone()[0]),
            }
        return {
            "db_path": str(self.db_path),
            "exists": True,
            "document_count": document_count,
            "source_counts": source_counts,
            "scope_counts": scope_counts,
            "schema_version": SCHEMA_VERSION,
            "embedding_model_version": EMBEDDING_MODEL_VERSION,
        }

    def query(self, *, q: str, k: int = 8, filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        query_vector = embed_sparse(q, dim=self.dim)
        if not query_vector:
            return []
        filters = {key: str(value) for key, value in (filters or {}).items() if str(value or "").strip()}
        where_clauses: list[str] = []
        params: list[Any] = []
        for key in ("owner_layer", "system_id", "addon_id", "module_id", "setting_id", "campaign_id", "source_kind", "content_type"):
            if key in filters:
                where_clauses.append(f"d.{key} = ?")
                params.append(filters[key])
        sql = """
            SELECT
                d.doc_id,
                d.scope_key,
                d.owner_layer,
                d.system_id,
                d.addon_id,
                d.module_id,
                d.setting_id,
                d.campaign_id,
                d.source_kind,
                d.content_type,
                d.title,
                d.heading,
                d.source_path,
                d.ui_url,
                d.chunk_index,
                d.text,
                d.updated_at,
                v.sparse_json
            FROM documents d
            JOIN vectors v ON v.document_id = d.id
        """
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        candidates: list[dict[str, Any]] = []
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        for row in rows:
            vector = {int(key): float(value) for key, value in json.loads(row[17]).items()}
            score = _cosine_sparse(query_vector, vector)
            if score <= 0:
                continue
            candidates.append(
                {
                    "doc_id": row[0],
                    "scope_key": row[1],
                    "owner_layer": row[2],
                    "system_id": row[3],
                    "addon_id": row[4],
                    "module_id": row[5],
                    "setting_id": row[6],
                    "campaign_id": row[7],
                    "source_kind": row[8],
                    "content_type": row[9],
                    "title": row[10],
                    "heading": row[11],
                    "source_path": row[12],
                    "ui_url": row[13],
                    "chunk_index": row[14],
                    "text": row[15],
                    "updated_at": row[16],
                    "score": round(score, 6),
                }
            )
        candidates.sort(key=lambda item: item["score"], reverse=True)
        return candidates[: max(1, min(int(k or 8), 50))]

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS index_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                owner_layer TEXT NOT NULL,
                system_id TEXT NOT NULL,
                addon_id TEXT NOT NULL,
                module_id TEXT NOT NULL,
                setting_id TEXT NOT NULL,
                campaign_id TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                content_type TEXT NOT NULL,
                title TEXT NOT NULL,
                heading TEXT NOT NULL,
                source_path TEXT NOT NULL,
                ui_url TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                token_count INTEGER NOT NULL,
                char_count INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_doc
                ON documents (doc_id, chunk_index);
            CREATE INDEX IF NOT EXISTS idx_documents_scope
                ON documents (system_id, addon_id, module_id, campaign_id, source_kind, content_type);
            CREATE TABLE IF NOT EXISTS vectors (
                document_id INTEGER PRIMARY KEY,
                dim INTEGER NOT NULL,
                sparse_json TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("embedding_model_version", EMBEDDING_MODEL_VERSION),
        )
        conn.commit()

    def _discover_chunks(self) -> Iterable[VectorChunk]:
        yield from self._discover_rulebook_markdown_chunks()
        yield from self._discover_module_lore_chunks()
        yield from self._discover_manifest_chunks()
        yield from self._discover_campaign_content_chunks()
        yield from self._discover_record_chunks()

    def _discover_rulebook_markdown_chunks(self) -> Iterable[VectorChunk]:
        root = self.systems_root
        if not root.exists():
            return
        for path in sorted(root.glob("*/addons/*/source_markdown/*.md")):
            relative_parts = path.relative_to(root).parts
            system_id = relative_parts[0]
            addon_id = relative_parts[2]
            title = path.stem.replace("_", " ").replace("-", " ").strip() or path.stem
            relative = path.relative_to(self.project_root).as_posix()
            updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
            for index, (heading, text) in enumerate(_split_markdown(path.read_text(encoding="utf-8", errors="replace")), start=1):
                clean = re.sub(r"\s+", " ", text).strip()
                if not clean:
                    continue
                source_key = f"rulebook:{system_id}:{addon_id}:{relative}"
                yield VectorChunk(
                    doc_id=hashlib.sha256(f"{source_key}:{index}".encode("utf-8")).hexdigest(),
                    scope_key=f"{system_id}/{addon_id}",
                    owner_layer="canonical",
                    system_id=system_id,
                    addon_id=addon_id,
                    module_id="",
                    setting_id="",
                    campaign_id="",
                    source_kind="rulebook_markdown",
                    content_type="rulebook",
                    title=title,
                    heading=heading,
                    source_path=relative,
                    ui_url="",
                    chunk_index=index,
                    text=clean,
                    sha256=hashlib.sha256(clean.encode("utf-8")).hexdigest(),
                    updated_at=updated_at,
                )

    def _discover_module_lore_chunks(self) -> Iterable[VectorChunk]:
        root = self.systems_root
        if not root.exists():
            return
        for path in sorted(root.glob("*/addons/*/modules/*/lore/**/*.md")):
            relative_parts = path.relative_to(root).parts
            system_id = relative_parts[0]
            addon_id = relative_parts[2]
            module_id = relative_parts[4]
            module_root = root / system_id / "addons" / addon_id / "modules" / module_id
            relative = path.relative_to(self.project_root).as_posix()
            branch_parts = list(path.relative_to(module_root / "lore").parts)
            title = path.stem.replace("_", " ").title()
            updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
            source_kind = "module_lore"
            if branch_parts and branch_parts[0] == "ai_lore":
                source_kind = "ai_lore"
            elif branch_parts and branch_parts[0] == "_migration_staging":
                source_kind = "migration_staging"
            if branch_parts:
                title = " / ".join(part.replace("_", " ").title() for part in branch_parts)
            ui_url = f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/lore"
            if branch_parts:
                target_parts = [part[:-3] if part.endswith(".md") else part for part in branch_parts]
                ui_url += "/" + "/".join(target_parts).replace("//", "/")
            for index, (heading, text) in enumerate(_split_markdown(path.read_text(encoding="utf-8", errors="replace")), start=1):
                clean = re.sub(r"\s+", " ", text).strip()
                if not clean:
                    continue
                source_key = f"lore:{system_id}:{addon_id}:{module_id}:{relative}"
                yield VectorChunk(
                    doc_id=hashlib.sha256(f"{source_key}:{index}".encode("utf-8")).hexdigest(),
                    scope_key=f"{system_id}/{addon_id}/{module_id}",
                    owner_layer="canonical",
                    system_id=system_id,
                    addon_id=addon_id,
                    module_id=module_id,
                    setting_id=module_id,
                    campaign_id="",
                    source_kind=source_kind,
                    content_type="lore_document",
                    title=title,
                    heading=heading,
                    source_path=relative,
                    ui_url=ui_url,
                    chunk_index=index,
                    text=clean,
                    sha256=hashlib.sha256(clean.encode("utf-8")).hexdigest(),
                    updated_at=updated_at,
                )

    def _discover_manifest_chunks(self) -> Iterable[VectorChunk]:
        root = self.systems_root
        if not root.exists():
            return
        for path in sorted(root.glob("*/addons/*/modules/*/**/manifest.json")):
            relative = path.relative_to(self.project_root).as_posix()
            relative_parts = path.relative_to(root).parts
            system_id = relative_parts[0]
            addon_id = relative_parts[2]
            module_id = relative_parts[4]
            module_root = root / system_id / "addons" / addon_id / "modules" / module_id
            payload = self._load_json(path)
            if not payload:
                continue
            title = str(payload.get("label") or payload.get("title") or path.parent.name)
            content_type = str(payload.get("kind") or "manifest").strip().lower() or "manifest"
            text = self._manifest_text(payload)
            if not text:
                continue
            updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
            ui_url = self._module_manifest_ui_url(
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
                module_root=module_root,
                manifest_path=path,
            )
            for index, (heading, chunk_text) in enumerate(_split_markdown(text), start=1):
                clean = re.sub(r"\s+", " ", chunk_text).strip()
                if not clean:
                    continue
                source_key = f"manifest:{relative}"
                yield VectorChunk(
                    doc_id=hashlib.sha256(f"{source_key}:{index}".encode("utf-8")).hexdigest(),
                    scope_key=f"{system_id}/{addon_id}/{module_id}",
                    owner_layer="canonical",
                    system_id=system_id,
                    addon_id=addon_id,
                    module_id=module_id,
                    setting_id=module_id,
                    campaign_id="",
                    source_kind="module_manifest",
                    content_type=content_type,
                    title=title,
                    heading=heading,
                    source_path=relative,
                    ui_url=ui_url,
                    chunk_index=index,
                    text=clean,
                    sha256=hashlib.sha256(clean.encode("utf-8")).hexdigest(),
                    updated_at=updated_at,
                )

    def _discover_campaign_content_chunks(self) -> Iterable[VectorChunk]:
        root = self.content_root
        if not root.exists():
            return
        for path in sorted(root.rglob("manifest.json")):
            relative = path.relative_to(self.project_root).as_posix()
            payload = self._load_json(path)
            if not payload:
                continue
            parts = path.relative_to(root).parts
            system_id = parts[0] if len(parts) > 0 else ""
            setting_id = parts[1] if len(parts) > 1 else ""
            campaign_id = parts[2] if len(parts) > 2 else ""
            title = str(payload.get("label") or payload.get("title") or path.parent.name)
            content_type = str(payload.get("kind") or "manifest").strip().lower() or "manifest"
            text = self._manifest_text(payload)
            if not text:
                continue
            updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
            for index, (heading, chunk_text) in enumerate(_split_markdown(text), start=1):
                clean = re.sub(r"\s+", " ", chunk_text).strip()
                if not clean:
                    continue
                source_key = f"campaign_manifest:{relative}"
                yield VectorChunk(
                    doc_id=hashlib.sha256(f"{source_key}:{index}".encode("utf-8")).hexdigest(),
                    scope_key=f"{system_id}/{setting_id}/{campaign_id}",
                    owner_layer="campaign",
                    system_id=system_id,
                    addon_id="",
                    module_id="",
                    setting_id=setting_id,
                    campaign_id=campaign_id,
                    source_kind="campaign_manifest",
                    content_type=content_type,
                    title=title,
                    heading=heading,
                    source_path=relative,
                    ui_url="",
                    chunk_index=index,
                    text=clean,
                    sha256=hashlib.sha256(clean.encode("utf-8")).hexdigest(),
                    updated_at=updated_at,
                )
        for path in sorted(root.rglob("*.md")):
            relative = path.relative_to(self.project_root).as_posix()
            parts = path.relative_to(root).parts
            system_id = parts[0] if len(parts) > 0 else ""
            setting_id = parts[1] if len(parts) > 1 else ""
            campaign_id = parts[2] if len(parts) > 2 else ""
            updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
            title = " / ".join(part.replace("_", " ").title() for part in path.relative_to(root).with_suffix("").parts)
            for index, (heading, chunk_text) in enumerate(_split_markdown(path.read_text(encoding="utf-8", errors="replace")), start=1):
                clean = re.sub(r"\s+", " ", chunk_text).strip()
                if not clean:
                    continue
                source_key = f"campaign_lore:{relative}"
                yield VectorChunk(
                    doc_id=hashlib.sha256(f"{source_key}:{index}".encode("utf-8")).hexdigest(),
                    scope_key=f"{system_id}/{setting_id}/{campaign_id}",
                    owner_layer="campaign",
                    system_id=system_id,
                    addon_id="",
                    module_id="",
                    setting_id=setting_id,
                    campaign_id=campaign_id,
                    source_kind="campaign_lore",
                    content_type="lore_document",
                    title=title,
                    heading=heading,
                    source_path=relative,
                    ui_url="",
                    chunk_index=index,
                    text=clean,
                    sha256=hashlib.sha256(clean.encode("utf-8")).hexdigest(),
                    updated_at=updated_at,
                )

    def _discover_record_chunks(self) -> Iterable[VectorChunk]:
        records_root = self.data_root / "records"
        if not records_root.exists():
            return
        for path in sorted(records_root.glob("*.json")):
            payload = self._load_json(path)
            if not payload:
                continue
            context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
            system_id = str(context.get("system_id") or "")
            setting_id = str(context.get("setting_id") or "")
            campaign_id = str(context.get("campaign_id") or "")
            relative = path.relative_to(self.project_root).as_posix()
            title = str(payload.get("title") or path.stem)
            content_type = str(payload.get("type") or "record")
            text = self._record_text(payload)
            if not text:
                continue
            updated_at = str(((payload.get("audit") or {}) if isinstance(payload.get("audit"), dict) else {}).get("updated_at") or _utc_now_iso())
            for index, (heading, chunk_text) in enumerate(_split_markdown(text), start=1):
                clean = re.sub(r"\s+", " ", chunk_text).strip()
                if not clean:
                    continue
                source_key = f"record:{relative}"
                yield VectorChunk(
                    doc_id=hashlib.sha256(f"{source_key}:{index}".encode("utf-8")).hexdigest(),
                    scope_key=f"{system_id}/{setting_id}/{campaign_id}",
                    owner_layer="campaign" if campaign_id else "canonical",
                    system_id=system_id,
                    addon_id=str(((payload.get("system") or {}) if isinstance(payload.get("system"), dict) else {}).get("addon_id") or ""),
                    module_id="",
                    setting_id=setting_id,
                    campaign_id=campaign_id,
                    source_kind="record",
                    content_type=content_type,
                    title=title,
                    heading=heading,
                    source_path=relative,
                    ui_url="",
                    chunk_index=index,
                    text=clean,
                    sha256=hashlib.sha256(clean.encode("utf-8")).hexdigest(),
                    updated_at=updated_at,
                )

    def _load_json(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _manifest_text(self, payload: dict[str, Any]) -> str:
        parts: list[str] = []
        label = str(payload.get("label") or payload.get("title") or "")
        kind = str(payload.get("kind") or "")
        summary = str(payload.get("summary") or payload.get("description") or "")
        if label:
            parts.append(f"# {label}")
        if kind:
            parts.append(f"Kind: {kind}")
        if summary:
            parts.append(summary)
        details = payload.get("details")
        if isinstance(details, dict):
            for key, value in details.items():
                rendered = self._stringify_value(value)
                if rendered:
                    parts.append(f"## {key.replace('_', ' ').title()}\n{rendered}")
        for key in ("subgroups", "tags", "notes", "scope", "theme", "default_campaign_style"):
            rendered = self._stringify_value(payload.get(key))
            if rendered:
                parts.append(f"## {key.replace('_', ' ').title()}\n{rendered}")
        return "\n\n".join(part for part in parts if part.strip())

    def _record_text(self, payload: dict[str, Any]) -> str:
        parts: list[str] = []
        title = str(payload.get("title") or "")
        record_type = str(payload.get("type") or "")
        if title:
            parts.append(f"# {title}")
        if record_type:
            parts.append(f"Type: {record_type}")
        for section_name in ("content", "metadata", "source", "extensions"):
            section = payload.get(section_name)
            if isinstance(section, dict):
                for key, value in section.items():
                    rendered = self._stringify_value(value)
                    if rendered:
                        parts.append(f"## {key.replace('_', ' ').title()}\n{rendered}")
        return "\n\n".join(part for part in parts if part.strip())

    def _stringify_value(self, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            rendered = [self._stringify_value(item) for item in value]
            rendered = [item for item in rendered if item]
            return "\n".join(f"- {item}" for item in rendered)
        if isinstance(value, dict):
            rendered_lines: list[str] = []
            for key, nested in value.items():
                nested_rendered = self._stringify_value(nested)
                if nested_rendered:
                    rendered_lines.append(f"{key.replace('_', ' ').title()}: {nested_rendered}")
            return "\n".join(rendered_lines)
        return ""

    def _module_manifest_ui_url(
        self,
        *,
        system_id: str,
        addon_id: str,
        module_id: str,
        module_root: Path,
        manifest_path: Path,
    ) -> str:
        relative = manifest_path.relative_to(module_root)
        parts = list(relative.parts)
        if parts == ["manifest.json"]:
            return f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
        if len(parts) >= 3 and parts[0] == "regions":
            if parts[-1] != "manifest.json":
                return ""
            if len(parts) == 3:
                return f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{parts[1]}"
            if len(parts) == 5 and parts[2] == "subregions":
                return (
                    f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{parts[1]}/subregions/{parts[3]}"
                )
        if len(parts) >= 3 and parts[0] == "peoples":
            if len(parts) == 3:
                return f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/peoples/{parts[1]}"
            if len(parts) == 5 and parts[2] == "subgroups":
                return (
                    f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/peoples/{parts[1]}/subgroups/{parts[3]}"
                )
        return ""
