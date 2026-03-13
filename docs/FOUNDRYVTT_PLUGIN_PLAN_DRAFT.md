# Draft Plan: FoundryVTT Plugin for Direct Sync

## Goal
Create a FoundryVTT module that can communicate with this app and directly transfer:
- Characters
- Items (including cyphers/artifacts/equipment/attacks)
- Journal entries

The sync should support both:
- Foundry -> App (import into local storage)
- App -> Foundry (export/create/update in Foundry)

## Current Project Context
- Existing conversion logic already exists in:
  - `Plugins/foundryVTT/importer.py`
  - `Plugins/foundryVTT/exporter.py`
- Existing app endpoints for character import/export already exist (server-side bridge).
- Plugin enable/disable state already exists in app (`config/plugins_state.json` + index plugin cards).

This plan builds on that foundation and moves communication to a true Foundry module.

## High-Level Architecture

### Components
1. Foundry module (client-side)
- Adds UI buttons and sync dialogs in Foundry.
- Reads selected Actor/Item/JournalEntry from Foundry document APIs.
- Calls app HTTP endpoints over local network.

2. App plugin API (server-side)
- Receives Foundry payloads and stores normalized records.
- Returns save references and conflict info.
- Provides export payloads that Foundry can ingest.

3. Mapping layer
- Reuses existing importer/exporter translation functions.
- Keeps schema conversion isolated from route handlers.

### Data Flow
1. Foundry user clicks `Send to GM-Tools`.
2. Foundry module serializes document payload.
3. Module POSTs to app plugin endpoint.
4. App maps payload -> canonical record -> saves to storage.
5. App returns success + filename + summary.
6. Optional backlink UUID metadata is stored on both sides.

## Security Model (Minimum)
- App API key/token required for plugin sync endpoints.
- CORS restricted to configured Foundry origin(s).
- Read/write routes namespaced under `/plugins/foundryvtt/*`.
- Optional allowlist: only localhost/LAN ranges.
- Log every sync action with timestamp and source.

## Endpoint Draft (App Side)

### Handshake
- `GET /plugins/foundryvtt/health`
- `POST /plugins/foundryvtt/handshake`
  - validates token, returns version compatibility + capabilities

### Import from Foundry
- `POST /plugins/foundryvtt/import/actor`
- `POST /plugins/foundryvtt/import/item`
- `POST /plugins/foundryvtt/import/journal`

### Export to Foundry
- `POST /plugins/foundryvtt/export/character_sheet/<filename>`
- `POST /plugins/foundryvtt/export/storage/<filename>`
- `POST /plugins/foundryvtt/export/lore/<slug>`

### Optional Batch
- `POST /plugins/foundryvtt/import/batch`
- `POST /plugins/foundryvtt/export/batch`

## Foundry Module Structure (Draft)
- `module.json`
- `scripts/main.js`
- `scripts/api-client.js`
- `scripts/mappers/actor.js`
- `scripts/mappers/item.js`
- `scripts/mappers/journal.js`
- `scripts/ui/sync-dialog.js`
- `styles/module.css`
- `templates/sync-dialog.hbs`

## Mapping Rules (Core)

### Characters
- Foundry `Actor(type=pc)` -> app `character_sheet` (preferred) or `character`.
- Preserve:
  - pools, edges, damage track, recovery rolls
  - descriptor/type/focus
  - chosen abilities/skills/cyphers/artifacts/attacks
  - notes/description

### Items
- Foundry item type routing:
  - `cypher` -> `cypher`
  - `artifact` -> `artifact`
  - `attack` -> `attack`
  - `equipment` -> `equipment`
  - `ability/skill/descriptor/focus/type/flavor` -> corresponding canonical type
- Include source metadata:
  - `source = foundry_vtt`
  - `foundry_uuid`
  - `foundry_world_id`

### Journal Entries
- `JournalEntry` / `JournalEntryPage` -> app `lore` (or `prompt` based on target category).
- Preserve markdown/plaintext content and tags.
- Strip/record internal `@UUID[...]` links as backlink metadata for later rule-link conversion.

## Sync UX (Foundry)

### In Actor/Item/Journal sheets
- Add buttons:
  - `Send to GM-Tools`
  - `Pull from GM-Tools` (when linked)

### Bulk sync dialog
- Select document type + folder + destination mapping.
- Dry run preview:
  - create/update/skip counts
  - conflict list
- Confirm -> execute.

### Conflict handling
- Modes:
  - `create_only`
  - `update_if_newer`
  - `force_update`
- Show per-record diff summary (name/type/modified date/description hash).

## Versioning and Compatibility
- Handshake returns:
  - app plugin API version
  - Foundry system version support matrix
- Use semantic versioning for plugin API:
  - `v1` for initial stable routes
- Include migration strategy for field changes.

## Phased Implementation Plan

### Phase 1: Transport + Auth
- Add namespaced plugin endpoints and token auth.
- Build Foundry module settings:
  - app URL
  - API token
  - timeout/retry
- Implement handshake and health check.

### Phase 2: Character Sync
- Implement actor -> character_sheet import.
- Implement character_sheet -> actor export.
- Add single-document buttons in Actor sheet.

### Phase 3: Item + Cypher Sync
- Implement item import route with type mapping.
- Implement export route for storage item -> Foundry item.
- Add item sheet buttons and folder-level bulk send.

### Phase 4: Journal Sync
- Implement journal/page import route -> lore.
- Preserve uuid links in metadata.
- Add journal sheet bulk send.

### Phase 5: Batch + Conflict UX
- Add batch endpoints and dry-run mode.
- Add conflict strategy UI and summary report.
- Add retry/failure queue in Foundry dialog.

### Phase 6: Polish + Hardening
- Add structured logs and sync history page in app.
- Add plugin health card on index with last successful sync.
- Add test fixtures and smoke tests for core document types.

## Testing Plan

### App tests
- Route auth tests (401/403/200).
- Mapping contract tests for actor/item/journal.
- Roundtrip tests:
  - Foundry JSON -> app record -> Foundry JSON.

### Foundry module tests
- API client tests (token, timeout, retries).
- Mapping tests with exported fixture data.
- Manual integration checklist on target Foundry + Cypher system versions.

## Acceptance Criteria
- Character sync works both directions for baseline Cypher PC sheets.
- Item/cypher/artifact sync creates correctly typed app records.
- Journal sync imports content without losing body text.
- Token auth and origin checks protect plugin endpoints.
- Bulk dry-run preview exists before destructive updates.
- Failures are reported per-record without aborting entire batch.

## Risks and Mitigations
- Foundry schema drift:
  - Keep mappers isolated and version-gated.
- Duplicate record explosion:
  - Use UUID backlink metadata and deterministic matching rules.
- Network friction (self-signed/local certs):
  - Provide clear local HTTP setup docs first, HTTPS optional later.
- Journal formatting mismatch:
  - Normalize to markdown/plain text and keep raw payload snapshots.

## Next Step
Start with Phase 1 + Phase 2 as a minimal usable milestone:
- handshake/auth
- one-click actor import/export
- metadata backlinking enabled from day one.
