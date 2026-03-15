# Rebuild Feature Inventory

## Purpose
This document inventories the current legacy app feature set and assigns each feature a likely destination in the rebuild.

It is a planning artifact only. It does not approve implementation details by itself.

## Source Review Basis
This inventory is based on the current monolith structure, especially:
- `lol_api/api.py`
- `lol_api/app.py`
- `lol_api/storage.py`
- `lol_api/config_loader.py`
- `lol_api/generator.py`
- `lol_api/lore.py`
- `lol_api/compendium.py`
- `lol_api/official_compendium.py`
- `lol_api/prompts.py`
- `lol_api/settings.py`
- `lol_api/config_enrichment.py`
- `Plugins/foundryVTT/*`
- `Plugins/docling/*`

## Classification Key
- `core`
- `system`
- `system-addon`
- `plugin`
- `setting-content`
- `campaign-content`
- `retire-or-rethink`

## Quick Summary

### Likely Core
- app bootstrap and runtime configuration
- auth, sessions, and roles
- plugin discovery and enable/disable state
- audit logging and event history
- storage and trash lifecycle
- generic metadata and taxonomy context
- tag and backlink graph
- generic search shell
- generic document/image browser shell
- generic content CRUD
- map project persistence
- campaign management

### Likely System
- Cypher character, NPC, creature, cypher, artifact, encounter, inn, and settlement generation rules
- Cypher stat blocks
- Cypher character sheet structure
- Cypher compendium semantics
- Cypher roller behavior

### Likely System Addon
- CSRD content pack
- official rulebook and supplement content packs
- sourcebook-specific parsing and tagging rules

### Likely Plugins
- FoundryVTT sync and conversion
- OpenAI remote provider
- Ollama local provider
- Docling/vector index
- PDF import pipeline

### Likely Setting or Campaign Content
- Land of Legends data files
- lore entries
- area/settlement/race/profession/world flavor content
- campaign-specific maps and saved play assets

## Inventory Matrix

