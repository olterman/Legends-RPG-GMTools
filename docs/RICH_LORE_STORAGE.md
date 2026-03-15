# Rich Lore Storage

`GMForge` keeps structural manifests distributed with the world nodes, but keeps rich prose in a **central module lore repository**.

## Split Of Responsibility

- `manifest.json`
  - stable structural metadata
  - identity, hierarchy, and canonical fields
  - generator and migration friendly
- `modules/<module>/lore/...`
  - canonical authored lore
  - reusable setting truth
  - rendered alongside manifests in the app
- `modules/<module>/lore/ai_lore/...`
  - AI-generated or AI-assisted lore drafts
  - mirrored to the same world hierarchy
  - separate from canonical approved lore

## Central Folder Pattern

```text
<module>/
  lore/
    README.md
    overview.md
    history.md
    culture.md
    religion.md
    politics.md
    relationships.md
    secrets.md

    peoples/
      alfir/
        overview.md
        subgroups/
          kalaquendi/
            overview.md

    regions/
      caldor_island/
        overview.md
        subregions/
          the_vale/
            overview.md
            villages/
              mountain_home/
                overview.md
                inns/
                  the_lucky_pick/
                    overview.md

    ai_lore/
      README.md
      peoples/
      regions/
      creatures/
      items/
      magic_crafting/
      system/
```

## Canonical Module Lore File Order

1. `overview.md`
2. `history.md`
3. `culture.md`
4. `religion.md`
5. `politics.md`
6. `relationships.md`
7. `secrets.md`

## Campaign Lore File Order

Campaign-local lore does **not** live in the module lore repository.

1. `overview.md`
2. `gm_notes.md`
3. `adventure_hooks.md`
4. `session_notes.md`
5. `reveals.md`
6. `changes.md`

## Authoring Rule

- Keep structural truth in `manifest.json`
- Keep canonical reusable prose in the module's central `lore/`
- Keep AI output in `lore/ai_lore/`
- Keep campaign prep and play-state lore in the campaign layer
- `gm_notes.md` and `adventure_hooks.md` are campaign files, not module files
- `secrets.md` is valid in canonical module lore when the hidden truth belongs to the setting itself

## Why

This avoids two bad outcomes:

- sprawling prose embedded into every manifest
- lore spread across hundreds of tiny sibling folders during content generation

The manifest defines what a node is.
The central lore repository defines what it means.
