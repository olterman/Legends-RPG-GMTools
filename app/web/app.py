from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from app.core.app import discover_systems
from app.core.auth import AuthService
from app.core.campaigns import CampaignService
from app.core.content import ContentService
from app.core.contracts import build_record, validate_authored_manifest
from app.core.contracts.context import normalize_token
from app.core.database import ensure_database
from app.core.config import MANIFEST_FILENAME, load_json_object
from app.core.generation import GenerationService
from app.core.generation.service import GenerationRequest
from app.core.lore_docs import load_lore_documents
from app.core.plugins import PluginService
from app.core.rulebooks import build_rulebook_toc, load_rulebook_document, render_rulebook_html
from app.core.search import VectorIndexService

OWNER_USERNAME = "olterman"
OWNER_EMAIL = "patrik@olterman.se"
OWNER_PASSWORD = "changeme"
OWNER_DISPLAY_NAME = "Patrik Olterman"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _systems_root(project_root: Path) -> Path:
    return project_root / "app" / "systems"


def _content_root(project_root: Path) -> Path:
    return project_root / "content"


def _data_root(project_root: Path) -> Path:
    return project_root / "data"


def _db_path(project_root: Path) -> Path:
    return _data_root(project_root) / "gmforge.db"


def _vector_index_root(project_root: Path) -> Path:
    return _data_root(project_root) / "vector_index"


def _branding_root(project_root: Path) -> Path:
    return _data_root(project_root) / "assets" / "branding"


def _branding_asset_info(project_root: Path) -> dict[str, str]:
    branding_root = _branding_root(project_root)
    logo_name = ""
    for candidate in (
        "gmf_logo.svg",
        "gmf-logo.svg",
        "gmf_logo.png",
        "gmf-logo.png",
        "gmf_logo.webp",
        "gmf-logo.webp",
    ):
        if (branding_root / candidate).exists():
            logo_name = candidate
            break
    favicon_name = ""
    for candidate in (
        "favicon.ico",
        "gmf_logo.png",
        "gmf-logo.png",
        "gmf_logo.svg",
        "gmf-logo.svg",
    ):
        if (branding_root / candidate).exists():
            favicon_name = candidate
            break
    return {
        "logo_name": logo_name,
        "logo_url": f"/assets/branding/{logo_name}" if logo_name else "",
        "favicon_name": favicon_name,
        "favicon_url": "/favicon.ico" if favicon_name else "",
    }


def _discover_setting_options(project_root: Path, *, system_id: str, expansion_id: str = "") -> list[dict[str, str]]:
    system_token = normalize_token(system_id)
    if not system_token or system_token == "none":
        return []
    items: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    systems = discover_systems(_systems_root(project_root))
    for system in systems:
        if system["id"] != system_token:
            continue
        for addon in system.get("addons", []):
            addon_id = str(addon.get("id") or "")
            if expansion_id and addon_id != normalize_token(expansion_id):
                continue
            for module in addon.get("modules", []):
                module_id = str(module.get("id") or "")
                if not module_id or module_id in seen_ids:
                    continue
                seen_ids.add(module_id)
                items.append(
                    {
                        "id": module_id,
                        "label": str(module.get("label") or module_id),
                        "expansion_id": addon_id,
                        "source_kind": "module",
                    }
                )
        break
    root = _content_root(project_root) / system_token
    if not root.exists():
        return items
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name.startswith("_"):
            continue
        manifest_path = child / MANIFEST_FILENAME
        if not manifest_path.exists():
            continue
        try:
            payload = load_json_object(manifest_path)
        except Exception:
            continue
        if str(payload.get("kind") or "") != "setting":
            continue
        if expansion_id and str(payload.get("expansion_id") or "") != normalize_token(expansion_id):
            continue
        item_id = str(payload.get("id") or child.name)
        if item_id in seen_ids:
            continue
        items.append(
            {
                "id": item_id,
                "label": str(payload.get("label") or child.name),
                "expansion_id": str(payload.get("expansion_id") or ""),
                "source_kind": "content",
            }
        )
    return items


