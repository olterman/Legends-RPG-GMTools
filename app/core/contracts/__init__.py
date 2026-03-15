"""Core contracts package."""

from .context import NONE_SYSTEM_ID, build_context, normalize_token, validate_context
from .content_schemas import (
    ALLOWED_MANIFEST_STATUS,
    build_inn_manifest,
    build_region_manifest,
    build_settlement_manifest,
    build_subregion_manifest,
    validate_authored_manifest,
    validate_inn_manifest,
    validate_region_manifest,
    validate_settlement_manifest,
    validate_subregion_manifest,
)
from .lore_layout import (
    CAMPAIGN_LORE_FILENAMES,
    CAMPAIGN_LORE_FILE_ORDER,
    MODULE_LORE_FILENAMES,
    MODULE_LORE_FILE_ORDER,
    lore_sort_key,
)
from .records import build_record, summarize_record, validate_record
from .source import ALLOWED_SOURCE_KINDS, build_source, validate_source

__all__ = [
    "ALLOWED_MANIFEST_STATUS",
    "ALLOWED_SOURCE_KINDS",
    "CAMPAIGN_LORE_FILENAMES",
    "CAMPAIGN_LORE_FILE_ORDER",
    "MODULE_LORE_FILENAMES",
    "MODULE_LORE_FILE_ORDER",
    "NONE_SYSTEM_ID",
    "build_context",
    "build_inn_manifest",
    "build_record",
    "build_region_manifest",
    "build_settlement_manifest",
    "build_source",
    "build_subregion_manifest",
    "normalize_token",
    "lore_sort_key",
    "summarize_record",
    "validate_authored_manifest",
    "validate_context",
    "validate_inn_manifest",
    "validate_record",
    "validate_region_manifest",
    "validate_settlement_manifest",
    "validate_subregion_manifest",
    "validate_source",
]
