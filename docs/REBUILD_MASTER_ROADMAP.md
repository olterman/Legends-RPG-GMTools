# Rebuild Master Roadmap

## Purpose
Rebuild the app from the ground up without carrying forward the current monolith structure.

This roadmap is for planning and sequencing only. It does not change the current app behavior.

## Goals
- Preserve the current codebase in a full backup so the rebuild can be abandoned safely.
- Create a minimal functional core with strong extension points.
- Move all rules-system-specific logic out of the core.
- Treat each RPG rules system as a first-class system module.
- Treat each rulebook or supplement as a system addon under its parent system.
- Organize playable content with:
  - primary hierarchy: `system -> setting -> campaign`
  - supporting taxonomy: `genre`
- Add first-class auditability, recoverability, and global relationship navigation.
- Rebuild each feature one by one against clean contracts instead of copying monolith internals.

## Non-Goals
- No direct in-place refactor of the current monolith.
- No partial architectural rewrite inside legacy files.
- No assumption that current feature boundaries are correct.

## Working Principles
- Backup first, then rebuild.
- Keep the core generic.
- Keep system logic isolated.
- Keep optional integrations optional.
- Prefer adapters over legacy code import.
- Rebuild by thin vertical slices.
- Every imported feature must justify its place in the new architecture.

## Success Criteria
- The new app can run with a minimal core and no system plugin loaded.
- A system plugin can be installed or removed without changing core code.
- A system addon can be installed or removed without breaking its parent system.
- Cypher-specific mechanics are fully isolated from the generic core.
- Setting and campaign structure works consistently across systems.
- Legacy data can be imported through migration adapters instead of being hardwired into the new app.
- User actions are recoverably logged with audit metadata.
- Tags and backlinks are navigable system-wide.
- Authentication, authorization, and schema migration are treated as first-class platform concerns.
- User-created content remains file-backed and portable.
- Relational platform state is database-backed and rebuildable from content plus event/index state where appropriate.

## Phase 0: Freeze and Backup

### Objective
Protect the current project before the rebuild begins.

### Actions
- Create a timestamped backup of the entire repository in a dedicated `backup/` folder.
- Preserve code, docs, config, storage, lore, imported compendium data, and plugin code.
- Keep the legacy app runnable in the backup snapshot.
- Record the backup path and timestamp in a short rebuild log.

### Deliverables
- Full backup snapshot
- Backup verification note
- Rebuild log started

### Exit Criteria
- The current project can be restored from backup without guesswork.

## Phase 1: Define the New Architecture

### Objective
Set the boundaries before any migration work begins.

### Target Layers
- `core`
  - app shell
  - auth/session layer
  - audit/event layer
  - plugin loader
  - storage contracts
  - database and migration contracts
  - metadata contracts
  - tag and backlink graph contracts
  - search/index contracts
  - generic content CRUD
  - campaign management
  - generic navigation and settings context
  - API routing layer
- `systems/<system_id>`
  - rules-system logic
  - stat logic
  - rule-aware generators
  - canonical system taxonomies
- `systems/<system_id>/addons/<addon_id>`
  - rulebook-specific content and overrides
  - supplement-specific tables, items, creatures, classes, tags, and metadata
- `content/<system_id>/<genre_id>/<setting_id>/<campaign_id>`
  - playable world content and campaign-specific material
- `plugins/<plugin_id>`
  - optional integrations and tools such as Foundry, OpenAI, Ollama, vector indexing, import/export tools
  - bundled-by-default ingestion plugins such as `docling` are still plugins, not core parsing code

### Core Architectural Rules
- Core must not know system-specific terms like `cypher`, `focus`, `edge`, or `tier`.
- Systems may define their own content types and mechanics, but must expose them through shared contracts.
- Addons may extend systems but may not bypass system contracts.
- Optional plugins must integrate through public capabilities only.
- Content hierarchy must be navigable without system-specific hacks.
- Sourcebook parsing should follow one markdown-first path: addon-owned raw source, bundled `docling` conversion, addon-owned markdown parser/importer, then canonical core records.
- Addons may also ship addon-owned html rulebook artifacts for browser reading, but backend parsing stays markdown-based.
- Core, systems, addons, and tools should all expose API endpoints where their capabilities are user-facing or automation-facing.

