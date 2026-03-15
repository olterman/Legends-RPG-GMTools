from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request as urllib_request

from app.core.generation.service import ExternalAIDraftProvider


class OllamaLocalProvider(ExternalAIDraftProvider):
    provider_id = "ollama_local"
    provider_label = "Ollama Local"

    def __init__(self, *, plugin: dict[str, Any], settings: dict[str, Any]) -> None:
        super().__init__(plugin=plugin, settings=settings)

    def generate_text(self, *, prompt: str) -> str:
        base_url = self._setting("base_url") or os.getenv("GMFORGE_OLLAMA_BASE_URL", "").strip() or "http://127.0.0.1:11434"
        model = self._setting("default_model") or os.getenv("GMFORGE_OLLAMA_MODEL", "").strip() or "llama3.1"
        keep_alive = self._setting("keep_alive") or os.getenv("GMFORGE_OLLAMA_KEEP_ALIVE", "").strip() or "10m"
        system_prompt = self._setting("system_prompt") or os.getenv("GMFORGE_OLLAMA_SYSTEM_PROMPT", "").strip()
        prompt_text = prompt if not system_prompt else f"{system_prompt}\n\n{prompt}"
        response = self._post_json(
            url=f"{base_url.rstrip('/')}/api/generate",
            payload={
                "model": model,
                "prompt": prompt_text,
                "stream": False,
                "keep_alive": keep_alive,
                "options": {"temperature": 0.2},
            },
        )
        text = str(response.get("response") or "").strip()
        if not text:
            raise ValueError("Ollama response was empty")
        return text

    def _post_json(self, *, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=300) as response:
                text = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"Ollama request failed with HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise ValueError(f"Ollama request failed: {exc.reason}") from exc
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Ollama response was not a JSON object")
        return data


def build_generation_provider(*, plugin: dict[str, Any], settings: dict[str, Any]) -> OllamaLocalProvider:
    return OllamaLocalProvider(plugin=plugin, settings=settings)
