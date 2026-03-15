from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.contracts import (
    build_inn_manifest,
    build_region_manifest,
    build_settlement_manifest,
    build_subregion_manifest,
)
from app.core.contracts.context import normalize_token


@dataclass(frozen=True)
class PublishResult:
    manifest_path: Path
    lore_path: Path
    item_id: str
    item_label: str
    item_kind: str
    ui_url: str


class GenerationPublisher:
    def __init__(self, *, project_root: Path) -> None:
        self.project_root = project_root

    def list_regions(self, *, system_id: str, addon_id: str, module_id: str) -> list[dict[str, str]]:
        return self._list_manifest_collection(
            self._module_root(system_id=system_id, addon_id=addon_id, module_id=module_id) / "regions"
        )

    def list_subregions(
        self,
        *,
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
    ) -> list[dict[str, str]]:
        return self._list_manifest_collection(
            self._module_root(system_id=system_id, addon_id=addon_id, module_id=module_id)
            / "regions"
            / region_id
            / "subregions"
        )

    def list_places(
        self,
        *,
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
        subregion_id: str,
        collection_name: str,
    ) -> list[dict[str, str]]:
        root = self._module_root(system_id=system_id, addon_id=addon_id, module_id=module_id) / "regions" / region_id
        if subregion_id:
            root = root / "subregions" / subregion_id
        return self._list_manifest_collection(root / collection_name)

    def publish_region(
        self,
        *,
        system_id: str,
        addon_id: str,
        module_id: str,
        title: str,
        summary: str,
        markdown_body: str,
        provider_id: str,
    ) -> PublishResult:
        module_root = self._module_root(system_id=system_id, addon_id=addon_id, module_id=module_id)
        item_id = self._normalized_id(title, "Region title is required")
        item_root = module_root / "regions" / item_id
        manifest = build_region_manifest(
            manifest_id=item_id,
            label=title,
            status="draft",
            summary=summary,
            notes=f"Generated in GMForge via {provider_id}.",
            description="",
            details={},
            source_refs=[f"generated:{provider_id}"],
        )
        lore_root = module_root / "lore" / "regions" / item_id
        return self._publish_node(
            item_root=item_root,
            manifest=manifest,
            lore_root=lore_root,
            markdown_body=markdown_body,
            title=title,
            item_kind="top_level_region",
            ui_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{item_id}",
        )

    def publish_subregion(
        self,
        *,
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
        title: str,
        summary: str,
        markdown_body: str,
        provider_id: str,
    ) -> PublishResult:
        module_root = self._module_root(system_id=system_id, addon_id=addon_id, module_id=module_id)
        item_id = self._normalized_id(title, "Subregion title is required")
        region_root = module_root / "regions" / region_id
        if not region_root.exists():
            raise FileNotFoundError(f"Region not found: {region_id}")
        item_root = region_root / "subregions" / item_id
        manifest = build_subregion_manifest(
            manifest_id=item_id,
            label=title,
            status="draft",
            summary=summary,
            notes=f"Generated in GMForge via {provider_id}.",
            description="",
            details={},
            source_refs=[f"generated:{provider_id}"],
        )
        lore_root = module_root / "lore" / "regions" / region_id / "subregions" / item_id
        return self._publish_node(
            item_root=item_root,
            manifest=manifest,
            lore_root=lore_root,
            markdown_body=markdown_body,
            title=title,
            item_kind="subregion",
            ui_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}/subregions/{item_id}",
        )

    def publish_settlement_like(
        self,
        *,
        kind: str,
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
        subregion_id: str,
        title: str,
        summary: str,
        markdown_body: str,
        provider_id: str,
    ) -> PublishResult:
        if kind not in {"settlement", "village", "city"}:
            raise ValueError(f"Unsupported settlement-like kind '{kind}'")
        collection_name = f"{kind}s" if kind != "city" else "cities"
        module_root = self._module_root(system_id=system_id, addon_id=addon_id, module_id=module_id)
        item_id = self._normalized_id(title, f"{kind.title()} title is required")
        target_root, lore_root_base, ui_base = self._resolve_region_target(
            module_root=module_root,
            system_id=system_id,
            addon_id=addon_id,
            module_id=module_id,
            region_id=region_id,
            subregion_id=subregion_id,
        )
        item_root = target_root / collection_name / item_id
        manifest = build_settlement_manifest(
            manifest_id=item_id,
            label=title,
            kind=kind,
            status="draft",
            summary=summary,
            notes=f"Generated in GMForge via {provider_id}.",
            description="",
            details={},
            source_refs=[f"generated:{provider_id}"],
        )
        lore_root = lore_root_base / collection_name / item_id
        return self._publish_node(
            item_root=item_root,
            manifest=manifest,
            lore_root=lore_root,
            markdown_body=markdown_body,
            title=title,
            item_kind=kind,
            ui_url=f"{ui_base}/{collection_name}/{item_id}",
        )

    def publish_inn(
        self,
        *,
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
        subregion_id: str,
        parent_collection: str,
        parent_id: str,
        title: str,
        summary: str,
        markdown_body: str,
        provider_id: str,
    ) -> PublishResult:
        if parent_collection not in {"villages", "cities", "settlements"}:
            raise ValueError(f"Unsupported inn parent collection '{parent_collection}'")
        module_root = self._module_root(system_id=system_id, addon_id=addon_id, module_id=module_id)
        item_id = self._normalized_id(title, "Inn title is required")
        target_root, lore_root_base, ui_base = self._resolve_region_target(
            module_root=module_root,
            system_id=system_id,
            addon_id=addon_id,
            module_id=module_id,
            region_id=region_id,
            subregion_id=subregion_id,
        )
        parent_root = target_root / parent_collection / parent_id
        if not parent_root.exists():
            raise FileNotFoundError(f"Parent place not found: {parent_collection}/{parent_id}")
        item_root = parent_root / "inns" / item_id
        manifest = build_inn_manifest(
            manifest_id=item_id,
            label=title,
            status="draft",
            summary=summary,
            notes=f"Generated in GMForge via {provider_id}.",
            description="",
            details={},
            source_refs=[f"generated:{provider_id}"],
        )
        lore_root = lore_root_base / parent_collection / parent_id / "inns" / item_id
        return self._publish_node(
            item_root=item_root,
            manifest=manifest,
            lore_root=lore_root,
            markdown_body=markdown_body,
            title=title,
            item_kind="inn",
            ui_url=f"{ui_base}/{parent_collection}/{parent_id}/inns/{item_id}",
        )

    def _resolve_region_target(
        self,
        *,
        module_root: Path,
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
        subregion_id: str,
    ) -> tuple[Path, Path, str]:
        region_root = module_root / "regions" / region_id
        if not region_root.exists():
            raise FileNotFoundError(f"Region not found: {region_id}")
        ui_base = f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}"
        lore_root = module_root / "lore" / "regions" / region_id
        if subregion_id:
            region_root = region_root / "subregions" / subregion_id
            if not region_root.exists():
                raise FileNotFoundError(f"Subregion not found: {subregion_id}")
            ui_base = f"{ui_base}/subregions/{subregion_id}"
            lore_root = lore_root / "subregions" / subregion_id
        return region_root, lore_root, ui_base

    def _publish_node(
        self,
        *,
        item_root: Path,
        manifest: dict,
        lore_root: Path,
        markdown_body: str,
        title: str,
        item_kind: str,
        ui_url: str,
    ) -> PublishResult:
        if item_root.exists():
            raise FileExistsError(f"Item already exists: {item_root.name}")
        item_root.mkdir(parents=True, exist_ok=False)
        manifest_path = item_root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        lore_root.mkdir(parents=True, exist_ok=True)
        lore_path = lore_root / "overview.md"
        lore_text = markdown_body.strip()
        if not lore_text.startswith("# "):
            lore_text = f"# {title}\n\n{lore_text}".strip()
        lore_path.write_text(f"{lore_text}\n", encoding="utf-8")

        return PublishResult(
            manifest_path=manifest_path,
            lore_path=lore_path,
            item_id=str(manifest["id"]),
            item_label=str(manifest["label"]),
            item_kind=item_kind,
            ui_url=ui_url,
        )

    def _list_manifest_collection(self, root: Path) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if not root.exists() or not root.is_dir():
            return items
        for child in sorted(root.iterdir()):
            manifest_path = child / "manifest.json"
            if not child.is_dir() or not manifest_path.exists():
                continue
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            items.append({"id": str(payload.get("id") or child.name), "label": str(payload.get("label") or child.name)})
        return items

    def _normalized_id(self, title: str, error_message: str) -> str:
        item_id = normalize_token(title)
        if not item_id:
            raise ValueError(error_message)
        return item_id

    def _module_root(self, *, system_id: str, addon_id: str, module_id: str) -> Path:
        root = (
            self.project_root
            / "app"
            / "systems"
            / normalize_token(system_id)
            / "addons"
            / normalize_token(addon_id)
            / "modules"
            / normalize_token(module_id)
        )
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Module not found: {system_id}/{addon_id}/{module_id}")
        return root