### Deliverables
- Approved target directory model
- Approved vocabulary for `core`, `system`, `addon`, `plugin`, `genre`, `setting`, `campaign`
- Shared contract checklist

### Exit Criteria
- We can explain where any future feature belongs without ambiguity.

## Phase 2: Define Canonical Contracts

### Objective
Create the shared language that every module must use.

### Required Record Contract
Every canonical record should support:
- `id`
- `type`
- `name` or `title`
- `content`
- `metadata`
- `system`
- `addon`
- `genre`
- `setting`
- `campaign`
- `source`
- `schema_version`

Hierarchy note:
- user-facing organization should center on `system -> setting -> campaign`
- `genre` remains an important taxonomy field for filtering and defaults

### Required Metadata Contract
Metadata should support:
- `tags`
- `created_at`
- `updated_at`
- `created_by`
- `sourcebook`
- `pages`
- `area`
- `location`
- `status`
- `visibility`

### Required Audit/Event Contract
The platform should define a core audit/event model that can capture:
- actor/user id
- action type
- target entity type
- target entity id
- context (`system`, `setting`, `campaign`)
- timestamp
- request or system-call metadata
- before/after references where relevant
- AI prompt/provider metadata where relevant

### Required Relationship Contract
The platform should define first-class contracts for:
- tags
- backlinks
- related entity edges
- system-wide tag queries
- generated tag directories

### Required Storage Architecture Rule
The platform should adopt a hybrid storage model:
- content records remain file-backed
- relational overlays and platform state are database-backed
- file-backed content remains the durable source of truth for user-created playable data
- relational projections should be rebuildable where feasible

### Capability Contracts
Define shared capability interfaces for:
- storage
- database migration
- auth
- audit logging
- tag graph and backlinks
- search
- indexing
- content validation
- rendering
- generation
- rules resolution
- import/export
- API exposure and endpoint registration

### Deliverables
- Canonical record schema draft
- Capability registry draft
- Versioning rules for schema changes

### Exit Criteria
- New features can be built against contracts without touching legacy code.

## Phase 3: Feature Inventory and Classification

### Objective
Audit the current app and decide what survives, what moves, and what gets retired.

### Classification Buckets
- `core`
- `system-specific`
- `system-addon-specific`
- `optional-plugin`
- `setting-content`
- `campaign-content`
- `retire`

### Decision Tests

#### Core
Put a feature in `core` if it:
- works without any RPG rules system
- is useful across multiple systems
- provides platform behavior rather than game mechanics

Examples:
- storage
- search
- metadata tagging
- CRUD
- plugin discovery
- campaign selection

#### System-Specific
Put a feature in `system-specific` if it:
- depends on mechanics or concepts unique to a rules system
- uses system-native character/item/stat structures
- requires rules interpretation

Examples:
- Cypher stat blocks
- descriptors, foci, edges, tier logic
- rules-aware character generation

#### System Addon
Put a feature in `system-addon-specific` if it:
- belongs to one rulebook or supplement
- extends the parent system with book-specific content or rules

Examples:
- one sourcebook's creatures
- one supplement's powers or equipment
- one book's setting-flavored tables

#### Optional Plugin
Put a feature in `optional-plugin` if it:
- is an external integration
- can be removed without breaking the platform
- is not required for baseline app use

Examples:
- Foundry sync
- OpenAI provider
- Ollama provider
- Docling/vector indexing

#### Retire
Put a feature in `retire` if it:
- duplicates another feature
- only exists because of monolith constraints
- would not be rebuilt if designing cleanly today

### Deliverables
- Feature inventory sheet
- Classification for every current feature
- Migration priority for every classified feature

### Exit Criteria
- No migration starts until each feature has an approved destination.

## Phase 4: Build the New Empty Skeleton

### Objective
Create a pristine new app structure before importing any features.

### Actions
- Create empty top-level folders for core, systems, addons, content, plugins, and migrations.
- Add architecture docs and schema docs first.
- Add placeholder module boundaries and registration points.
- Add a minimal app bootstrap that can start with no system loaded.

