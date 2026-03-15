# Rebuild Wave A Implementation Spec

## Purpose
Define the first implementation wave of the rebuild before any new app code is written.

Wave A establishes:
- the target top-level folder structure
- the canonical record envelope
- the canonical context model
- the core storage API
- the direction for auth, audit, tags, and data persistence
- the legacy adapter strategy

This document is prescriptive. It is intended to reduce ambiguity before coding starts.

## Wave A Goal
Build the smallest viable platform core that can exist without any rules system loaded.

This is a hard requirement:
- the base app must run with no systems loaded
- the base app must run with no plugins loaded
- the canonical fallback system context is `system_id = "none"`
- systems and plugins extend the core, but are never required for the core to boot

Wave A does not include:
- Cypher generation
- CSRD loading
- Foundry sync
- AI providers
- vector indexing
- PDF import or export

## Wave A Deliverables
- pristine target folder structure
- canonical record schema v1 draft
- canonical context schema v1 draft
- core storage service contract
- legacy storage adapter plan
- implementation order for the first coding pass

## 1. Target Folder Structure

### Decision
Use a clean top-level split between platform code, systems, optional plugins, content, and migration tooling.

### Proposed Folder Tree
```text
.
├── app/
│   ├── core/
│   │   ├── app/
│   │   ├── auth/
│   │   ├── audit/
│   │   ├── config/
│   │   ├── context/
│   │   ├── content/
│   │   ├── contracts/
│   │   ├── database/
│   │   ├── graph/
│   │   ├── search/
│   │   ├── storage/
│   │   └── utils/
│   ├── systems/
│   │   └── README.md
│   └── plugins/
│       └── README.md
├── content/
│   └── README.md
├── data/
│   ├── records/
│   ├── indexes/
│   ├── assets/
│   └── trash/
├── legacy/
│   ├── snapshot/
│   └── adapters/
├── docs/
├── tests/
│   ├── core/
│   ├── fixtures/
│   └── integration/
└── tools/
```

### Folder Responsibilities

#### `app/core`
Platform runtime that must remain system-agnostic.

#### `app/systems`
Rules-system packages such as `cypher`.

#### `app/plugins`
Optional integrations and non-essential tooling.

#### `content`
User and project content organized by:
- primary hierarchy:
  - system
  - setting
  - campaign
- supporting taxonomy:
  - genre

#### `data`
Runtime-managed records, indexes, assets, and trash.

Persistent relational state should eventually live in a database layer with migration support.

#### `legacy/snapshot`
Backup copy of the old app or old exported data.

#### `legacy/adapters`
Migration and normalization code for importing legacy material.

#### `tools`
Developer utilities, scaffolds, validators, migration runners.

## 2. Architectural Boundaries

### Core Must Own
- app bootstrap
- dependency registration
- API bootstrap and endpoint registration primitives
- auth and session primitives
- role and permission primitives
- audit/event logging primitives
- context resolution
- config pack loading
- canonical record validation
- database schema and migration management
- storage
- tag and backlink graph primitives
- content CRUD primitives
- campaign management primitives
- search provider contracts
- plugin and system registration

### Core Must Not Own
- rules mechanics
- rulebook semantics
- system-native stat blocks
- system-native content types
- external API provider logic
- sourcebook-specific parsing rules

### API Rule
The new platform should be API-first.

- any core capability that matters to the user should be reachable through an API endpoint
- systems should expose API endpoints for system-owned workflows
- addons should expose API endpoints for addon-owned rulebooks, imports, and related surfaces
- tools and plugins should expose API endpoints when they provide runtime functionality

The browser UI should consume these APIs wherever practical.

### Systems May Own
- system-native content types
- generation logic
- stat rules
- system tools and system UI modules
- system validation rules

### Plugins May Own
- provider integrations
- import/export tools
- indexing engines
- scaffolding tools
- editorial workflows
- bundled document ingestion providers such as `docling`

### Parsing Rule
The rebuild should converge on one markdown-first parsing path for source material.

- raw documents remain owned by the relevant addon in `source/`
- bundled `docling` converts those documents into addon-owned markdown and html
- addon parsers and importers consume markdown
- addon reading surfaces may use addon-owned html render artifacts
- core services only receive normalized canonical records

The core must not accumulate sourcebook-specific PDF or DOCX parsing code.

## 3. Canonical Record Envelope v1

### Decision
Every persisted record should use one top-level envelope shape regardless of source.

### Canonical Record
```json
{
  "schema_version": "1.0",
  "record_version": 1,
  "id": "rec_01hxyz...",
  "type": "lore_entry",
  "title": "The Red Gate",
  "slug": "the_red_gate",
  "system": {
    "id": "none",
    "addon_id": ""
  },
  "context": {
    "genre_id": "fantasy",
    "setting_id": "lands_of_legends",
    "campaign_id": "campaign_alpha"
  },
  "source": {
    "kind": "local",
    "origin": "user",
    "sourcebook": "",
    "pages": [],
    "external_ref": ""
  },
  "content": {},
  "metadata": {
    "tags": [],
    "summary": "",
    "description": "",
    "area_id": "",
    "location_id": "",
    "visibility": "private",
    "status": "active",
    "images": []
  },
  "audit": {
    "created_at": "2026-03-15T10:00:00Z",
    "updated_at": "2026-03-15T10:00:00Z",
    "created_by": "local_user",
    "updated_by": "local_user"
  },
  "links": [],
  "extensions": {}
}
```

### Required Fields
- `schema_version`
- `record_version`
- `id`
- `type`
- `title`
- `system`
- `context`
- `source`
- `content`
- `metadata`
- `audit`

### Optional Fields
- `slug`
- `links`
- `extensions`

### Design Rules
- `content` holds the type-specific payload.
- `metadata` holds cross-cutting descriptive fields used by UI, search, and organization.
- `extensions` is the only place where temporary or plugin-specific fields may live if they are not yet formalized.
- `system.id = "none"` is valid for fully generic records.
- `addon_id` must be empty when no addon applies.
- tags must remain queryable and relationship-friendly across the whole platform.

### Type Strategy
Wave A should not attempt to model every final type.

Use a small starting set:
- `generic_note`
- `lore_entry`
- `asset_ref`
- `generated_card`
- `character_record`
- `location_record`

This list will expand later through systems and addons.

### Anti-Goals
- No top-level `payload`/`result` split in the new core record.
- No top-level `setting/settings/environment/world` aliases in the canonical schema.
- No source-specific record shapes in storage.

## 4. Canonical Context Model v1

### Decision
Every record and every runtime session should resolve through the same four-level context hierarchy.

### Context Structure
```json
{
  "system_id": "cypher",
  "genre_id": "fantasy",
  "setting_id": "lands_of_legends",
  "campaign_id": "campaign_alpha"
}
```

### Field Rules
- `system_id`
  - required for system-bound records
  - may be `"none"` for generic core records
- `genre_id`
  - required when content belongs to a genre context
- `setting_id`
  - optional for purely genre-level content
- `campaign_id`
  - optional for reusable setting-level content

### Context Semantics
- `system_id` determines available rules modules
- `setting_id` determines reusable world data
- `campaign_id` determines play-instance overlays and local modifications
- `genre_id` provides supporting taxonomy, defaults, and discovery filters

### Inheritance Rules
- campaign may extend or override setting content
- setting may extend or override genre defaults where genre is used
- genre may extend or override system defaults only through declared contracts
- core never assumes any specific system, genre, setting, or campaign exists

### Context Resolution Order
1. explicit request context
2. active session context
3. campaign defaults
4. setting defaults
5. genre defaults
6. system defaults
7. platform fallback

## 5. Canonical Source Model v1

### Decision
Source metadata should be structured rather than spread across ad hoc fields.

### Source Structure
```json
{
  "kind": "local",
  "origin": "user",
  "sourcebook": "Cypher System Rulebook",
  "pages": ["123", "124"],
  "external_ref": "foundry://Actor/abc123"
}
```

