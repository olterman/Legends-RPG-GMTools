from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .context import NONE_SYSTEM_ID, build_context, validate_context
from .ids import new_record_id
from .source import build_source, validate_source

RECORD_SCHEMA_VERSION = "1.0"
ALLOWED_VISIBILITY = {"private", "shared", "public"}
ALLOWED_STATUS = {"active", "draft", "archived", "trashed"}
ALLOWED_TOP_LEVEL_KEYS = {
    "schema_version",
    "record_version",
    "id",
    "type",
    "title",
    "slug",
    "system",
    "context",
    "source",
    "content",
    "metadata",
    "audit",
    "links",
    "extensions",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_slug(value: Any) -> str:
    from .context import normalize_token

    return normalize_token(value)


def build_system_ref(*, system_id: Any = NONE_SYSTEM_ID, addon_id: Any = "") -> dict[str, str]:
    from .context import normalize_token

    return {
        "id": normalize_token(system_id) or NONE_SYSTEM_ID,
        "addon_id": normalize_token(addon_id),
    }


def build_metadata(
    *,
    tags: Any = None,
    summary: Any = "",
    description: Any = "",
    area_id: Any = "",
    location_id: Any = "",
    visibility: Any = "private",
    status: Any = "active",
    images: Any = None,
) -> dict[str, Any]:
    clean_tags: list[str] = []
    raw_tags = tags or []
    if isinstance(raw_tags, str):
        raw_tags = [part.strip() for part in raw_tags.split(",") if part.strip()]
    if isinstance(raw_tags, (list, tuple, set)):
        for value in raw_tags:
            text = str(value or "").strip()
            if text and text not in clean_tags:
                clean_tags.append(text)

    clean_images: list[str] = []
    raw_images = images or []
    if isinstance(raw_images, str):
        raw_images = [raw_images]
    if isinstance(raw_images, (list, tuple, set)):
        for value in raw_images:
            text = str(value or "").strip()
            if text and text not in clean_images:
                clean_images.append(text)

    normalized_visibility = str(visibility or "private").strip().lower() or "private"
    normalized_status = str(status or "active").strip().lower() or "active"

    return {
        "tags": clean_tags,
        "summary": str(summary or "").strip(),
        "description": str(description or "").strip(),
        "area_id": normalize_slug(area_id),
        "location_id": normalize_slug(location_id),
        "visibility": normalized_visibility,
        "status": normalized_status,
        "images": clean_images,
    }


def build_audit(
    *,
    created_at: Any = None,
    updated_at: Any = None,
    created_by: Any = "local_user",
    updated_by: Any = "local_user",
) -> dict[str, str]:
    created = str(created_at or utc_now_iso()).strip()
    updated = str(updated_at or created).strip()
    return {
        "created_at": created,
        "updated_at": updated,
        "created_by": str(created_by or "local_user").strip() or "local_user",
        "updated_by": str(updated_by or "local_user").strip() or "local_user",
    }


def build_record(
    *,
    record_type: Any,
    title: Any,
    slug: Any = "",
    system_id: Any = NONE_SYSTEM_ID,
    addon_id: Any = "",
    setting_id: Any = "",
    campaign_id: Any = "",
    source: dict[str, Any] | None = None,
    content: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
    links: list[dict[str, Any]] | None = None,
    extensions: dict[str, Any] | None = None,
    record_id: Any = "",
    record_version: int = 1,
) -> dict[str, Any]:
    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "record_version": int(record_version or 1),
        "id": str(record_id or new_record_id()).strip(),
        "type": str(record_type or "").strip(),
        "title": str(title or "").strip(),
        "slug": normalize_slug(slug),
        "system": build_system_ref(system_id=system_id, addon_id=addon_id),
        "context": build_context(
            system_id=system_id,
            setting_id=setting_id,
            campaign_id=campaign_id,
        ),
        "source": build_source(**(source or {})),
        "content": dict(content or {}),
        "metadata": build_metadata(**(metadata or {})),
        "audit": build_audit(**(audit or {})),
        "links": list(links or []),
        "extensions": dict(extensions or {}),
    }


def validate_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("record must be an object")

    extra_keys = set(record.keys()) - ALLOWED_TOP_LEVEL_KEYS
    if extra_keys:
        raise ValueError(f"unsupported top-level record keys: {sorted(extra_keys)}")

    normalized = build_record(
        record_type=record.get("type"),
        title=record.get("title"),
        slug=record.get("slug"),
        system_id=((record.get("system") or {}) if isinstance(record.get("system"), dict) else {}).get("id"),
        addon_id=((record.get("system") or {}) if isinstance(record.get("system"), dict) else {}).get("addon_id"),
        setting_id=((record.get("context") or {}) if isinstance(record.get("context"), dict) else {}).get("setting_id"),
        campaign_id=((record.get("context") or {}) if isinstance(record.get("context"), dict) else {}).get("campaign_id"),
        source=record.get("source") if isinstance(record.get("source"), dict) else {},
        content=record.get("content") if isinstance(record.get("content"), dict) else {},
        metadata=record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
        audit=record.get("audit") if isinstance(record.get("audit"), dict) else {},
        links=record.get("links") if isinstance(record.get("links"), list) else [],
        extensions=record.get("extensions") if isinstance(record.get("extensions"), dict) else {},
        record_id=record.get("id"),
        record_version=int(record.get("record_version") or 1),
    )

    if str(record.get("schema_version") or RECORD_SCHEMA_VERSION) != RECORD_SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version '{record.get('schema_version')}'")
    if not normalized["id"]:
        raise ValueError("record.id is required")
    if not normalized["type"]:
        raise ValueError("record.type is required")
    if not normalized["title"]:
        raise ValueError("record.title is required")

    normalized["context"] = validate_context(normalized["context"])
    normalized["source"] = validate_source(normalized["source"])

    if normalized["metadata"]["visibility"] not in ALLOWED_VISIBILITY:
        raise ValueError(f"unsupported metadata.visibility '{normalized['metadata']['visibility']}'")
    if normalized["metadata"]["status"] not in ALLOWED_STATUS:
        raise ValueError(f"unsupported metadata.status '{normalized['metadata']['status']}'")

    return normalized


def summarize_record(record: dict[str, Any]) -> dict[str, Any]:
    validated = validate_record(record)
    return {
        "id": validated["id"],
        "type": validated["type"],
        "title": validated["title"],
        "system_id": validated["context"]["system_id"],
        "addon_id": validated["system"]["addon_id"],
        "setting_id": validated["context"]["setting_id"],
        "campaign_id": validated["context"]["campaign_id"],
        "status": validated["metadata"]["status"],
        "summary": validated["metadata"]["summary"],
        "tags": list(validated["metadata"]["tags"]),
        "updated_at": validated["audit"]["updated_at"],
    }