### Deliverables
- Clean folder tree
- Minimal app bootstrap
- Empty plugin and system loading paths

### Exit Criteria
- The new app runs as an empty shell without legacy logic.

## Phase 5: Import the Minimal Core

### Objective
Make the platform useful before adding any rules system.

### Import Order
1. Shared schemas and validation
2. Database and migration layer
3. Auth and roles layer
4. Storage layer
5. Audit/event layer
6. Tag/backlink layer
7. Plugin loader
8. System loader
9. Search/index contracts
10. Generic content CRUD
11. Generic navigation for system, setting, campaign, and genre taxonomy

### Rules
- No Cypher-specific names in core APIs.
- No world-specific defaults in core code.
- No plugin may reach inside core internals directly.

### Deliverables
- Working minimal core
- Test coverage for storage and plugin loading
- Basic UI or API shell for navigation

### Exit Criteria
- The platform can store and retrieve generic records with context metadata.

## Phase 6: Add System Plugin Support

### Objective
Prove the system architecture before migrating actual game features.

### Actions
- Define the system plugin interface.
- Support system registration and capability exposure.
- Allow systems to contribute:
  - content types
  - validation rules
  - generation capabilities
  - search filters
  - UI panels or routes if needed

### Deliverables
- Stable system plugin API
- One reference system plugin shell

### Exit Criteria
- The app can load a system module without editing core code.

## Phase 7: Rebuild Cypher as a System Plugin

### Objective
Move Cypher behavior out of the core and into a clean isolated system package.

### Actions
- Rebuild Cypher rules as `systems/cypher`.
- Isolate stat blocks, item semantics, character structure, and generation logic there.
- Identify every Cypher-specific field in the legacy app and map it to the new system API.
- Keep legacy imports behind adapters rather than direct module reuse where possible.

### Deliverables
- `cypher` system plugin
- Cypher content type map
- Cypher migration notes

### Exit Criteria
- The new app can run with Cypher enabled or disabled without core changes.

## Phase 8: Rebuild Addons Under Each System

### Objective
Separate system core from book- or supplement-specific content.

### Actions
- Define addon registration under `systems/<system_id>/addons/<addon_id>`.
- Treat each rulebook or supplement as its own addon package.
- Move book-specific content, tags, and overrides into addons.
- Ensure addon load order is deterministic and visible.

### Deliverables
- Addon contract
- First Cypher addon migrated
- Load-order and dependency rules

### Exit Criteria
- Book-specific content can be enabled, disabled, or updated independently of the system core.

## Phase 9: Rebuild the World Hierarchy

### Objective
Make world organization first-class and system-aware.

### Required Hierarchy
- `system`
- `genre`
- `setting`
- `campaign`

### Rules
- Genre is broader thematic classification.
- Setting is a reusable world or sub-world.
- Campaign is a playable instance under a setting.
- Campaign data must be allowed to override or extend setting data without mutating the setting source.

### Deliverables
- World hierarchy model
- Generic navigation and filtering
- Content resolution rules across system, setting, and campaign levels

### Exit Criteria
- Users can switch context cleanly across system, genre, setting, and campaign.

## Phase 10: Migrate Features One by One

### Objective
Reintroduce functionality through controlled migration slices.

### Migration Loop
For each feature:
1. Capture current behavior.
2. List inputs, outputs, and hidden dependencies.
3. Classify it as core, system, addon, plugin, setting, campaign, or retire.
4. Remove Cypher- or Lands-of-Legends-specific assumptions.
5. Rebuild against canonical contracts.
6. Add migration tests and fixtures.
7. Verify the new feature without calling legacy internals.
8. Mark the legacy feature as replaced.

### Recommended Migration Order
1. Generic storage and retrieval
2. Generic search and filters
3. Generic content browser
4. Lore/content management
5. Generic generator pipeline shell
6. Cypher generator implementation
7. Compendium import and browse
8. AI provider plugins
9. Foundry plugin
10. Vector/PDF plugins

### Exit Criteria
- Every migrated feature works in the new architecture without monolith coupling.

## Phase 11: Data Migration and Legacy Adapters

### Objective
Bring forward valuable data without dragging forward the old architecture.

