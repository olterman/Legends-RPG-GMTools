# Sprint Roadmap: Mobile UI, Campaign Mode, Data-Driven Generation

Date opened: 2026-03-13
Status: Active
Scope owner: Legends RPG GMTools core

## Progress Snapshot (Updated March 13, 2026)

### Done
- [x] Added provider-based AI generation architecture (`Ollama Local` and `OpenAI Remote`).
- [x] Added OpenAI plugin defaults and low-cost default model path (`gpt-4o-mini`).
- [x] Added AI provider selection on AI generation and Setting Wizard flows.
- [x] Added semantic/vector retrieval plumbing and initial UI query path.
- [x] Added pluginized Docling ingestion pipeline for local compendium text extraction.
- [x] Added expanded compendium catalog surfaces and per-compendium landing support.

### In Progress
- [ ] Parsing quality pass for official compendiums (type correctness and field normalization).
- [ ] Semantic/LLM response UI normalization into fully clickable, card-native output.
- [ ] Search UX polish for advanced semantic/AI query controls.

### Not Started
- [ ] Campaign Mode MVP dashboard.
- [ ] Auth model + GM/Player account boundaries.
- [ ] Persistent DB migration groundwork.

## Objectives
- Fix mobile UX blockers in navigation and two-column search/output flow.
- Add a Campaign Mode hub for GMs to monitor scenes, actors, and dice activity in one place.
- Upgrade generation pipelines to use existing project data/indexes as first-class input, with YAML as fallback.

## Priority Order
1. Mobile UI fixes (immediate user impact).
2. Campaign Mode MVP (session management impact).
3. Data-driven generation upgrade (quality + scalability impact).
4. Auth and account model (security + role-based UX impact).

## Track 1: Mobile UI

### Goals
- Menu automatically collapses to a hamburger menu on mobile breakpoints.
- Search and output layout avoids sending right-side output below long result lists.

### Implementation Checklist
- [ ] Define shared mobile breakpoint behavior for nav and search pages.
- [ ] Convert top navigation to responsive collapse at mobile widths.
- [ ] Add mobile nav open/close interactions with keyboard and overlay dismissal.
- [ ] Redesign search/output page for mobile:
- [ ] Keep output panel reachable without scrolling past entire result list.
- [ ] Add sticky or segmented mobile view toggle (`Results` / `Output`) where needed.
- [ ] Verify behavior across index, search, lore, and compendium entry points.
- [ ] Add smoke tests for mobile nav visibility and output panel access path.

### Done When
- Mobile users can access menu actions via hamburger on all major pages.
- Output panel is available within 1-2 interactions from search view on phone.
- No excessive vertical scroll required to reach output when results are long.

## Track 2: Campaign Mode

### Goals
- Provide GM dashboard with campaign-level overview of scenes, actors, and dice rollers.

### Implementation Checklist
- [ ] Define `Campaign Mode` information architecture and navigation entry.
- [ ] Add Campaign overview page with three core panels:
- [ ] Scenes (list + quick open + status tags).
- [ ] Actors (PC/NPC presence and quick drill-in).
- [ ] Dice Rollers (recent activity feed and summary counts).
- [ ] Add campaign/session filtering (setting, area, active session).
- [ ] Add data contracts for scene/actor/roll aggregation endpoints.
- [ ] Add initial persistence for session context (active campaign/session state).
- [ ] Add smoke tests for panel rendering and empty-state fallbacks.

### Done When
- GM can open one page and see scenes, actors, and dice activity without context switching.
- Campaign overview supports quick navigation into detail views.
- Dashboard works with empty data and high-volume data sets.

## Track 3: Better Generation (Data-Driven)

### Goals
- Replace YAML-only/random-only generation inputs with data providers that read existing storage, lore, and indexed sources.

