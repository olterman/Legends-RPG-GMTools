# Land Of Legends Taxonomy Migration Note

## Purpose
Record intentional taxonomy changes between the legacy `Lands of Legends` lore structure and the rebuilt `Land of Legends` module structure.

This note exists for migration clarity only.

It should not be copied into finished in-world rule text, module lore, or player-facing setting content.

## Scope
Applies to the rebuilt module:

- `app/systems/cypher/addons/godforsaken/modules/land_of_legends/`

## Intentional Changes

### 1. Naming
- Legacy naming often used `Lands of Legends`
- Rebuild canonical naming is `Land of Legends`
- Rebuild canonical setting/module id is `land_of_legends`

### 2. Small Folk
- In the rebuild taxonomy, `Duergar` is grouped under `Small Folk`
- This is an intentional editorial change from the legacy lore structure

### 3. The Others
- The rebuild introduces a new top-level people grouping: `The Others`
- `Velim` now belongs under `The Others`
- In legacy structure, `Velim` was previously grouped under `Small Folk`

### 4. Fellic Taxonomy
- The rebuild now uses a normalized Latin-style subgroup naming set for Fellic-related taxonomy review
- Current Fellic subgroup names are:
  - `Feline`
  - `Lupine`
  - `Canine`
  - `Ursine`
  - `Bovine`
  - `Chelonian`
  - `Avian`
  - `Anatine`
- This is an intentional terminology decision for the rebuild taxonomy layer
- It should be treated as a migration/editorial note until final canon naming is locked

## Current Rebuild People Review Groups
The rebuild currently tracks these top-level people groups for review:
- `Human`
- `Small Folk`
- `Fellic`
- `The Others`
- `Alfir`
- `Uruk`

These groupings are part of the active rebuild taxonomy review and may continue to evolve before final canon/module content is locked.

## Migration Rule
When importing or reconciling legacy `Lands of Legends` material:
- do not assume legacy taxonomy is final
- use this note to explain why a mapping differs
- keep the migration rationale in adapter/migration space, not in finished system/module content
