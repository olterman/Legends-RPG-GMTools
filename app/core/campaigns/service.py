from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config.loader import MANIFEST_FILENAME, load_json_object
from app.core.contracts.context import build_context, normalize_token, validate_context


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _title_from_token(value: str) -> str:
    return str(value or "").replace("_", " ").strip().title()


class CampaignService:
    def __init__(self, content_root: Path) -> None:
        self.content_root = Path(content_root)
        self.content_root.mkdir(parents=True, exist_ok=True)

    def ensure_setting(
        self,
        *,
        system_id: str,
        expansion_id: str = "",
        setting_id: str,
        setting_label: str = "",
        summary: str = "",
    ) -> dict[str, Any]:
        context = validate_context(
            build_context(
                system_id=system_id,
                setting_id=setting_id,
            )
        )
        setting_path = self.setting_manifest_path(context)
        if setting_path.exists():
            return load_json_object(setting_path)

        payload = {
            "id": context["setting_id"],
            "label": str(setting_label or _title_from_token(context["setting_id"])).strip(),
            "kind": "setting",
            "system_id": context["system_id"],
            "expansion_id": normalize_token(expansion_id),
            "summary": str(summary or "").strip(),
        }
        _write_json(setting_path, payload)
        return payload

    def create_campaign(
        self,
        *,
        system_id: str,
        expansion_id: str = "",
        setting_id: str,
        campaign_id: str,
        campaign_label: str = "",
        summary: str = "",
    ) -> dict[str, Any]:
        context = validate_context(
            build_context(
                system_id=system_id,
                setting_id=setting_id,
                campaign_id=campaign_id,
            )
        )
        self.ensure_setting(
            system_id=context["system_id"],
            expansion_id=expansion_id,
            setting_id=context["setting_id"],
        )

        campaign_path = self.campaign_manifest_path(context)
        if campaign_path.exists():
            raise FileExistsError(f"campaign already exists: {context['campaign_id']}")

        payload = {
            "id": context["campaign_id"],
            "label": str(campaign_label or _title_from_token(context["campaign_id"])).strip(),
            "kind": "campaign",
            "system_id": context["system_id"],
            "expansion_id": normalize_token(expansion_id),
            "setting_id": context["setting_id"],
            "summary": str(summary or "").strip(),
        }
        _write_json(campaign_path, payload)
        return payload

    def list_campaigns(
        self,
        *,
        system_id: str,
        expansion_id: str = "",
        setting_id: str,
    ) -> list[dict[str, Any]]:
        context = validate_context(
            build_context(system_id=system_id, setting_id=setting_id)
        )
        root = self.content_root / context["system_id"] / context["setting_id"]
        if not root.exists():
            return []
        items: list[dict[str, Any]] = []
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            manifest_path = child / MANIFEST_FILENAME
            if not manifest_path.exists():
                continue
            try:
                payload = load_json_object(manifest_path)
            except Exception:
                continue
            if str(payload.get("kind") or "") == "campaign":
                if expansion_id and str(payload.get("expansion_id") or "") != normalize_token(expansion_id):
                    continue
                items.append(payload)
        return items

    def setting_manifest_path(self, context: dict[str, Any]) -> Path:
        ctx = validate_context(context)
        return self.content_root / ctx["system_id"] / ctx["setting_id"] / MANIFEST_FILENAME

    def campaign_manifest_path(self, context: dict[str, Any]) -> Path:
        ctx = validate_context(context)
        return (
            self.content_root
            / ctx["system_id"]
            / ctx["setting_id"]
            / ctx["campaign_id"]
            / MANIFEST_FILENAME
        )
