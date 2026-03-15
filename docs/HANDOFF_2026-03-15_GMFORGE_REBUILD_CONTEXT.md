# GMForge Rebuild Handoff - 2026-03-15

This file is a restart-safe summary of the current rebuild state so work can continue on a new machine without losing context.

## Current Focus

The active rebuild focus is:

- `Cypher -> Godforsaken -> Land of Legends`
- canonical world/module structure
- central lore storage
- AI lore support
- vector retrieval
- AI-assisted generation
- canonical publishing into the new hierarchy

The user explicitly does **not** want the new build runtime to depend on legacy paths or legacy directories. Legacy content is migration input only.

## Key Rules We Agreed On

- New build reads new-build paths only.
- Legacy files are migration sources only and should be removable later.
- Rich lore should live centrally under the module `lore/` tree, not scattered beside every node.
- `gm_notes` and `adventure_hooks` belong to the future campaign layer, not the canonical module lore layer.
- AI providers should remain plugins in the new structure.
- Vector search should be one root-level system with metadata scoping, not separate isolated DBs per expansion/system.

## Canonical Content Layout

Main module:

- [`app/systems/cypher/addons/godforsaken/modules/land_of_legends/`](../app/systems/cypher/addons/godforsaken/modules/land_of_legends)

Important branches:

- `regions/`
- `peoples/`
- `creatures/`
- `items/`
- `system/`
- `lore/`

Removed:

- `magic_crafting/`

Moved:

- `cantrips`, `spells` -> `system/`
- `components`, `ingredients` -> `items/`

## Lore Storage Model

Canonical module lore is now central-first under:

- [`app/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/`](../app/systems/cypher/addons/godforsaken/modules/land_of_legends/lore)

Examples:

- `lore/overview.md`
- `lore/history.md`
- `lore/culture.md`
- `lore/religion.md`
- `lore/relationships.md`
- `lore/peoples/alfir/overview.md`
- `lore/regions/caldor_island/overview.md`

Canonical module lore file pattern:

- `overview.md`
- `history.md`
- `culture.md`
- `religion.md`
- `politics.md`
- `relationships.md`
- `secrets.md`

Only `overview.md` needs to exist everywhere. The rest are added where supported by imported lore.

Reference docs:

- [`docs/RICH_LORE_STORAGE.md`](./RICH_LORE_STORAGE.md)
- [`app/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/README.md`](../app/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/README.md)

## AI Lore Branch

AI lore is now a real visible branch in the new structure:

- [`app/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/ai_lore/`](../app/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/ai_lore)

Sub-branches currently in place:

- `overview.md`
- `art_prompts/`
- `drift_tests/`
- `doctrine/`
- `identity/`
- `race_triage/`

Examples already transferred:

- `doctrine/cosmology.md`
- `doctrine/xanthir.md`
- `identity/gorthim.md`
- `identity/gurthim.md`
- `drift_tests/cosmology_religion.md`
- `art_prompts/race_style_sheet.md`
- `race_triage/fellic_aspect_mapping.md`
- `race_triage/legacy_descriptor_notes.md`

## Legacy Lore Migration

Migration staging area:

- [`app/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/_migration_staging/`](../app/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/_migration_staging)

Key files:

- [`README.md`](../app/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/_migration_staging/README.md)
- [`INDEX.md`](../app/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/_migration_staging/INDEX.md)
- `legacy_entries/*.md`

Important migration note:

- We created a persistent in-repo staging area so no legacy lore is lost while being split into the new structure.
- Many legacy files needed to be broken up across canonical lore docs and AI lore docs.
- The migration is much further along than at the start of the day, but it is **not safe to assume every legacy lore fragment is perfectly fitted yet**.

What is true now:

- The central lore tree is populated enough to browse and retrieve meaningful context.
- Religion and creature branches were explicitly deepened after the user pointed out missing content.
- Some broad reference files are marked `mostly placed`, not `fully resolved`.

When resuming lore migration, start from:

- [`_migration_staging/INDEX.md`](../app/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/_migration_staging/INDEX.md)

## Module and World Modeling Status

### Peoples

Top-level peoples are in place, including:

- Alfir
- Human
- Uruk
- Small Folk
- Fellic
- Lhainim
- The Others

Subgroups exist and are browsable as first-class pages.

Race/people lore is attached in central lore.

### Regions

Top-level regions are in place, including:

- Caldor Island
- Fenmir Free Cities
- and the broader Land of Legends region set

Caldor Island was used as the first concrete nested geography slice.

Current nested pattern:

- region
- subregion
- village/city/settlement
- inn

Example path:

- `regions/caldor_island/subregions/the_vale/villages/mountain_home/inns/the_lucky_pick/manifest.json`

Important modeling rule:

- files live at the true canonical location
- top-level region browsing can aggregate nested content recursively
- do not duplicate village/lake/etc files at both top-level region and subregion level

### Creatures

Creature top-level groups exist:

- animals
- beasts
- monsters
- gurthim
- gorthim

The lore landing page was fixed to show these branches after the user flagged that only `daelgast` was visible.

## Web/UI Status

The Flask UI now supports:

- module landing page with top-level category boxes
- category landing pages
- people pages
- subgroup pages
- region pages
- subregion pages
- village/city/settlement pages
- inn pages
- lore landing pages and lore branch pages
- record workspace
- generator workspace

Key templates:

