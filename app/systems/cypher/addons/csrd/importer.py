from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.content import ContentService
from app.core.contracts import build_record
from .markdown_parser import load_markdown, parse_descriptor_markdown

CSRD_SOURCE_LABEL = "Cypher System Reference Document 2025-08-22"


def _load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a top-level object")
    return data


def _descriptor_record_from_csrd(card: dict[str, Any]) -> dict[str, Any]:
    title = str(card.get("title") or "").strip()
    slug = str(card.get("slug") or "").strip()
    if not title:
        raise ValueError("descriptor title is required")
    if not slug:
        raise ValueError("descriptor slug is required")

    summary = str(card.get("summary") or "").strip()
    text = str(card.get("text") or "").strip()
    details = card.get("details") if isinstance(card.get("details"), list) else []

    return build_record(
        record_type="descriptor_record",
        title=title,
        slug=slug,
        system_id="cypher",
        addon_id="csrd",
        source={
            "kind": "addon_pack",
            "origin": "csrd",
            "sourcebook": str(card.get("source") or CSRD_SOURCE_LABEL).strip(),
            "pages": [],
            "external_ref": f"csrd/descriptors/{slug}.json",
        },
        content={
            "csrd_type": str(card.get("type") or "descriptor"),
            "summary": summary,
            "text": text,
            "details": [str(item) for item in details],
            "raw_card": card,
        },
        metadata={
            "summary": summary,
            "description": summary or text[:400],
            "tags": [
                "cypher",
                "csrd",
                "descriptor",
            ],
        },
        record_id=f"cypher_csrd_descriptor_{slug}",
    )


def import_csrd_descriptor_file(
    path: Path,
    *,
    content_service: ContentService,
    actor_user_id: str = "",
) -> dict[str, Any]:
    card = _load_json_object(path)
    record = _descriptor_record_from_csrd(card)
    record_id = str(record["id"])
    try:
        existing = content_service.get_record(record_id)
    except FileNotFoundError:
        return content_service.create_record(
            record,
            actor_user_id=actor_user_id,
            request_kind="system_import",
            provider_id="csrd",
        )

    updated = dict(record)
    updated["audit"] = dict(existing.get("audit") or {})
    updated["audit"]["updated_by"] = actor_user_id or "system_import"
    return content_service.update_record(
        record_id,
        updated,
        actor_user_id=actor_user_id,
        request_kind="system_import",
        provider_id="csrd",
    )


def import_csrd_descriptors(
    descriptors_dir: Path,
    *,
    content_service: ContentService,
    actor_user_id: str = "",
) -> list[dict[str, Any]]:
    if not descriptors_dir.exists() or not descriptors_dir.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(descriptors_dir.glob("*.json")):
        items.append(
            import_csrd_descriptor_file(
                path,
                content_service=content_service,
                actor_user_id=actor_user_id,
            )
        )
    return items


def import_csrd_descriptor_markdown_file(
    path: Path,
    *,
    content_service: ContentService,
    actor_user_id: str = "",
) -> list[dict[str, Any]]:
    markdown_text = load_markdown(path)
    imported: list[dict[str, Any]] = []
    for card in parse_descriptor_markdown(markdown_text):
        record = _descriptor_record_from_csrd(
            {
                "title": card["title"],
                "slug": card["slug"],
                "summary": card["summary"],
                "text": card["text"],
                "type": card["type"],
                "source": CSRD_SOURCE_LABEL,
            }
        )
        record["source"]["kind"] = "addon_pack"
        record["source"]["origin"] = "csrd_markdown"
        record["source"]["external_ref"] = str(path)
        record_id = str(record["id"])
        try:
            existing = content_service.get_record(record_id)
        except FileNotFoundError:
            imported.append(
                content_service.create_record(
                    record,
                    actor_user_id=actor_user_id,
                    request_kind="system_import",
                    provider_id="csrd_markdown",
                )
            )
            continue

        updated = dict(record)
        updated["audit"] = dict(existing.get("audit") or {})
        updated["audit"]["updated_by"] = actor_user_id or "system_import"
        imported.append(
            content_service.update_record(
                record_id,
                updated,
                actor_user_id=actor_user_id,
                request_kind="system_import",
                provider_id="csrd_markdown",
            )
        )
    return imported
