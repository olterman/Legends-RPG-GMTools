# Rebuild Second-Pass Inventory

## Purpose
This document drills into the highest-priority migration slices for the rebuild.

It focuses on:
- entry points
- hidden dependencies
- contract needs
- known blockers
- recommended migration order

This is still planning only.

## Scope
This second pass covers the first rebuild waves:
- storage
- context/settings/config
- search shell
- lore CRUD
- `cypher` system shell
- `csrd` addon shell

## 1. Storage

### Legacy Sources
- `lol_api/storage.py`
- storage routes inside `lol_api/api.py`
- vector sync hooks in `Plugins/docling/vector_index.py`

### What It Does Today
- saves generated records as JSON files
- organizes records by derived type-based subdirectory
- special-cases Foundry imports into nested subfolders
- lists, loads, updates, searches, trashes, restores, and expunges records
- extracts summary fields for UI cards

### Current Entry Points
- generation endpoints
- storage listing/search endpoints
- storage update/delete/trash endpoints
- vector indexing sync hooks
- image attach/detach endpoints

### Hidden Dependencies
- assumes legacy record shape:
  - `record.result`
  - `record.payload`
  - `result.metadata`
- assumes type naming through:
  - `primarycategory`
  - `type`
  - metadata fallbacks
- assumes `setting/settings` metadata for folder routing in Foundry imports
- assumes `environment` and `area` are aliases
- assumes description can be guessed from many possible locations in the record

### Current Strengths
- file-based records are simple and inspectable
- trash lifecycle already exists
- filenames and persistence are deterministic enough for local workflows

### Current Weaknesses
- storage shape is not a clean canonical contract yet
- storage summaries are built with many legacy heuristics
- folder routing is partly source-specific rather than contract-driven
- storage layer knows too much about current entity types and metadata aliases

### Rebuild Contract Needs
- canonical record envelope
- canonical metadata model
- storage driver interface
- summary/index projection rules
- attachment/reference model
- trash/archive behavior

### Migration Recommendation
- rebuild this first as a pure core service
- define a new canonical envelope before migrating any feature onto it
- support legacy import through an adapter, not through storage core itself

### Proposed New Boundary
- `core/storage`
- `migration/legacy_importers/storage`

### Blockers
- canonical record schema not finalized
- campaign inheritance/reference strategy not finalized
- attachment model not finalized

### Done Criteria
- core storage no longer knows about Cypher, Foundry, or current legacy field aliases
- legacy records can be imported through a translator
- search and UI can consume clean summary projections

## 2. Context, Settings, and Config

### Legacy Sources
- `lol_api/settings.py`
- `lol_api/config_loader.py`
- settings routes and setting wizard logic in `lol_api/api.py`
- `config/core`
- `config/settings`
- `config/worlds`

### What It Does Today
- loads layered config from flat, core, genre, and world folders
- resolves defaults and setting descriptors
- normalizes current setting tokens and aliases
- attaches `setting/settings/genre` metadata to items
- builds navigation models for genre and setting selection

### Current Entry Points
- app startup
- settings UI
- setting wizard
- generation flows
- lore normalization
- storage metadata normalization
- search filtering

### Hidden Dependencies
- still uses overlapping terminology:
  - `world`
  - `setting`
  - `settings`
  - `genre`
- still supports legacy aliases such as:
  - `lands_of_legends`
  - `lands_of_legend`
- treats `worlds` and `settings` as interchangeable in places
- current config loader also handles `environment -> area` aliasing

### Current Strengths
- layered config is already close to the desired direction
- taxonomy and descriptor helpers are reusable
- default and expansion logic is already centralized

### Current Weaknesses
- terminology is transitional rather than canonical
- core config loading currently mixes schema loading with compatibility aliasing
- app startup assumes one active setting rather than a richer context model

### Rebuild Contract Needs
- canonical context model:
  - `system`
  - `genre`
  - `setting`
  - `campaign`
- config provider interface
- context resolution rules
- hierarchy inheritance rules
- validation rules for config packs

### Migration Recommendation
- rebuild this alongside storage in the first core wave
- split config loading from compatibility translation
- make the new context model explicit before moving any generators

### Proposed New Boundary
- `core/context`
- `core/config`
- `plugins/scaffolding` for setting/system creation tooling

### Blockers
- folder structure for the rebuild must be approved
- inheritance model between setting and campaign must be approved
- decision needed on whether content remains file-based, DB-backed, or hybrid

