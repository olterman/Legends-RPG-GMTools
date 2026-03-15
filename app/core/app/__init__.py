"""Core app bootstrap package."""

from .system_loader import (
    ADDON_MANIFEST_FILENAME,
    CONTENT_TYPE_MANIFEST_FILENAME,
    SYSTEM_MANIFEST_FILENAME,
    discover_systems,
    validate_addon_manifest,
    validate_content_types_manifest,
    validate_system_manifest,
)

__all__ = [
    "ADDON_MANIFEST_FILENAME",
    "CONTENT_TYPE_MANIFEST_FILENAME",
    "SYSTEM_MANIFEST_FILENAME",
    "discover_systems",
    "validate_addon_manifest",
    "validate_content_types_manifest",
    "validate_system_manifest",
]
