# Ollama Local Plugin

This plugin adds API routes that call a local/LAN Ollama instance and ground responses with chunks from the local vector index.

## Endpoints

- `GET /plugins/ollama-local/health`
- `POST /plugins/ollama-local/query`

## Environment

- `LOL_OLLAMA_BASE_URL` (default: `http://127.0.0.1:11434`)
- `LOL_OLLAMA_DEFAULT_MODEL` (default: `llama3.1`)

## Query payload

```json
{
  "q": "What does Godforsaken say about black dogs?",
  "model": "llama3.1",
  "k": 8,
  "compendium_id": "godforsaken",
  "base_url": "http://192.168.1.42:11434"
}
```

`base_url` is optional; if omitted, the plugin uses `LOL_OLLAMA_BASE_URL`.

## Response

Returns:
- model answer text
- cited vector chunks used as context
- selected model/base URL metadata
