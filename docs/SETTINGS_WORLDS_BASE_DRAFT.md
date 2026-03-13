# Draft: Core Genres + Settings Base Architecture

## Purpose
Define a stable base model for:
- Core genres (Cypher genre layer)
- Settings (world/sub-setting layer)
- Imports from world books (private, not synced)

This draft is intended to future-proof generation, search, and imports so every record can be filtered by genre/setting.

## Design Principles
- Every canonical record must have at least one `settings` tag.
- Prefer two-level tagging:
  - `genre` = primary genre token
  - `setting` = selected setting token
  - `settings` = full tag list (`genre` + optional `setting`)
- Setting data extends genre data, not replaces it.
- Imported book content stays private in `PDF_Repository/private_compendium`.
- UI filtering should work by:
  - genre only
  - setting only
  - both

## Canonical IDs
Use lowercase snake_case IDs everywhere.

Core genre baseline:
- `fantasy`
- `modern`
- `modern_magic`
- `cyberpunk`
- `science_fiction`
- `horror`
- `romance`
- `superheroes`
- `post_apocalyptic`
- `fairy_tale`
- `historical`
- `weird_west`

Example setting IDs:
- `lands_of_legends`
- `night_city_shards`
- `ashen_frontier`

## File/Folder Structure
Use this layering:

1. `config/core/*`
- Global reusable content (system-wide logic and generic roles)

2. `config/settings/<genre_id>/*`
- Genre-level defaults (styles, professions, NPC role tendencies, etc.)

3. `config/worlds/<setting_id>/*`
- Setting-specific overrides and content (areas, races, settlements, encounters, names, lore enrichment)

4. `config/02_settings.yaml`
- Registry linking genres to settings:
  - `genres.catalog.<genre_id>.settings: [...]`

## Minimum Files Per Genre
For each genre folder (`config/settings/<genre_id>/`):
- `00_setting.yaml` (genre identity and defaults)
- `01_styles.yaml`
- `11_professions.yaml`
- `13_npc_roles.yaml`
- `README.md` (scope + what belongs here)

## Minimum Files Per Setting
For each setting folder (`config/worlds/<setting_id>/`):
- `00_world.yaml` (setting identity + parent genre)
- `01_setting.yaml` (setting flavor overrides)
- `10_races.yaml`
- `12_areas.yaml`
- `20_settlements.yaml`
- `21_encounters.yaml`
- `22_cyphers.yaml`
- `24_names.yaml`
- `90_lore_enrichment.yaml`

## Required Metadata Rules (All Content Types)
Each generated/imported/saved record should include:
- `metadata.genre` (primary genre token)
- `metadata.setting` (selected setting token)
- `metadata.settings` (array, includes genre + optional setting)
- optional:
  - `metadata.area`
  - `metadata.location`
  - `metadata.sourcebook`
  - `metadata.pages`

Rule:
- If no explicit genre/setting is provided, attach configured defaults.

## World Book Import Workflow (Private)
1. Place PDF in `PDF_Repository/Genre_Books/` (genre books) or `PDF_Repository/Setting_Books/` (setting books).
2. Parse/extract into `PDF_Repository/private_compendium/`.
3. Assign:
  - `book` (sourcebook title)
  - `pages`
  - `settings` (genre + optional setting tags)
4. Reclassify noisy/mis-typed imports.
5. Rebuild private index.
6. Expose in unified search via source/compendium filters.

## Suggested Book-to-Genre Mapping (Initial)
- `Godforsaken` -> `fantasy`
- `Claim the Sky` -> `superheroes`
- `Stay Alive` -> `horror`
- `The Stars Are Fire` -> `science_fiction`
- `High Noon at Midnight` -> `weird_west`
- `Neon Rain` -> `cyberpunk`
- `Rust and Redemption` -> `post_apocalyptic`
- `We Are All Mad Here` -> `fairy_tale`
- `It’s Only Magic` -> `modern_magic` (or dual-tag with `fantasy` if desired)

## Bootstrap Checklist (Per New Genre + Setting)
1. Add genre folder and minimum files.
2. Register genre in `config/02_settings.yaml`.
3. Add one seed setting and link it under that genre.
4. Add at least:
  - 3 areas
  - 3 settlements
  - 10 races/variants or equivalent ancestry model
  - 20 cypher/artifact entries
5. Validate:
  - generation works
  - search filters by genre/setting
  - imports receive correct tags

## Acceptance Criteria
- All canonical categories are genre/setting-tagged.
- Setting dropdown appears only when settings exist for selected genre.
- Unified search can filter by genre/setting/sourcebook.
- Import pipeline preserves legal/private storage boundaries.
- New genre/setting can be added without code changes (config-only path).

## Next Implementation Steps
1. Add a small validator script: `scripts/validate_settings_worlds.py`.
2. Add one CLI scaffold command for new genre/setting.
3. Add an import mapping config file for sourcebook -> genre/setting tags.
4. Add a “Settings Health” section on index page (counts per genre/setting).
