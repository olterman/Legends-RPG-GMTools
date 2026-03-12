# API Reference

Detailed reference for the Lands of Legends GM-Tools API.

Base URL (local): `http://localhost:5000`

## Conventions

- Request/response format: JSON
- Errors: JSON with `{"error": "..."}` and non-2xx status
- Generation endpoints persist results to `storage/*.json`
- Optional deterministic behavior via `seed`

## Health and Metadata

### `GET /health`
Returns service health and active setting name.

Example response:
```json
{
  "status": "ok",
  "setting": "Lands of Legends"
}
```

### `GET /meta`
Returns generator metadata for UI clients.

Key fields:
- `types`
- `genders`
- `races`
- `professions`
- `environments`
- `monster_environments`
- `monster_roles`
- `monster_families`
- `styles`

### `GET /meta/races`
Returns full race map from config, including variants.

### `POST /reload`
Reloads all YAML config from disk into live app state.

Example response:
```json
{
  "status": "reloaded",
  "top_level_keys": ["cyphers", "encounters", "environments"]
}
```

## Generation Endpoints

All generation endpoints:
- method: `POST`
- content type: `application/json`
- return generated object plus `storage` metadata

### `POST /generate/character`
Required payload:
- `gender`
- `race`
- `profession`
- `environment`

Optional payload:
- `variant`
- `mood`
- `seed`

### `POST /generate/npc`
Same required/optional fields as character.

Adds stat block fields:
- `stat_block`
- `stat_block_text`

### `POST /generate/monster`
Required payload:
- `environment`

Optional payload:
- `family` (random if omitted)
- `role` (random if omitted)
- `mood`
- `seed`

Adds stat block fields:
- `stat_block`
- `stat_block_text`

### `POST /generate/settlement`
Required payload:
- `environment`

Optional payload:
- `mood`
- `seed`

### `POST /generate/encounter`
Required payload:
- `environment`

Optional payload:
- `seed`

### `POST /generate/cypher`
Required payload:
- `environment`

Optional payload:
- `seed`

### `POST /generate/inn`
Required payload:
- `environment`

Optional payload:
- `mood`
- `seed`

## Batch Generation

### `POST /generate/batch`
Payload:
```json
{
  "seed": "campaign-1",
  "items": [
    {
      "type": "character",
      "gender": "female",
      "race": "human",
      "profession": "rogue",
      "environment": "fenmir_highlands"
    },
    {
      "type": "cypher",
      "environment": "cirdion"
    }
  ]
}
```

Behavior:
- `items` must be a list
- each item must include `type`
- each item is generated independently
- successful items are persisted

Response:
- `results`: successful generated items
- `errors`: failed items with `index`, `error`, and original `item`
- status code:
  - `200` when all succeed
  - `207` on partial success

## Storage Endpoints

### `GET /storage`
Returns list of saved records with summary fields:
- `filename`
- `saved_at`
- `type`
- `name`
- `metadata`

### `GET /storage/<filename>`
Returns full saved record:
- `saved_at`
- `filename`
- `payload`
- `result`

### `GET /storage/search`
Query params (all optional):
- `type`
- `environment`
- `race`
- `profession`
- `name`

Example:
```bash
curl -s "http://localhost:5000/storage/search?type=npc&environment=fenmir_highlands"
```

## Compendium Endpoints

### `GET /compendium`
Returns parsed index counts from `CSRD/compendium/index.json`.

### `GET /compendium/<item_type>`
`item_type` must be one of:
- `cypher`
- `creature`
- `character_type`
- `flavor`
- `descriptor`
- `focus`
- `ability`

Returns list plus count.

### `GET /compendium/<item_type>/<slug>`
Returns full compendium entry JSON.

### `GET /compendium/search`
Query params:
- `type` (optional: `cypher`, `creature`, `character_type`, `flavor`, `descriptor`, `focus`, or `ability`)
- `q` (optional search query)

Searches title/slug/category/environment/level in listed entries.

## Determinism and Seeds

RNG behavior:
- if `payload.seed` exists, that seed controls generation
- else if `?seed=` query param is set, it is combined with payload for deterministic results
- else generation is random

For batch:
- request-level `seed` is passed as global seed
- per-item payload still influences deterministic output

## Common Errors

Examples:
- missing required fields, e.g. `character requires gender, race, profession, and environment`
- unknown type in batch, e.g. `unknown type 'foo'`
- invalid compendium type, e.g. `item_type must be 'cypher' or 'creature'`
- missing file, e.g. `No saved result named '...'`

## cURL Examples

Generate NPC:
```bash
curl -s -X POST http://localhost:5000/generate/npc \
  -H 'Content-Type: application/json' \
  -d '{
    "gender": "male",
    "race": "human",
    "profession": "retired_warrior",
    "environment": "fenmir_highlands",
    "seed": "npc-001"
  }'
```

Generate monster with random role/family:
```bash
curl -s -X POST http://localhost:5000/generate/monster \
  -H 'Content-Type: application/json' \
  -d '{"environment":"gate_ruins"}'
```

Load saved record:
```bash
curl -s "http://localhost:5000/storage/character_20260311T173330.json"
```