| Feature Area | Current Source | What It Does Today | Likely Classification | Target Destination | Genericizable? | Current Coupling Risk | Migration Priority | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| App bootstrap | `lol_api/app.py` | Creates Flask app, loads config, binds paths, registers routes | core | `core/app` | yes | medium | high | Current startup assumes one monolith and one active setting |
| Route monolith | `lol_api/api.py` | Hosts nearly all UI, API, plugin, compendium, image, map, and generation routes | retire-or-rethink | split across `core`, `systems`, and `plugins` | partial | very high | high | This file is the main decomposition target |
| Plugin discovery | `lol_api/api.py` helper logic | Discovers plugins from `Plugins/` and reads plugin metadata | core | `core/plugins` | yes | low | high | Good candidate for early extraction |
| Auth and roles | mostly absent or implicit in legacy app | Login, session handling, GM/player boundaries, ownership, and permissions | core | `core/auth` | yes | high | high | Must become first-class rather than retrofitted later |
| Audit logging | mostly absent as a structured platform service | Logs create/update/delete/sync/generate operations with recovery context | core | `core/audit` | yes | high | high | Should capture system calls and AI prompt metadata where relevant |
| Database and migrations | mostly absent as a formal platform layer | Persistent relational state and schema upgrade path | core | `core/database` | yes | high | high | Needed for auth, audit, and long-term platform stability |
| Tag and backlink graph | currently fragmented across tags/search metadata | Clickable tags, system-wide tag search, backlinks, and tag directories | core | `core/graph` | yes | high | high | Should be a first-class relationship layer |
| Plugin state/settings UI | `lol_api/api.py`, `plugin_settings.html` | Enables/disables plugins and stores plugin settings | core | `core/plugins` | yes | low | high | Keep generic; plugin-specific fields exposed by contract |
| Storage layer | `lol_api/storage.py` | Saves, lists, loads, updates, searches, trashes, restores, expunges records | core | `core/storage` | yes | medium | high | Strong foundation, but record shape is still legacy-flavored |
| Trash lifecycle | `lol_api/storage.py`, `trash.html` | Soft delete and recovery for stored records | core | `core/storage` | yes | low | high | Preserve as baseline platform feature |
| Config loader | `lol_api/config_loader.py` | Loads layered config from core/settings/worlds folders | core | `core/config` | yes | medium | high | Needs generalization from current setting/world terminology |
| Settings taxonomy | `lol_api/settings.py` | Builds settings catalog, defaults, metadata attachment, nav model | core | `core/context` | yes | medium | high | Evolve into a context model centered on `system -> setting -> campaign`, with `genre` as supporting taxonomy |
| Campaign management | legacy behavior is implicit across storage/config/maps rather than first-class | Holds playable campaign state under a chosen system and setting | core | `core/campaigns` | yes | high | high | Must become explicit and first-class in the rebuild |
| Generic search shell | `lol_api/api.py`, `search.html` | Unified browsing across storage, lore, compendium, prompts, plugins | core | `core/search` | yes | high | high | Keep shell generic; source-specific providers plug in |
| Docs browser | `lol_api/api.py`, `docs_browser.html` | Reads and displays project docs and text/JSON/YAML files | core | `core/docs` | yes | low | medium | Useful, but should stay clearly separated from gameplay features |
| Image browser and attachments | `lol_api/api.py`, `image_browser.html` | Uploads images, attaches/detaches them from storage and lore records | core | `core/assets` | yes | medium | medium | Good platform feature if entity-agnostic |
| Map project persistence | `lol_api/api.py`, `map_editor.html`, `maps/projects/*` | Stores editable map projects with markers and areas | campaign-content | `content/.../campaign/...` with core service support | partial | medium | medium | Persistence is generic; map semantics belong closer to campaign layer |
| Lore index and CRUD | `lol_api/lore.py`, `ai_lore_browser.html` | Loads, searches, updates, trashes, and restores lore items | core | `core/content` | yes | medium | high | Keep CRUD generic; derived AI lore should be separated |
| AI-derived lore synthesis | `lol_api/lore.py` | Builds inferred lore views for race, area, doctrine, profession, creature categories | setting-content | `content/<system>/<genre>/<setting>` plus optional services | partial | high | medium | Current implementation mixes content derivation with Cypher/Lands-specific assumptions |
| Prompt library | `lol_api/prompts.py` | Loads, searches, updates, and trashes prompt items | plugin | `plugins/ai-prompts` or `core/prompts` if kept minimal | yes | low | medium | Decide whether prompts are platform capability or AI plugin concern |
| Config enrichment review | `lol_api/config_enrichment.py`, `config_enrichment.html` | Reviews generated YAML candidates and writes config enrichment files | plugin | `plugins/content-enrichment` | partial | medium | low | Optional editorial tooling, not core runtime |
| Generator pipeline shell | `lol_api/api.py` + `lol_api/generator.py` | Handles generation requests and persistence | split: core + system | `core/generation` plus `systems/<id>/generation` | partial | very high | high | Keep orchestration generic, move rule logic out |
| Character generation | `lol_api/generator.py` | Generates player characters with Cypher-flavored structure | system | `systems/cypher/generation` | partial | very high | high | Separate generic prompting from Cypher mechanics |
| NPC generation | `lol_api/generator.py` | Generates NPCs and Cypher stat blocks | system | `systems/cypher/generation` | partial | very high | high | Same migration pattern as character generation |
| Monster/creature generation | `lol_api/generator.py` | Generates monsters/creatures with role/family/environment logic | system | `systems/cypher/generation` | partial | very high | high | Environment/family tables may partly become addon or setting content |
| Settlement generation | `lol_api/generator.py` | Generates settlements using current setting data | split: core + setting-content | generic shell in core, content in `content/...` | partial | high | medium | Content model is reusable, current output is setting-bound |
| Encounter generation | `lol_api/generator.py` | Generates encounters with current world and Cypher assumptions | split: core + system + setting-content | mixed | partial | high | medium | Good example of a feature that spans multiple layers |
| Cypher generation | `lol_api/generator.py` | Generates one-use Cypher items | system | `systems/cypher/generation` | no | very high | medium | Must be fully isolated from core |
| Artifact generation | `lol_api/generator.py` | Generates artifacts with depletion and item semantics | system | `systems/cypher/generation` | partial | very high | medium | Generic item generation may exist later, but current logic is Cypher-specific |
| Inn generation | `lol_api/generator.py` | Generates inns/taverns flavored by setting context | split: core + setting-content | mixed | yes | high | medium | Could become generic worldbuilding content with optional system overlays |
| Raw text parser | `lol_api/generator.py` | Parses raw text entries into typed cards | plugin | `plugins/importers/raw-text` | yes | medium | medium | Likely belongs to content import tooling rather than runtime generation |
| CSRD compendium access | `lol_api/compendium.py`, `CSRD/compendium/*` | Loads, lists, searches, and reads CSRD card data | system-addon | `systems/cypher/addons/csrd` | no | low | high | Strong candidate for first addon migration |
| Official compendium access | `lol_api/official_compendium.py`, `PDF_Repository/private_compendium/*` | Loads imported official book cards and searches them | system-addon | `systems/<id>/addons/<addon_id>` plus import metadata | partial | medium | high | Book-origin content should live as addon packs, not monolith globals |
| Compendium landing/catalog UX | `lol_api/api.py`, `compendium_landing.html`, `players_guide.html` | Exposes compendium sources and entry points | core | `core/catalog` | yes | medium | medium | Generic catalog shell with system/addon providers underneath |
| Settings management UI | `lol_api/api.py`, `settings.html`, `settings_detail.html`, `setting_wizard.html` | Manages setting metadata, creates folders/files, edits world config | split: core + content scaffolding plugin | partial | high | high | Important, but should be rebuilt against the new hierarchy, not current folder assumptions |
| Setting wizard/scaffolding | `lol_api/api.py`, `setting_wizard.html` | Creates new setting bundles and starter files | plugin | `plugins/scaffolding` | yes | medium | medium | Good tooling, but not runtime core |
| Character studio | `character_studio.html`, related routes in `api.py` | Provides Cypher-oriented character creation/browsing flow | system | `systems/cypher/ui` | no | high | medium | Strongly system-specific |
| Character sheet PDF export/fill | `api.py`, `PDF_Repository/FormFillableCharacterSheet/*` | Reads PDF fields and fills character sheet PDFs | system or plugin | `systems/cypher/export` or `plugins/pdf-export` | partial | medium | low | Depends on whether PDF export is considered a system-specific addon capability |
| Dice roller | `dice_roller.html`, route in `api.py` | Generic dice rolling UI | core | `core/tools/dice` | yes | low | low | Nice candidate for minimal-tool core |
| Cypher roller | `cypher_roller.html`, route in `api.py` | Cypher-specific roller UI | system | `systems/cypher/tools` | no | low | low | Isolated system tool |
| FoundryVTT importer | `Plugins/foundryVTT/importer.py` | Converts Foundry actors/items into app records | plugin | `plugins/foundryvtt` | partial | medium | medium | Mapping logic should call system contracts, not hardcode only Cypher later |
| FoundryVTT exporter | `Plugins/foundryVTT/exporter.py` | Converts app records into Foundry actor/item payloads | plugin | `plugins/foundryvtt` | partial | medium | medium | Same as importer |
| FoundryVTT HTTP bridge | `lol_api/api.py` plugin endpoints | Exposes health, handshake, import, and export sync endpoints | plugin | `plugins/foundryvtt` | yes | medium | medium | Keep fully optional |
| AI provider selection and generation | `api.py`, `ai_generate.html`, plugin toggles | Routes generation through OpenAI or Ollama and vision flows | plugin | `plugins/openai_remote`, `plugins/ollama_local` plus generic provider contract | yes | high | medium | Core should only define provider interface |
| AI vision prompting | `api.py` helper prompt text | Builds image-analysis prompts that currently mention Cypher output | split: core + system | provider shell generic, prompts in system/plugin layer | partial | high | medium | Current text is explicitly Cypher-centric |
| Semantic/vector search | `Plugins/docling/vector_index.py`, `api.py` vector routes | Builds sparse index and queries semantic snippets across docs and cards | plugin | `plugins/docling` | yes | medium | medium | Good plugin candidate with generic indexing contract |
| Plugin-backed compendium sync/index maintenance | `api.py`, `Plugins/docling/vector_index.py` | Syncs storage cards into vector index | plugin | `plugins/docling` | yes | low | medium | Useful extension point once storage contracts are stable |
| Search aliases and legacy browse routes | multiple redirects in `api.py` | Redirects old browse pages into unified search | retire-or-rethink | remove after rebuild | yes | low | low | Do not reintroduce legacy aliases unless still useful |
| Land of Legends world data | `config/worlds/lands_of_legends/*`, `lore/entries/*` | Setting-specific races, areas, settlements, names, and lore | setting-content | `content/cypher/fantasy/land_of_legends/...` | no | low | high | This is content, not platform logic |
| Saved generated records | `storage/*` | Local generated content across many types | campaign-content | campaign-aware storage under canonical contracts | yes | medium | high | Decide inheritance/reference model during migration |