### Allowed `kind` Values for Wave A
- `local`
- `imported`
- `generated`
- `system_pack`
- `addon_pack`
- `plugin_sync`

### Allowed `origin` Examples
- `user`
- `legacy_import`
- `csrd`
- `foundryvtt`
- `openai_remote`
- `ollama_local`

## 6. Metadata Model v1

### Decision
Metadata should contain fields that are genuinely cross-cutting and frequently queried.

### Metadata Fields
- `tags`
- `summary`
- `description`
- `area_id`
- `location_id`
- `visibility`
- `status`
- `images`

### Allowed `visibility`
- `private`
- `shared`
- `public`

### Allowed `status`
- `active`
- `draft`
- `archived`
- `trashed`

### Rules
- `summary` should be short and optimized for result-card display.
- `description` may be longer and optimized for detail views.
- `images` must store normalized asset references only.

### Audit/Event Direction
Wave A should assume a core audit trail exists, even if the full event store is implemented in a later wave.

Every meaningful write should eventually be able to emit an event containing:
- actor
- action
- target entity
- context
- timestamps
- source/provider metadata
- AI prompt metadata where relevant

## 7. Core Storage API v1

### Decision
Storage should be exposed through a small contract that does not care whether records came from generation, imports, or manual editing.

### Interface
```python
class RecordStore:
    def create(record: dict) -> dict: ...
    def get(record_id: str) -> dict: ...
    def update(record_id: str, record: dict) -> dict: ...
    def delete(record_id: str) -> dict: ...
    def restore(record_id: str) -> dict: ...
    def expunge(record_id: str) -> dict: ...
    def list(filters: dict | None = None) -> list[dict]: ...
    def search(query: str = "", filters: dict | None = None) -> list[dict]: ...
    def summarize(record: dict) -> dict: ...
```

### Minimum Filters for Wave A
- `type`
- `system_id`
- `genre_id`
- `setting_id`
- `campaign_id`
- `status`
- `tag`

### Storage Responsibilities
- validate record envelope
- assign ids when absent
- persist records
- maintain summary projections
- manage trash lifecycle
- normalize write timestamps

### Storage Source of Truth Rule
For playable and user-created content, the canonical source of truth should remain the file-backed record store.

### Storage Must Not Do
- infer system mechanics
- special-case one source type over another
- understand Cypher-specific fields
- rewrite legacy aliases inside canonical records

### Persistence Strategy
Wave A record storage should stay file-based for the first implementation slice.

However, the platform should be designed with an eventual database-backed layer for:
- auth
- sessions
- roles
- permissions
- migration tracking
- audit/event logs
- tag/backlink graph indexes

Chosen architecture:
- content records are file-backed
- relational platform state is database-backed
- the database acts as a relational overlay, not the sole source of truth for user-created playable content
- relational indexes should be rebuildable where feasible from files plus platform history

Recommended layout:
```text
data/records/<record_id>.json
data/indexes/records_summary.json
data/trash/<record_id>.json
```

Alternative sharded layout can be added later if scale requires it.

### Summary Projection Shape
```json
{
  "id": "rec_01hxyz",
  "type": "lore_entry",
  "title": "The Red Gate",
  "system_id": "none",
  "genre_id": "fantasy",
  "setting_id": "lands_of_legends",
  "campaign_id": "campaign_alpha",
  "status": "active",
  "summary": "Ancient shattered gate ruin in the northern hills.",
  "tags": ["gate", "ruins"],
  "updated_at": "2026-03-15T10:00:00Z"
}
```

## 8. Validation Rules for Wave A

### Envelope Validation
- reject records missing required top-level blocks
- reject unknown top-level alias fields from canonical writes
- reject malformed context blocks
- reject malformed source blocks

### Future Platform Concerns Locked Early
Wave A should leave architectural room for:
- database migrations
- user accounts
- GM/player authorization
- audit/event persistence
- tag graph and backlink indexing

### Content Validation
- only minimal type-specific validation in Wave A
- strict system-specific validation belongs to later system modules

