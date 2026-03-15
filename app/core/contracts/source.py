from __future__ import annotations

from typing import Any

ALLOWED_SOURCE_KINDS = {
    "local",
    "imported",
    "generated",
    "system_pack",
    "addon_pack",
    "plugin_sync",
}


def build_source(
    *,
    kind: Any = "local",
    origin: Any = "user",
    sourcebook: Any = "",
    pages: Any = None,
    external_ref: Any = "",
) -> dict[str, Any]:
    normalized_kind = str(kind or "local").strip().lower() or "local"
    normalized_origin = str(origin or "user").strip() or "user"
    page_values: list[str] = []
    raw_pages = pages or []
    if isinstance(raw_pages, str):
        raw_pages = [part.strip() for part in raw_pages.split(",") if part.strip()]
    if isinstance(raw_pages, (list, tuple, set)):
        for value in raw_pages:
            text = str(value or "").strip()
            if text and text not in page_values:
                page_values.append(text)
    return {
        "kind": normalized_kind,
        "origin": normalized_origin,
        "sourcebook": str(sourcebook or "").strip(),
        "pages": page_values,
        "external_ref": str(external_ref or "").strip(),
    }


def validate_source(source: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise ValueError("source must be an object")
    normalized = build_source(
        kind=source.get("kind"),
        origin=source.get("origin"),
        sourcebook=source.get("sourcebook"),
        pages=source.get("pages"),
        external_ref=source.get("external_ref"),
    )
    if normalized["kind"] not in ALLOWED_SOURCE_KINDS:
        raise ValueError(f"unsupported source.kind '{normalized['kind']}'")
    if not normalized["origin"]:
        raise ValueError("source.origin is required")
    return normalized
