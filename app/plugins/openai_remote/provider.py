from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request as urllib_request

from app.core.generation.service import ExternalAIDraftProvider


class OpenAIRemoteProvider(ExternalAIDraftProvider):
    provider_id = "openai_remote"
    provider_label = "OpenAI Remote"

    def __init__(self, *, plugin: dict[str, Any], settings: dict[str, Any]) -> None:
        super().__init__(plugin=plugin, settings=settings)

    def generate_text(self, *, prompt: str) -> str:
        api_key = self._setting("api_key") or os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("GMFORGE_OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("OpenAI provider requires an API key in plugin settings or OPENAI_API_KEY")
        base_url = self._setting("base_url") or os.getenv("GMFORGE_OPENAI_BASE_URL", "").strip() or "https://api.openai.com"
        model = self._setting("default_model") or os.getenv("GMFORGE_OPENAI_MODEL", "").strip() or "gpt-4o-mini"
        system_prompt = self._setting("system_prompt") or os.getenv("GMFORGE_OPENAI_SYSTEM_PROMPT", "").strip()
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }
        response = self._post_json(
            url=f"{base_url.rstrip('/')}/v1/chat/completions",
            payload=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        choices = response.get("choices") if isinstance(response, dict) else []
        if not isinstance(choices, list) or not choices:
            raise ValueError("OpenAI response did not include any choices")
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        text = str(message.get("content") or "").strip()
        if not text:
            raise ValueError("OpenAI response content was empty")
        return text

    def _post_json(self, *, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                **headers,
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=300) as response:
                text = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"OpenAI request failed with HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise ValueError(f"OpenAI request failed: {exc.reason}") from exc
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("OpenAI response was not a JSON object")
        return data


def build_generation_provider(*, plugin: dict[str, Any], settings: dict[str, Any]) -> OpenAIRemoteProvider:
    return OpenAIRemoteProvider(plugin=plugin, settings=settings)
