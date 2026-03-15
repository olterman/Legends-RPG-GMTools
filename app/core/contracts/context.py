from __future__ import annotations

import re
from typing import Any

CONTEXT_SCHEMA_VERSION = "1.0"
NONE_SYSTEM_ID = "none"


def normalize_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def build_context(
    *,
    system_id: Any = NONE_SYSTEM_ID,
    setting_id: Any = "",
    campaign_id: Any = "",
) -> dict[str, str]:
    system = normalize_token(system_id) or NONE_SYSTEM_ID
    setting = normalize_token(setting_id)
    campaign = normalize_token(campaign_id)
    return {
        "system_id": system,
        "setting_id": setting,
        "campaign_id": campaign,
    }


def validate_context(context: dict[str, Any]) -> dict[str, str]:
    if not isinstance(context, dict):
        raise ValueError("context must be an object")

    normalized = build_context(
        system_id=context.get("system_id"),
        setting_id=context.get("setting_id"),
        campaign_id=context.get("campaign_id"),
    )

    if not normalized["system_id"]:
        raise ValueError("context.system_id is required")
    if normalized["campaign_id"] and not normalized["setting_id"]:
        raise ValueError("context.campaign_id requires context.setting_id")

    return normalized