## Recommended Migration Queue

### Wave 1: Minimum Core
- app bootstrap
- plugin discovery
- storage layer
- config/context model
- generic content CRUD
- generic search shell

### Wave 2: Context and Content
- world hierarchy
- lore CRUD
- catalog/compendium shell
- image attachment service
- map persistence service

### Wave 3: System Framework
- system plugin contract
- addon contract
- `cypher` system shell
- first addon: `csrd`

### Wave 4: Generation
- generic generation orchestration
- Cypher generators one by one
- character studio
- Cypher-specific tools

### Wave 5: Optional Integrations
- FoundryVTT
- OpenAI remote
- Ollama local
- Docling/vector indexing
- scaffolding/import/editorial tooling

## Features That Need Explicit Re-Design

### Route Monolith
The current `lol_api/api.py` file is too large and mixes:
- HTML page routing
- JSON APIs
- plugin APIs
- generation orchestration
- compendium browsing
- image and docs tooling
- setting management
- Foundry endpoints

The rebuild should split this by responsibility instead of preserving route groupings.

### Generator Logic
The current generator module mixes:
- generic text shaping
- world-content lookup
- system mechanics
- output formatting
- storage-adjacent assumptions

It should be decomposed into:
- generic orchestration
- system rules
- setting content lookup
- rendering/output adapters

