# Product Roadmap

## Status Update (March 13, 2026)

### Recently Completed
- [x] Consolidated search direction: single primary Search experience retained; redundant browse paths deprecated/removed from active flow.
- [x] Source-aware card UX: consistent source badges, source color system, and normalized card actions across major search surfaces.
- [x] Trash lifecycle implemented end-to-end (delete, recover, expunge) with dedicated Trash Bin page.
- [x] FoundryVTT plugin foundation shipped (handshake + actor/item import paths) and treated as a first-class compendium source.
- [x] Foundry imports tagged as `FoundryVTT`, with compendium/source filter integration.
- [x] Docling plugin added and wired into plugin ecosystem.
- [x] Compendium index/landing architecture expanded (core rules, genres, settings groupings + compendium pages).
- [x] Vector index foundation added (semantic query path, chunking/index scripts, plugin wiring).
- [x] AI provider split added (`Ollama Local` + `OpenAI Remote`) with provider selection in AI generation flows.
- [x] Setting Wizard implemented and integrated with provider-based generation.

### In Progress
- [ ] High-quality official compendium parsing from Docling text into reliably typed canonical cards.
- [ ] Semantic/Ollama result UX polish (fully card-native semantic answers and output panel behavior).
- [ ] Foundry sync expansion to robust bulk/manual sync-all workflows with stronger conflict handling.

### Next Session Priority
1. Stabilize parser quality for official compendiums (especially NPC/creature classification).
2. Complete semantic/AI result presentation parity with normal search cards.
3. Continue Foundry sync hardening (manual sync-all flows + folder/setting targeting).

## Completed This Week
- Implemented global source badges/colors (`CSRD` and `House`) in search flows.
- Added edit/delete + trash/recover/expunge lifecycle for Unified Search and Local Library.
- Added edit/delete + trash/recover/expunge lifecycle for Lore Browser.
- Added dedicated Trash Bin page and navigation entry.
- Added structured editors with inline JSON validation hints.
- Migrated lore category labeling from `environment` to `area`.
- Added storage and lore schema versioning (`schema_version: 1.0`) for new writes.
- Added automated smoke tests for filtering, trash lifecycle, and lore index consistency.

## Small Tweaks
- [x] Search result cards: render image thumbnails under the type label.
- [x] Uploaded images: auto-resize to web-safe dimensions and support click-to-open full-size popup preview.
- [x] Upload defaults: auto-set image `friendly_name` from attached entity name and auto-tag with `area`, `genre`, and selected `setting`.
- [x] Standardize canonical `description` support across core entity types and all result cards.
- [x] Keep compact card action icons (edit/trash) anchored in the lower-right corner for consistency.
- [x] Evaluate consolidating Library, Lore, CSRD, and Unified search into one search experience (now adopted as primary direction).
- [ ] Semantic search UX follow-up: add a one-click “Use Snippet in Prompt/Generator Context” action for selected vector hits.
- [ ] Semantic retrieval ranking tweak: prioritize readable narrative/rules chunks by default while still keeping TOC/index chunks available for page-number lookup queries.
- [ ] Foundry bridge UX tweak: show the current GMTools sync target setting near Foundry sheet sync actions/tooltips for quick visibility.
- [ ] Foundry media sync follow-up: support optional GMTools image upsync back to Foundry when local images are added/replaced (deferred).
- [ ] AI Generate UX tweak: add one-click type-based source presets (recommended compendium/source checkbox defaults per type like `encounter`, `npc`, `cypher`, etc.).
- [ ] Setting Wizard hardening: strict YAML output contracts and schema validation on generated setting bundles.
- [ ] Compendium parsing refinement: preserve page anchors while removing low-value image-only chunk noise from retrieval ranking.

## Current Focus (March 13, 2026)
- Reference execution roadmap: `docs/SPRINT_MOBILE_CAMPAIGN_GENERATION_ROADMAP.md`
- Prioritize three parallel tracks:
  - Mobile-first UI behavior and layout fixes.
  - Campaign Mode (GM overview for scenes, actors, and dice).
  - Data-driven generation (prefer local indexed/storage data over hardcoded YAML-only inputs).
- Track account/auth requirements in parallel:
  - login flow and session handling
  - GM vs Player roles and permission boundaries
- Start with mobile fixes first to unblock daily usability, then ship Campaign Mode MVP, then complete generation data-provider migration.
- Require each track to ship with:
  - smoke-test notes
  - schema/storage impact notes
  - rollback notes

## Near Term (0-6 weeks)

### 1) Genre and Setting Data Model (Top Priority)
- Reference draft plan: `docs/SETTINGS_WORLDS_BASE_DRAFT.md`
- Enforce genre-aware tagging across all content types: character, lore, cypher/artifact, ability, skill, focus, settlement, encounter, map data.
- Keep support for multi-tag records (`settings` list).
- Ensure search, browse, and generation all honor active `genre/setting` context consistently.
- Establish baseline core genres:
  - Fantasy
  - Modern
  - Modern Magic
  - Cyberpunk
  - Science Fiction
  - Horror
  - Romance
  - Superheroes
  - Post-Apocalyptic
  - Fairy Tale
  - Historical
  - Weird West
- Done when:
  - All generated and saved content includes valid genre/setting metadata.
  - Setting/core genre selection consistently filters generation and search endpoints.
  - Config and storage use `area` as canonical geography key (`environment` remains alias-only).

### Genre/Setting Implementation Checklist
#### Phase A: Registry and Validation
- [ ] Add `scripts/validate_settings_worlds.py`.
- [ ] Validate `config/02_settings.yaml` IDs and referential integrity.
- [ ] Validate every setting in `config/worlds/*/00_world.yaml` has a parent genre.
- [ ] Validate every setting folder has required minimum files.
- [ ] Fail CI/local smoke checks on invalid genre/setting references.

#### Phase B: Canonical Metadata Enforcement
- [ ] Enforce `metadata.setting` and `metadata.settings` for all canonical categories on save/update.
- [ ] Enforce `metadata.genre` alongside `metadata.setting` (with backward-compatible aliases).
- [ ] Ensure parser/generator/import flows write `area` as canonical key and keep `environment` as alias.
- [ ] Backfill missing genre/setting tags for existing local records via migration script.
- [ ] Add migration report output: scanned/updated/skipped/error counts.

#### Phase C: Search and Filtering
- [ ] Make genre/setting filter behavior consistent in unified search, lore, and imported content.
- [ ] Add sourcebook/page-aware filtering hooks for imported records.
- [ ] Ensure compendium filters and genre/setting filters compose correctly.
- [ ] Add smoke tests for combined filters (`genre + setting + source + type`).

#### Phase D: Import Mapping From World Books
- [ ] Add import mapping file (`config/import_map.yaml`) for `sourcebook -> genre/setting tags`.
- [ ] Apply mapping automatically in official importer and raw-text parser.
- [ ] Preserve `sourcebook` and `pages` in metadata and show badges in results.
- [ ] Add reclassification/audit pass after import and rebuild index automatically.

#### Phase E: Bootstrap Scaffolding
- [ ] Add scaffold command for new genre and setting folder templates.
- [ ] Generate starter files with placeholders for styles/professions/areas/races/cyphers.
- [ ] Auto-register new genre/setting in `config/02_settings.yaml`.
- [ ] Add docs page for “create genre/setting in < 10 minutes”.

#### Phase F: UX and Observability
- [ ] Add a “Settings Health” panel on index page with counts per genre/setting.
- [ ] Add “untagged items” warning badge when metadata is missing.
- [ ] Add quick fix actions for missing `genre/setting` tags.
- [ ] Add weekly integrity report command for genre/setting coverage.

### 2) Content Management UX
- Finalize edit/delete/recover/expunge across:
  - Unified Search
  - Local Library
  - Lore Browser
- Add lightweight field validation and clearer save error messaging.
- Add audit metadata to edits (`updated_at`, `updated_by` placeholder) for safer collaboration.
- Done when:
  - All local content surfaces support edit/delete with recover/expunge.
  - Invalid JSON/structured field errors are shown inline before save.
  - Edit operations persist deterministic, readable records with version metadata.

### 3) Information Architecture
- Expand landing page into a usable table of contents:
  - Core generators
  - Search/browse tools
  - Compendium/rules/lore entry points
  - “How to use” quick-start
- Add references/links to official material in context (inspired by Old Gus-style discoverability).
- Done when:
  - Landing page provides clear start paths for generation, search, lore, and compendium.
  - Key pages are reachable in <= 2 clicks from Home.
  - Official references are visible and easy to open.

### 4) Rules and Compendium Quality
- Skill compendium refinement:
  - Canonicalize near-duplicate skills.
  - Preserve source evidence.
  - Rebuild and verify Character Studio skill selection.
- Tag rule text with source/version (`csrd`, `house`, revision id).
- Done when:
  - Skill canonicalization eliminates known near-duplicates.
  - Character Studio references canonical skill labels only.
  - Rule entries expose source/version metadata in API and UI.

### UI Tweaks 
- for all the charachters/npcs/cyphers/artifacts/locations/ and equipment categories I want the search results (in all searches to have a fourth icon "copy art prompt" that puts together an ai art prompt (optimised for atomic pro) the prompt should contain description, area prompt (named environment in the prompt) props and weapons (attacks?)  and the legend style prompt picking the correct style prompt depending on type ie. character for character item for cyphers etc


## Mid Term (2-4 months)

### 1) Character Studio v2
- Optional second descriptor (for ancestry/race model).
- Equipment selection during creation.
- Profession pipelines by genre/type/flavor.
- Export character sheets to fillable PDF.
- Done when:
  - Character creation includes optional second descriptor and equipment flow.
  - Profession choices are genre-aware and type/flavor-aware.
  - Fillable PDF export works for current sheet state.

### 2) Cypher/Artifact Domain Split
- Promote artifact as first-class type.
- Rule: depletion-based items classify as artifact.
- Separate generation/search filters and storage views for cyphers vs artifacts.
- Done when:
  - Artifact type is first-class in API, storage, and UI filters.
  - Depletion-based classification rule is enforced and test-covered.

### 3) Equipment and Item Expansion
- Add baseline fantasy equipment set.
- Introduce genre-aware item packs (not fantasy-only assumptions).
- Done when:
  - Baseline fantasy equipment is complete and searchable.
  - Additional genre packs can be added without schema changes.

### 4) PDF and Rulebook Navigation
- Add official PDF repository integration.
- Support deep links/bookmarks into official PDFs from compendium/rules pages.
- Done when:
  - PDF library is browseable and linkable by anchor/bookmark.
  - Relevant compendium/rule entries include PDF deep links where available.

### 5) Lore and Markdown Pipeline
- Improve markdown parsing and section extraction reliability.
- Add preview, diff-style review, and safe re-ingest workflow for lore rebuilds.
- Done when:
  - Lore import supports preview and validation before write.
  - Re-ingest preserves stable slugs and updates index safely.
  - Markdown parsing handles common Logseq block patterns reliably.

### 6) Vector Knowledge Index
- Reference roadmap: `docs/VECTOR_DATABASE_WORLD_FILES_ROADMAP.md`
- Build a local vector database pipeline from world/config/lore files.
- Support semantic retrieval filtered by genre, setting, type, area, and source.
- Integrate semantic retrieval into search and generation context workflows.
- Progress:
  - [x] Initial vector build/query flow implemented.
  - [x] Semantic query path available in Search.
  - [ ] Retrieval relevance/formatting polish and card-native rendering still in progress.
- Done when:
  - Index build is incremental and deterministic.
  - Query endpoint returns cited chunks with source metadata.
  - Semantic search is available in UI and usable for content generation context.

## Future (4+ months)

### 1) Setting Creation Wizard
- Guided creation of new setting profiles under core genres.
- Bootstrap config files, default prompts, and starter lore taxonomy.
- Validation checks to prevent broken setting setups.
- Done when:
  - New setting creation is wizard-driven and produces valid config bundles.
  - New setting is immediately selectable in UI without manual file edits.

### 2) Media and Map Layer
- Attach images to cyphers, artifacts, locations, NPCs, and characters.
- World-aware prompt generation for visual style consistency.
- Map tools with pins tied to locations/areas and searchable entities.
- Done when:
  - Entities support media attachment with clear source attribution.
  - Maps can persist location pins linked to searchable records.

### 3) AI Connectors
- Optional one-click image generation actions from relevant cards.
- Queue/history/retry model for generation jobs.
- Automatic AI image scan adding friendly name - alt description 
- Done when:
  - Users can trigger image generation from eligible cards.
  - Generation jobs are traceable with status, retry, and result history.

### 4) Foundry VTT Integration
- Prioritize Foundry -> GMTools sync before GMTools -> Foundry export.
- Phase 1: inbound sync for PCs, NPCs, creatures, items, scenes, and journal-driven lore.
- Phase 2: outbound export from GMTools into Foundry for characters, NPCs/creatures, and selected items.
- Maintain a stable schema contract and migration strategy between tool and module versions.
- Done when:
  - Foundry -> GMTools sync covers core actor/content types without manual transformations.
  - GMTools -> Foundry export is implemented as a later, explicit workflow after inbound sync is stable.
  - Version negotiation and migration path are documented and tested.

### Foundry VTT Integration Checklist
#### Phase A: Foundry -> GMTools Sync First
- [ ] Bulk sync actors from Foundry into GMTools (PCs, NPCs, creatures).
- [ ] Add bulk item sync for cyphers, artifacts, attacks, equipment, abilities, and skills.
- [ ] Add scene sync into GMTools location/area-aware records.
- [ ] Add journal entry sync into GMTools lore records.
- [ ] Add sync status markers (`synced from FoundryVTT`) consistently across result cards and detail views.
- [ ] Add duplicate/conflict handling for repeated syncs.

#### Phase B: Stabilize the Bridge
- [ ] Define versioned payload contracts for actors, items, scenes, and journals.
- [ ] Add migration handling for older Foundry-imported records.
- [ ] Add per-sync reporting: created, updated, skipped, failed.
- [ ] Add smoke tests for Foundry actor/item import paths.

#### Phase C: GMTools -> Foundry Export Later
- [ ] Export `character_sheet` to Foundry PC actor.
- [ ] Export `npc` and `creature` to Foundry NPC actor.
- [ ] Export selected item types (cypher, artifact, attack, equipment) to Foundry items.
- [ ] Add create-vs-update flow for exports targeting existing Foundry entities.
- [ ] Add safe round-trip metadata/backlinks before enabling true two-way sync.

## Suggestions (Execution)
- Keep this roadmap updated weekly from merged work, not planned work.
- Require new major features to include:
  - schema/version impact note
  - smoke-test impact note
  - rollback strategy note
