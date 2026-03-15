# Ollama Local Plugin

This bundled plugin provides an Ollama-backed generation provider for the
GMForge generation workspace.

Configuration lives in `config/plugins_settings.json` under `ollama_local`.

Supported settings:
- `base_url`
- `default_model`
- `keep_alive`
- `system_prompt`

Environment fallbacks:
- `GMFORGE_OLLAMA_BASE_URL`
- `GMFORGE_OLLAMA_MODEL`
- `GMFORGE_OLLAMA_KEEP_ALIVE`
- `GMFORGE_OLLAMA_SYSTEM_PROMPT`
