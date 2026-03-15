from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any


class PluginService:
    def __init__(self, *, project_root: Path) -> None:
        self.project_root = project_root
        self.plugins_root = project_root / "app" / "plugins"
        self.settings_path = project_root / "config" / "plugins_settings.json"
        self.secrets_path = project_root / "data" / "plugins" / "plugin_secrets.json"

    def discover_plugins(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if not self.plugins_root.exists() or not self.plugins_root.is_dir():
            return items
        for child in sorted(self.plugins_root.iterdir()):
            if not child.is_dir() or child.name.startswith(".") or child.name.startswith("_"):
                continue
            metadata = self._load_plugin_metadata(child)
            if metadata is None:
                continue
            items.append(metadata)
        return items

    def get_plugin(self, plugin_id: str) -> dict[str, Any] | None:
        wanted = str(plugin_id or "").strip()
        if not wanted:
            return None
        for plugin in self.discover_plugins():
            if str(plugin.get("id") or "") == wanted:
                return plugin
        return None

    def load_settings_store(self) -> dict[str, dict[str, Any]]:
        if not self.settings_path.exists():
            return {}
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        store: dict[str, dict[str, Any]] = {}
        for key, value in payload.items():
            if isinstance(value, dict):
                store[str(key)] = dict(value)
        return store

    def load_plugin_settings(self, plugin_id: str) -> dict[str, Any]:
        plugin_key = str(plugin_id or "").strip()
        merged = dict(self.load_settings_store().get(plugin_key, {}))
        merged.update(self.load_secrets_store().get(plugin_key, {}))
        return merged

    def load_secrets_store(self) -> dict[str, dict[str, Any]]:
        if not self.secrets_path.exists():
            return {}
        try:
            payload = json.loads(self.secrets_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        store: dict[str, dict[str, Any]] = {}
        for key, value in payload.items():
            if isinstance(value, dict):
                store[str(key)] = dict(value)
        return store

    def is_enabled(self, plugin_id: str) -> bool:
        metadata = self.get_plugin(plugin_id)
        if metadata is None:
            return False
        settings = self.load_plugin_settings(plugin_id)
        enabled_value = settings.get("enabled")
        if enabled_value is None:
            return bool(metadata.get("enabled_by_default", False))
        return bool(enabled_value)

    def load_generation_providers(self) -> list[Any]:
        providers: list[Any] = []
        for plugin in self.discover_plugins():
            plugin_id = str(plugin.get("id") or "").strip()
            if not plugin_id or not self.is_enabled(plugin_id):
                continue
            provider = self._load_generation_provider(plugin)
            if provider is not None:
                providers.append(provider)
        return providers

    def _load_plugin_metadata(self, plugin_root: Path) -> dict[str, Any] | None:
        metadata_path = plugin_root / "plugin.json"
        if not metadata_path.exists():
            return None
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        plugin_id = str(payload.get("id") or plugin_root.name).strip() or plugin_root.name
        payload["id"] = plugin_id
        payload["name"] = str(payload.get("name") or plugin_id.replace("_", " ").title())
        payload["status"] = str(payload.get("status") or "planned")
        payload["bundled"] = bool(payload.get("bundled", True))
        payload["enabled_by_default"] = bool(payload.get("enabled_by_default", False))
        payload["root_path"] = str(plugin_root)
        return payload

    def _load_generation_provider(self, plugin: dict[str, Any]) -> Any | None:
        plugin_id = str(plugin.get("id") or "").strip()
        if not plugin_id:
            return None
        try:
            module = importlib.import_module(f"app.plugins.{plugin_id}.provider")
        except ModuleNotFoundError:
            return None
        factory = getattr(module, "build_generation_provider", None)
        if factory is None:
            return None
        return factory(plugin=plugin, settings=self.load_plugin_settings(plugin_id))
