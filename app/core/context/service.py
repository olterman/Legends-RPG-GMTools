from __future__ import annotations

from typing import Any

from app.core.contracts.context import NONE_SYSTEM_ID, build_context, validate_context


class ContextService:
    def __init__(self, *, default_context: dict[str, Any] | None = None) -> None:
        self.default_context = validate_context(default_context or build_context(system_id=NONE_SYSTEM_ID))

    def resolve(
        self,
        *,
        requested: dict[str, Any] | None = None,
        session: dict[str, Any] | None = None,
        campaign_defaults: dict[str, Any] | None = None,
        setting_defaults: dict[str, Any] | None = None,
        system_defaults: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        layers = [
            system_defaults or {},
            setting_defaults or {},
            campaign_defaults or {},
            session or {},
            requested or {},
        ]

        merged = dict(self.default_context)
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            candidate = dict(merged)
            for key in ("system_id", "setting_id", "campaign_id"):
                value = layer.get(key)
                if value is not None and str(value).strip():
                    candidate[key] = value
            merged = validate_context(candidate)
        return merged

    def clear_to_level(self, context: dict[str, Any], *, level: str) -> dict[str, str]:
        validated = validate_context(context)
        if level == "system":
            return build_context(system_id=validated["system_id"])
        if level == "setting":
            return build_context(
                system_id=validated["system_id"],
                setting_id=validated["setting_id"],
            )
        if level == "campaign":
            return validated
        raise ValueError(f"unsupported context level '{level}'")
