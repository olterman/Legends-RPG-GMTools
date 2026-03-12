# Setting Config Layer

Each setting folder contains shared config for that core setting.

Example:
- `config/settings/fantasy/`

Load precedence (low -> high):
1. `config/*.yaml` (legacy base)
2. `config/core/*.yaml` (shared cross-setting)
3. `config/settings/<core_setting>/*.yaml` (setting-shared)
4. `config/worlds/<world_id>/*.yaml` (world overrides)

`<core_setting>` is selected from `world.core_setting` in the active world folder.