### Settings Terminology
The current app uses overlapping ideas like:
- `world`
- `setting`
- `settings`

The rebuild should normalize around:
- `system`
- `setting`
- `campaign`

With:
- `genre` retained as supporting taxonomy for filtering, classification, and defaults

### AI Features
The current AI flows are useful but should be treated as optional capability layers rather than central app logic.

## Features Most Likely to Be Retired or Deferred
- legacy alias routes that only exist for old navigation paths
- any UI page that duplicates unified search without adding distinct value
- monolith-only helper flows that exist because responsibilities were not separated

## Open Decisions Before We Start the Inventory-to-Migration Pass
- Is the prompt library core platform data or an AI plugin concern?
- Is PDF character-sheet export a system capability or a generic export plugin?
- Should map editing be a core tool or a campaign-level module?
- Should docs browsing ship in the first rebuild milestone or wait until the platform stabilizes?
- Which feature becomes the first end-to-end proof slice after core and `cypher/csrd` are in place?

## Suggested Next Planning Step
Build a second-pass inventory that drills into each legacy feature with:
- entry points
- hidden dependencies
- required data contracts
- test fixtures needed
- migration blockers

That second-pass document should start with the highest-priority features only:
- storage
- settings/context
- search
- lore CRUD
- `cypher` system shell
- `csrd` addon