### Implementation Checklist
- [x] Define provider interface for generation sources (`yaml`, `storage`, `lore`, `vector/index`) via plugin/provider routing foundations.
- [ ] Implement weighted selection pipeline using existing records before fallback tables.
- [ ] Add source attribution metadata to generated output (`source`, `source_id`, `confidence` when applicable).
- [ ] Add toggles per generator: strict random, mixed, data-first.
- [ ] Add guardrails for sparse datasets (fallback chain and warnings).
- [x] Add quality checks to prevent malformed mixed-source outputs (initial normalization + server-side save safeguards).
- [ ] Add smoke tests for deterministic seeds with mixed providers.

### Done When
- Generators can pull candidate values from existing data stores without manual YAML edits.
- Outputs include source attribution for at least one data-backed segment.
- Fallback to YAML still works when project data is missing or disabled.

## Track 4: Login and GM/Player Accounts

### Goals
- Add authentication so users can sign in.
- Establish role-aware access boundaries between GM and Player accounts.

### Implementation Checklist
- [ ] Define auth model (local password, invite flow, and optional token/session expiry policy).
- [ ] Add account schema and migration plan (user, role, campaign membership, status).
- [ ] Add login/logout/session endpoints and UI flow.
- [ ] Add baseline roles:
- [ ] `gm` role with campaign management rights.
- [ ] `player` role with limited read/write rights based on campaign permissions.
- [ ] Define authorization matrix for key pages and APIs (search, lore, generation, campaign mode, Foundry sync controls).
- [ ] Add guardrails for privileged actions (bulk sync, destructive edits, settings changes).
- [ ] Add smoke tests for auth required routes and role access boundaries.

### Done When
- Users must authenticate to access protected areas.
- GM and Player roles enforce different permissions in UI and API.
- Campaign Mode exposes GM-only controls while allowing safe player-visible views where intended.

## Track 5: Persistent Database Transition

### Goals
- Introduce a persistent database foundation to support auth, campaign state, concurrent edits, sync jobs, and auditability.
- Keep flat-file content writes working during migration, then progressively move domains without a hard cutover.

### Implementation Checklist
- [ ] Choose primary DB target (`PostgreSQL` for multi-user/server use; `SQLite` only for local single-user mode).
- [ ] Add DB config and connection bootstrap (env vars, health checks, startup validation).
- [ ] Introduce repository/data-access layer so APIs stop coupling directly to storage files for operational domains.
- [ ] Phase 1 tables (operational):
- [ ] `users`, `sessions`, `roles`, `campaigns`, `campaign_memberships`.
- [ ] `dice_events`, `sync_jobs`, `locks`, `audit_events`.
- [ ] Add migrations and versioned schema management.
- [ ] Wire auth/account flows to DB-backed storage.
- [ ] Wire campaign mode state and dice history to DB-backed storage.
- [ ] Phase 2 metadata indexing:
- [ ] Add DB metadata index for flat-file content (type/source/setting/area/location/timestamps).
- [ ] Route search/filter operations through DB index while preserving existing JSON payload source.
- [ ] Add background index rebuild and integrity checks.
- [ ] Phase 3 optional full-content migration:
- [ ] Move selected canonical entities fully into DB where transactionality/versioning adds value.
- [ ] Keep export/backup compatibility with flat-file JSON snapshots.
- [ ] Add smoke/integration tests for DB + fallback behavior.

### Done When
- Operational domains run on DB with transactional guarantees.
- Search/filter performance and reliability improve through DB metadata indexing.
- Flat-file compatibility remains available during transition and for backup/export workflows.
- Rollback path exists to file-backed behavior for non-destructive failure scenarios.

## Logging and Delivery

### Work Log
- 2026-03-13: Roadmap created and linked from `ROADMAP.md`.
- 2026-03-13: Added auth/account track for login plus GM/Player role model.
- 2026-03-13: Added persistent database transition track with phased migration plan.
- 2026-03-13: Added AI provider split (`Ollama`/`OpenAI`) into generation and setting wizard flows.
- 2026-03-13: Added semantic/vector retrieval baseline and pluginized Docling ingestion path.
- 2026-03-13: Added progress snapshot section to distinguish completed/in-progress/not-started scope.

### Weekly Update Template
- Date:
- Track:
- Progress:
- Risks/Blockers:
- Smoke-test impact:
- Schema/storage impact:
- Rollback note:
