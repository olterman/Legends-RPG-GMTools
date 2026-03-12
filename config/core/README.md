# Core Config Layer

`config/core/` is reserved for shared configuration that applies across all worlds.

Suggested contents over time:
- shared styles
- shared generation defaults
- shared base rules/tables

Load precedence (lowest -> highest):
1. `config/*.yaml` (legacy flat files)
2. `config/core/*.yaml` (shared layer)
3. `config/worlds/<world_id>/*.yaml` (world overrides)

This allows a world creation wizard to scaffold a new folder with only its deltas.
