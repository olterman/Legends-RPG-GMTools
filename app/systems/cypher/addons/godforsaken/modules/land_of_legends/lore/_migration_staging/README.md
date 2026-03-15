# Legacy Lore Migration Staging

This folder is the safety net for legacy `Land of Legends` lore migration.

## Purpose

Use this staging area to make sure no legacy lore is lost while we split large mixed documents into the new canonical structure.

Each staged file preserves:

- the legacy source file name
- title and excerpt
- categories and terms
- suggested destination paths in the new lore tree
- the full legacy markdown body

## Rules

- This folder is not canonical lore.
- Do not link the app directly to this folder.
- Promote reviewed content into the main `lore/` tree or `lore/ai_lore/` tree.
- Leave the staged source file in place until every useful fragment has been placed elsewhere.

## Layout

```text
_migration_staging/
  README.md
  INDEX.md
  legacy_entries/
    world_seed.md
    the_lilim.md
    the_fellic.md
    ...
```

## Promotion Workflow

1. Read the staged legacy entry.
2. Split the content into canonical lore files and, where appropriate, `ai_lore` working files.
3. Update the staged entry notes if the mapping becomes clearer.
4. Remove the staged file only when we are confident every useful piece has a home.
