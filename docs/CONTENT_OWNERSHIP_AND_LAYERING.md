# Content Ownership And Layering

## Purpose
Define where canonical content lives, where campaign state lives, and how reusable world content is layered without duplication.

This is a core rebuild rule for `GMForge`.

## Main Principle
`GMForge` should separate:
- canonical reusable content
- campaign-local play state

Canonical reusable content belongs to the system/addon/module layer.

Campaign-local play state belongs to the campaign layer.

Campaigns may extend, reference, or override reusable content, but should not mutate the canonical source owned by the module or setting.

## Ownership Layers

### System Or Addon Module Layer
Use this layer for shipped, reusable, authored content.

Examples:
- official rulebook-derived records
- official setting/module lore
- reusable NPC definitions
- reusable locations
- reusable world maps
- reusable item definitions
- reusable factions
- reusable marker layers for setting maps

Typical location:
- `app/systems/<system>/addons/<addon>/modules/<module>/...`

This layer is effectively immutable from the point of view of a campaign.

### Campaign Layer
Use this layer for local play state and campaign-specific content.

Examples:
- player characters
- campaign journals and notes
- session content
- campaign-local maps or map overlays
- campaign-specific lore
- encounter state
- campaign-specific NPC instances or overrides
- discovered markers, GM notes, routes, pins, and stateful annotations

Typical location:
- `content/<system>/<setting>/<campaign>/...`

This layer is mutable by the campaign and should never rewrite the shipped module source.

## Type Ownership Rules

### Characters
- characters are campaign-owned
- a character belongs to one campaign
- canonical storage should be inside the campaign folder

### NPCs
- NPCs are setting/module-owned by default
- the canonical reusable NPC definition belongs to the module or setting
- campaigns may reference an NPC from that canonical layer
- campaigns may create a campaign-local NPC overlay or variant when needed

This avoids duplicating the same NPC across many campaigns while still allowing campaign-specific divergence.

### Maps
- base maps are setting/module-owned
- base marker layers are setting/module-owned
- campaign overlays are campaign-owned

Campaign overlays may contain:
- markers
- notes
- route lines
- encounter pins
- discovered locations
- fog/state

Campaign overlays must not mutate the base map or its base markers.

### Lore
Lore may live in either layer depending on meaning:
- canonical world lore belongs to the module/setting layer
- campaign events, secrets, and local developments belong to the campaign layer

### Items
Items may live in either layer depending on meaning:
- reusable item definitions belong to the module/setting layer
- possessions, campaign loot, and mutable item state belong to the campaign layer

## Overlay Model
When a campaign uses reusable content from a module/setting:
1. the campaign references the canonical entity
2. the campaign may add local state
3. the campaign may add a local override or variant when necessary

This should be treated as a layering model, not as copy-and-mutate.

## Storage Rule
- shipped canonical content belongs in `app/systems/...`
- user-created and campaign-created content belongs in `content/...`
- the database may index relationships between them, but should not be the sole source of truth for the content itself

## API Consequence
The platform should support API surfaces for:
- reading canonical module content
- reading campaign-local content
- creating campaign-local overlays
- resolving effective content views that merge canonical content with campaign-local state where appropriate

## Initial Practical Rule
Use these defaults unless a type-specific exception is justified:
- reusable world content: module/setting-owned
- player-specific or play-state content: campaign-owned
- campaign changes should layer on top of canonical content, not rewrite it