### Actions
- Define import adapters for legacy storage records.
- Define import adapters for lore, config, compendium, and generated outputs.
- Normalize metadata into the new canonical model.
- Flag ambiguous records for review instead of silently importing them.

### Deliverables
- Legacy adapter scripts
- Import validation reports
- Data migration checklist

### Exit Criteria
- Existing content can be brought forward with traceable transformations.

## Phase 12: Hardening and Cutover

### Objective
Make the rebuild stable enough to replace the old app.

### Actions
- Add end-to-end tests for core workflows.
- Validate plugin isolation.
- Validate system isolation.
- Validate addon registration and dependency handling.
- Run migration dry runs on real legacy data.
- Document rollback path.

### Deliverables
- Test suite
- Cutover checklist
- Rollback checklist
- Release readiness notes

### Exit Criteria
- The new app can replace the legacy app with an acceptable migration and rollback path.

## Migration Guardrails
- Do not copy legacy structure blindly.
- Do not allow system-specific fields into core contracts.
- Do not embed setting defaults in core code.
- Do not make external integrations mandatory.
- Do not migrate duplicate UI routes or dead-end features without re-evaluation.

## Suggested Initial Deliverables for the Rebuild

### Milestone A
- Full backup completed
- Rebuild roadmap approved
- Empty pristine app skeleton created

### Milestone B
- Core schemas
- Storage layer
- Plugin loader
- System loader

### Milestone C
- World hierarchy
- Generic CRUD
- Generic search shell

### Milestone D
- First `cypher` system plugin
- First Cypher addon

### Milestone E
- One end-to-end generator migrated cleanly

### Milestone F
- Remaining features migrated by priority

## Feature Inventory Template

Use this table while auditing legacy functionality.

| Legacy Feature | Current Module/File | What It Does | Classification | Target Destination | Genericizable? | Cypher-Specific? | Priority | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Example: storage listing | `lol_api/storage.py` | Lists saved records | core | `core/storage` | yes | no | high | baseline platform capability |
| Example: NPC generation | `lol_api/generator.py` | Generates NPCs with Cypher-flavored stats | system-specific | `systems/cypher/generation` | partial | yes | high | split generic prompt flow from Cypher rules |

## Migration Checklist Template

Copy this for each feature before migration starts.

### Feature
- Name:
- Legacy source:
- Owner layer:

### Behavior Snapshot
- Inputs:
- Outputs:
- Hidden dependencies:
- Current UI/API entry points:

### Classification
- Core, system, addon, plugin, setting, campaign, or retire:
- Why:

### Generalization Review
- What is reusable across RPG systems:
- What is Cypher-specific:
- What is Lands-of-Legends-specific:
- What should move to config instead of code:

### Migration Plan
- New destination:
- Required contracts:
- Data migration needs:
- Test fixtures needed:
- Blocking decisions:

### Done Criteria
- Feature rebuilt on new contracts:
- No legacy internals required:
- Tests passing:
- Legacy replacement decision recorded:

## Current Likely Core Candidates
- app bootstrap
- plugin discovery
- system discovery
- storage and schema versioning
- metadata and tagging
- search and indexing contracts
- generic content CRUD
- context selection for system, genre, setting, and campaign

## Current Likely Plugin Candidates
- FoundryVTT sync
- OpenAI remote provider
- Ollama local provider
- Docling/vector indexing

## Current Likely Cypher System Candidates
- character rules
- NPC stat logic
- creature rules
- cypher/artifact logic
- descriptors, foci, flavors, types, abilities
- rules-aware generation

## Open Questions to Resolve Before Migration Starts
- What framework powers the rebuilt app shell?
- Should systems be pure backend modules, or can they register UI panels too?
- Will content records be file-based, database-backed, or hybrid?
- Will campaigns inherit content by reference, copy, or overlay?
- How strict should plugin sandboxing be?
- What is the minimum core feature set for the first usable rebuild milestone?

## Immediate Next Steps
1. Create the backup folder and snapshot procedure.
2. Approve the target folder structure.
3. Build the full feature inventory from the legacy app.
4. Mark each feature as core, system, addon, plugin, setting, campaign, or retire.
5. Create the pristine new app skeleton only after the inventory is approved.
