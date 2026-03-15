# GMForge Core Product Definition

## Purpose
Define the core product identity for `GMForge` so rebuild decisions stay aligned.

## Product Statement
`GMForge` is a core GM platform for managing rules, settings, campaigns, and playable content across multiple RPG systems, with optional plugins for AI assistance and Foundry sync.

## Hard Requirement
The base app must function with:
- no systems loaded
- no plugins loaded

In that state, `GMForge` still provides a usable generic platform core for organizing content and running core workflows.

## Core Capabilities
The `GMForge` core should be able to:
- query and browse rules and reference documents
- create and manage lore
- create and manage characters
- create and manage NPCs
- create and manage items
- create and manage maps
- create and manage campaigns
- log all meaningful user and system actions in a recoverable audit trail
- support global clickable tags, backlinks, and tag-based directories
- store, search, organize, and relate all of the above
- expose core capabilities, systems, addons, and tools through API endpoints as well as browser UI

## Primary User-Facing Hierarchy
The main operational hierarchy is:
- `system`
- `setting`
- `campaign`

This is the structure users should think in when using the app:
1. choose a system
2. choose or create a setting
3. choose or create a campaign inside that setting

## Supporting Taxonomy
`genre` is still important, but it is supporting taxonomy rather than the main user-facing spine.

Genre should help with:
- classification
- filtering
- defaults
- content discovery
- cross-setting organization

But the day-to-day campaign workflow should center on:
- system
- setting
- campaign

## Relationship Rules
- one system can have multiple settings
- one setting can have multiple campaigns
- campaigns inherit from their parent setting
- campaigns can add or override local content without mutating the base setting
- the same app instance can hold multiple systems side by side

## Content Layering
`GMForge` should use layered ownership for reusable world content versus campaign play state.

- canonical reusable content belongs to the system/addon/module layer
- campaign-local play state belongs to the campaign layer
- campaigns may reference or override canonical content without mutating it

Examples:
- characters are campaign-owned
- NPCs are module/setting-owned with campaign overlays when needed
- maps use module-owned base layers plus campaign-owned overlay layers

See [`docs/CONTENT_OWNERSHIP_AND_LAYERING.md`](/home/olterman/Projects/Legends-RPG-GMTools/docs/CONTENT_OWNERSHIP_AND_LAYERING.md).

## Storage Model
`GMForge` should use a hybrid storage architecture.

### File-Backed Source of Truth
User-created and project-created content should remain file-based wherever practical, especially:
- lore
- characters
- NPCs
- items
- maps
- settings and campaign content

These files are the durable source of truth for playable content.

### Database-Backed Relational Layer
The database should hold platform state and relational overlays, especially:
- users
- sessions
- roles and permissions
- audit events
- tags
- backlinks
- relationship indexes
- schema migration tracking

### Design Consequence
- content should remain portable and future-proof
- relational indexes should be rebuildable
- deleting or rebuilding the database must not destroy user-created content files

## Ownership Boundaries

### Core Owns
- content management workflows
- campaign management
- settings management
- storage
- audit logging and event history
- tag and backlink graph services
- authentication and authorization
- user and role management
- database schema migration management
- search
- map management
- generic document/rules querying
- API routing and endpoint conventions for core capabilities

### Systems Own
- what a character means in that ruleset
- what an NPC means in that ruleset
- what an item means in that ruleset
- rules mechanics
- stat structures
- system-native validation
- system API surfaces for system-owned workflows and data

### Plugins Own
- AI-assisted generation or editing
- Foundry sync/import/export
- bundled document ingestion providers such as `docling`
- vector indexing
- external provider integrations
- optional import/export pipelines
- tool/plugin API surfaces for optional capabilities

## Example Boundary
- “Create NPC” is a core capability.
- “What fields does a Cypher NPC have?” is a system capability.
- “Generate that NPC with OpenAI/Ollama help” is a plugin capability.
- “Sync that NPC to Foundry” is a plugin capability.

## Parsing and Ingestion
`GMForge` should use a markdown-first ingestion model.

- raw addon-owned source documents live with their addon
- a bundled-by-default `docling` plugin converts raw source into markdown and html
- addon parsers and importers consume markdown as their primary parsing substrate
- addon rulebook reading surfaces may serve addon-owned html artifacts
- the core never owns sourcebook-specific parsing rules

This keeps one main parsing pipeline for sourcebooks and avoids parallel parser stacks for the same material.

## Audit and Recovery
Every meaningful action should be logged by the core platform, including:
- who performed the action
- when it happened
- what entity was created, updated, deleted, restored, or synced
- the system call or internal action that performed it
- the relevant input payload
- the resulting record ids or affected entities

If AI was used, the audit trail should preserve the relevant prompt and provider metadata so actions can be reviewed or reconstructed later.

## Tags and Backlinks
Tags should be first-class navigational objects in the core platform.

That means:
- every tag is clickable
- every tag is searchable system-wide
- the platform can show all items with a given tag
- the platform can build backlink views
- the platform can build tag directories and relationship views

## Users, Roles, and Auth
The rebuilt platform should include:
- login
- authentication
- authorization
- at minimum a `GM` and `Player` layer

This implies a persistent database-backed identity layer and a managed migration path for schema upgrades.

## Design Consequence
The rebuild should optimize first for:
- strong generic core workflows
- clean system boundaries
- optional plugin enhancements
- API-first access to those capabilities

Not for:
- hardwiring one rules system into the platform
- making AI or Foundry required for baseline usefulness

## API Requirement
All major platform capabilities should be reachable through API endpoints.

That includes:
- core content and campaign workflows
- system-owned record types and rules workflows
- addon-owned rulebook and import surfaces
- tool and plugin operations

The browser UI should be treated as one client of those APIs, not the only access path.