- [`app/web/templates/module.html`](../app/web/templates/module.html)
- [`app/web/templates/module_item.html`](../app/web/templates/module_item.html)
- [`app/web/templates/module_collection.html`](../app/web/templates/module_collection.html)
- [`app/web/templates/module_lore_document.html`](../app/web/templates/module_lore_document.html)
- [`app/web/templates/generate.html`](../app/web/templates/generate.html)

Important UI choices already made:

- breadcrumb trail is clickable
- title area uses a shared partial, not duplicated hero markup
- detail pages have a right-side square image placeholder
- module landing page is cleaner and category-box based
- category landing pages show linked tags for their subcategories

## Content Schemas

Canonical authored manifest schema support exists for:

- `top_level_region`
- `subregion`
- `settlement`
- `village`
- `city`
- `inn`

Primary contract files:

- [`app/core/contracts/content_schemas.py`](../app/core/contracts/content_schemas.py)
- [`app/core/contracts/lore_layout.py`](../app/core/contracts/lore_layout.py)

Load-time validation was wired so malformed authored manifests fail instead of silently rendering.

Known expected regression:

- a demo bad inn manifest intentionally contains unsupported detail keys like `reputation`
- tests log this on purpose

## Vector Database

The vector DB is implemented as a root-level scoped service, not separate per-system DBs.

Main files:

- [`app/core/search/vector_index.py`](../app/core/search/vector_index.py)
- [`scripts/build_vector_index.py`](../scripts/build_vector_index.py)

Storage:

- [`data/vector_index/vector_index.sqlite`](../data/vector_index/vector_index.sqlite)

Design:

- one root vector subsystem
- metadata scoping by ownership/context
- no runtime dependency on legacy app directories

The index includes new-structure content and also copied migration staging content under a separate source kind so it can be filtered.

API routes already exist:

- `GET /api/vector/stats`
- `GET /api/vector/query`
- `POST /api/vector/reindex`

## AI Provider Plugins

AI providers are plugins in the new structure:

- [`app/plugins/openai_remote/`](../app/plugins/openai_remote)
- [`app/plugins/ollama_local/`](../app/plugins/ollama_local)

Plugin loader:

- [`app/core/plugins/service.py`](../app/core/plugins/service.py)

Generation service:

- [`app/core/generation/service.py`](../app/core/generation/service.py)

Important runtime rule:

- do not read legacy plugin config/secrets at runtime
- new build secrets/config must live under new-build-owned locations

Current secret location:

- [`data/plugins/plugin_secrets.json`](../data/plugins/plugin_secrets.json)

This file is gitignored and replaced the accidental runtime tie to the old legacy config path.

## Generator Status

Generator UI:

- [`/workspace/generate`](../app/web/templates/generate.html)

What it does now:

- gathers scoped retrieval context from the vector DB
- uses plugin-loaded AI providers
- builds a generated draft
- can still create a saved draft record
- can now publish directly to canonical module structure for all currently schema-backed authored types

Canonical publish support now exists for:

- `top_level_region`
- `subregion`
- `settlement`
- `village`
- `city`
- `inn`

Publisher:

- [`app/core/generation/publisher.py`](../app/core/generation/publisher.py)

Important caveat:

- canonical publish targets are wired
- provider-generated output quality is still not fully type-shaped
- next improvement should be better structured draft shaping for `city`, `inn`, `subregion`, etc., not just better publish destinations

## Records

Record workspace and detail/edit flow exist:

- `/workspace/records`
- `/workspace/records/<id>`
- `/workspace/records/<id>/edit`

Templates:

- [`app/web/templates/records.html`](../app/web/templates/records.html)
- [`app/web/templates/record_detail.html`](../app/web/templates/record_detail.html)
- [`app/web/templates/record_edit.html`](../app/web/templates/record_edit.html)

Record create/update/delete triggers vector sync.

## Tests and Verification

Focused suites that were passing at handoff:

```bash
python -m unittest tests.core.test_generation_publisher tests.core.test_generation_service tests.core.test_web_app
```

Last result before handoff:

- `Ran 55 tests in 21.205s`
- `OK`

Known noisy output during tests:

- expected demo invalid-inn regression log
- some SQLite `ResourceWarning` noise

## Most Important Remaining Work

1. Continue fitting the remaining legacy lore fragments into the new canonical lore and AI lore structure.
2. Improve generator output shaping so each content type produces stronger canonical fields before publish.
3. Expand canonical publish flow beyond current authored types if/when more schemas are added.
4. Eventually remove runtime and content dependence on all remaining legacy directories once migration is complete.

## Good Resume Points

If starting fresh on the new machine, resume from one of these:

- lore migration:
  - [`app/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/_migration_staging/INDEX.md`](../app/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/_migration_staging/INDEX.md)
- generator/publish shaping:
  - [`app/core/generation/service.py`](../app/core/generation/service.py)
  - [`app/core/generation/publisher.py`](../app/core/generation/publisher.py)
  - [`app/web/templates/generate.html`](../app/web/templates/generate.html)
- vector retrieval:
  - [`app/core/search/vector_index.py`](../app/core/search/vector_index.py)
- AI provider plugins:
  - [`app/core/plugins/service.py`](../app/core/plugins/service.py)
  - [`app/plugins/openai_remote/`](../app/plugins/openai_remote)
  - [`app/plugins/ollama_local/`](../app/plugins/ollama_local)

## One-Line State Summary

The rebuild now has a real canonical world structure, central lore storage, AI lore branch, root-scoped vector retrieval, plugin-based AI providers, a working generator UI, and direct canonical publishing for all currently schema-backed authored world types, but lore fitting and generated output shaping still need another pass before legacy can be fully discarded.
