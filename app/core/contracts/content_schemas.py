from __future__ import annotations

from typing import Any

from .context import normalize_token

WORLD_MANIFEST_SCHEMA_VERSION = "1.0"
ALLOWED_MANIFEST_STATUS = {"planned", "proposed", "draft", "active", "deprecated", "archived"}

COMMON_MANIFEST_KEYS = {
    "schema_version",
    "id",
    "label",
    "kind",
    "status",
    "summary",
    "notes",
    "description",
    "details",
    "source_refs",
}

REGION_KINDS = {"top_level_region"}
SUBREGION_KINDS = {"subregion"}
SETTLEMENT_KINDS = {"settlement", "village", "city"}
INN_KINDS = {"inn"}

SETTLEMENT_DETAIL_KEYS = {"notable_inn", "economy", "culture"}
INN_DETAIL_KEYS = {"proprietor", "atmosphere", "clientele", "notable_feature", "rumor_or_hook"}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_detail_map(details: Any) -> dict[str, str]:
    if not isinstance(details, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in details.items():
        detail_key = normalize_token(key)
        if not detail_key:
            continue
        normalized[detail_key] = _normalize_text(value)
    return normalized


def _normalize_source_refs(source_refs: Any) -> list[str]:
    if isinstance(source_refs, str):
        source_refs = [source_refs]
    normalized: list[str] = []
    if isinstance(source_refs, (list, tuple, set)):
        for value in source_refs:
            text = _normalize_text(value)
            if text and text not in normalized:
                normalized.append(text)
    return normalized


def _build_manifest(
    *,
    manifest_id: Any,
    label: Any,
    kind: Any,
    status: Any = "draft",
    summary: Any = "",
    notes: Any = "",
    description: Any = "",
    details: Any = None,
    source_refs: Any = None,
) -> dict[str, Any]:
    return {
        "schema_version": WORLD_MANIFEST_SCHEMA_VERSION,
        "id": normalize_token(manifest_id),
        "label": _normalize_text(label),
        "kind": normalize_token(kind),
        "status": _normalize_text(status).lower() or "draft",
        "summary": _normalize_text(summary),
        "notes": _normalize_text(notes),
        "description": _normalize_text(description),
        "details": _normalize_detail_map(details),
        "source_refs": _normalize_source_refs(source_refs),
    }


def build_region_manifest(**kwargs: Any) -> dict[str, Any]:
    return _build_manifest(kind="top_level_region", **kwargs)


def build_subregion_manifest(**kwargs: Any) -> dict[str, Any]:
    return _build_manifest(kind="subregion", **kwargs)


def build_settlement_manifest(*, kind: Any = "village", **kwargs: Any) -> dict[str, Any]:
    return _build_manifest(kind=kind, **kwargs)


def build_inn_manifest(**kwargs: Any) -> dict[str, Any]:
    return _build_manifest(kind="inn", **kwargs)


def _validate_common_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")

    extra_keys = set(manifest.keys()) - COMMON_MANIFEST_KEYS
    if extra_keys:
        raise ValueError(f"unsupported manifest keys: {sorted(extra_keys)}")

    normalized = _build_manifest(
        manifest_id=manifest.get("id"),
        label=manifest.get("label"),
        kind=manifest.get("kind"),
        status=manifest.get("status"),
        summary=manifest.get("summary"),
        notes=manifest.get("notes"),
        description=manifest.get("description"),
        details=manifest.get("details"),
        source_refs=manifest.get("source_refs"),
    )

    if str(manifest.get("schema_version") or WORLD_MANIFEST_SCHEMA_VERSION) != WORLD_MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version '{manifest.get('schema_version')}'")
    if not normalized["id"]:
        raise ValueError("manifest.id is required")
    if not normalized["label"]:
        raise ValueError("manifest.label is required")
    if not normalized["kind"]:
        raise ValueError("manifest.kind is required")
    if normalized["status"] not in ALLOWED_MANIFEST_STATUS:
        raise ValueError(f"unsupported manifest.status '{normalized['status']}'")
    return normalized


def validate_region_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    normalized = _validate_common_manifest(manifest)
    if normalized["kind"] not in REGION_KINDS:
        raise ValueError(f"unsupported region kind '{normalized['kind']}'")
    return normalized


def validate_subregion_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    normalized = _validate_common_manifest(manifest)
    if normalized["kind"] not in SUBREGION_KINDS:
        raise ValueError(f"unsupported subregion kind '{normalized['kind']}'")
    return normalized


def validate_settlement_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    normalized = _validate_common_manifest(manifest)
    if normalized["kind"] not in SETTLEMENT_KINDS:
        raise ValueError(f"unsupported settlement kind '{normalized['kind']}'")
    extra_detail_keys = set(normalized["details"].keys()) - SETTLEMENT_DETAIL_KEYS
    if extra_detail_keys:
        raise ValueError(f"unsupported settlement detail keys: {sorted(extra_detail_keys)}")
    return normalized


def validate_inn_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    normalized = _validate_common_manifest(manifest)
    if normalized["kind"] not in INN_KINDS:
        raise ValueError(f"unsupported inn kind '{normalized['kind']}'")
    extra_detail_keys = set(normalized["details"].keys()) - INN_DETAIL_KEYS
    if extra_detail_keys:
        raise ValueError(f"unsupported inn detail keys: {sorted(extra_detail_keys)}")
    return normalized


def validate_authored_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    kind = normalize_token((manifest or {}).get("kind"))
    if kind in REGION_KINDS:
        return validate_region_manifest(manifest)
    if kind in SUBREGION_KINDS:
        return validate_subregion_manifest(manifest)
    if kind in SETTLEMENT_KINDS:
        return validate_settlement_manifest(manifest)
    if kind in INN_KINDS:
        return validate_inn_manifest(manifest)
    raise ValueError(f"unsupported authored manifest kind '{kind}'")