### Done Criteria
- no new core code uses legacy `world/settings` ambiguity
- core can resolve context without knowing Cypher or Lands of Legends
- existing settings can be imported through adapters or validated pack loaders

## 3. Search Shell

### Legacy Sources
- unified search logic in `lol_api/api.py`
- storage search in `lol_api/storage.py`
- lore search in `lol_api/lore.py`
- compendium search in `lol_api/compendium.py`
- official compendium search in `lol_api/official_compendium.py`
- vector query routes and plugin hooks
- `lol_api/templates/search.html`

### What It Does Today
- aggregates multiple content sources into one browsing/search surface
- filters across storage, lore, compendium, official imports, and vector sources
- supports source-aware cards and result metadata

### Current Entry Points
- `/search`
- redirect aliases from older browse pages
- supporting JSON endpoints

### Hidden Dependencies
- route logic in `api.py` currently acts as orchestrator, aggregator, and formatter
- result shapes differ heavily by source
- settings/source/type filters rely on many source-specific field names
- vector search is partly embedded into current search behavior

### Current Strengths
- unified search is the right product direction
- source-aware cards and filters are valuable and portable

### Current Weaknesses
- aggregation and formatting are coupled to the route monolith
- result contracts are not normalized enough
- too many provider-specific branches live in one place

### Rebuild Contract Needs
- search provider contract
- normalized search result card contract
- source registry
- filter grammar
- optional semantic search extension interface

### Migration Recommendation
- rebuild the search shell after storage and context are stable
- search core should only know provider contracts and result cards
- individual sources register providers:
  - storage
  - lore
  - addons
  - plugins

### Proposed New Boundary
- `core/search`
- providers under `core`, `systems`, and `plugins`

### Blockers
- canonical summary/result contract not finalized
- source registry design not finalized

### Done Criteria
- search page can render mixed providers through one normalized result contract
- no provider-specific formatting logic remains in the central route layer

## 4. Lore CRUD

### Legacy Sources
- `lol_api/lore.py`
- lore routes in `lol_api/api.py`
- `lore/index.json`
- `lore/entries/*.json`

### What It Does Today
- loads lore index
- loads full lore entries
- searches lore by text, setting, and location
- updates entries and index
- supports trash, restore, and expunge
- normalizes categories, settings, areas, images, and location metadata

### Current Entry Points
- lore browser/search routes
- lore CRUD endpoints
- image attachment flows
- AI-derived lore browsing

### Hidden Dependencies
- normalization assumes legacy aliases:
  - `environment`
  - `area`
  - `setting`
  - `settings`
- location entry rules are embedded in lore service logic
- AI-derived lore helpers are mixed in the same module as basic CRUD
- some matching logic contains setting-specific heuristics

### Current Strengths
- lore CRUD itself is relatively clean
- index maintenance is explicit and file-based
- trash lifecycle mirrors storage behavior well

### Current Weaknesses
- CRUD and AI-derived/inference logic are mixed together
- location semantics are partly hardcoded
- current module reaches toward setting-specific interpretation logic

### Rebuild Contract Needs
- generic content CRUD contract
- lore/content subtype schema
- indexing contract
- content derivation interface for optional AI/enrichment views

### Migration Recommendation
- split this into two pieces:
  - generic lore/content CRUD in core
  - AI-derived lore synthesis in plugin or content-service layer
- migrate CRUD early
- defer synthesized lore until core content contracts are stable

### Proposed New Boundary
- `core/content/lore`
- optional enrichment under `plugins/content-enrichment` or a system/content service

### Blockers
- canonical content record contract not finalized
- decision needed on whether “lore” is a special type or just one content subtype

### Done Criteria
- lore CRUD works on canonical records
- AI-derived lore is no longer bundled into the core content service

## 5. Cypher System Shell

### Legacy Sources
- `lol_api/generator.py`
- Cypher-oriented UI routes and templates in `lol_api/api.py`
- `character_studio.html`
- `cypher_roller.html`
- current CSRD and official compendium assumptions throughout the app

### What It Does Today
- defines Cypher-flavored generation outputs
- produces Cypher stat blocks
- uses Cypher item classes like `cypher` and `artifact`
- supports Cypher-specific browsing and tools

