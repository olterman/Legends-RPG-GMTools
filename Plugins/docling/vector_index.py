from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DOCLING_ROOT = "PDF_Repository/private_compendium/_docling"
DEFAULT_OFFICIAL_ROOT = "PDF_Repository/private_compendium"
DEFAULT_STORAGE_ROOT = "storage"
DEFAULT_OUTPUT_ROOT = "PDF_Repository/private_compendium/_vector"
DEFAULT_DB_NAME = "vector_index.sqlite"
DEFAULT_DIM = 768
SCHEMA_VERSION = 1
EMBEDDING_MODEL_VERSION = "hashed-bow-v1"
LOCAL_LIBRARY_COMPENDIUM_ID = "local_library"


@dataclass
class ChunkRow:
    compendium_id: str
    source_path: str
    heading: str
    chunk_index: int
    text: str
    sha256: str
    token_count: int
    char_count: int


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _safe_slug(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or ""))
    while "__" in clean:
        clean = clean.replace("__", "_")
    return clean.strip("_") or "unknown"


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9'\-]{0,63}", str(text or "").lower())


def _hash_index(token: str, dim: int) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, byteorder="big", signed=False)
    return value % dim


def _hash_sign(token: str) -> float:
    digest = hashlib.md5(token.encode("utf-8")).digest()  # noqa: S324 - deterministic sign bit only
    return 1.0 if (digest[0] & 1) else -1.0


def embed_sparse(text: str, *, dim: int) -> tuple[dict[int, float], float]:
    vec: dict[int, float] = {}
    for tok in _tokenize(text):
        idx = _hash_index(tok, dim)
        vec[idx] = vec.get(idx, 0.0) + _hash_sign(tok)
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm > 0:
        vec = {k: (v / norm) for k, v in vec.items() if abs(v) > 1e-9}
    return vec, norm