### ID Rules
- ids must be stable, unique, and opaque
- slugs are optional and human-readable
- storage paths must not be derived from user-controlled relative paths

## 9. Legacy Adapter Strategy

### Decision
Legacy compatibility should live in adapters, not in new core services.

### Adapter Location
- `legacy/adapters/storage`
- `legacy/adapters/lore`
- `legacy/adapters/config`

### Adapter Responsibilities
- read legacy file shapes
- normalize old aliases:
  - `environment -> area_id`
  - `setting/settings/world -> context fields`
  - `payload/result -> canonical envelope`
- infer record type
- generate canonical summaries
- preserve provenance in `source.origin = legacy_import`

### Adapter Rules
- adapters may be heuristic
- core writes must not be heuristic
- ambiguous legacy records should be flagged, not silently forced

### Example Legacy-to-Canonical Mapping

#### Legacy
```json
{
  "schema_version": "1.0",
  "saved_at": "2026-03-14T12:00:00Z",
  "filename": "npc/npc_20260314T120000.json",
  "payload": {
    "profession": "guard",
    "environment": "fenmir"
  },
  "result": {
    "type": "npc",
    "name": "Arvid",
    "text": "....",
    "metadata": {
      "setting": "lands_of_legend",
      "environment": "fenmir"
    }
  }
}
```

#### Canonical
```json
{
  "schema_version": "1.0",
  "record_version": 1,
  "id": "rec_imported_...",
  "type": "character_record",
  "title": "Arvid",
  "slug": "arvid",
  "system": {
    "id": "cypher",
    "addon_id": ""
  },
  "context": {
    "genre_id": "fantasy",
    "setting_id": "lands_of_legends",
    "campaign_id": ""
  },
  "source": {
    "kind": "generated",
    "origin": "legacy_import",
    "sourcebook": "",
    "pages": [],
    "external_ref": "npc/npc_20260314T120000.json"
  },
  "content": {
    "legacy_payload": {
      "profession": "guard",
      "environment": "fenmir"
    },
    "legacy_result": {
      "type": "npc",
      "text": "...."
    }
  },
  "metadata": {
    "tags": ["npc"],
    "summary": "",
    "description": "",
    "area_id": "fenmir",
    "location_id": "",
    "visibility": "private",
    "status": "active",
    "images": []
  },
  "audit": {
    "created_at": "2026-03-14T12:00:00Z",
    "updated_at": "2026-03-14T12:00:00Z",
    "created_by": "legacy_import",
    "updated_by": "legacy_import"
  },
  "links": [],
  "extensions": {
    "legacy_type": "npc"
  }
}
```

## 10. Wave A Implementation Order

### Step 1
Create the pristine folder skeleton only.

### Step 2
Add core contracts:
- record schema helpers
- context schema helpers
- source schema helpers

### Step 3
Add storage interfaces and file-backed implementation.

### Step 4
Add validation and summary projection logic.

### Step 5
Add legacy storage adapter runner for read-only migration tests.

### Step 6
Add tests for:
- create/get/update/delete/restore/expunge
- summary projection
- malformed record rejection
- legacy record translation

## 11. Wave A Exit Criteria
- app core can boot with no systems loaded
- canonical records can be written and read through one storage API
- context model is enforced consistently
- no core code relies on legacy aliases
- at least one legacy record can be translated through adapter code into the new envelope

## 12. Explicit Deferred Items
- search provider implementation details
- lore CRUD implementation details
- system plugin contract details
- addon contract details
- UI routing structure
- authentication and multi-user ownership model

## 13. Decisions Locked by This Spec
- use `app/core`, `app/systems`, and `app/plugins`
- use a single canonical record envelope
- use `system -> genre -> setting -> campaign` as the only canonical context hierarchy
- keep legacy compatibility in adapters only
- keep Wave A file-based

## 14. Recommended Next Document
After this spec, the next planning document should be:
- `REBUILD_WAVE_B_SPEC.md`

That should define:
- search provider contracts
- content CRUD contracts
- lore/content indexing
- normalized result-card schema