def _split_system_addons(system: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    core_rules: list[dict[str, str]] = []
    expansions: list[dict[str, str]] = []
    for addon in system.get("addons", []):
        item = {
            "id": addon["id"],
            "label": addon["name"],
            "kind": str(addon.get("kind") or "sourcebook"),
        }
        if item["kind"] == "core_rules":
            core_rules.append(item)
        else:
            expansions.append(item)
    return core_rules, expansions


def _build_workspace_options(
    project_root: Path,
    campaign_service: CampaignService,
    *,
    selected_system_id: str = "",
    selected_expansion_id: str = "",
    selected_setting_id: str = "",
) -> dict[str, Any]:
    systems = discover_systems(_systems_root(project_root))
    system_options = [{"id": "none", "label": "No System"}]
    system_options.extend({"id": system["id"], "label": system["name"]} for system in systems)
    selected_system = normalize_token(selected_system_id) or (systems[0]["id"] if systems else "none")
    core_rules: list[dict[str, str]] = []
    expansions: list[dict[str, str]] = []
    for system in systems:
        if system["id"] == selected_system:
            core_rules, expansions = _split_system_addons(system)
            break
    selected_expansion = normalize_token(selected_expansion_id) or (expansions[0]["id"] if expansions else "")
    settings = _discover_setting_options(
        project_root,
        system_id=selected_system,
        expansion_id=selected_expansion,
    )
    selected_setting = normalize_token(selected_setting_id) or (settings[0]["id"] if settings else "")
    campaigns = []
    if selected_system and selected_setting:
        campaigns = campaign_service.list_campaigns(
            system_id=selected_system,
            expansion_id=selected_expansion,
            setting_id=selected_setting,
        )
    return {
        "systems": system_options,
        "core_rules": core_rules,
        "expansions": expansions,
        "settings": settings,
        "campaigns": campaigns,
        "selected_system_id": selected_system,
        "selected_expansion_id": selected_expansion,
        "selected_setting_id": selected_setting,
    }


def _find_rulebook(
    *,
    project_root: Path,
    system_id: str,
    addon_id: str,
    rulebook_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    systems = discover_systems(_systems_root(project_root))
    for system in systems:
        if system["id"] != system_id:
            continue
        for addon in system.get("addons", []):
            if addon["id"] != addon_id:
                continue
            for rulebook in addon.get("rulebooks", []):
                if rulebook["id"] == rulebook_id:
                    return system, addon, rulebook
    raise FileNotFoundError(f"rulebook not found: {system_id}/{addon_id}/{rulebook_id}")


def _find_module(
    *,
    project_root: Path,
    system_id: str,
    addon_id: str,
    module_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    systems = discover_systems(_systems_root(project_root))
    for system in systems:
        if system["id"] != system_id:
            continue
        for addon in system.get("addons", []):
            if addon["id"] != addon_id:
                continue
            for module in addon.get("modules", []):
                if module["id"] == module_id:
                    return system, addon, module
    raise FileNotFoundError(f"module not found: {system_id}/{addon_id}/{module_id}")


def _load_module_collection(module_root: Path, collection_name: str) -> list[dict[str, Any]]:
    collection_root = module_root / collection_name
    items: list[dict[str, Any]] = []
    if not collection_root.exists() or not collection_root.is_dir():
        return items
    for child in sorted(collection_root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            payload = load_json_object(manifest_path)
        except Exception:
            continue
        item = _normalize_authored_payload(payload, fallback_id=child.name, fallback_label=child.name)
        items.append(item)
    return items


def _load_module_item(module_root: Path, collection_name: str, item_id: str) -> dict[str, Any]:
    manifest_path = module_root / collection_name / item_id / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"module item not found: {collection_name}/{item_id}")
    payload = load_json_object(manifest_path)
    return _normalize_authored_payload(payload, fallback_id=item_id, fallback_label=item_id)


def _load_module_item_collection(
    module_root: Path,
    collection_name: str,
    item_id: str,
    nested_collection_name: str,
) -> list[dict[str, Any]]:
    nested_root = module_root / collection_name / item_id / nested_collection_name
    items: list[dict[str, Any]] = []
    if not nested_root.exists() or not nested_root.is_dir():
        return items
    for child in sorted(nested_root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            payload = load_json_object(manifest_path)
        except Exception:
            continue
        item = _normalize_authored_payload(payload, fallback_id=child.name, fallback_label=child.name)
        items.append(item)
    return items


REGION_CATEGORY_LABELS = {
    "subregions": "Subregions",
    "cities": "Cities",
    "villages": "Villages",
    "settlements": "Settlements",
    "landmarks": "Landmarks",
    "forests": "Forests",
    "rivers": "Rivers",
    "lakes": "Lakes",
    "islands": "Islands",
    "mountains": "Mountains",
    "caves": "Caves",
    "dungeons": "Dungeons",
    "ruins": "Ruins",
}


PLACE_CATEGORY_LABELS = {
    "inns": "Inns",
}


MODULE_COLLECTION_CONFIG: dict[str, dict[str, Any]] = {
    "regions": {
        "label": "Regions",
        "description": "Top-level lands, coasts, wilderness, and major geographic areas in the module.",
        "empty_text": "No regions defined yet.",
        "item_kind_label": "region",
        "detail_route": "region",
    },
    "peoples": {
        "label": "Peoples",
        "description": "Playable and setting-defining peoples, with subgroup links where they exist.",
        "empty_text": "No peoples defined yet.",
        "item_kind_label": "people",
        "detail_route": "people",
    },
    "creatures": {
        "label": "Creatures",
        "description": "Creature taxonomies and non-player species groupings for the setting.",
        "empty_text": "No creature groups defined yet.",
        "item_kind_label": "creature group",
    },
    "items": {
        "label": "Items",
        "description": "Artifacts, cyphers, equipment, weapons, armor, ingredients, and components.",
        "empty_text": "No item categories defined yet.",
        "item_kind_label": "item category",
    },
    "system": {
        "label": "System",
        "description": "Cypher-facing system content like abilities, skills, focus, descriptors, attacks, spells, and cantrips.",
        "empty_text": "No system categories defined yet.",
        "item_kind_label": "system category",
    },
    "lore": {
        "label": "Lore",
        "description": "Canonical module lore documents and lore branches stored in the central lore repository.",
        "empty_text": "No lore categories defined yet.",
        "item_kind_label": "lore section",
    },
}


def _region_category_items(module_root: Path, region_id: str) -> list[dict[str, str]]:
    categories_root = module_root / "regions" / region_id
    items: list[dict[str, str]] = []
    for category_id, label in REGION_CATEGORY_LABELS.items():
        category_path = categories_root / category_id
        if not category_path.exists() or not category_path.is_dir():
            continue
        items.append(
            {
                "id": category_id,
                "label": label,
                "kind": "region_category",
                "path": str(category_path.relative_to(module_root)),
            }
        )
    return items


def _load_manifest_dir_entries(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not root.exists() or not root.is_dir():
        return entries
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            payload = load_json_object(manifest_path)
        except Exception:
            continue
        item = dict(payload)
        item["id"] = str(item.get("id") or child.name)
        item["label"] = str(item.get("label") or child.name)
        entries.append(item)
    return entries


def _load_manifest_file(manifest_path: Path, *, fallback_id: str = "", fallback_label: str = "") -> dict[str, Any]:
    payload = load_json_object(manifest_path)
    return _normalize_authored_payload(
        payload,
        fallback_id=fallback_id or manifest_path.parent.name,
        fallback_label=fallback_label or manifest_path.parent.name,
    )


def _normalize_authored_payload(payload: dict[str, Any], *, fallback_id: str, fallback_label: str) -> dict[str, Any]:
    item = dict(payload)
    item["id"] = str(item.get("id") or fallback_id)
    item["label"] = str(item.get("label") or fallback_label)
    kind = str(item.get("kind") or "").strip().lower()
    if kind in {"top_level_region", "subregion", "settlement", "village", "city", "inn"}:
        item = validate_authored_manifest(item)
    return item


def _find_subregion_path(region_root: Path, subregion_id: str) -> Path | None:
    subregions_root = region_root / "subregions"
    if not subregions_root.exists() or not subregions_root.is_dir():
        return None
    for child in sorted(subregions_root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name == subregion_id and (child / "manifest.json").exists():
            return child
        nested = _find_subregion_path(child, subregion_id)
        if nested is not None:
            return nested
    return None


def _load_place_sections(place_root: Path) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for category_id, label in PLACE_CATEGORY_LABELS.items():
        entries = _load_manifest_dir_entries(place_root / category_id)
        if entries:
            sections.append({"id": category_id, "label": label, "entries": entries})
    return sections


def _add_place_ui_urls(
    sections: list[dict[str, Any]],
    *,
    base_path: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for section in sections:
        updated = dict(section)
        updated_entries: list[dict[str, Any]] = []
        for entry in section.get("entries", []):
            entry = dict(entry)
            if section.get("id") == "inns":
                entry["ui_url"] = f"{base_path}/inns/{entry['id']}"
            updated_entries.append(entry)
        updated["entries"] = updated_entries
        items.append(updated)
    return items


def _module_collection_ui_url(system_id: str, addon_id: str, module_id: str, collection_name: str) -> str:
    return f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/{collection_name}"


def _module_item_ui_url(
    *,
    system_id: str,
    addon_id: str,
    module_id: str,
    collection_name: str,
    item_id: str,
) -> str:
    if collection_name == "regions":
        return f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{item_id}"
    if collection_name == "peoples":
        return f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/peoples/{item_id}"
    if collection_name == "lore":
        return f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/lore/{item_id}"
    return ""


LORE_DOC_LABELS = {
    "overview": "Overview",
    "history": "History",
    "culture": "Culture",
    "religion": "Religion",
    "politics": "Politics",
    "relationships": "Relationships",
    "secrets": "Secrets",
}

LORE_BRANCH_LABELS = {
    "ai_lore": "AI Lore",
    "art_prompts": "Art Prompts",
    "drift_tests": "Drift Tests",
    "race_triage": "Race Triage",
}


def _lore_branch_label(slug: str) -> str:
    return LORE_BRANCH_LABELS.get(slug, slug.replace("_", " ").title())


def _lore_branch_tags(path: Path, *, parent_url: str) -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    if not path.exists() or not path.is_dir():
        return tags
    for child in sorted(path.iterdir()):
        if child.name.startswith(".") or child.name.startswith("_") or not child.is_dir():
            continue
        has_markdown = any(grandchild.is_file() and grandchild.suffix == ".md" for grandchild in child.iterdir())
        if has_markdown:
            tags.append(
                {
                    "label": _lore_branch_label(child.name).lower(),
                    "ui_url": f"{parent_url}/{child.name}",
                }
            )
            continue
        for grandchild in sorted(child.iterdir()):
            if not grandchild.is_dir() or grandchild.name.startswith(".") or grandchild.name.startswith("_"):
                continue
            tags.append(
                {
                    "label": grandchild.name.replace("_", " "),
                    "ui_url": f"{parent_url}/{child.name}/{grandchild.name}",
                }
            )
    return tags


def _load_lore_collection(module_root: Path) -> list[dict[str, Any]]:
    lore_root = module_root / "lore"
    if not lore_root.exists() or not lore_root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for slug, label in LORE_DOC_LABELS.items():
        path = lore_root / f"{slug}.md"
        if path.exists():
            items.append(
                {
                    "id": slug,
                    "label": label,
                    "kind": "lore_document",
                    "status": "active",
                    "summary": f"Canonical {label.lower()} lore for the Land of Legends module.",
                }
            )
    for child in sorted(lore_root.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name.startswith("_"):
            continue
        items.append(
            {
                "id": child.name,
                "label": _lore_branch_label(child.name),
                "kind": "lore_branch",
                "status": "active",
                "summary": (
                    "AI-assisted staging branch for prompts, drift checks, and triage material."
                    if child.name == "ai_lore"
                    else f"Central lore branch for {child.name.replace('_', ' ')} content."
                ),
                "collection_tags": _lore_branch_tags(
                    child,
                    parent_url=f"/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/{child.name}",
                ),
            }
        )
    return items


def _load_lore_branch_entries(
    *,
    module_root: Path,
    branch_root: Path,
    base_url: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(branch_root.iterdir()):
        if path.name.startswith(".") or path.name.startswith("_"):
            continue
        if path.is_file() and path.suffix == ".md":
            items.append(
                {
                    "id": path.stem,
                    "label": LORE_DOC_LABELS.get(path.stem, path.stem.replace("_", " ").title()),
                    "kind": "lore_document",
                    "status": "active",
                    "summary": f"Canonical {path.stem.replace('_', ' ')} lore document.",
                    "ui_url": f"{base_url}/{path.stem}",
                }
            )
        elif path.is_dir():
            items.append(
                {
                    "id": path.name,
                    "label": _lore_branch_label(path.name),
                    "kind": "lore_branch",
                    "status": "active",
                    "summary": (
                        "AI-assisted staging branch for prompts, drift checks, and triage material."
                        if path.name == "ai_lore"
                        else f"Lore branch for {path.name.replace('_', ' ')}."
                    ),
                    "ui_url": f"{base_url}/{path.name}",
                    "collection_tags": _lore_branch_tags(path, parent_url=f"{base_url}/{path.name}"),
                }
            )
    return items


def _resolve_lore_target(module_root: Path, lore_path: list[str]) -> Path:
    target = module_root / "lore"
    for part in lore_path:
        target = target / part
    return target


def _module_collection_cards(
    *,
    system_id: str,
    addon_id: str,
    module_id: str,
    module_root: Path,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for collection_name, config in MODULE_COLLECTION_CONFIG.items():
        if collection_name == "lore":
            items = _load_lore_collection(module_root)
        else:
            items = _load_module_collection(module_root, collection_name)
        enriched_items: list[dict[str, Any]] = []
        for item in items:
            entry = dict(item)
            entry["ui_url"] = _module_item_ui_url(
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
                collection_name=collection_name,
                item_id=entry["id"],
            )
            collection_tags: list[dict[str, str]] = list(entry.get("collection_tags") or [])
            if collection_name == "peoples":
                collection_tags = []
                for subgroup in entry.get("subgroups") or []:
                    collection_tags.append(
                        {
                            "label": str(subgroup),
                            "ui_url": (
                                f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                                f"/peoples/{entry['id']}/subgroups/{subgroup}"
                            ),
                        }
                    )
            elif collection_name == "regions":
                collection_tags = []
                for subregion in _load_module_item_collection(module_root, "regions", entry["id"], "subregions"):
                    collection_tags.append(
                        {
                            "label": str(subregion["label"]),
                            "ui_url": (
                                f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                                f"/regions/{entry['id']}/subregions/{subregion['id']}"
                            ),
                        }
                    )
            entry["collection_tags"] = collection_tags
            enriched_items.append(entry)
        cards.append(
            {
                "id": collection_name,
                "label": config["label"],
                "description": config["description"],
                "empty_text": config["empty_text"],
                "item_kind_label": config["item_kind_label"],
                "badge_field": str(config.get("badge_field") or ""),
                "ui_url": _module_collection_ui_url(system_id, addon_id, module_id, collection_name),
                "count": len(enriched_items),
                "items": enriched_items,
            }
        )
    return cards


def _render_module_item(
    *,
    system: dict[str, Any],
    addon: dict[str, Any],
    module: dict[str, Any],
    module_root: Path,
    item: dict[str, Any],
    item_root: Path,
    item_kind_label: str,
    collection_name: str,
    child_items: list[dict[str, Any]] | None = None,
    child_kind_label: str = "",
    grouped_child_sections: list[dict[str, Any]] | None = None,
    grouped_child_label: str = "",
    back_url: str = "",
    back_label: str = "",
    breadcrumb_links: list[dict[str, str]] | None = None,
) -> str:
    return render_template(
        "module_item.html",
        system=system,
        addon=addon,
        module=module,
        item=item,
        item_kind_label=item_kind_label,
        collection_name=collection_name,
        child_items=child_items or [],
        child_kind_label=child_kind_label,
        grouped_child_sections=grouped_child_sections or [],
        grouped_child_label=grouped_child_label,
        back_url=back_url,
        back_label=back_label,
        breadcrumb_links=breadcrumb_links or [],
        lore_documents=load_lore_documents(item_root, module_root=module_root),
    )


def _load_region_sections(module_root: Path, region_id: str) -> list[dict[str, Any]]:
    def _collect_nested_category_entries(region_path: Path, category_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        subregions_root = region_path / "subregions"
        if not subregions_root.exists() or not subregions_root.is_dir():
            return items
        for child in sorted(subregions_root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            manifest_path = child / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                subregion = _load_manifest_file(manifest_path, fallback_id=child.name, fallback_label=child.name)
            except Exception:
                continue
            direct_entries = _load_manifest_dir_entries(child / category_id)
            for entry in direct_entries:
                entry = dict(entry)
                entry["parent_region_id"] = subregion["id"]
                entry["parent_region_label"] = subregion["label"]
                if category_id == "subregions":
                    entry["ui_url"] = (
                        f"/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/{region_id}/subregions/{entry['id']}"
                    )
                elif category_id == "cities":
                    entry["ui_url"] = (
                        f"/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/{region_id}/subregions/{subregion['id']}/cities/{entry['id']}"
                    )
                elif category_id == "villages":
                    entry["ui_url"] = (
                        f"/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/{region_id}/subregions/{subregion['id']}/villages/{entry['id']}"
                    )
                items.append(entry)
            nested_entries = _collect_nested_category_entries(child, category_id)
            for entry in nested_entries:
                items.append(entry)
        return items

    region_root = module_root / "regions" / region_id
    sections: list[dict[str, Any]] = []
    for category_id, label in REGION_CATEGORY_LABELS.items():
        direct_entries = _load_manifest_dir_entries(region_root / category_id)
        for entry in direct_entries:
            if category_id == "subregions":
                entry["ui_url"] = (
                    f"/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/{region_id}/subregions/{entry['id']}"
                )
            elif category_id == "cities":
                entry["ui_url"] = (
                    f"/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/{region_id}/cities/{entry['id']}"
                )
            elif category_id == "villages":
                entry["ui_url"] = (
                    f"/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/{region_id}/villages/{entry['id']}"
                )
        nested_entries = _collect_nested_category_entries(region_root, category_id)
        entries = direct_entries + nested_entries
        if entries:
            sections.append({"id": category_id, "label": label, "entries": entries})
    return sections


def _load_subregion_sections(subregion_root: Path) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for category_id, label in REGION_CATEGORY_LABELS.items():
        if category_id == "subregions":
            continue
        entries = _load_manifest_dir_entries(subregion_root / category_id)
        if category_id == "cities":
            for entry in entries:
                entry["ui_url"] = (
                    f"/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/"
                    f"{subregion_root.parents[1].name}/subregions/{subregion_root.name}/cities/{entry['id']}"
                )
        elif category_id == "villages":
            for entry in entries:
                entry["ui_url"] = (
                    f"/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/"
                    f"{subregion_root.parents[1].name}/subregions/{subregion_root.name}/villages/{entry['id']}"
                )
        if entries:
            sections.append({"id": category_id, "label": label, "entries": entries})
    return sections


def _serialize_systems(systems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for system in systems:
        item = dict(system)
        addons: list[dict[str, Any]] = []
        for addon in system.get("addons", []):
            addon_item = dict(addon)
            addon_item["api_url"] = f"/api/systems/{system['id']}/addons/{addon['id']}"
            addon_item["modules"] = []
            for module in addon.get("modules", []):
                module_item = dict(module)
                module_item["api_url"] = (
                    f"/api/systems/{system['id']}/addons/{addon['id']}/modules/{module['id']}"
                )
                module_item["ui_url"] = (
                    f"/systems/{system['id']}/addons/{addon['id']}/modules/{module['id']}"
                )
                addon_item["modules"].append(module_item)
            rulebooks: list[dict[str, Any]] = []
            for rulebook in addon.get("rulebooks", []):
                rulebook_item = dict(rulebook)
                rulebook_item["api_url"] = (
                    f"/api/systems/{system['id']}/addons/{addon['id']}/rulebooks/{rulebook['id']}"
                )
                rulebook_item["ui_url"] = (
                    f"/systems/{system['id']}/addons/{addon['id']}/rulebooks/{rulebook['id']}"
                )
                rulebooks.append(rulebook_item)
            addon_item["rulebooks"] = rulebooks
            addons.append(addon_item)
        item["addons"] = addons
        item["api_url"] = f"/api/systems/{system['id']}"
        items.append(item)
    return items


def _serialize_rulebook_payload(
    *,
    system: dict[str, Any],
    addon: dict[str, Any],
    rulebook: dict[str, Any],
    resolved_root: Path,
) -> dict[str, Any]:
    addon_root = resolved_root / "app" / "systems" / system["id"] / "addons" / addon["id"]
    markdown_path = addon_root / rulebook["markdown_path"]
    document = load_rulebook_document(markdown_path, title=rulebook["title"])
    html_path = addon_root / rulebook["html_path"] if rulebook.get("html_path") else None
    html_exists = bool(html_path and html_path.exists() and html_path.is_file())
    return {
        "system": {"id": system["id"], "name": system["name"]},
        "addon": {"id": addon["id"], "name": addon["name"]},
        "rulebook": dict(rulebook),
        "document": {
            "title": document.title,
            "markdown_path": document.markdown_path,
            "toc": [
                {
                    "level": heading.level,
                    "title": heading.title,
                    "anchor": heading.anchor,
                    "line_number": heading.line_number,
                }
                for heading in build_rulebook_toc(document, max_level=2)
            ],
            "headings_count": len(document.headings),
            "html_available": html_exists,
            "ui_url": f"/systems/{system['id']}/addons/{addon['id']}/rulebooks/{rulebook['id']}",
            "html_url": (
                f"/systems/{system['id']}/addons/{addon['id']}/rulebooks/{rulebook['id']}/html"
                if html_exists
                else ""
            ),
            "rendered_html": render_rulebook_html(document),
        },
    }


def _json_error(message: str, *, status: int):
    response = jsonify({"error": message})
    response.status_code = status
    return response


def _request_json() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


def _request_actor_user_id(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("actor_user_id") or "").strip()
    if explicit:
        return explicit
    current_user = getattr(g, "current_user", None)
    return str(getattr(current_user, "id", "") or "")


def _sync_vector_index(vector_service: VectorIndexService) -> dict[str, Any]:
    return vector_service.build()


def _generation_form(
    *,
    title: str = "",
    record_type: str = "lore_entry",
    system_id: str = "",
    expansion_id: str = "",
    setting_id: str = "",
    campaign_id: str = "",
    focus_query: str = "",
    notes: str = "",
    source_kind: str = "",
    provider_id: str = "",
) -> dict[str, str]:
    return {
        "title": title,
        "record_type": record_type,
        "system_id": system_id,
        "expansion_id": expansion_id,
        "setting_id": setting_id,
        "campaign_id": campaign_id,
        "focus_query": focus_query,
        "notes": notes,
        "source_kind": source_kind,
        "provider_id": provider_id,
    }


def _request_bearer_token() -> str:
    header = str(request.headers.get("Authorization") or "").strip()
    if not header:
        return ""
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return value.strip()


def _build_record_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("record"), dict):
        return dict(payload["record"])
    return build_record(
        record_type=payload.get("record_type") or payload.get("type"),
        title=payload.get("title"),
        slug=payload.get("slug"),
        system_id=payload.get("system_id"),
        addon_id=payload.get("addon_id"),
        setting_id=payload.get("setting_id"),
        campaign_id=payload.get("campaign_id"),
        source=payload.get("source") if isinstance(payload.get("source"), dict) else {},
        content=payload.get("content") if isinstance(payload.get("content"), dict) else {},
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        audit=payload.get("audit") if isinstance(payload.get("audit"), dict) else {},
        links=payload.get("links") if isinstance(payload.get("links"), list) else [],
        extensions=payload.get("extensions") if isinstance(payload.get("extensions"), dict) else {},
        record_id=payload.get("id"),
    )


def _merge_record(current: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("record"), dict):
        merged = dict(payload["record"])
        merged["id"] = current["id"]
        return merged

    merged = dict(current)
    for key in ("type", "title", "slug"):
        if key in payload:
            merged[key] = payload[key]

    if any(key in payload for key in ("system_id", "addon_id")):
        system = dict(merged.get("system") or {})
        if "system_id" in payload:
            system["id"] = payload.get("system_id")
        if "addon_id" in payload:
            system["addon_id"] = payload.get("addon_id")
        merged["system"] = system

    if any(key in payload for key in ("setting_id", "campaign_id", "system_id")):
        context = dict(merged.get("context") or {})
        if "system_id" in payload:
            context["system_id"] = payload.get("system_id")
        for key in ("setting_id", "campaign_id"):
            if key in payload:
                context[key] = payload.get(key)
        merged["context"] = context

    for key in ("source", "content", "metadata", "audit", "extensions"):
        if isinstance(payload.get(key), dict):
            nested = dict(merged.get(key) or {})
            nested.update(payload[key])
            merged[key] = nested
    if "links" in payload and isinstance(payload.get("links"), list):
        merged["links"] = payload["links"]
    return merged


def create_app(*, project_root: Path | None = None) -> Flask:
    resolved_root = (project_root or _project_root()).resolve()
    branding = _branding_asset_info(resolved_root)
    ensure_database(_db_path(resolved_root))
    auth_service = AuthService(_db_path(resolved_root))
    auth_service.ensure_user(
        username=OWNER_USERNAME,
        email=OWNER_EMAIL,
        display_name=OWNER_DISPLAY_NAME,
        password=OWNER_PASSWORD,
        role="owner",
    )
    content_service = ContentService(data_root=_data_root(resolved_root), db_path=_db_path(resolved_root))
    campaign_service = CampaignService(_content_root(resolved_root))
    vector_service = VectorIndexService(project_root=resolved_root, index_root=_vector_index_root(resolved_root))
    plugin_service = PluginService(project_root=resolved_root)
    generation_service = GenerationService(vector_service=vector_service, plugin_service=plugin_service)
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
    )
    app.secret_key = os.getenv("GMFORGE_SECRET_KEY", "gmforge-dev-secret")
    app.config["GMFORGE_PROJECT_ROOT"] = str(resolved_root)
    app.config["GMFORGE_AUTH_SERVICE"] = auth_service
    app.config["GMFORGE_BRANDING"] = branding
    app.config["GMFORGE_VECTOR_SERVICE"] = vector_service
    app.config["GMFORGE_GENERATION_SERVICE"] = generation_service
    app.config["GMFORGE_PLUGIN_SERVICE"] = plugin_service

    def _session_user():
        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            return None
        loaded_session = auth_service.get_session(session_id)
        if loaded_session is None:
            session.pop("session_id", None)
            return None
        user = auth_service.get_user_by_id(loaded_session.user_id)
        if user is None or not user.is_active:
            session.pop("session_id", None)
            return None
        return user

    def _bearer_session_and_user():
        token = _request_bearer_token()
        if not token:
            return None, None
        loaded_session = auth_service.get_session(token)
        if loaded_session is None:
            return None, None
        user = auth_service.get_user_by_id(loaded_session.user_id)
        if user is None or not user.is_active:
            return None, None
        return loaded_session, user

    @app.context_processor
    def inject_auth_state() -> dict[str, Any]:
        return {
            "current_user": getattr(g, "current_user", None),
            "branding": app.config.get("GMFORGE_BRANDING", {}),
        }

    @app.before_request
    def require_login():
        g.current_user = None
        g.api_session = None
        endpoint = request.endpoint or ""
        if endpoint in {"login", "logout", "api_login", "branding_asset", "favicon", "static"}:
            return None
        if request.path.startswith("/api/"):
            g.api_session, g.current_user = _bearer_session_and_user()
            if g.current_user is not None:
                return None
            return _json_error("bearer token required", status=401)
        g.current_user = _session_user()
        if g.current_user is not None:
            return None
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("login", next=next_url))

    @app.route("/login", methods=["GET", "POST"])
    def login() -> str:
        error = ""
        if request.method == "POST":
            user = auth_service.authenticate(
                username=str(request.form.get("username") or ""),
                password=str(request.form.get("password") or ""),
            )
            if user is None:
                error = "Invalid username or password."
            else:
                created_session = auth_service.create_session(user_id=user.id, ttl_hours=12)
                session["session_id"] = created_session.id
                target = str(request.args.get("next") or request.form.get("next") or "").strip()
                if not target.startswith("/"):
                    target = url_for("index")
                return redirect(target)
        return render_template(
            "login.html",
            error=error,
            seeded_owner={"username": OWNER_USERNAME, "email": OWNER_EMAIL},
            next_url=str(request.args.get("next") or request.form.get("next") or "").strip(),
        )

    @app.get("/assets/branding/<path:filename>")
    def branding_asset(filename: str):
        branding_root = _branding_root(resolved_root)
        asset_path = (branding_root / filename).resolve()
        if branding_root.resolve() not in asset_path.parents or not asset_path.exists() or not asset_path.is_file():
            abort(404)
        return send_file(asset_path)

    @app.get("/favicon.ico")
    def favicon():
        favicon_name = str(branding.get("favicon_name") or "")
        if not favicon_name:
            abort(404)
        return send_file(_branding_root(resolved_root) / favicon_name)

    @app.post("/api/session/login")
    def api_login():
        payload = _request_json()
        user = auth_service.authenticate(
            username=str(payload.get("username") or ""),
            password=str(payload.get("password") or ""),
        )
        if user is None:
            return _json_error("invalid username or password", status=401)
        created_session = auth_service.create_session(user_id=user.id, ttl_hours=12)
        return jsonify(
            {
                "access_token": created_session.id,
                "token_type": "Bearer",
                "expires_at": created_session.expires_at,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "display_name": user.display_name,
                    "role": user.role,
                },
            }
        )

    @app.get("/api/session")
    def api_session():
        if g.current_user is None:
            return _json_error("bearer token required", status=401)
        return jsonify(
            {
                "access_token": str(getattr(g.api_session, "id", "") or ""),
                "user": {
                    "id": g.current_user.id,
                    "username": g.current_user.username,
                    "email": g.current_user.email,
                    "display_name": g.current_user.display_name,
                    "role": g.current_user.role,
                }
            }
        )

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        session_id = str(session.pop("session_id", "") or "").strip()
        if session_id:
            try:
                auth_service.revoke_session(session_id)
            except FileNotFoundError:
                pass
        return redirect(url_for("login"))

    @app.post("/api/session/logout")
    def api_logout():
        session_id = str(getattr(g.api_session, "id", "") or "").strip() or _request_bearer_token()
        if not session_id:
            return _json_error("bearer token required", status=401)
        try:
            auth_service.revoke_session(session_id)
        except FileNotFoundError:
            return _json_error("session not found", status=404)
        return jsonify({"status": "logged_out"})

    @app.get("/")
    def index() -> str:
        systems = discover_systems(_systems_root(resolved_root))
        return render_template("index.html", systems=_serialize_systems(systems))

    @app.route("/workspace/campaigns", methods=["GET", "POST"])
    def campaigns_workspace() -> str:
        error = ""
        message = ""
        selected_system_id = str(request.values.get("system_id") or "").strip()
        selected_expansion_id = str(request.values.get("expansion_id") or "").strip()
        selected_setting_id = str(request.values.get("setting_id") or "").strip()
        if request.method == "POST":
            try:
                campaign_service.create_campaign(
                    system_id=request.form.get("system_id"),
                    expansion_id=request.form.get("expansion_id") or "",
                    setting_id=request.form.get("setting_id"),
                    campaign_id=request.form.get("campaign_id"),
                    campaign_label=request.form.get("campaign_label") or "",
                    summary=request.form.get("summary") or "",
                )
                message = "Campaign created."
                selected_system_id = str(request.form.get("system_id") or "")
                selected_expansion_id = str(request.form.get("expansion_id") or "")
                selected_setting_id = str(request.form.get("setting_id") or "")
            except Exception as exc:
                error = str(exc)

        options = _build_workspace_options(
            resolved_root,
            campaign_service,
            selected_system_id=selected_system_id,
            selected_expansion_id=selected_expansion_id,
            selected_setting_id=selected_setting_id,
        )
        filters = {
            "system_id": options["selected_system_id"],
            "expansion_id": options["selected_expansion_id"],
            "setting_id": options["selected_setting_id"],
        }
        campaigns = options["campaigns"]
        return render_template(
            "campaigns.html",
            campaigns=campaigns,
            filters=filters,
            options=options,
            error=error,
            message=message,
        )

    @app.route("/workspace/records", methods=["GET", "POST"])
    def records_workspace() -> str:
        error = ""
        message = ""
        selected_system_id = str(request.values.get("system_id") or "").strip()
        selected_expansion_id = str(request.values.get("expansion_id") or "").strip()
        selected_setting_id = str(request.values.get("setting_id") or "").strip()
        if request.method == "POST":
            try:
                record = build_record(
                    record_type=request.form.get("record_type"),
                    title=request.form.get("title"),
                    slug=request.form.get("slug") or "",
                    system_id=request.form.get("system_id") or "none",
                    addon_id=request.form.get("expansion_id") or "",
                    setting_id=request.form.get("setting_id") or "",
                    campaign_id=request.form.get("campaign_id") or "",
                    content={"body": request.form.get("body") or ""},
                    metadata={
                        "tags": [tag.strip() for tag in str(request.form.get("tags") or "").split(",") if tag.strip()],
                        "summary": request.form.get("summary") or "",
                    },
                )
                created = content_service.create_record(
                    record,
                    actor_user_id=str(getattr(g.current_user, "id", "") or ""),
                )
                _sync_vector_index(vector_service)
                return redirect(url_for("record_detail_workspace", record_id=created["id"], created="1"))
                selected_system_id = str(request.form.get("system_id") or "")
                selected_expansion_id = str(request.form.get("expansion_id") or "")
                selected_setting_id = str(request.form.get("setting_id") or "")
            except Exception as exc:
                error = str(exc)

        options = _build_workspace_options(
            resolved_root,
            campaign_service,
            selected_system_id=selected_system_id,
            selected_expansion_id=selected_expansion_id,
            selected_setting_id=selected_setting_id,
        )
        filters = {
            "query": str(request.values.get("q") or "").strip(),
            "type": str(request.values.get("type") or "").strip(),
            "system_id": options["selected_system_id"],
            "addon_id": options["selected_expansion_id"],
            "setting_id": options["selected_setting_id"],
            "campaign_id": str(request.values.get("campaign_id") or "").strip() or (
                str(options["campaigns"][0].get("id") or "") if options["campaigns"] else ""
            ),
            "tag": str(request.values.get("tag") or "").strip(),
        }
        store_filters = {key: value for key, value in filters.items() if key != "query" and value}
        records = (
            content_service.search_records(query=filters["query"], filters=store_filters)
            if filters["query"]
            else content_service.list_records(filters=store_filters)
        )
        return render_template(
            "records.html",
            records=records,
            filters=filters,
            options=options,
            error=error,
            message=message,
        )

    @app.get("/workspace/records/<record_id>")
    def record_detail_workspace(record_id: str) -> str:
        try:
            record = content_service.get_record(record_id)
        except FileNotFoundError:
            abort(404)
        message = "Record created." if str(request.args.get("created") or "").strip() == "1" else ""
        return render_template("record_detail.html", record=record, message=message)

    @app.route("/workspace/records/<record_id>/edit", methods=["GET", "POST"])
    def record_edit_workspace(record_id: str) -> str:
        error = ""
        try:
            record = content_service.get_record(record_id)
        except FileNotFoundError:
            abort(404)
        if request.method == "POST":
            try:
                updated = _merge_record(
                    record,
                    {
                        "type": request.form.get("record_type") or record.get("type"),
                        "title": request.form.get("title") or record.get("title"),
                        "slug": request.form.get("slug") or "",
                        "content": {"body": request.form.get("body") or ""},
                        "metadata": {
                            "summary": request.form.get("summary") or "",
                            "tags": [tag.strip() for tag in str(request.form.get("tags") or "").split(",") if tag.strip()],
                        },
                    },
                )
                content_service.update_record(
                    record_id,
                    updated,
                    actor_user_id=str(getattr(g.current_user, "id", "") or ""),
                )
                _sync_vector_index(vector_service)
                return redirect(url_for("record_detail_workspace", record_id=record_id))
            except Exception as exc:
                error = str(exc)
        return render_template("record_edit.html", record=record, error=error)

    @app.route("/workspace/generate", methods=["GET", "POST"])
    def generate_workspace() -> str:
        error = ""
        form = _generation_form(
            system_id=str(request.values.get("system_id") or "cypher").strip(),
            expansion_id=str(request.values.get("expansion_id") or "godforsaken").strip(),
            setting_id=str(request.values.get("setting_id") or "land_of_legends").strip(),
            campaign_id=str(request.values.get("campaign_id") or "").strip(),
            title=str(request.values.get("title") or "").strip(),
            record_type=str(request.values.get("record_type") or "lore_entry").strip(),
            focus_query=str(request.values.get("focus_query") or "").strip(),
            notes=str(request.values.get("notes") or "").strip(),
            source_kind=str(request.values.get("source_kind") or "").strip(),
            provider_id=str(request.values.get("provider_id") or "local_structured_draft").strip(),
        )
        options = _build_workspace_options(
            resolved_root,
            campaign_service,
            selected_system_id=form["system_id"],
            selected_expansion_id=form["expansion_id"],
            selected_setting_id=form["setting_id"],
        )
        source_kind_options = ["module_lore", "module_manifest", "ai_lore", "migration_staging", "record", "rulebook_markdown"]
        provider_options = generation_service.list_providers()
        draft_result: dict[str, Any] | None = None
        if request.method == "POST":
            try:
                draft_result = generation_service.build_draft(
                    GenerationRequest(
                        title=form["title"],
                        record_type=form["record_type"],
                        system_id=form["system_id"],
                        addon_id=form["expansion_id"],
                        setting_id=form["setting_id"],
                        campaign_id=form["campaign_id"],
                        focus_query=form["focus_query"],
                        notes=form["notes"],
                        source_kind=form["source_kind"],
                        provider_id=form["provider_id"],
                    )
                )
                if str(request.form.get("action") or "") == "create_record":
                    created = content_service.create_record(
                        build_record(
                            record_type=draft_result["proposed_record"]["record_type"],
                            title=draft_result["proposed_record"]["title"] or "Untitled Draft",
                            slug="",
                            system_id=form["system_id"] or "none",
                            addon_id=form["expansion_id"],
                            setting_id=form["setting_id"],
                            campaign_id=form["campaign_id"],
                            source={"kind": "generated"},
                            content={"body": draft_result["proposed_record"]["body"]},
                            metadata={
                                "summary": draft_result["proposed_record"]["summary"],
                                "status": "draft",
                                "tags": draft_result["proposed_record"]["tags"],
                            },
                        ),
                        actor_user_id=str(getattr(g.current_user, "id", "") or ""),
                        request_kind="generator",
                        provider_id=draft_result["provider_id"],
                        prompt_text=draft_result["prompt_text"],
                    )
                    _sync_vector_index(vector_service)
                    return redirect(url_for("record_edit_workspace", record_id=created["id"]))
            except Exception as exc:
                error = str(exc)
        return render_template(
            "generate.html",
            form=form,
            options=options,
            source_kind_options=source_kind_options,
            provider_options=provider_options,
            draft_result=draft_result,
            error=error,
        )

    @app.get("/api/systems")
    def api_systems():
        systems = discover_systems(_systems_root(resolved_root))
        return jsonify({"systems": _serialize_systems(systems)})

    @app.get("/api/vector/stats")
    def api_vector_stats():
        return jsonify({"index": vector_service.stats()})

    @app.get("/api/vector/query")
    def api_vector_query():
        query = str(request.args.get("q") or "").strip()
        if not query:
            return _json_error("query string q is required", status=400)
        try:
            k = int(str(request.args.get("k") or "8"))
        except ValueError:
            return _json_error("k must be an integer", status=400)
        filters = {
            "owner_layer": str(request.args.get("owner_layer") or "").strip(),
            "system_id": str(request.args.get("system_id") or "").strip(),
            "addon_id": str(request.args.get("addon_id") or "").strip(),
            "module_id": str(request.args.get("module_id") or "").strip(),
            "setting_id": str(request.args.get("setting_id") or "").strip(),
            "campaign_id": str(request.args.get("campaign_id") or "").strip(),
            "source_kind": str(request.args.get("source_kind") or "").strip(),
            "content_type": str(request.args.get("content_type") or "").strip(),
        }
        items = vector_service.query(q=query, k=k, filters=filters)
        return jsonify({"query": query, "k": max(1, min(k, 50)), "items": items})

    @app.post("/api/vector/reindex")
    def api_vector_reindex():
        stats = vector_service.build()
        return jsonify({"status": "ok", "index": stats})

    @app.get("/api/systems/<system_id>")
    def api_system(system_id: str):
        systems = discover_systems(_systems_root(resolved_root))
        for system in systems:
            if system["id"] == system_id:
                return jsonify({"system": _serialize_systems([system])[0]})
        abort(404)

    @app.get("/api/systems/<system_id>/addons/<addon_id>")
    def api_addon(system_id: str, addon_id: str):
        systems = discover_systems(_systems_root(resolved_root))
        for system in systems:
            if system["id"] != system_id:
                continue
            for addon in system.get("addons", []):
                if addon["id"] == addon_id:
                    payload = dict(addon)
                    payload["system_id"] = system_id
                    payload["api_url"] = f"/api/systems/{system_id}/addons/{addon_id}"
                    return jsonify({"addon": payload})
        abort(404)

    @app.get("/api/systems/<system_id>/addons/<addon_id>/modules/<module_id>")
    def api_module(system_id: str, addon_id: str, module_id: str):
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
        except FileNotFoundError:
            abort(404)
        module_root = (
            resolved_root
            / "app"
            / "systems"
            / system_id
            / "addons"
            / addon_id
            / "modules"
            / module_id
        )
        return jsonify(
            {
                "system": {"id": system["id"], "name": system["name"]},
                "addon": {"id": addon["id"], "name": addon["name"]},
                "module": {
                    **dict(module),
                    "api_url": f"/api/systems/{system_id}/addons/{addon_id}/modules/{module_id}",
                    "ui_url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}",
                },
                "regions": _load_module_collection(module_root, "regions"),
                "peoples": _load_module_collection(module_root, "peoples"),
                "creatures": _load_module_collection(module_root, "creatures"),
                "items": _load_module_collection(module_root, "items"),
                "system_categories": _load_module_collection(module_root, "system"),
                "lore": _load_lore_collection(module_root),
            }
        )

    @app.get("/api/systems/<system_id>/addons/<addon_id>/modules/<module_id>/regions/<region_id>")
    def api_module_region(system_id: str, addon_id: str, module_id: str, region_id: str):
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            region = _load_module_item(module_root, "regions", region_id)
        except FileNotFoundError:
            abort(404)
        return jsonify(
            {
                "system": {"id": system["id"], "name": system["name"]},
                "addon": {"id": addon["id"], "name": addon["name"]},
                "module": {
                    "id": module["id"],
                    "label": module["label"],
                    "api_url": f"/api/systems/{system_id}/addons/{addon_id}/modules/{module_id}",
                    "ui_url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}",
                },
                "region": {
                    **region,
                    "api_url": (
                        f"/api/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}"
                    ),
                    "ui_url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
                },
            }
        )

    @app.get("/api/systems/<system_id>/addons/<addon_id>/modules/<module_id>/peoples/<people_id>")
    def api_module_people(system_id: str, addon_id: str, module_id: str, people_id: str):
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            people = _load_module_item(module_root, "peoples", people_id)
        except FileNotFoundError:
            abort(404)
        return jsonify(
            {
                "system": {"id": system["id"], "name": system["name"]},
                "addon": {"id": addon["id"], "name": addon["name"]},
                "module": {
                    "id": module["id"],
                    "label": module["label"],
                    "api_url": f"/api/systems/{system_id}/addons/{addon_id}/modules/{module_id}",
                    "ui_url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}",
                },
                "people": {
                    **people,
                    "api_url": (
                        f"/api/systems/{system_id}/addons/{addon_id}/modules/{module_id}/peoples/{people_id}"
                    ),
                    "ui_url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/peoples/{people_id}",
                },
            }
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>")
    def module_view(system_id: str, addon_id: str, module_id: str) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
        except FileNotFoundError:
            abort(404)
        module_root = (
            resolved_root
            / "app"
            / "systems"
            / system_id
            / "addons"
            / addon_id
            / "modules"
            / module_id
        )
        return render_template(
            "module.html",
            system=system,
            addon=addon,
            module=module,
            collection_cards=_module_collection_cards(
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
                module_root=module_root,
            ),
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/<collection_name>")
    def module_collection_view(system_id: str, addon_id: str, module_id: str, collection_name: str) -> str:
        if collection_name not in MODULE_COLLECTION_CONFIG:
            abort(404)
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
        except FileNotFoundError:
            abort(404)
        module_root = (
            resolved_root
            / "app"
            / "systems"
            / system_id
            / "addons"
            / addon_id
            / "modules"
            / module_id
        )
        config = MODULE_COLLECTION_CONFIG[collection_name]
        items = _module_collection_cards(
            system_id=system_id,
            addon_id=addon_id,
            module_id=module_id,
            module_root=module_root,
        )
        collection = next((item for item in items if item["id"] == collection_name), None)
        if collection is None:
            abort(404)
        return render_template(
            "module_collection.html",
            system=system,
            addon=addon,
            module=module,
            collection=collection,
            items=collection["items"],
            lore_documents=load_lore_documents(module_root, module_root=module_root) if collection_name == "lore" else [],
            back_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}",
            back_label=module["label"],
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/lore/<path:lore_path>")
    def module_lore_view(system_id: str, addon_id: str, module_id: str, lore_path: str) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
        except FileNotFoundError:
            abort(404)
        module_root = (
            resolved_root
            / "app"
            / "systems"
            / system_id
            / "addons"
            / addon_id
            / "modules"
            / module_id
        )
        parts = [part for part in lore_path.split("/") if part]
        if not parts:
            abort(404)
        target = _resolve_lore_target(module_root, parts)
        markdown_target = target.with_suffix(".md") if target.suffix != ".md" else target
        if markdown_target.exists() and markdown_target.is_file():
            markdown_text = markdown_target.read_text(encoding="utf-8", errors="replace")
            title = markdown_target.stem.replace("_", " ").title()
            document = load_rulebook_document(markdown_target, title=title)
            parent_parts = parts[:-1]
            back_url = (
                f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/lore/"
                f"{'/'.join(parent_parts)}"
                if parent_parts
                else f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/lore"
            )
            back_label = parent_parts[-1].replace("_", " ").title() if parent_parts else "Lore"
            return render_template(
                "module_lore_document.html",
                system=system,
                addon=addon,
                module=module,
                document=document,
                rendered_html=render_rulebook_html(document),
                lore_path=parts,
                back_url=back_url,
                back_label=back_label,
            )
        if target.exists() and target.is_dir():
            items = _load_lore_branch_entries(
                module_root=module_root,
                branch_root=target,
                base_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/lore/{'/'.join(parts)}",
            )
            collection = {
                "id": parts[-1],
                "label": parts[-1].replace("_", " ").title(),
                "description": f"Canonical lore branch for {' / '.join(part.replace('_', ' ').title() for part in parts)}.",
                "count": len(items),
                "item_kind_label": "lore entry",
                "empty_text": "No lore entries in this branch yet.",
            }
            return render_template(
                "module_collection.html",
                system=system,
                addon=addon,
                module=module,
                collection=collection,
                items=items,
                lore_documents=load_lore_documents(target, module_root=module_root),
                back_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/lore",
                back_label="Lore",
            )
        abort(404)

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/regions/<region_id>")
    def module_region_view(system_id: str, addon_id: str, module_id: str, region_id: str) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            region = _load_module_item(module_root, "regions", region_id)
            region_categories = _region_category_items(module_root, region_id)
            region_sections = _load_region_sections(module_root, region_id)
        except FileNotFoundError:
            abort(404)
        return _render_module_item(
            system=system,
            addon=addon,
            module=module,
            module_root=module_root,
            item=region,
            item_root=module_root / "regions" / region_id,
            item_kind_label="Region",
            collection_name="regions",
            child_items=region_categories,
            child_kind_label="Starter Categories",
            grouped_child_sections=region_sections,
            grouped_child_label="Authored Region Entries",
            back_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}",
            back_label=module["label"],
            breadcrumb_links=[
                {
                    "label": region["label"],
                    "url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
                }
            ],
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/regions/<region_id>/subregions/<subregion_id>")
    def module_subregion_view(system_id: str, addon_id: str, module_id: str, region_id: str, subregion_id: str) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            region_root = module_root / "regions" / region_id
            region = _load_module_item(module_root, "regions", region_id)
            subregion_root = _find_subregion_path(region_root, subregion_id)
            if subregion_root is None:
                raise FileNotFoundError(subregion_id)
            subregion = _load_manifest_file(subregion_root / "manifest.json", fallback_id=subregion_id, fallback_label=subregion_id)
            subregion_sections = _load_subregion_sections(subregion_root)
            for section in subregion_sections:
                if section["id"] == "villages":
                    for entry in section["entries"]:
                        entry["ui_url"] = (
                            f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}/subregions/{subregion_id}/villages/{entry['id']}"
                        )
        except FileNotFoundError:
            abort(404)
        return _render_module_item(
            system=system,
            addon=addon,
            module=module,
            module_root=module_root,
            item=subregion,
            item_root=subregion_root,
            item_kind_label="Subregion",
            collection_name="subregions",
            grouped_child_sections=subregion_sections,
            grouped_child_label="Subregion Entries",
            back_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
            back_label=region["label"],
            breadcrumb_links=[
                {
                    "label": region["label"],
                    "url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
                },
                {
                    "label": subregion["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/subregions/{subregion_id}"
                    ),
                },
            ],
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/regions/<region_id>/subregions/<subregion_id>/villages/<village_id>")
    def module_subregion_village_view(
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
        subregion_id: str,
        village_id: str,
    ) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            region_root = module_root / "regions" / region_id
            subregion_root = _find_subregion_path(region_root, subregion_id)
            if subregion_root is None:
                raise FileNotFoundError(subregion_id)
            subregion = _load_manifest_file(subregion_root / "manifest.json", fallback_id=subregion_id, fallback_label=subregion_id)
            village_root = subregion_root / "villages" / village_id
            village = _load_manifest_file(village_root / "manifest.json", fallback_id=village_id, fallback_label=village_id)
            village_sections = _add_place_ui_urls(
                _load_place_sections(village_root),
                base_path=(
                    f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                    f"/regions/{region_id}/subregions/{subregion_id}/villages/{village_id}"
                ),
            )
        except FileNotFoundError:
            abort(404)
        return _render_module_item(
            system=system,
            addon=addon,
            module=module,
            module_root=module_root,
            item=village,
            item_root=village_root,
            item_kind_label="Village",
            collection_name="villages",
            grouped_child_sections=village_sections,
            grouped_child_label="Village Entries",
            back_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}/subregions/{subregion_id}",
            back_label=subregion["label"],
            breadcrumb_links=[
                {
                    "label": region_id.replace("_", " ").title(),
                    "url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
                },
                {
                    "label": subregion["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/subregions/{subregion_id}"
                    ),
                },
                {
                    "label": village["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/subregions/{subregion_id}/villages/{village_id}"
                    ),
                },
            ],
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/regions/<region_id>/subregions/<subregion_id>/cities/<city_id>")
    def module_subregion_city_view(
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
        subregion_id: str,
        city_id: str,
    ) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            region_root = module_root / "regions" / region_id
            subregion_root = _find_subregion_path(region_root, subregion_id)
            if subregion_root is None:
                raise FileNotFoundError(subregion_id)
            subregion = _load_manifest_file(subregion_root / "manifest.json", fallback_id=subregion_id, fallback_label=subregion_id)
            city_root = subregion_root / "cities" / city_id
            city = _load_manifest_file(city_root / "manifest.json", fallback_id=city_id, fallback_label=city_id)
            city_sections = _add_place_ui_urls(
                _load_place_sections(city_root),
                base_path=(
                    f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                    f"/regions/{region_id}/subregions/{subregion_id}/cities/{city_id}"
                ),
            )
        except FileNotFoundError:
            abort(404)
        return _render_module_item(
            system=system,
            addon=addon,
            module=module,
            module_root=module_root,
            item=city,
            item_root=city_root,
            item_kind_label="City",
            collection_name="cities",
            grouped_child_sections=city_sections,
            grouped_child_label="City Entries",
            back_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}/subregions/{subregion_id}",
            back_label=subregion["label"],
            breadcrumb_links=[
                {
                    "label": region_id.replace("_", " ").title(),
                    "url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
                },
                {
                    "label": subregion["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/subregions/{subregion_id}"
                    ),
                },
                {
                    "label": city["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/subregions/{subregion_id}/cities/{city_id}"
                    ),
                },
            ],
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/regions/<region_id>/villages/<village_id>")
    def module_region_village_view(
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
        village_id: str,
    ) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            region = _load_module_item(module_root, "regions", region_id)
            village_root = module_root / "regions" / region_id / "villages" / village_id
            village = _load_manifest_file(village_root / "manifest.json", fallback_id=village_id, fallback_label=village_id)
            village_sections = _add_place_ui_urls(
                _load_place_sections(village_root),
                base_path=(
                    f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                    f"/regions/{region_id}/villages/{village_id}"
                ),
            )
        except FileNotFoundError:
            abort(404)
        return _render_module_item(
            system=system,
            addon=addon,
            module=module,
            module_root=module_root,
            item=village,
            item_root=village_root,
            item_kind_label="Village",
            collection_name="villages",
            grouped_child_sections=village_sections,
            grouped_child_label="Village Entries",
            back_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
            back_label=region["label"],
            breadcrumb_links=[
                {
                    "label": region["label"],
                    "url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
                },
                {
                    "label": village["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/villages/{village_id}"
                    ),
                },
            ],
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/regions/<region_id>/cities/<city_id>")
    def module_region_city_view(
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
        city_id: str,
    ) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            region = _load_module_item(module_root, "regions", region_id)
            city_root = module_root / "regions" / region_id / "cities" / city_id
            city = _load_manifest_file(city_root / "manifest.json", fallback_id=city_id, fallback_label=city_id)
            city_sections = _add_place_ui_urls(
                _load_place_sections(city_root),
                base_path=(
                    f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                    f"/regions/{region_id}/cities/{city_id}"
                ),
            )
        except FileNotFoundError:
            abort(404)
        return _render_module_item(
            system=system,
            addon=addon,
            module=module,
            module_root=module_root,
            item=city,
            item_root=city_root,
            item_kind_label="City",
            collection_name="cities",
            grouped_child_sections=city_sections,
            grouped_child_label="City Entries",
            back_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
            back_label=region["label"],
            breadcrumb_links=[
                {
                    "label": region["label"],
                    "url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
                },
                {
                    "label": city["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/cities/{city_id}"
                    ),
                },
            ],
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/regions/<region_id>/villages/<village_id>/inns/<inn_id>")
    def module_region_village_inn_view(
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
        village_id: str,
        inn_id: str,
    ) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            village_root = module_root / "regions" / region_id / "villages" / village_id
            village = _load_manifest_file(village_root / "manifest.json", fallback_id=village_id, fallback_label=village_id)
            inn_root = village_root / "inns" / inn_id
            inn = _load_manifest_file(inn_root / "manifest.json", fallback_id=inn_id, fallback_label=inn_id)
        except FileNotFoundError:
            abort(404)
        return _render_module_item(
            system=system,
            addon=addon,
            module=module,
            module_root=module_root,
            item=inn,
            item_root=inn_root,
            item_kind_label="Inn",
            collection_name="inns",
            back_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}/villages/{village_id}",
            back_label=village["label"],
            breadcrumb_links=[
                {
                    "label": region_id.replace("_", " ").title(),
                    "url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
                },
                {
                    "label": village["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/villages/{village_id}"
                    ),
                },
                {
                    "label": inn["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/villages/{village_id}/inns/{inn_id}"
                    ),
                },
            ],
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/regions/<region_id>/cities/<city_id>/inns/<inn_id>")
    def module_region_city_inn_view(
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
        city_id: str,
        inn_id: str,
    ) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            city_root = module_root / "regions" / region_id / "cities" / city_id
            city = _load_manifest_file(city_root / "manifest.json", fallback_id=city_id, fallback_label=city_id)
            inn_root = city_root / "inns" / inn_id
            inn = _load_manifest_file(inn_root / "manifest.json", fallback_id=inn_id, fallback_label=inn_id)
        except FileNotFoundError:
            abort(404)
        return _render_module_item(
            system=system,
            addon=addon,
            module=module,
            module_root=module_root,
            item=inn,
            item_root=inn_root,
            item_kind_label="Inn",
            collection_name="inns",
            back_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}/cities/{city_id}",
            back_label=city["label"],
            breadcrumb_links=[
                {
                    "label": region_id.replace("_", " ").title(),
                    "url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
                },
                {
                    "label": city["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/cities/{city_id}"
                    ),
                },
                {
                    "label": inn["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/cities/{city_id}/inns/{inn_id}"
                    ),
                },
            ],
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/regions/<region_id>/subregions/<subregion_id>/villages/<village_id>/inns/<inn_id>")
    def module_subregion_village_inn_view(
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
        subregion_id: str,
        village_id: str,
        inn_id: str,
    ) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            region_root = module_root / "regions" / region_id
            subregion_root = _find_subregion_path(region_root, subregion_id)
            if subregion_root is None:
                raise FileNotFoundError(subregion_id)
            village_root = subregion_root / "villages" / village_id
            village = _load_manifest_file(village_root / "manifest.json", fallback_id=village_id, fallback_label=village_id)
            inn_root = village_root / "inns" / inn_id
            inn = _load_manifest_file(inn_root / "manifest.json", fallback_id=inn_id, fallback_label=inn_id)
        except FileNotFoundError:
            abort(404)
        return _render_module_item(
            system=system,
            addon=addon,
            module=module,
            module_root=module_root,
            item=inn,
            item_root=inn_root,
            item_kind_label="Inn",
            collection_name="inns",
            back_url=(
                f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                f"/regions/{region_id}/subregions/{subregion_id}/villages/{village_id}"
            ),
            back_label=village["label"],
            breadcrumb_links=[
                {
                    "label": region_id.replace("_", " ").title(),
                    "url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
                },
                {
                    "label": subregion_id.replace("_", " ").title(),
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/subregions/{subregion_id}"
                    ),
                },
                {
                    "label": village["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/subregions/{subregion_id}/villages/{village_id}"
                    ),
                },
                {
                    "label": inn["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/subregions/{subregion_id}/villages/{village_id}/inns/{inn_id}"
                    ),
                },
            ],
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/regions/<region_id>/subregions/<subregion_id>/cities/<city_id>/inns/<inn_id>")
    def module_subregion_city_inn_view(
        system_id: str,
        addon_id: str,
        module_id: str,
        region_id: str,
        subregion_id: str,
        city_id: str,
        inn_id: str,
    ) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            region_root = module_root / "regions" / region_id
            subregion_root = _find_subregion_path(region_root, subregion_id)
            if subregion_root is None:
                raise FileNotFoundError(subregion_id)
            city_root = subregion_root / "cities" / city_id
            city = _load_manifest_file(city_root / "manifest.json", fallback_id=city_id, fallback_label=city_id)
            inn_root = city_root / "inns" / inn_id
            inn = _load_manifest_file(inn_root / "manifest.json", fallback_id=inn_id, fallback_label=inn_id)
        except FileNotFoundError:
            abort(404)
        return _render_module_item(
            system=system,
            addon=addon,
            module=module,
            module_root=module_root,
            item=inn,
            item_root=inn_root,
            item_kind_label="Inn",
            collection_name="inns",
            back_url=(
                f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                f"/regions/{region_id}/subregions/{subregion_id}/cities/{city_id}"
            ),
            back_label=city["label"],
            breadcrumb_links=[
                {
                    "label": region_id.replace("_", " ").title(),
                    "url": f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/regions/{region_id}",
                },
                {
                    "label": subregion_id.replace("_", " ").title(),
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/subregions/{subregion_id}"
                    ),
                },
                {
                    "label": city["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/subregions/{subregion_id}/cities/{city_id}"
                    ),
                },
                {
                    "label": inn["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/regions/{region_id}/subregions/{subregion_id}/cities/{city_id}/inns/{inn_id}"
                    ),
                },
            ],
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/peoples/<people_id>")
    def module_people_view(system_id: str, addon_id: str, module_id: str, people_id: str) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            people = _load_module_item(module_root, "peoples", people_id)
            people_children = _load_module_item_collection(module_root, "peoples", people_id, "subgroups")
            for child in people_children:
                child["ui_url"] = (
                    f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                    f"/peoples/{people_id}/subgroups/{child['id']}"
                )
        except FileNotFoundError:
            abort(404)
        return _render_module_item(
            system=system,
            addon=addon,
            module=module,
            module_root=module_root,
            item=people,
            item_root=module_root / "peoples" / people_id,
            item_kind_label="People",
            collection_name="peoples",
            child_items=people_children,
            child_kind_label="Subgroups",
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/modules/<module_id>/peoples/<people_id>/subgroups/<subgroup_id>")
    def module_people_subgroup_view(system_id: str, addon_id: str, module_id: str, people_id: str, subgroup_id: str) -> str:
        try:
            system, addon, module = _find_module(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                module_id=module_id,
            )
            module_root = (
                resolved_root
                / "app"
                / "systems"
                / system_id
                / "addons"
                / addon_id
                / "modules"
                / module_id
            )
            people = _load_module_item(module_root, "peoples", people_id)
            subgroup_root = module_root / "peoples" / people_id / "subgroups" / subgroup_id
            subgroup = _load_manifest_file(
                subgroup_root / "manifest.json",
                fallback_id=subgroup_id,
                fallback_label=subgroup_id,
            )
        except FileNotFoundError:
            abort(404)
        return _render_module_item(
            system=system,
            addon=addon,
            module=module,
            module_root=module_root,
            item=subgroup,
            item_root=subgroup_root,
            item_kind_label="People Subgroup",
            collection_name="subgroups",
            back_url=f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}/peoples/{people_id}",
            back_label=people["label"],
            breadcrumb_links=[
                {
                    "label": people["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/peoples/{people_id}"
                    ),
                },
                {
                    "label": subgroup["label"],
                    "url": (
                        f"/systems/{system_id}/addons/{addon_id}/modules/{module_id}"
                        f"/peoples/{people_id}/subgroups/{subgroup_id}"
                    ),
                },
            ],
        )

    @app.get("/api/systems/<system_id>/addons/<addon_id>/rulebooks/<rulebook_id>")
    def api_rulebook(system_id: str, addon_id: str, rulebook_id: str):
        try:
            system, addon, rulebook = _find_rulebook(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                rulebook_id=rulebook_id,
            )
        except FileNotFoundError:
            abort(404)
        return jsonify(
            _serialize_rulebook_payload(
                system=system,
                addon=addon,
                rulebook=rulebook,
                resolved_root=resolved_root,
            )
        )

    @app.get("/api/campaigns")
    def api_campaigns():
        system_id = str(request.args.get("system_id") or "").strip()
        expansion_id = str(request.args.get("expansion_id") or "").strip()
        setting_id = str(request.args.get("setting_id") or "").strip()
        if not system_id or not setting_id:
            return _json_error("system_id and setting_id are required", status=400)
        return jsonify(
            {
                "campaigns": campaign_service.list_campaigns(
                    system_id=system_id,
                    expansion_id=expansion_id,
                    setting_id=setting_id,
                )
            }
        )

    @app.post("/api/campaigns")
    def api_create_campaign():
        payload = _request_json()
        try:
            campaign = campaign_service.create_campaign(
                system_id=payload.get("system_id"),
                expansion_id=payload.get("expansion_id") or "",
                setting_id=payload.get("setting_id"),
                campaign_id=payload.get("campaign_id"),
                campaign_label=payload.get("campaign_label") or payload.get("label") or "",
                summary=payload.get("summary") or "",
            )
        except FileExistsError as exc:
            return _json_error(str(exc), status=409)
        except Exception as exc:
            return _json_error(str(exc), status=400)
        return jsonify({"campaign": campaign}), 201

    @app.get("/api/records")
    def api_records():
        query = str(request.args.get("q") or "").strip()
        filters = {
            "type": str(request.args.get("type") or "").strip(),
            "system_id": str(request.args.get("system_id") or "").strip(),
            "addon_id": str(request.args.get("addon_id") or request.args.get("expansion_id") or "").strip(),
            "setting_id": str(request.args.get("setting_id") or "").strip(),
            "campaign_id": str(request.args.get("campaign_id") or "").strip(),
            "status": str(request.args.get("status") or "").strip(),
            "tag": str(request.args.get("tag") or "").strip(),
        }
        clean_filters = {key: value for key, value in filters.items() if value}
        items = content_service.search_records(query=query, filters=clean_filters) if query else content_service.list_records(filters=clean_filters)
        return jsonify({"records": items})

    @app.post("/api/records")
    def api_create_record():
        payload = _request_json()
        try:
            record = _build_record_from_payload(payload)
            created = content_service.create_record(
                record,
                actor_user_id=_request_actor_user_id(payload),
                request_kind=str(payload.get("request_kind") or "manual"),
                provider_id=str(payload.get("provider_id") or ""),
                prompt_text=str(payload.get("prompt_text") or ""),
            )
            vector_sync = _sync_vector_index(vector_service)
        except FileExistsError as exc:
            return _json_error(str(exc), status=409)
        except Exception as exc:
            return _json_error(str(exc), status=400)
        return jsonify({"record": created, "vector_sync": vector_sync}), 201

    @app.get("/api/records/<record_id>")
    def api_record(record_id: str):
        try:
            return jsonify({"record": content_service.get_record(record_id)})
        except FileNotFoundError:
            return _json_error(f"record not found: {record_id}", status=404)

    @app.put("/api/records/<record_id>")
    def api_update_record(record_id: str):
        payload = _request_json()
        try:
            current = content_service.get_record(record_id)
            merged = _merge_record(current, payload)
            updated = content_service.update_record(
                record_id,
                merged,
                actor_user_id=_request_actor_user_id(payload),
                request_kind=str(payload.get("request_kind") or "manual"),
                provider_id=str(payload.get("provider_id") or ""),
                prompt_text=str(payload.get("prompt_text") or ""),
            )
            vector_sync = _sync_vector_index(vector_service)
        except FileNotFoundError:
            return _json_error(f"record not found: {record_id}", status=404)
        except Exception as exc:
            return _json_error(str(exc), status=400)
        return jsonify({"record": updated, "vector_sync": vector_sync})

    @app.delete("/api/records/<record_id>")
    def api_delete_record(record_id: str):
        payload = _request_json()
        try:
            result = content_service.delete_record(
                record_id,
                actor_user_id=_request_actor_user_id(payload),
                request_kind=str(payload.get("request_kind") or "manual"),
            )
            vector_sync = _sync_vector_index(vector_service)
        except FileNotFoundError:
            return _json_error(f"record not found: {record_id}", status=404)
        return jsonify({**result, "vector_sync": vector_sync})

    @app.get("/systems/<system_id>/addons/<addon_id>/rulebooks/<rulebook_id>")
    def rulebook_view(system_id: str, addon_id: str, rulebook_id: str) -> str:
        try:
            system, addon, rulebook = _find_rulebook(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                rulebook_id=rulebook_id,
            )
        except FileNotFoundError:
            abort(404)

        addon_root = resolved_root / "app" / "systems" / system_id / "addons" / addon_id
        markdown_path = addon_root / rulebook["markdown_path"]
        document = load_rulebook_document(markdown_path, title=rulebook["title"])
        html_path = addon_root / rulebook["html_path"] if rulebook.get("html_path") else None
        html_exists = bool(html_path and html_path.exists() and html_path.is_file())
        return render_template(
            "rulebook.html",
            system=system,
            addon=addon,
            rulebook=rulebook,
            document=document,
            toc=build_rulebook_toc(document, max_level=2),
            rendered_html=render_rulebook_html(document),
            html_exists=html_exists,
            raw_html_url=url_for(
                "rulebook_html_asset",
                system_id=system_id,
                addon_id=addon_id,
                rulebook_id=rulebook_id,
            )
            if html_exists
            else "",
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/rulebooks/<rulebook_id>/html")
    def rulebook_html_asset(system_id: str, addon_id: str, rulebook_id: str):
        try:
            _, _, rulebook = _find_rulebook(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                rulebook_id=rulebook_id,
            )
        except FileNotFoundError:
            abort(404)
        addon_root = resolved_root / "app" / "systems" / system_id / "addons" / addon_id
        html_path = addon_root / rulebook["html_path"]
        if not html_path.exists() or not html_path.is_file():
            abort(404)
        return send_file(html_path)

    return app