def _cosine_sparse(a: dict[int, float], b: dict[int, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return float(sum(v * b.get(k, 0.0) for k, v in a.items()))


def discover_docling_markdown(docling_root: Path, *, compendium_ids: set[str] | None = None) -> list[Path]:
    items: list[Path] = []
    if not docling_root.exists():
        return items
    for path in sorted(docling_root.rglob("*")):
        if not path.is_file():
            continue
        lower_name = path.name.lower()
        if not (lower_name.endswith(".md") or lower_name.endswith(".md-first-run")):
            continue
        rel = path.relative_to(docling_root)
        if len(rel.parts) < 2:
            continue
        cid = rel.parts[0].strip().lower()
        if compendium_ids and cid not in compendium_ids:
            continue
        items.append(path)
    return items


def sanitize_markdown_for_chunking(text: str) -> str:
    """
    Remove common OCR/image artifact noise before chunking.
    This keeps semantic chunks readable and useful.
    """
    raw = str(text or "").replace("\r\n", "\n")

    # Remove markdown image tags and HTML img tags.
    raw = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", raw)
    raw = re.sub(r"<img\b[^>]*>", " ", raw, flags=re.IGNORECASE)

    cleaned_lines: list[str] = []
    for line in raw.split("\n"):
        s = str(line or "").strip()
        if not s:
            cleaned_lines.append("")
            continue

        # Drop obvious binary/data URI payload lines.
        if "data:image/" in s.lower():
            continue

        # Drop very long token-only garbage lines (common from OCR/image blobs).
        if len(s) >= 140 and " " not in s:
            continue

        letters = sum(ch.isalpha() for ch in s)
        digits = sum(ch.isdigit() for ch in s)
        punct = sum((not ch.isalnum() and not ch.isspace()) for ch in s)
        total = max(1, len(s))
        alpha_ratio = letters / total
        noise_ratio = (digits + punct) / total

        # Heuristic: long line with low alphabetic content is likely noise.
        if len(s) >= 100 and alpha_ratio < 0.25 and noise_ratio > 0.6:
            continue

        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def split_hybrid_markdown(text: str, *, max_chars: int = 900, overlap_chars: int = 180) -> list[tuple[str, str]]:
    raw = sanitize_markdown_for_chunking(text)
    lines = raw.split("\n")
    sections: list[tuple[str, list[str]]] = []
    current_heading = "Document"
    current_lines: list[str] = []

    for line in lines:
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
        paras = [p.strip() for p in re.split(r"\n\s*\n", block) if p.strip()]
        if not paras:
            continue
        cursor = ""
        for para in paras:
            candidate = f"{cursor}\n\n{para}".strip() if cursor else para
            if len(candidate) <= max_chars:
                cursor = candidate
                continue
            if cursor:
                chunks.append((heading, cursor.strip()))
                tail = cursor[-overlap_chars:].strip()
                cursor = f"{tail}\n\n{para}".strip() if tail else para
            else:
                start = 0
                step = max(120, max_chars - overlap_chars)
                while start < len(para):
                    end = min(len(para), start + max_chars)
                    piece = para[start:end].strip()
                    if piece:
                        chunks.append((heading, piece))
                    if end >= len(para):
                        break
                    start += step
                cursor = ""
        if cursor:
            chunks.append((heading, cursor.strip()))
    return chunks


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS index_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compendium_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            heading TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            char_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_unique
            ON documents (compendium_id, source_path, chunk_index);
        CREATE INDEX IF NOT EXISTS idx_documents_compendium
            ON documents (compendium_id);
        CREATE TABLE IF NOT EXISTS vectors (
            doc_id INTEGER PRIMARY KEY,
            dim INTEGER NOT NULL,
            norm REAL NOT NULL,
            sparse_json TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)",
        ("embedding_model_version", EMBEDDING_MODEL_VERSION),
    )
    conn.commit()


def _chunk_rows_for_markdown(path: Path, *, root: Path) -> list[ChunkRow]:
    rel = str(path.relative_to(root)).replace("\\", "/")
    compendium_id = rel.split("/", 1)[0].strip().lower()
    text = path.read_text(encoding="utf-8", errors="replace")
    chunks = split_hybrid_markdown(text)
    rows: list[ChunkRow] = []
    for idx, (heading, chunk_text) in enumerate(chunks, start=1):
        clean = re.sub(r"\s+", " ", chunk_text).strip()
        if not clean:
            continue
        digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()
        rows.append(
            ChunkRow(
                compendium_id=compendium_id,
                source_path=rel,
                heading=heading,
                chunk_index=idx,
                text=clean,
                sha256=digest,
                token_count=len(_tokenize(clean)),
                char_count=len(clean),
            )
        )
    return rows


def discover_official_card_json(official_root: Path) -> list[Path]:
    if not official_root.exists():
        return []
    allowed_dirs = {
        "abilities",
        "skills",
        "foci",
        "descriptors",
        "types",
        "flavors",
        "creatures",
        "npcs",
        "cyphers",
        "artifacts",
        "encounters",
        "locations",
        "areas",
        "races",
        "equipment",
        "items",
        "lore",
    }
    items: list[Path] = []
    for path in sorted(official_root.rglob("*.json")):
        if not path.is_file():
            continue
        rel = path.relative_to(official_root)
        if not rel.parts:
            continue
        first = rel.parts[0].strip().lower()
        if first.startswith("_"):
            continue
        if first not in allowed_dirs:
            continue
        items.append(path)
    return items


def discover_storage_json(storage_root: Path) -> list[Path]:
    if not storage_root.exists():
        return []
    items: list[Path] = []
    for path in sorted(storage_root.rglob("*.json")):
        if not path.is_file():
            continue
        rel = path.relative_to(storage_root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        items.append(path)
    return items


def _flatten_for_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_flatten_for_text(v) for v in value]
        return "; ".join(p for p in parts if p)
    if isinstance(value, dict):
        parts: list[str] = []
        for k, v in value.items():
            text = _flatten_for_text(v)
            if text:
                parts.append(f"{k}: {text}")
        return "\n".join(parts)
    return str(value).strip()


def _extract_official_compendium_id(card: dict[str, Any], fallback: str) -> str:
    metadata = card.get("metadata") if isinstance(card.get("metadata"), dict) else {}
    cid = (
        card.get("compendium_id")
        or metadata.get("compendium_id")
        or card.get("book")
        or metadata.get("book")
        or fallback
    )
    return _safe_slug(str(cid or fallback))


def _build_card_markdown(card: dict[str, Any], *, source_kind: str, rel: str) -> tuple[str, str, str]:
    if source_kind == "storage" and isinstance(card.get("result"), dict):
        wrapped = card
        card = dict(wrapped.get("result") or {})
        card["saved_at"] = wrapped.get("saved_at")
        card["filename"] = wrapped.get("filename") or rel
        card["payload"] = wrapped.get("payload") if isinstance(wrapped.get("payload"), dict) else {}
        if not isinstance(card.get("metadata"), dict):
            card["metadata"] = {}

    title = str(card.get("title") or card.get("name") or Path(rel).stem).strip() or Path(rel).stem
    card_type = str(card.get("type") or "").strip().lower()
    description = str(card.get("description") or "").strip()
    text = str(card.get("text") or "").strip()
    sections = card.get("sections") if isinstance(card.get("sections"), dict) else {}
    stat_block = card.get("stat_block") if isinstance(card.get("stat_block"), dict) else {}
    metadata = card.get("metadata") if isinstance(card.get("metadata"), dict) else {}
    saved_at = str(card.get("saved_at") or "").strip()
    filename = str(card.get("filename") or "").strip()
    source = str(card.get("source") or metadata.get("source") or source_kind).strip()
    book = str(card.get("book") or metadata.get("book") or "").strip()
    pages = str(card.get("pages") or metadata.get("pages") or "").strip()
    setting = str(card.get("setting") or metadata.get("setting") or "").strip()
    area = str(metadata.get("area") or metadata.get("environment") or "").strip()
    location = str(metadata.get("location") or "").strip()

    body: list[str] = [
        f"# {title}",
        "",
        f"Type: {card_type or 'unknown'}",
        f"Source: {source}",
    ]
    if book:
        body.append(f"Book: {book}")
    if pages:
        body.append(f"Pages: {pages}")
    if setting:
        body.append(f"Setting: {setting}")
    if area:
        body.append(f"Area: {area}")
    if location:
        body.append(f"Location: {location}")
    if saved_at:
        body.append(f"Saved At: {saved_at}")
    if filename:
        body.append(f"Filename: {filename}")
    body.append("")
    if description:
        body.extend(["## Description", description, ""])
    if sections:
        body.extend(["## Sections", _flatten_for_text(sections), ""])
    if stat_block:
        body.extend(["## Stat Block", _flatten_for_text(stat_block), ""])
    if text:
        body.extend(["## Text", text, ""])
    if metadata:
        body.extend(["## Metadata", _flatten_for_text(metadata), ""])
    markdown = "\n".join(body).strip()
    heading = title
    return heading, markdown, card_type


def _chunk_rows_for_json_card(
    path: Path,
    *,
    root: Path,
    source_kind: str,
) -> list[ChunkRow]:
    rel = str(path.relative_to(root)).replace("\\", "/")
    try:
        card = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(card, dict):
        return []

    if source_kind == "official":
        compendium_id = _extract_official_compendium_id(card, fallback=Path(rel).parts[0] if Path(rel).parts else "sourcebooks")
        source_path = f"official/{rel}"
    else:
        compendium_id = LOCAL_LIBRARY_COMPENDIUM_ID
        source_path = f"storage/{rel}"

    heading, markdown, _ = _build_card_markdown(card, source_kind=source_kind, rel=rel)
    chunks = split_hybrid_markdown(markdown)
    rows: list[ChunkRow] = []
    for idx, (chunk_heading, chunk_text) in enumerate(chunks, start=1):
        clean = re.sub(r"\s+", " ", chunk_text).strip()
        if not clean:
            continue
        digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()
        rows.append(
            ChunkRow(
                compendium_id=compendium_id,
                source_path=source_path,
                heading=chunk_heading or heading,
                chunk_index=idx,
                text=clean,
                sha256=digest,
                token_count=len(_tokenize(clean)),
                char_count=len(clean),
            )
        )
    return rows


def _upsert_rows_for_source(
    conn: sqlite3.Connection,
    *,
    source_path: str,
    rows: list[ChunkRow],
    dim: int,
) -> tuple[int, int, int]:
    inserted = 0
    updated = 0
    removed = 0
    existing = conn.execute(
        "SELECT id, chunk_index, sha256 FROM documents WHERE source_path = ?",
        (source_path,),
    ).fetchall()
    by_idx = {int(r["chunk_index"]): dict(r) for r in existing}
    keep_ids: set[int] = set()

    for row in rows:
        old = by_idx.get(row.chunk_index)
        if old and str(old.get("sha256")) == row.sha256:
            keep_ids.add(int(old["id"]))
            continue

        now = datetime.now(timezone.utc).isoformat()
        if old:
            conn.execute(
                """
                UPDATE documents
                SET compendium_id = ?, heading = ?, text = ?, sha256 = ?, token_count = ?, char_count = ?, created_at = ?
                WHERE id = ?
                """,
                (
                    row.compendium_id,
                    row.heading,
                    row.text,
                    row.sha256,
                    row.token_count,
                    row.char_count,
                    now,
                    int(old["id"]),
                ),
            )
            doc_id = int(old["id"])
            updated += 1
        else:
            cur = conn.execute(
                """
                INSERT INTO documents (
                    compendium_id, source_path, heading, chunk_index, text, sha256, token_count, char_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.compendium_id,
                    row.source_path,
                    row.heading,
                    row.chunk_index,
                    row.text,
                    row.sha256,
                    row.token_count,
                    row.char_count,
                    now,
                ),
            )
            doc_id = int(cur.lastrowid)
            inserted += 1
        keep_ids.add(doc_id)

        vec, norm = embed_sparse(row.text, dim=dim)
        sparse_json = json.dumps([[int(k), float(v)] for k, v in sorted(vec.items())], ensure_ascii=False)
        conn.execute(
            "INSERT OR REPLACE INTO vectors(doc_id, dim, norm, sparse_json) VALUES (?, ?, ?, ?)",
            (doc_id, int(dim), float(norm), sparse_json),
        )

    stale_ids = [
        int(r["id"]) for r in existing
        if int(r["id"]) not in keep_ids
    ]
    if stale_ids:
        conn.executemany("DELETE FROM vectors WHERE doc_id = ?", [(sid,) for sid in stale_ids])
        conn.executemany("DELETE FROM documents WHERE id = ?", [(sid,) for sid in stale_ids])
        removed += len(stale_ids)
    return inserted, updated, removed


def build_index(
    *,
    docling_root: Path,
    official_root: Path,
    storage_root: Path,
    output_root: Path,
    compendium_ids: set[str] | None = None,
    include_official_cards: bool = True,
    include_storage_cards: bool = True,
    dim: int = DEFAULT_DIM,
    verbose: bool = True,
) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    db_path = output_root / DEFAULT_DB_NAME
    md_files = discover_docling_markdown(docling_root, compendium_ids=compendium_ids)
    official_cards = discover_official_card_json(official_root) if include_official_cards else []
    storage_cards = discover_storage_json(storage_root) if include_storage_cards else []
    if verbose:
        print(f"[vector] markdown files discovered: {len(md_files)}")
        print(f"[vector] official card files discovered: {len(official_cards)}")
        print(f"[vector] storage card files discovered: {len(storage_cards)}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    total_chunks = 0
    inserted = 0
    updated = 0
    removed = 0

    for md in md_files:
        rows = _chunk_rows_for_markdown(md, root=docling_root)
        total_chunks += len(rows)
        rel = str(md.relative_to(docling_root)).replace("\\", "/")
        if verbose:
            print(f"[vector] {rel}: {len(rows)} chunks")
        i, u, r = _upsert_rows_for_source(conn, source_path=rel, rows=rows, dim=dim)
        inserted += i
        updated += u
        removed += r

    for card_path in official_cards:
        rows = _chunk_rows_for_json_card(card_path, root=official_root, source_kind="official")
        if compendium_ids:
            rows = [row for row in rows if row.compendium_id in compendium_ids]
        if not rows:
            continue
        total_chunks += len(rows)
        source_path = rows[0].source_path
        if verbose:
            print(f"[vector] {source_path}: {len(rows)} chunks")
        i, u, r = _upsert_rows_for_source(conn, source_path=source_path, rows=rows, dim=dim)
        inserted += i
        updated += u
        removed += r

    for card_path in storage_cards:
        rows = _chunk_rows_for_json_card(card_path, root=storage_root, source_kind="storage")
        if compendium_ids:
            rows = [row for row in rows if row.compendium_id in compendium_ids]
        if not rows:
            continue
        total_chunks += len(rows)
        source_path = rows[0].source_path
        if verbose:
            print(f"[vector] {source_path}: {len(rows)} chunks")
        i, u, r = _upsert_rows_for_source(conn, source_path=source_path, rows=rows, dim=dim)
        inserted += i
        updated += u
        removed += r

    conn.execute(
        "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)",
        ("last_built_at", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()

    stats = conn.execute(
        "SELECT compendium_id, COUNT(*) AS c FROM documents GROUP BY compendium_id ORDER BY compendium_id"
    ).fetchall()
    counts_by_compendium = {str(r["compendium_id"]): int(r["c"]) for r in stats}
    total_docs = int(sum(counts_by_compendium.values()))
    conn.close()

    summary = {
        "status": "ok",
        "db_path": str(db_path),
        "docling_root": str(docling_root),
        "official_root": str(official_root),
        "storage_root": str(storage_root),
        "files_processed": len(md_files),
        "official_cards_processed": len(official_cards) if include_official_cards else 0,
        "storage_cards_processed": len(storage_cards) if include_storage_cards else 0,
        "total_chunks_seen": int(total_chunks),
        "inserted": int(inserted),
        "updated": int(updated),
        "removed": int(removed),
        "total_docs": int(total_docs),
        "counts_by_compendium": counts_by_compendium,
        "schema_version": SCHEMA_VERSION,
        "embedding_model_version": EMBEDDING_MODEL_VERSION,
        "dim": int(dim),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = output_root / "build_manifest.json"
    manifest_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def query_index(
    *,
    output_root: Path,
    query: str,
    k: int,
    compendium_id: str = "",
    dim: int = DEFAULT_DIM,
) -> dict:
    db_path = output_root / DEFAULT_DB_NAME
    if not db_path.exists():
        raise FileNotFoundError(f"vector db not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    qvec, _ = embed_sparse(query, dim=dim)
    where = ""
    params: list[object] = []
    if compendium_id:
        where = "WHERE d.compendium_id = ?"
        params.append(compendium_id.strip().lower())
    rows = conn.execute(
        f"""
        SELECT d.id, d.compendium_id, d.source_path, d.heading, d.chunk_index, d.text, v.sparse_json
        FROM documents d
        JOIN vectors v ON v.doc_id = d.id
        {where}
        """,
        params,
    ).fetchall()
    scored = []
    for row in rows:
        sparse = json.loads(str(row["sparse_json"] or "[]"))
        vec = {int(kv[0]): float(kv[1]) for kv in sparse if isinstance(kv, list) and len(kv) == 2}
        score = _cosine_sparse(qvec, vec)
        if score <= 0:
            continue
        scored.append({
            "score": score,
            "compendium_id": str(row["compendium_id"]),
            "source_path": str(row["source_path"]),
            "heading": str(row["heading"]),
            "chunk_index": int(row["chunk_index"]),
            "text": str(row["text"]),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    conn.close()
    return {
        "query": query,
        "k": int(k),
        "count": len(scored[:k]),
        "items": scored[:k],
    }


def stats_index(*, output_root: Path) -> dict:
    db_path = output_root / DEFAULT_DB_NAME
    if not db_path.exists():
        return {"exists": False, "db_path": str(db_path), "total_docs": 0, "counts_by_compendium": {}}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT compendium_id, COUNT(*) AS c FROM documents GROUP BY compendium_id ORDER BY compendium_id"
    ).fetchall()
    counts = {str(r["compendium_id"]): int(r["c"]) for r in rows}
    total = int(sum(counts.values()))
    meta_rows = conn.execute("SELECT key, value FROM index_meta").fetchall()
    meta = {str(r["key"]): str(r["value"]) for r in meta_rows}
    conn.close()
    return {
        "exists": True,
        "db_path": str(db_path),
        "total_docs": total,
        "counts_by_compendium": counts,
        "meta": meta,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m Plugins.docling.vector_index",
        description="Build/query a local hybrid-chunk vector index from Docling markdown output.",
    )
    parser.add_argument(
        "--docling-root",
        default=DEFAULT_DOCLING_ROOT,
        help=f"Docling markdown root (default: {DEFAULT_DOCLING_ROOT})",
    )
    parser.add_argument(
        "--official-root",
        default=DEFAULT_OFFICIAL_ROOT,
        help=f"Official/private compendium JSON root (default: {DEFAULT_OFFICIAL_ROOT})",
    )
    parser.add_argument(
        "--storage-root",
        default=DEFAULT_STORAGE_ROOT,
        help=f"Local storage JSON root (default: {DEFAULT_STORAGE_ROOT})",
    )
    parser.add_argument(
        "--output-root",
        default=DEFAULT_OUTPUT_ROOT,
        help=f"Vector output root (default: {DEFAULT_OUTPUT_ROOT})",
    )
    parser.add_argument(
        "--dim",
        type=int,
        default=DEFAULT_DIM,
        help=f"Embedding vector dimensions (default: {DEFAULT_DIM})",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    build = sub.add_parser("build", help="Build or incrementally update vector index.")
    build.add_argument(
        "--compendium-id",
        action="append",
        default=[],
        help="Limit build to one or more compendium IDs (docling folder/book ids, or local_library).",
    )
    build.add_argument(
        "--no-official-cards",
        action="store_true",
        help="Skip indexing official/sourcebook JSON cards.",
    )
    build.add_argument(
        "--no-storage-cards",
        action="store_true",
        help="Skip indexing local storage/library JSON cards.",
    )
    build.add_argument("--quiet", action="store_true", help="Reduce log output.")

    query = sub.add_parser("query", help="Run similarity query against vector index.")
    query.add_argument("--q", required=True, help="Query text.")
    query.add_argument("--k", type=int, default=8, help="Top-k results.")
    query.add_argument("--compendium-id", default="", help="Optional compendium filter.")

    sub.add_parser("stats", help="Show vector index stats.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    root = _repo_root()
    docling_root = (root / str(args.docling_root)).resolve() if not Path(str(args.docling_root)).is_absolute() else Path(str(args.docling_root)).resolve()
    official_root = (root / str(args.official_root)).resolve() if not Path(str(args.official_root)).is_absolute() else Path(str(args.official_root)).resolve()
    storage_root = (root / str(args.storage_root)).resolve() if not Path(str(args.storage_root)).is_absolute() else Path(str(args.storage_root)).resolve()
    output_root = (root / str(args.output_root)).resolve() if not Path(str(args.output_root)).is_absolute() else Path(str(args.output_root)).resolve()
    dim = max(64, int(args.dim or DEFAULT_DIM))

    if args.cmd == "build":
        ids = {str(x).strip().lower() for x in (args.compendium_id or []) if str(x).strip()}
        summary = build_index(
            docling_root=docling_root,
            official_root=official_root,
            storage_root=storage_root,
            output_root=output_root,
            compendium_ids=ids or None,
            include_official_cards=not bool(args.no_official_cards),
            include_storage_cards=not bool(args.no_storage_cards),
            dim=dim,
            verbose=not bool(args.quiet),
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "query":
        result = query_index(
            output_root=output_root,
            query=str(args.q or "").strip(),
            k=max(1, int(args.k or 8)),
            compendium_id=str(args.compendium_id or "").strip().lower(),
            dim=dim,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "stats":
        result = stats_index(output_root=output_root)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
