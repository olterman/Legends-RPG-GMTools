from __future__ import annotations

MODULE_LORE_FILE_ORDER = [
    "overview.md",
    "history.md",
    "culture.md",
    "religion.md",
    "politics.md",
    "relationships.md",
    "secrets.md",
]

CAMPAIGN_LORE_FILE_ORDER = [
    "overview.md",
    "gm_notes.md",
    "adventure_hooks.md",
    "session_notes.md",
    "reveals.md",
    "changes.md",
]

MODULE_LORE_FILENAMES = tuple(MODULE_LORE_FILE_ORDER)
CAMPAIGN_LORE_FILENAMES = tuple(CAMPAIGN_LORE_FILE_ORDER)


def lore_sort_key(filename: str) -> tuple[int, str]:
    normalized = str(filename or "").strip().lower()
    try:
        return (MODULE_LORE_FILE_ORDER.index(normalized), normalized)
    except ValueError:
        return (len(MODULE_LORE_FILE_ORDER), normalized)
