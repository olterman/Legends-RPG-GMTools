# World Configs

Each subfolder in `config/worlds/` is a world-specific config layer.

Example:
- `config/worlds/lands_of_legends/`

During load, files in a selected world folder are merged after core/legacy config,
so they can override base values safely.

World selection:
- Environment variable: `LOL_WORLD_ID`
- If omitted, the loader infers default world from `config/02_settings.yaml` defaults.