### Current Entry Points
- generation endpoints
- character studio
- Cypher roller
- Foundry mappings
- compendium browsing
- AI prompting that asks for Cypher outputs

### Hidden Dependencies
- generator mixes:
  - generic text shaping
  - naming utilities
  - setting lookup
  - Cypher mechanics
  - output formatting
- some UI pages assume Cypher-specific categories directly
- AI prompts explicitly request Cypher results in current helper text
- Foundry plugin mappings currently assume Cypher sheet/item semantics

### Current Strengths
- system-specific logic is already somewhat concentrated
- this gives us a strong candidate for the first system plugin proof

### Current Weaknesses
- no clean system boundary yet
- generic and system logic are heavily interwoven
- current naming and prompt-building paths blur content/system responsibilities

### Rebuild Contract Needs
- system plugin interface
- system content type registry
- system generation interface
- system rules/stat block interface
- system UI/tool registration interface

### Migration Recommendation
- do not migrate feature-by-feature until the system shell exists
- first create an empty `cypher` system plugin that registers:
  - system id
  - supported content types
  - validation hooks
  - generation capability slots
- then move one feature at a time into it

### Proposed New Boundary
- `systems/cypher`
- optional UI under `systems/cypher/ui`

### Blockers
- system plugin contract not finalized
- decision needed on whether systems can register UI directly or only backend capabilities

### Done Criteria
- core app runs with or without Cypher loaded
- Cypher types and generators are invisible to core unless the system is active

## 6. CSRD Addon Shell

### Legacy Sources
- `lol_api/compendium.py`
- `CSRD/compendium/*`
- CSRD parsing scripts under `CSRD/`

### What It Does Today
- exposes parsed CSRD content as browsable/searchable compendium data
- supports card types like:
  - cypher
  - artifact
  - creature
  - character type
  - flavor
  - descriptor
  - focus
  - ability
  - skill

### Current Entry Points
- compendium routes
- search integration
- character studio and generator support

### Hidden Dependencies
- compendium types are currently modeled as global app types rather than addon-provided content
- search and UI assume CSRD content is a built-in source
- some settings tags are attached at card level with legacy terminology

### Current Strengths
- module itself is relatively clean
- file-based JSON cards are a good addon content-pack format

### Current Weaknesses
- not yet framed as a system addon
- current app treats it more like a built-in global compendium

### Rebuild Contract Needs
- addon registration interface
- addon content manifest
- addon search provider
- addon source metadata contract

### Migration Recommendation
- make this the first addon proof
- keep the file-based card format if possible
- register it under `systems/cypher/addons/csrd`

### Proposed New Boundary
- `systems/cypher/addons/csrd`

### Blockers
- addon contract not finalized
- search provider contract not finalized

### Done Criteria
- CSRD loads as a Cypher addon, not as a core feature
- search sees it through addon provider registration

## Cross-Cutting Coupling Problems

### 1. Alias-Heavy Metadata
Current modules repeatedly normalize:
- `environment` and `area`
- `setting`, `settings`, `genre`, `genres`
- `world` and `setting`

This is useful for migration, but it should live in import adapters, not in new core logic.

### 2. Monolithic Route Layer
`lol_api/api.py` currently owns:
- routing
- orchestration
- formatting
- search aggregation
- plugin APIs
- image tooling
- docs tooling
- settings management
- generation flows

This must be split early or every migration will keep dragging route-coupling forward.

### 3. Mixed Generic and Cypher Logic
The generator and AI prompt layers contain both:
- generic content ideas
- explicit Cypher mechanics and output expectations

The rebuild should separate:
- generic orchestration
- system-specific rules
- setting content
- optional provider integrations

## Recommended First Implementation Wave

### Wave A
- finalize canonical record envelope
- finalize context model
- build new core storage
- build new core context/config loader

### Wave B
- build search provider contract
- build generic lore/content CRUD
- build normalized search result contract

### Wave C
- build system plugin contract
- create empty `cypher` system shell
- create empty `csrd` addon shell

## Decision Checklist Before Coding Starts
- approve canonical record envelope
- approve target folder structure
- approve context hierarchy
- decide whether systems can register UI directly
- decide whether storage remains file-first or hybrid
- decide whether lore is a special content class or just one subtype

## Suggested Next Planning Step
Turn Wave A into a concrete implementation spec:
- exact folder tree
- canonical record schema draft
- context schema draft
- storage API draft
- migration adapter plan for legacy records
