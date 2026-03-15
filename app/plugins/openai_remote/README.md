# OpenAI Remote Plugin

This bundled plugin provides an OpenAI-backed generation provider for the
GMForge generation workspace.

Configuration lives in `config/plugins_settings.json` under `openai_remote`.

Supported settings:
- `base_url`
- `default_model`
- `system_prompt`
- `api_key`

The plugin also accepts environment fallbacks:
- `OPENAI_API_KEY`
- `GMFORGE_OPENAI_API_KEY`
- `GMFORGE_OPENAI_BASE_URL`
- `GMFORGE_OPENAI_MODEL`
- `GMFORGE_OPENAI_SYSTEM_PROMPT`
