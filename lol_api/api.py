from __future__ import annotations

import ast
import base64
import hashlib
import json
import html
import os
import re
import sqlite3
import shutil
import subprocess
import sys
import uuid
import mimetypes
import yaml
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from flask import Flask, current_app, jsonify, request, render_template, send_from_directory, send_file, redirect
from werkzeug.utils import secure_filename
from .storage import (
    STORAGE_SCHEMA_VERSION,
    save_generated_result,
    list_saved_results,
    load_saved_result,
    search_saved_results,
    trash_saved_result,
    list_trashed_results,
    load_trashed_result,
    restore_trashed_result,
    expunge_trashed_result,
    update_saved_result,
)

from .config_loader import (
    load_config_dir,
    list_world_descriptors,
    infer_default_world_id,
    infer_core_genre_for_setting,
    list_setting_descriptors,
    infer_default_setting_id,
    load_world_layer,
    resolve_world_dir,
)
from .generator import (
    deterministic_rng,
    generate_character,
    generate_npc,
    generate_monster,
    generate_cypher,
    generate_artifact,
    generate_encounter,
    generate_inn,
    generate_settlement,
    parse_raw_text_entry,
    parse_raw_text_entries,
)

from .compendium import (
    load_compendium_index,
    list_compendium_items,
    load_compendium_item,
    search_compendium,
    SUPPORTED_COMPENDIUM_TYPES,
)
from .official_compendium import (
    load_official_compendium_index,
    list_official_items,
    load_official_item,
    search_official_compendium,
    SUPPORTED_OFFICIAL_COMPENDIUM_TYPES,
)
from .lore import (
    LOCATION_CATEGORY_PRIORITY,
    load_lore_index,
    list_ai_lore_items,
    list_lore_items,
    load_lore_item,
    search_ai_lore,
    search_lore,
    update_lore_item,
    list_trashed_lore_items,
    load_trashed_lore_item,
    trash_lore_item,
    restore_trashed_lore_item,
    expunge_trashed_lore_item,
)
from .prompts import (
    load_prompts_index,
    search_prompts,
    update_prompt,
    trash_prompt,
)
from .config_enrichment import (
    load_candidates,
    curated_candidates,
    load_generated_yaml,
    select_yaml_sections,
    write_yaml,
)
from .settings import (
    attach_settings_metadata,
    default_settings,
    normalize_setting_token,
    settings_catalog,
    settings_nav_model,
)
from Plugins.foundryVTT.importer import (
    foundry_actor_to_character_sheet,
    foundry_actor_to_npc_result,
    foundry_item_to_result,
)
from Plugins.foundryVTT.exporter import (
    character_sheet_result_to_foundry_actor,
    npc_or_creature_result_to_foundry_actor,
    cypher_result_to_foundry_item,
    artifact_result_to_foundry_item,
)
from Plugins.docling.vector_index import (
    remove_single_storage_card,
    sync_single_storage_card,
    sync_storage_index,
    query_index as vector_query_index,
    stats_index as vector_stats_index,
)


def plugin_roots_from_project_root(project_root: Path) -> list[Path]:
    roots: list[Path] = []
    for name in ("plugins", "Plugins"):
        path = project_root / name
        if path.exists() and path.is_dir():
            roots.append(path)
    return roots


def discover_plugins_from_roots(
    roots: list[Path],
    *,
    project_root: Path,
    state: dict[str, bool] | None = None,
) -> list[dict]:
    plugin_state = state or {}
    seen: set[str] = set()
    items: list[dict] = []
    for root in roots:
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name == "__pycache__":
                continue
            metadata_path = child / "plugin.json"
            package_marker = child / "__init__.py"
            if not metadata_path.exists() and not package_marker.exists():
                continue
            plugin_id = child.name
            if plugin_id in seen:
                continue
            seen.add(plugin_id)
            metadata: dict = {}
            if metadata_path.exists():
                try:
                    parsed = json.loads(metadata_path.read_text(encoding="utf-8"))
                    if isinstance(parsed, dict):
                        metadata = parsed
                except Exception:
                    metadata = {}
            items.append({
                "id": plugin_id,
                "name": str(metadata.get("name") or plugin_id),
                "summary": str(metadata.get("summary") or "").strip(),
                "docs_url": str(metadata.get("docs_url") or "").strip(),
                "path": str(child.relative_to(project_root)).replace("\\", "/"),
                "enabled": plugin_state.get(plugin_id, True),
            })
    return items


AI_GENERATE_VISION_TYPES = {"encounter", "npc", "creature", "player_character", "artifact", "cypher", "landmark", "settlement", "inn"}
OLLAMA_VISION_MODEL = "llama3.2-vision"


def ai_generate_vision_prompt(content_type: str) -> str:
    content_type_normalized = str(content_type or "").strip().lower()
    prompts = {
        "encounter": (
            "Analyze the image as an RPG encounter seed. Identify the scene, threats, factions, mood, terrain, "
            "points of tension, and what is about to happen. Reconcile visible details with any retrieved local lore before inventing new facts. "
            "Convert what you infer into a playable Cypher System encounter."
        ),
        "npc": (
            "Analyze the image as a character portrait or scene reference. Infer the subject's role, demeanor, status, gear, "
            "motivation, likely environment, and how they would interact with players. Infer likely gender, profession, race, and culture from visible cues when possible, "
            "but stay restrained if the evidence is weak. Anchor those cues in retrieved local lore whenever possible. "
            "Convert those cues into a playable Cypher System NPC."
        ),
        "creature": (
            "Analyze the image as a creature, beast, monster, or supernatural threat reference. Infer anatomy, movement, habitat, hunting or defensive behavior, "
            "temperament, and the sort of danger it presents in play. Reconcile what you see with retrieved local lore so the result feels like a native creature of the setting "
            "instead of a generic monster. Convert those cues into a playable Cypher System creature."
        ),
        "player_character": (
            "Analyze the image as a player character portrait or concept reference. Infer the subject's archetype, demeanor, gear, fighting style, "
            "social role, and the sort of tier 1 abilities they would plausibly begin with. Infer likely gender, profession, race, and culture from visible cues when possible, "
            "but stay restrained if the evidence is weak. Reconcile what you see with retrieved local lore, ancestry, "
            "profession, area, and culture context so the result feels like a real local pregen rather than a generic fantasy hero. Convert those cues into a complete "
            "Cypher System player character with attacks and starting equipment."
        ),
        "artifact": (
            "Analyze the image as a strange magical, numenera, occult, or rare item reference. Infer what the object looks like, "
            "how it is carried or activated, what it likely does, and what makes it dangerous or valuable. Match the item to local setting history, factions, "
            "materials, or traditions if the retrieved lore supports that. Convert that into a Cypher System artifact."
        ),
        "cypher": (
            "Analyze the image as inspiration for a one-use Cypher item. Infer the object's form, material, activation style, and a concise but flavorful effect. "
            "Where possible, tie it to retrieved local lore instead of making it feel generic. "
            "Convert the visual cues into a Cypher System cypher."
        ),
        "landmark": (
            "Analyze the image as a world landmark or notable site. Infer the location type, visible features, atmosphere, history hints, danger signs, and adventure potential. "
            "Prioritize local lore continuity when interpreting the site's history, names, and significance. Convert those cues into a Cypher System landmark entry."
        ),
        "settlement": (
            "Analyze the image as a settlement, outpost, district, village, city, or inhabited location. Infer how people live there, the settlement type, economy, social tone, "
            "architecture, local landmark, and current tension. Make the result feel native to the retrieved local lore, not like a generic fantasy settlement. "
            "Convert those cues into a Cypher System settlement."
        ),
        "inn": (
            "Analyze the image as an inn, tavern, roadhouse, hostel, or public house. Infer its atmosphere, clientele, social role, notable features, proprietor vibe, and local rumors. "
            "Anchor the result in retrieved local lore and culture-specific naming patterns so it feels like a real establishment of the setting rather than a generic fantasy tavern."
        ),
    }
    return prompts.get(
        content_type_normalized,
        "Analyze the image carefully and convert the visible cues into useful Cypher System worldbuilding content, preferring retrieved local lore over generic invention.",
    )


def register_routes(app: Flask) -> None:
    ## Helpers 
    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    DOCS_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".rst"}
    FOUNDRY_COMPENDIUM_ID = "foundryvtt"
    PLAYERS_GUIDE_DOC_PATH = (
        "PDF_Repository/private_compendium/_docling/"
        "cypher_og_cspg_old_gus_cypher_system_players_guide/"
        "cypher-og-cspg-old-gus-cypher-system-players-guide.md"
    )
    DATA_IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*\]\(data:image[^)]*\)", re.IGNORECASE | re.DOTALL)

    def normalize_source_key(value: object) -> str:
        text = str(value or "").strip().lower()
        return re.sub(r"[^a-z0-9]+", "", text)

    def is_foundry_source(value: object) -> bool:
        key = normalize_source_key(value)
        return key in {"foundryvtt", "foundry"}

    def configured_settings_catalog() -> list[str]:
        return settings_catalog(current_app.config["LOL_CONFIG"])

    def configured_default_settings() -> list[str]:
        return default_settings(current_app.config["LOL_CONFIG"])

    def configured_settings_nav() -> dict:
        return settings_nav_model(current_app.config["LOL_CONFIG"])

    def plugin_roots() -> list[Path]:
        return plugin_roots_from_project_root(current_app.config["LOL_PROJECT_ROOT"])

    def private_compendium_root() -> Path:
        return current_app.config["LOL_PROJECT_ROOT"] / "PDF_Repository" / "private_compendium"

    def compendium_profiles_dir() -> Path:
        return private_compendium_root() / "compendiums"

    def load_compendium_profiles() -> dict[str, dict]:
        project_root = current_app.config["LOL_PROJECT_ROOT"]
        profiles_dir = compendium_profiles_dir()
        profiles: dict[str, dict] = {}
        if not profiles_dir.exists():
            profiles_dir_files: list[Path] = []
        else:
            profiles_dir_files = sorted(profiles_dir.glob("*.json"))
        for path in profiles_dir_files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            profile_id = str(payload.get("id") or path.stem).strip().lower()
            if not profile_id:
                continue
            payload["id"] = profile_id
            payload["profile_path"] = str(path.relative_to(project_root)).replace("\\", "/")
            profiles[profile_id] = payload

        pdf_root = project_root / "PDF_Repository"
        auto_scan_roots = [
            ("Genre_Books", "official"),
            ("Setting_Books", "official"),
            ("Core_Rules", "core_pdf"),
        ]
        for folder_name, source_kind in auto_scan_roots:
            folder = pdf_root / folder_name
            if not folder.exists() or not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.pdf")):
                profile_id = _safe_slug(path.stem)
                if not profile_id or profile_id in profiles:
                    continue
                pretty_name = re.sub(r"[_\-]+", " ", path.stem).strip()
                pretty_name = re.sub(r"\s+", " ", pretty_name)
                profiles[profile_id] = {
                    "id": profile_id,
                    "name": pretty_name.title() if pretty_name else path.stem,
                    "subtitle": "Auto-discovered PDF sourcebook",
                    "pdf_relative_path": str(path.relative_to(pdf_root)).replace("\\", "/"),
                    "profile_path": "",
                    "source_kind": source_kind,
                    "book_title": pretty_name.title() if pretty_name else path.stem,
                }
        return profiles

    def _official_compendium_default_genre(compendium_id: str) -> str:
        cid = str(compendium_id or "").strip().lower()
        defaults = {
            "godforsaken": "Fantasy",
            "claim_the_sky": "Superheroes",
            "the_stars_are_fire": "Science Fiction",
            "its_only_magic": "Modern Magic",
            "high_noon_at_midnight": "Weird West",
            "neon_rain": "Cyberpunk",
            "rust_and_redemption": "Post-Apocalyptic",
            "stay_alive": "Horror",
            "we_are_all_mad_here": "Fairy Tale",
            "first_responders": "Modern",
        }
        return str(defaults.get(cid) or "Mixed")

    def _official_setting_world_default(compendium_id: str) -> str:
        cid = str(compendium_id or "").strip().lower()
        # Setting books map to a concrete world/setting identity.
        defaults = {
            "path_of_the_planebreaker": "Path of the Planebreaker",
            "planar_bestiary": "Path of the Planebreaker",
            "planar_character_options": "Path of the Planebreaker",
            "predation": "Predation",
            "gods_of_the_fall": "Gods of the Fall",
            "gunslinger_knights": "Gunslinger Knights",
            "old_gods_of_appalachia": "Old Gods of Appalachia",
            "the_origin": "The Origin",
            "unmasked": "Unmasked",
        }
        return str(defaults.get(cid) or "")

    def _display_sourcebook_label(value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        key = _safe_slug(raw)
        if "old_gods_of_appalachia" in key:
            return "Old Gods"
        if "cypher_system" in key and ("core_rulebook" in key or "rulebook" in key):
            return "Core Rulebook"
        return raw

    def _with_display_sourcebook_label(entry: dict | None) -> dict:
        if not isinstance(entry, dict):
            return {}
        out = dict(entry)
        if "book" in out:
            out["book"] = _display_sourcebook_label(out.get("book"))
        return out

    def _storage_card_ref_exists(storage_dir: Path, value: object) -> bool:
        raw = str(value or "").strip().replace("\\", "/")
        if not raw:
            return False
        rel = raw
        if raw.startswith("/storage/"):
            rel = raw[len("/storage/"):]
        elif raw.startswith("storage/"):
            rel = raw[len("storage/"):]
        if not rel.endswith(".json"):
            return False
        target = (storage_dir / rel).resolve()
        root = storage_dir.resolve()
        if not str(target).startswith(str(root) + "/") and target != root:
            return False
        return target.exists() and target.is_file()

    def _is_official_genre_book(compendium_id: str) -> bool:
        cid = str(compendium_id or "").strip().lower()
        return cid in {
            "godforsaken",
            "claim_the_sky",
            "the_stars_are_fire",
            "its_only_magic",
            "high_noon_at_midnight",
            "neon_rain",
            "rust_and_redemption",
            "stay_alive",
            "we_are_all_mad_here",
            "first_responders",
        }

    def compendium_taxonomy_tags(profile: dict, *, source_kind: str, compendium_id: str) -> dict[str, str]:
        cid = str(compendium_id or "").strip().lower()
        p = profile if isinstance(profile, dict) else {}

        core_rules = str(p.get("core_rules_tag") or "").strip()
        genre = str(p.get("genre_tag") or p.get("genre") or "").strip()
        setting = str(p.get("setting_tag") or p.get("setting") or "").strip()

        if cid == "csrd":
            if not core_rules:
                core_rules = "Core Rules"
            if not genre:
                genre = "Universal"
            if not setting:
                setting = "Core"
        elif source_kind == "official":
            if not core_rules:
                core_rules = "Supplement"
            if not genre:
                genre = _official_compendium_default_genre(cid)
            if not setting:
                explicit_setting = str(p.get("setting_world") or "").strip()
                inferred_world = _official_setting_world_default(cid)
                if explicit_setting:
                    setting = explicit_setting
                elif inferred_world:
                    setting = inferred_world
                elif _is_official_genre_book(cid):
                    setting = "Any"
                else:
                    setting = str(p.get("book_title") or p.get("name") or "").strip() or "Unspecified"
        elif source_kind == "core_pdf":
            if not core_rules:
                core_rules = "Core Rules"
            if not genre:
                genre = "Universal"
            if not setting:
                setting = str(p.get("name") or "Cypher System").strip()
        elif source_kind == "foundry":
            if not core_rules:
                core_rules = "N/A"
            if not genre:
                genre = "Mixed"
            if not setting:
                setting = "Mixed"
        elif source_kind == "settings_catalog":
            if not core_rules:
                core_rules = "Campaign Framework"
            if not genre:
                genre = "Multi-Genre"
            if not setting:
                setting = "All Settings"

        return {
            "core_rules": core_rules,
            "genre": genre,
            "setting": setting,
        }

    def compendium_source_kind(compendium_id: str, profile: dict | None = None) -> str:
        cid = str(compendium_id or "").strip().lower()
        if cid == "csrd":
            return "csrd"
        if cid == FOUNDRY_COMPENDIUM_ID:
            return "foundry"
        if cid in {"settings_catalog", "settings"}:
            return "settings_catalog"
        p = profile if isinstance(profile, dict) else {}
        configured = str(p.get("source_kind") or "").strip().lower()
        if configured in {"official", "core_pdf", "settings_catalog"}:
            return configured
        return "official"

    def _safe_slug(value: str) -> str:
        clean = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or ""))
        while "__" in clean:
            clean = clean.replace("__", "_")
        return clean.strip("_") or "unknown"

    def _pid_running(pid: int | None) -> bool:
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    def _read_json(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def map_projects_dir() -> Path:
        return current_app.config["LOL_PROJECT_ROOT"] / "maps" / "projects"

    def map_project_path(project_id: str) -> Path:
        pid = _safe_slug(project_id)
        return map_projects_dir() / f"{pid}.json"

    def _normalize_map_marker(value: object) -> dict[str, object]:
        raw = value if isinstance(value, dict) else {}
        marker_type = str(raw.get("type") or "landmark").strip().lower()
        if marker_type not in {"city", "settlement", "village", "landmark"}:
            marker_type = "landmark"
        try:
            x = float(raw.get("x"))
        except Exception:
            x = 0.0
        try:
            y = float(raw.get("y"))
        except Exception:
            y = 0.0
        x = max(0.0, min(100.0, x))
        y = max(0.0, min(100.0, y))
        return {
            "id": str(raw.get("id") or uuid.uuid4().hex[:10]).strip() or uuid.uuid4().hex[:10],
            "type": marker_type,
            "x": round(x, 4),
            "y": round(y, 4),
            "label": str(raw.get("label") or raw.get("name") or "").strip(),
            "brief": str(raw.get("brief") or "").strip(),
            "provider": str(raw.get("provider") or "").strip().lower() or "ollama_local",
            "content_type": str(raw.get("content_type") or "").strip().lower(),
            "storage_filename": str(raw.get("storage_filename") or "").strip(),
            "card_name": str(raw.get("card_name") or "").strip(),
            "card_type": str(raw.get("card_type") or "").strip().lower(),
            "card_summary": str(raw.get("card_summary") or "").strip(),
            "card": raw.get("card") if isinstance(raw.get("card"), dict) else {},
        }

    def _normalize_map_area(value: object) -> dict[str, object]:
        raw = value if isinstance(value, dict) else {}
        points_raw = raw.get("points") if isinstance(raw.get("points"), list) else []
        points: list[dict[str, float]] = []
        for item in points_raw:
            if not isinstance(item, dict):
                continue
            try:
                x = float(item.get("x"))
                y = float(item.get("y"))
            except Exception:
                continue
            x = max(0.0, min(100.0, x))
            y = max(0.0, min(100.0, y))
            points.append({"x": round(x, 4), "y": round(y, 4)})
        if len(points) < 3:
            points = []

        def centroid(values: list[dict[str, float]]) -> tuple[float, float]:
            if not values:
                return (50.0, 50.0)
            return (
                sum(point["x"] for point in values) / len(values),
                sum(point["y"] for point in values) / len(values),
            )

        default_x, default_y = centroid(points)
        try:
            label_x = float(raw.get("label_x"))
        except Exception:
            label_x = default_x
        try:
            label_y = float(raw.get("label_y"))
        except Exception:
            label_y = default_y
        label_x = max(0.0, min(100.0, label_x))
        label_y = max(0.0, min(100.0, label_y))

        return {
            "id": str(raw.get("id") or uuid.uuid4().hex[:10]).strip() or uuid.uuid4().hex[:10],
            "name": str(raw.get("name") or raw.get("label") or "").strip() or "Unnamed Area",
            "points": points,
            "label_x": round(label_x, 4),
            "label_y": round(label_y, 4),
            "notes": str(raw.get("notes") or "").strip(),
        }

    def _normalize_map_project(value: object) -> dict[str, object]:
        raw = value if isinstance(value, dict) else {}
        name = str(raw.get("name") or "").strip() or "Untitled Map"
        raw_id = str(raw.get("id") or "").strip()
        project_id = _safe_slug(raw_id) if raw_id else ""
        if not project_id or project_id == "unknown":
            project_id = _safe_slug(name)
        if project_id == "unknown":
            project_id = ""
        project_id = project_id or f"map_project_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        markers_raw = raw.get("markers") if isinstance(raw.get("markers"), list) else []
        markers = [_normalize_map_marker(item) for item in markers_raw if isinstance(item, dict)]
        areas_raw = raw.get("areas") if isinstance(raw.get("areas"), list) else []
        areas = [_normalize_map_area(item) for item in areas_raw if isinstance(item, dict)]
        updated_at = str(raw.get("updated_at") or datetime.now(timezone.utc).isoformat()).strip()
        created_at = str(raw.get("created_at") or updated_at).strip()
        return {
            "id": project_id,
            "name": name,
            "setting": normalize_setting_token(str(raw.get("setting") or "").strip()),
            "area": str(raw.get("area") or "").strip(),
            "map_image": str(raw.get("map_image") or raw.get("image") or "").strip(),
            "map_image_path": normalize_image_ref(str(raw.get("map_image_path") or "").strip()),
            "notes": str(raw.get("notes") or "").strip(),
            "is_default": bool(raw.get("is_default")),
            "markers": markers,
            "areas": areas,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def list_map_projects() -> list[dict[str, object]]:
        root = map_projects_dir()
        items: list[dict[str, object]] = []
        if not root.exists():
            return items
        for path in sorted(root.glob("*.json"), reverse=True):
            data = _read_json(path)
            if not data:
                continue
            project = _normalize_map_project(data)
            items.append({
                "id": str(project.get("id") or ""),
                "name": str(project.get("name") or ""),
                "setting": str(project.get("setting") or ""),
                "area": str(project.get("area") or ""),
                "map_image": str(project.get("map_image") or ""),
                "map_image_path": str(project.get("map_image_path") or ""),
                "is_default": bool(project.get("is_default")),
                "marker_count": len(project.get("markers") or []),
                "area_count": len(project.get("areas") or []),
                "updated_at": str(project.get("updated_at") or ""),
            })
        items.sort(
            key=lambda item: (
                0 if bool(item.get("is_default")) else 1,
                -datetime.fromisoformat(
                    str(item.get("updated_at") or datetime.now(timezone.utc).isoformat())
                ).timestamp(),
            )
        )
        return items

    def load_map_project(project_id: str) -> dict[str, object]:
        path = map_project_path(project_id)
        if not path.exists():
            raise FileNotFoundError(project_id)
        return _normalize_map_project(_read_json(path))

    def save_map_project(data: object) -> dict[str, object]:
        project = _normalize_map_project(data)
        project["updated_at"] = datetime.now(timezone.utc).isoformat()
        if not str(project.get("created_at") or "").strip():
            project["created_at"] = str(project["updated_at"])
        if bool(project.get("is_default")):
            root = map_projects_dir()
            root.mkdir(parents=True, exist_ok=True)
            for path in sorted(root.glob("*.json")):
                if path == map_project_path(str(project.get("id") or "")):
                    continue
                existing = _read_json(path)
                if not existing:
                    continue
                normalized = _normalize_map_project(existing)
                if not bool(normalized.get("is_default")):
                    continue
                normalized["is_default"] = False
                _write_json(path, normalized)
        _write_json(map_project_path(str(project.get("id") or "")), project)
        return project

    def find_map_project_placements(*, storage_filename: str = "", card_name: str = "") -> list[dict[str, object]]:
        target_filename = str(storage_filename or "").strip()
        target_name = str(card_name or "").strip().lower()
        if not target_filename and not target_name:
            return []
        placements: list[dict[str, object]] = []
        for project_summary in list_map_projects():
            project_id = str(project_summary.get("id") or "").strip()
            if not project_id:
                continue
            try:
                project = load_map_project(project_id)
            except FileNotFoundError:
                continue
            markers = project.get("markers") if isinstance(project.get("markers"), list) else []
            for marker in markers:
                if not isinstance(marker, dict):
                    continue
                marker_filename = str(marker.get("storage_filename") or "").strip()
                marker_name = str(marker.get("card_name") or marker.get("label") or "").strip().lower()
                filename_match = bool(target_filename and marker_filename and marker_filename == target_filename)
                name_match = bool(target_name and marker_name and marker_name == target_name)
                if not filename_match and not name_match:
                    continue
                placements.append({
                    "project_id": project_id,
                    "project_name": str(project.get("name") or project_summary.get("name") or "").strip(),
                    "project_setting": str(project.get("setting") or project_summary.get("setting") or "").strip(),
                    "project_area": str(project.get("area") or project_summary.get("area") or "").strip(),
                    "marker_id": str(marker.get("id") or "").strip(),
                    "marker_label": str(marker.get("label") or marker.get("card_name") or "").strip(),
                    "marker_type": str(marker.get("type") or "").strip(),
                    "storage_filename": marker_filename,
                    "x": marker.get("x"),
                    "y": marker.get("y"),
                })
        return placements

    def _map_location_card_entries(
        *,
        setting: str = "",
        area: str = "",
        marker_type: str = "",
        query: str = "",
    ) -> list[dict[str, object]]:
        items = list_saved_results(
            current_app.config["LOL_STORAGE_DIR"],
            default_settings=configured_default_settings(),
        )
        wanted_setting = normalize_setting_token(setting)
        wanted_area = str(area or "").strip().lower()
        wanted_marker_type = str(marker_type or "").strip().lower()
        wanted_query = " ".join(str(query or "").strip().lower().replace("_", " ").split())
        rows: list[dict[str, object]] = []
        seen: set[str] = set()

        for item in items:
            filename = str(item.get("filename") or "").strip()
            if not filename or filename in seen:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            result_type = str(item.get("type") or "").strip().lower()
            subtype = str(metadata.get("subtype") or metadata.get("location_category_type") or "").strip().lower()
            place_type = subtype or result_type
            is_place = (
                result_type in {"location", "settlement", "inn", "city", "village", "landmark"}
                or subtype in {"landmark", "city", "village", "settlement", "inn", "river", "lake", "mountain"}
            )
            if not is_place:
                continue

            if wanted_marker_type:
                if wanted_marker_type == "landmark":
                    if place_type != "landmark":
                        continue
                elif wanted_marker_type == "city":
                    if place_type not in {"city", "settlement"}:
                        continue
                elif wanted_marker_type == "village":
                    if place_type not in {"village", "settlement"}:
                        continue
                elif wanted_marker_type == "settlement":
                    if place_type not in {"settlement", "city", "village", "inn"}:
                        continue

            settings = metadata.get("settings") if isinstance(metadata.get("settings"), list) else []
            normalized_settings = [normalize_setting_token(value) for value in settings if str(value or "").strip()]
            fallback_setting = normalize_setting_token(str(metadata.get("setting") or "").strip())
            if fallback_setting and fallback_setting not in normalized_settings:
                normalized_settings.append(fallback_setting)
            if wanted_setting and wanted_setting not in normalized_settings:
                continue

            current_area = str(metadata.get("area") or metadata.get("environment") or "").strip().lower()
            if wanted_area and current_area != wanted_area:
                continue

            name = str(item.get("name") or "").strip()
            description = str(item.get("description") or "").strip()
            current_location = str(metadata.get("location") or "").strip()
            haystack = " ".join(
                bit for bit in [
                    name.lower(),
                    description.lower(),
                    current_location.lower(),
                    current_area,
                    place_type.replace("_", " "),
                ] if bit
            )
            if wanted_query and wanted_query not in haystack.replace("_", " "):
                continue

            seen.add(filename)
            rows.append({
                "filename": filename,
                "name": name or filename,
                "type": result_type or "location",
                "place_type": place_type or result_type or "location",
                "area": str(metadata.get("area") or metadata.get("environment") or "").strip(),
                "location": current_location,
                "setting": normalized_settings[0] if normalized_settings else "",
                "description": description,
            })

        rows.sort(key=lambda row: (str(row.get("name") or "").lower(), str(row.get("filename") or "").lower()))
        return rows

    def resolve_profile_pdf_path(profile: dict) -> Path | None:
        rel = str(profile.get("pdf_relative_path") or "").strip().replace("\\", "/")
        root = (current_app.config["LOL_PROJECT_ROOT"] / "PDF_Repository").resolve()
        candidates: list[Path] = []

        if rel:
            target = (root / rel).resolve()
            if str(target).startswith(str(root)):
                candidates.append(target)
            if rel.startswith("Setting_Books/"):
                alt = (root / rel.replace("Setting_Books/", "Genre_Books/", 1)).resolve()
                if str(alt).startswith(str(root)):
                    candidates.append(alt)
            if rel.startswith("Genre_Books/"):
                alt = (root / rel.replace("Genre_Books/", "Setting_Books/", 1)).resolve()
                if str(alt).startswith(str(root)):
                    candidates.append(alt)

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate

        # Last-resort filename match inside known book roots.
        filename = Path(rel).name if rel else ""
        if filename:
            for folder in ("Genre_Books", "Setting_Books", "Core_Rules"):
                match = (root / folder / filename).resolve()
                if str(match).startswith(str(root)) and match.exists() and match.is_file():
                    return match
        return None

    def docling_root() -> Path:
        configured = str(get_plugin_settings("docling").get("output_root") or "PDF_Repository/private_compendium/_docling").strip()
        project_root = current_app.config["LOL_PROJECT_ROOT"]
        path = Path(configured)
        resolved = (project_root / path).resolve() if not path.is_absolute() else path.resolve()
        try:
            resolved.relative_to(project_root)
        except ValueError:
            return private_compendium_root() / "_docling"
        return resolved

    def docling_status_path() -> Path:
        return docling_root() / "runner_status.json"

    def docling_markdown_files_for_compendium(profile: dict) -> list[Path]:
        root = docling_root()
        if not root.exists():
            return []
        candidates = compendium_docling_slugs(profile)
        allowed_suffixes = (".md", ".md-first-run")
        files: list[Path] = []
        seen: set[str] = set()
        for slug in candidates:
            d = root / slug
            if not d.exists() or not d.is_dir():
                continue
            for path in sorted(d.iterdir()):
                if not path.is_file():
                    continue
                name = path.name.lower()
                if not any(name.endswith(sfx) for sfx in allowed_suffixes):
                    continue
                key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                files.append(path)
        return files

    def compendium_docling_slugs(profile: dict) -> list[str]:
        profile_id = str(profile.get("id") or "").strip().lower()
        pdf_path = resolve_profile_pdf_path(profile)
        candidates: list[str] = []
        if profile_id:
            candidates.append(profile_id)
        if pdf_path is not None:
            candidates.append(_safe_slug(pdf_path.stem))
        unique: list[str] = []
        seen: set[str] = set()
        for value in candidates:
            text = str(value or "").strip().lower()
            if not text or text in seen:
                continue
            seen.add(text)
            unique.append(text)
        return unique

    def docling_runtime_state() -> dict:
        status_path = docling_status_path()
        status = _read_json(status_path)
        state = str(status.get("state") or "").strip().lower()
        pid = int(status.get("pid") or 0) if str(status.get("pid") or "").isdigit() else 0
        running = state == "running" and _pid_running(pid)
        if state == "running" and not running:
            status["state"] = "completed"
            status["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(status_path, status)
        status["running"] = running
        return status

    def parser_jobs_dir() -> Path:
        path = private_compendium_root() / "_parser_jobs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def parser_status_path(compendium_id: str) -> Path:
        return parser_jobs_dir() / f"{compendium_id}.json"

    def parser_runtime_state(compendium_id: str) -> dict:
        path = parser_status_path(compendium_id)
        data = _read_json(path)
        state = str(data.get("state") or "").strip().lower()
        pid = int(data.get("pid") or 0) if str(data.get("pid") or "").isdigit() else 0
        running = state == "running" and _pid_running(pid)
        if state == "running" and not running:
            data["state"] = "completed"
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(path, data)
        data["running"] = running
        return data

    def vector_index_root() -> Path:
        path = private_compendium_root() / "_vector"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def sync_saved_record_to_vector(filename: str) -> dict[str, int | str]:
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        path = (storage_dir / filename).resolve()
        root = storage_dir.resolve()
        if not str(path).startswith(str(root) + "/") and path != root:
            raise FileNotFoundError(f"No saved result named '{filename}'")
        if not path.exists():
            raise FileNotFoundError(f"No saved result named '{filename}'")
        return sync_single_storage_card(
            storage_root=storage_dir,
            card_path=path,
            output_root=vector_index_root(),
        )

    def remove_saved_record_from_vector(filename: str) -> dict[str, int | str]:
        return remove_single_storage_card(
            storage_root=current_app.config["LOL_STORAGE_DIR"],
            relative_filename=filename,
            output_root=vector_index_root(),
        )

    def vector_jobs_dir() -> Path:
        path = private_compendium_root() / "_vector_jobs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def vector_status_path(compendium_id: str) -> Path:
        return vector_jobs_dir() / f"{compendium_id}.json"

    def vector_runtime_state(compendium_id: str) -> dict:
        path = vector_status_path(compendium_id)
        data = _read_json(path)
        state = str(data.get("state") or "").strip().lower()
        pid = int(data.get("pid") or 0) if str(data.get("pid") or "").isdigit() else 0
        running = state == "running" and _pid_running(pid)
        if state == "running" and not running:
            data["state"] = "completed"
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(path, data)
        data["running"] = running
        return data

    def vector_count_for_compendium(compendium_id: str, aliases: list[str] | None = None) -> int:
        db_path = vector_index_root() / "vector_index.sqlite"
        if not db_path.exists():
            return 0
        candidate_ids = [str(compendium_id or "").strip().lower()]
        for alias in aliases or []:
            text = str(alias or "").strip().lower()
            if text and text not in candidate_ids:
                candidate_ids.append(text)
        candidate_ids = [x for x in candidate_ids if x]
        if not candidate_ids:
            return 0
        try:
            conn = sqlite3.connect(str(db_path))
            placeholders = ",".join("?" for _ in candidate_ids)
            row = conn.execute(
                f"SELECT COUNT(*) FROM documents WHERE compendium_id IN ({placeholders})",
                tuple(candidate_ids),
            ).fetchone()
            conn.close()
            return int(row[0] or 0) if row else 0
        except Exception:
            return 0

    def _launch_background(cmd: list[str], *, log_path: Path, env_extra: dict[str, str] | None = None) -> int:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as handle:
            env = os.environ.copy()
            if env_extra:
                for key, value in env_extra.items():
                    env[str(key)] = str(value)
            proc = subprocess.Popen(
                cmd,
                cwd=str(current_app.config["LOL_PROJECT_ROOT"]),
                stdout=handle,
                stderr=subprocess.STDOUT,
                env=env,
            )
        return int(proc.pid)

    def detect_docling_device() -> str:
        try:
            proc = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if proc.returncode == 0 and str(proc.stdout or "").strip():
                return "cuda"
        except Exception:
            pass
        return "cpu"

    def start_docling_for_pdf(pdf_path: Path, compendium_id: str) -> int:
        settings = get_plugin_settings("docling")
        preferred_device = str(settings.get("default_device") or "auto").strip().lower()
        if preferred_device in {"cpu", "cuda"}:
            device = preferred_device
        else:
            device = detect_docling_device()
        output_root = str(settings.get("output_root") or "PDF_Repository/private_compendium/_docling").strip()
        cmd_template = str(settings.get("command_template") or "").strip()
        cmd = [
            sys.executable,
            "-m",
            "Plugins.docling.runner",
            "--pdf",
            str(pdf_path),
            "--device",
            device,
            "--output-root",
            output_root,
            "--quiet",
        ]
        return _launch_background(
            cmd,
            log_path=docling_root() / "runner.log",
            env_extra={"DOCLING_CMD_TEMPLATE": cmd_template} if cmd_template else None,
        )

    def start_parser_for_pdf(profile: dict, pdf_path: Path) -> int:
        cid = str(profile.get("id") or "").strip().lower()
        book_title = str(profile.get("book_title") or profile.get("name") or pdf_path.stem).strip()
        settings = profile.get("settings")
        if not isinstance(settings, list):
            settings = []
        docling_files = docling_markdown_files_for_compendium(profile)
        cmd = [sys.executable, "scripts/import_official_pdf_compendium.py", "--out-dir", str(private_compendium_root())]
        if docling_files:
            cmd.extend(["auto-import-docling", "--book", book_title, "--prefix-slug-with-book"])
            for md in docling_files:
                cmd.extend(["--markdown", str(md)])
        else:
            cmd.extend([
                "auto-import",
                "--pdf",
                str(pdf_path),
                "--book",
                book_title,
                "--prefix-slug-with-book",
            ])
        if settings:
            cmd.extend(["--settings", ",".join([str(s).strip() for s in settings if str(s).strip()])])
        pid = _launch_background(
            cmd,
            log_path=parser_jobs_dir() / f"{cid}.log",
        )
        _write_json(
            parser_status_path(cid),
            {
                "state": "running",
                "pid": pid,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "compendium_id": cid,
                "pdf_path": str(pdf_path),
                "book_title": book_title,
                "docling_files": [str(p) for p in docling_files],
                "command": cmd,
                "log_path": str((parser_jobs_dir() / f"{cid}.log")),
            },
        )
        return pid

    def start_vector_index_for_compendium(compendium_id: str) -> int:
        cid = str(compendium_id or "").strip().lower()
        cmd = [
            sys.executable,
            "-m",
            "Plugins.docling.vector_index",
            "--docling-root",
            str(docling_root()),
            "--output-root",
            str(vector_index_root()),
            "build",
            "--compendium-id",
            cid,
            "--quiet",
        ]
        pid = _launch_background(
            cmd,
            log_path=vector_jobs_dir() / f"{cid}.log",
        )
        _write_json(
            vector_status_path(cid),
            {
                "state": "running",
                "pid": pid,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "compendium_id": cid,
                "command": cmd,
                "log_path": str((vector_jobs_dir() / f"{cid}.log")),
            },
        )
        return pid

    def official_book_item_count_by_compendium_id() -> dict[str, int]:
        official_dir = current_app.config["LOL_OFFICIAL_COMPENDIUM_DIR"]
        index = load_official_compendium_index(official_dir) or {}
        items = index.get("items") or []
        counts: dict[str, int] = {}
        for row in items:
            if not isinstance(row, dict):
                continue
            cid = normalize_source_key(row.get("book"))
            if not cid:
                continue
            counts[cid] = counts.get(cid, 0) + 1
        return counts

    def compendium_pipeline_status(
        profile: dict,
        *,
        source_kind: str,
        parser_count: int = 0,
        auto_start: bool = True,
    ) -> dict:
        cid = str(profile.get("id") or "").strip().lower()
        pdf_path = resolve_profile_pdf_path(profile)
        has_pdf_reference = bool(str(profile.get("pdf_relative_path") or "").strip())
        pdf_present = bool(pdf_path and pdf_path.exists())
        enabled = True
        disabled_reason = ""
        if has_pdf_reference and not pdf_present:
            enabled = False
            disabled_reason = "missing_pdf"

        docling_files = docling_markdown_files_for_compendium(profile)
        docling_processed = bool(docling_files)
        docling_status = docling_runtime_state()
        docling_running = bool(docling_status.get("running"))
        parser_status = parser_runtime_state(cid) if cid else {}
        parser_running = bool(parser_status.get("running"))
        parser_processed = int(parser_count or 0) > 0
        vector_status = vector_runtime_state(cid) if cid else {}
        vector_running = bool(vector_status.get("running"))
        docling_slugs = compendium_docling_slugs(profile)
        vector_processed = vector_count_for_compendium(
            cid,
            aliases=[x for x in docling_slugs if x != cid],
        ) > 0 if cid else False
        docling_started = False
        parser_started = False
        vector_started = False

        can_auto_docling_vector = source_kind in {"official", "core_pdf"} and enabled and pdf_present and pdf_path is not None
        can_auto_parser = source_kind == "official" and enabled and pdf_present and pdf_path is not None
        if auto_start and can_auto_docling_vector and not docling_processed and not docling_running:
            start_docling_for_pdf(pdf_path, cid)
            docling_started = True
            docling_running = True

        if auto_start and can_auto_parser and docling_processed and not parser_processed and not parser_running:
            start_parser_for_pdf(profile, pdf_path)
            parser_started = True
            parser_running = True

        if auto_start and can_auto_docling_vector and docling_processed and not vector_processed and not vector_running:
            start_vector_index_for_compendium(cid)
            vector_started = True
            vector_running = True

        raw_text_url = ""
        if docling_files:
            first = docling_files[0]
            rel = str(first.relative_to(docling_root())).replace("\\", "/")
            raw_text_url = f"/compendiums/{cid}/raw-text?path={rel}"

        return {
            "enabled": enabled,
            "disabled_reason": disabled_reason,
            "pdf_present": pdf_present,
            "pdf_path": str(pdf_path) if pdf_path else "",
            "docling_processed": docling_processed,
            "docling_running": docling_running,
            "docling_auto_started": docling_started,
            "docling_status": docling_status,
            "docling_markdown_count": len(docling_files),
            "docling_slugs": docling_slugs,
            "parser_processed": parser_processed,
            "parser_running": parser_running,
            "parser_auto_started": parser_started,
            "parser_status": parser_status,
            "vector_processed": vector_processed,
            "vector_running": vector_running,
            "vector_auto_started": vector_started,
            "vector_status": vector_status,
            "raw_text_url": raw_text_url,
        }

    def enabled_compendium_ids_for_search() -> set[str]:
        profiles = load_compendium_profiles()
        official_counts = official_book_item_count_by_compendium_id()
        ids: set[str] = {FOUNDRY_COMPENDIUM_ID}

        csrd_profile = {"id": "csrd", **(profiles.get("csrd") or {})}
        csrd_pipeline = compendium_pipeline_status(csrd_profile, source_kind="csrd", auto_start=False)
        if csrd_pipeline.get("enabled", True):
            ids.add("csrd")

        for pid, profile in profiles.items():
            cid = str(pid or "").strip().lower()
            if cid in {"csrd", FOUNDRY_COMPENDIUM_ID}:
                continue
            source_kind = compendium_source_kind(cid, profile)
            pipeline = compendium_pipeline_status(
                profile,
                source_kind=source_kind,
                parser_count=official_counts.get(cid, 0),
                auto_start=False,
            )
            if pipeline.get("enabled", True):
                ids.add(cid)
        return ids

    def plugin_state_path() -> Path:
        return current_app.config["LOL_CONFIG_DIR"] / "plugins_state.json"

    def plugin_settings_path() -> Path:
        return current_app.config["LOL_CONFIG_DIR"] / "plugins_settings.json"

    def plugin_secrets_path() -> Path:
        return current_app.config["LOL_CONFIG_DIR"] / "plugins_secrets.json"

    def load_plugin_settings_store() -> dict[str, dict]:
        path = plugin_settings_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, dict] = {}
        for key, value in data.items():
            plugin_id = str(key or "").strip()
            if not plugin_id or not isinstance(value, dict):
                continue
            out[plugin_id] = {str(k): str(v) for k, v in value.items()}
        return out

    def load_plugin_secrets_store() -> dict[str, dict]:
        path = plugin_secrets_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, dict] = {}
        for key, value in data.items():
            plugin_id = str(key or "").strip()
            if not plugin_id or not isinstance(value, dict):
                continue
            out[plugin_id] = {str(k): str(v) for k, v in value.items()}
        return out

    def save_plugin_settings_store(store: dict[str, dict]) -> None:
        path = plugin_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        serializable: dict[str, dict] = {}
        for plugin_id, values in sorted(store.items(), key=lambda kv: kv[0]):
            pid = str(plugin_id or "").strip()
            if not pid or not isinstance(values, dict):
                continue
            serializable[pid] = {str(k): str(v) for k, v in sorted(values.items(), key=lambda kv: kv[0])}
        path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")

    def save_plugin_secrets_store(store: dict[str, dict]) -> None:
        path = plugin_secrets_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        serializable: dict[str, dict] = {}
        for plugin_id, values in sorted(store.items(), key=lambda kv: kv[0]):
            pid = str(plugin_id or "").strip()
            if not pid or not isinstance(values, dict):
                continue
            serializable[pid] = {str(k): str(v) for k, v in sorted(values.items(), key=lambda kv: kv[0])}
        path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")

    def is_secret_plugin_setting(plugin_id: str, key: str) -> bool:
        pid = str(plugin_id or "").strip()
        skey = str(key or "").strip()
        secret_keys: dict[str, set[str]] = {
            "openai_remote": {"api_key"},
            "foundryVTT": {"api_token"},
        }
        return skey in secret_keys.get(pid, set())

    def plugin_settings_defaults(plugin_id: str) -> dict[str, str]:
        pid = str(plugin_id or "").strip()
        if pid == "docling":
            return {
                "default_device": "auto",
                "output_root": "PDF_Repository/private_compendium/_docling",
                "command_template": str(os.getenv("DOCLING_CMD_TEMPLATE", 'docling "{input}" --output "{output_dir}" --device {device}')).strip(),
            }
        if pid == "ollama_local":
            return {
                "base_url": str(current_app.config.get("LOL_OLLAMA_BASE_URL") or "http://127.0.0.1:11434").strip(),
                "default_model": str(current_app.config.get("LOL_OLLAMA_DEFAULT_MODEL") or "llama3.1").strip(),
                "keep_alive": "10m",
                "system_prompt": (
                    "You are Legends GMTools Assistant, a Cypher System-only GM copilot.\n"
                    "Use only the provided context snippets and citations.\n"
                    "Never mix in mechanics from other RPG systems.\n"
                    "\n"
                    "Hard constraints:\n"
                    "1) Cypher terminology only. Prefer: Level, Target Number (Level x 3), Health, Armor, Damage Inflicted, Movement, Modifications, Combat, Interaction, Use, GM Intrusion, Loot, Motive, Environment.\n"
                    "2) Forbidden terms unless directly quoted from context: AC, hit points/HP, initiative modifier, saving throw, DC, class feature, proficiency bonus, Essence, Momentum, Shaken, Shadow bloodline.\n"
                    "3) If context does not provide a rule/stat, say \"Not found in indexed Cypher context\" and give a safe placeholder, not invented mechanics.\n"
                    "4) Never invent page numbers. Cite only as [n] from provided snippets.\n"
                    "5) Keep output practical for table play and concise.\n"
                    "\n"
                    "If user asks for a random encounter, use this structure:\n"
                    "- Encounter Title\n"
                    "- Situation (2-3 sentences)\n"
                    "- Encounter Level and Target Number\n"
                    "- Creatures/NPCs (for each: Name, Level, Health, Armor, Damage Inflicted, Movement, Modifications)\n"
                    "- Tactics (3 bullets)\n"
                    "- GM Intrusion (1-2 options)\n"
                    "- Loot/Cyphers\n"
                    "- Assumptions / Missing Data\n"
                    "- Citations [n]\n"
                    "\n"
                    "Before finalizing, silently self-check and remove forbidden cross-system terms."
                    "\n\n"
                    "Description quality:\n"
                    "- Prefer richer descriptions by default (about 3-6 sentences) with concrete details.\n"
                    "- Include notable visual cues, mood, and context-relevant hooks when space allows.\n"
                    "- Stay concise overall, but avoid overly terse one-line descriptions unless requested."
                ),
            }
        if pid == "openai_remote":
            return {
                "base_url": str(current_app.config.get("LOL_OPENAI_BASE_URL") or "https://api.openai.com").strip(),
                "default_model": str(current_app.config.get("LOL_OPENAI_DEFAULT_MODEL") or "gpt-4o-mini").strip(),
                "api_key": str(current_app.config.get("LOL_OPENAI_API_KEY") or "").strip(),
                "system_prompt": (
                    "You are Legends GMTools Assistant, a Cypher System-only GM copilot.\n"
                    "Use only the provided context snippets and citations.\n"
                    "Never mix in mechanics from other RPG systems.\n"
                    "Never invent page numbers, stats, or rules not present in context.\n"
                    "Write richer descriptions by default (about 3-6 sentences) with concrete details,\n"
                    "while keeping the rest of the output practical and concise."
                ),
            }
        if pid == "foundryVTT":
            origins = current_app.config.get("LOL_FOUNDRYVTT_ALLOWED_ORIGINS") or []
            if isinstance(origins, str):
                origins_text = origins
            elif isinstance(origins, list):
                origins_text = ",".join(str(v).strip() for v in origins if str(v).strip())
            else:
                origins_text = ""
            defaults = {
                "api_token": str(current_app.config.get("LOL_FOUNDRYVTT_API_TOKEN") or "").strip(),
                "allowed_origins": origins_text,
            }
            for cid in sorted(enabled_compendium_ids_for_search()):
                if cid == FOUNDRY_COMPENDIUM_ID:
                    continue
                defaults[f"sync_compendium__{cid}"] = "0"
            return defaults
        return {}

    def get_plugin_settings(plugin_id: str) -> dict[str, str]:
        pid = str(plugin_id or "").strip()
        defaults = plugin_settings_defaults(pid)
        settings_store = load_plugin_settings_store()
        secrets_store = load_plugin_secrets_store()
        persisted = settings_store.get(pid) or {}
        secrets = secrets_store.get(pid) or {}
        merged = {**defaults}
        for key, value in persisted.items():
            if key in defaults:
                merged[key] = str(value)
        for key, value in secrets.items():
            if key in defaults and is_secret_plugin_setting(pid, key):
                merged[key] = str(value)
        return merged

    def update_plugin_settings(plugin_id: str, values: dict) -> dict[str, str]:
        pid = str(plugin_id or "").strip()
        defaults = plugin_settings_defaults(pid)
        if not defaults:
            raise ValueError(f"unknown plugin settings schema for '{pid}'")
        settings_store = load_plugin_settings_store()
        secrets_store = load_plugin_secrets_store()
        current_settings = settings_store.get(pid) or {}
        current_secrets = secrets_store.get(pid) or {}
        # Ensure sensitive fields are never persisted in the non-secret store.
        for key in list(current_settings.keys()):
            if is_secret_plugin_setting(pid, key):
                current_settings.pop(key, None)
        for key, raw in values.items():
            skey = str(key or "").strip()
            if skey not in defaults:
                continue
            value = str(raw or "").strip()
            if is_secret_plugin_setting(pid, skey):
                current_secrets[skey] = value
            else:
                current_settings[skey] = value
        settings_store[pid] = current_settings
        secrets_store[pid] = current_secrets
        save_plugin_settings_store(settings_store)
        save_plugin_secrets_store(secrets_store)
        return get_plugin_settings(pid)

    def load_plugin_state() -> dict[str, bool]:
        path = plugin_state_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        state: dict[str, bool] = {}
        for key, value in data.items():
            plugin_id = str(key or "").strip()
            if plugin_id:
                state[plugin_id] = bool(value)
        return state

    def save_plugin_state(state: dict[str, bool]) -> None:
        path = plugin_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {str(k): bool(v) for k, v in sorted(state.items()) if str(k).strip()}
        path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")

    def discover_plugins() -> list[dict]:
        return discover_plugins_from_roots(
            plugin_roots(),
            project_root=current_app.config["LOL_PROJECT_ROOT"],
            state=load_plugin_state(),
        )

    def is_plugin_enabled(plugin_id: str) -> bool:
        for item in discover_plugins():
            if item.get("id") == plugin_id:
                return bool(item.get("enabled"))
        return False

    def foundry_api_token() -> str:
        configured = get_plugin_settings("foundryVTT").get("api_token", "")
        return str(configured or "").strip()

    def foundry_allowed_origins() -> list[str]:
        values = get_plugin_settings("foundryVTT").get("allowed_origins", "")
        if isinstance(values, str):
            return [v.strip() for v in values.split(",") if v.strip()]
        return []

    def foundry_sync_compendium_key(compendium_id: str) -> str:
        return f"sync_compendium__{str(compendium_id or '').strip().lower()}"

    def foundry_sync_enabled_for_compendium(compendium_id: str) -> bool:
        cid = str(compendium_id or "").strip().lower()
        if not cid:
            return False
        values = get_plugin_settings("foundryVTT")
        raw = str(values.get(foundry_sync_compendium_key(cid)) or "0").strip().lower()
        return raw not in {"0", "false", "off", "no"}

    def find_foundry_target_compendium_id(payload: dict | None) -> str:
        if not isinstance(payload, dict):
            return ""
        explicit = str(payload.get("compendium_id") or "").strip().lower()
        if explicit:
            return explicit
        setting_value = str(payload.get("setting") or "").strip()
        if not setting_value:
            return ""
        slug = _safe_slug(setting_value)
        if slug in enabled_compendium_ids_for_search():
            return slug
        return ""

    def compendium_foundry_sync_state(compendium_id: str) -> dict[str, object]:
        cid = str(compendium_id or "").strip().lower()
        foundry_plugin = next(
            (item for item in discover_plugins() if str(item.get("id") or "").strip() == "foundryVTT"),
            None,
        )
        present = bool(foundry_plugin)
        plugin_enabled = bool(foundry_plugin.get("enabled")) if foundry_plugin else False
        can_toggle = present and cid not in {"", "settings_catalog", FOUNDRY_COMPENDIUM_ID}
        enabled = foundry_sync_enabled_for_compendium(cid) if can_toggle else False
        return {
            "present": present,
            "plugin_enabled": plugin_enabled,
            "can_toggle": can_toggle,
            "enabled": bool(enabled),
            "key": foundry_sync_compendium_key(cid) if can_toggle else "",
        }

    def normalize_http_base_url(raw: object, default: str) -> str:
        candidate = str(raw or "").strip() or str(default or "").strip()
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("invalid base_url; expected http(s)://host[:port]")
        return f"{parsed.scheme}://{parsed.netloc}"

    def ollama_base_url() -> str:
        return str(get_plugin_settings("ollama_local").get("base_url") or "http://127.0.0.1:11434").strip()

    def ollama_default_model() -> str:
        return str(get_plugin_settings("ollama_local").get("default_model") or "llama3.1").strip()

    def ollama_keep_alive() -> str:
        return str(get_plugin_settings("ollama_local").get("keep_alive") or "10m").strip()

    def ollama_system_prompt() -> str:
        return str(get_plugin_settings("ollama_local").get("system_prompt") or "").strip()

    def openai_base_url() -> str:
        return str(get_plugin_settings("openai_remote").get("base_url") or "https://api.openai.com").strip()

    def openai_default_model() -> str:
        return str(get_plugin_settings("openai_remote").get("default_model") or "gpt-4o-mini").strip()

    def openai_api_key() -> str:
        return str(get_plugin_settings("openai_remote").get("api_key") or "").strip()

    def openai_system_prompt() -> str:
        return str(get_plugin_settings("openai_remote").get("system_prompt") or "").strip()

    def ollama_post_json(base_url: str, path: str, payload: dict, *, timeout: int = 180) -> dict:
        url = f"{base_url.rstrip('/')}{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - user-configurable LAN endpoint by design
            text = resp.read().decode("utf-8", errors="replace")
        data = json.loads(text or "{}")
        return data if isinstance(data, dict) else {}

    def ollama_get_json(base_url: str, path: str, *, timeout: int = 20) -> dict:
        url = f"{base_url.rstrip('/')}{path}"
        req = Request(url, method="GET")
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - user-configurable LAN endpoint by design
            text = resp.read().decode("utf-8", errors="replace")
        data = json.loads(text or "{}")
        return data if isinstance(data, dict) else {}

    def openai_post_json(base_url: str, path: str, payload: dict, *, api_key: str, timeout: int = 240) -> dict:
        url = f"{base_url.rstrip('/')}{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        req = Request(url, data=body, headers=headers, method="POST")
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - user-configurable endpoint by design
            text = resp.read().decode("utf-8", errors="replace")
        data = json.loads(text or "{}")
        return data if isinstance(data, dict) else {}

    def plugin_settings_fields(plugin_id: str, values: dict[str, str]) -> list[dict]:
        pid = str(plugin_id or "").strip()
        if pid == "docling":
            return [
                {
                    "key": "default_device",
                    "label": "Default Device",
                    "type": "select",
                    "options": ["auto", "cuda", "cpu"],
                    "value": str(values.get("default_device") or "auto"),
                    "help": "Used by auto-started Docling jobs from compendium pipeline.",
                },
                {
                    "key": "output_root",
                    "label": "Output Root",
                    "type": "text",
                    "value": str(values.get("output_root") or "PDF_Repository/private_compendium/_docling"),
                    "help": "Project-relative folder for Docling markdown output and status manifests.",
                },
                {
                    "key": "command_template",
                    "label": "Command Template",
                    "type": "textarea",
                    "value": str(values.get("command_template") or ""),
                    "help": "Template placeholders: {input}, {output_dir}, {output_base}, {device}.",
                },
            ]
        if pid == "ollama_local":
            base_url = str(values.get("base_url") or "http://127.0.0.1:11434").strip()
            default_model = str(values.get("default_model") or "llama3.1").strip()
            model_options: list[str] = []
            try:
                tags = ollama_get_json(base_url, "/api/tags")
                models = tags.get("models") if isinstance(tags, dict) else []
                if isinstance(models, list):
                    for model in models:
                        if not isinstance(model, dict):
                            continue
                        name = str(model.get("name") or "").strip()
                        if name and name not in model_options:
                            model_options.append(name)
            except Exception:
                model_options = []
            if default_model and default_model not in model_options:
                model_options.insert(0, default_model)
            return [
                {
                    "key": "base_url",
                    "label": "Base URL",
                    "type": "text",
                    "value": str(values.get("base_url") or "http://127.0.0.1:11434"),
                    "help": "LAN/local Ollama endpoint used by plugin query route.",
                },
                {
                    "key": "default_model",
                    "label": "Default Model",
                    "type": "select" if model_options else "text",
                    "options": model_options,
                    "value": default_model,
                    "help": "Model used when no model is provided in requests. Dropdown is populated from /api/tags when reachable.",
                },
                {
                    "key": "keep_alive",
                    "label": "Keep Alive",
                    "type": "text",
                    "value": str(values.get("keep_alive") or "10m"),
                    "help": "How long to keep the model loaded in memory (examples: 5m, 30m, 1h, -1 to keep loaded).",
                },
                {
                    "key": "system_prompt",
                    "label": "System Prompt",
                    "type": "textarea",
                    "value": str(values.get("system_prompt") or ollama_system_prompt()),
                    "help": "Custom instruction prompt prepended to each RAG query. Default is tuned for Gemma 3.",
                },
            ]
        if pid == "openai_remote":
            return [
                {
                    "key": "base_url",
                    "label": "Base URL",
                    "type": "text",
                    "value": str(values.get("base_url") or "https://api.openai.com"),
                    "help": "OpenAI API base URL (default https://api.openai.com).",
                },
                {
                    "key": "default_model",
                    "label": "Default Model",
                    "type": "text",
                    "value": str(values.get("default_model") or "gpt-4o-mini"),
                    "help": "Model used when no model is provided in requests.",
                },
                {
                    "key": "api_key",
                    "label": "API Key",
                    "type": "password",
                    "value": str(values.get("api_key") or ""),
                    "help": "OpenAI API key (stored locally in config/plugins_secrets.json; gitignored).",
                },
                {
                    "key": "system_prompt",
                    "label": "System Prompt",
                    "type": "textarea",
                    "value": str(values.get("system_prompt") or openai_system_prompt()),
                    "help": "Instruction prompt prepended to each grounded query.",
                },
            ]
        if pid == "foundryVTT":
            fields = [
                {
                    "key": "api_token",
                    "label": "API Token",
                    "type": "password",
                    "value": str(values.get("api_token") or ""),
                    "help": "Bearer/X-Foundry token expected by Foundry plugin endpoints (optional, stored in config/plugins_secrets.json).",
                },
                {
                    "key": "allowed_origins",
                    "label": "Allowed Origins",
                    "type": "textarea",
                    "value": str(values.get("allowed_origins") or ""),
                    "help": "Comma-separated CORS origins; use * to allow all.",
                },
            ]
            profiles = load_compendium_profiles()
            for cid in sorted(enabled_compendium_ids_for_search()):
                if cid == FOUNDRY_COMPENDIUM_ID:
                    continue
                profile = profiles.get(cid) or {}
                comp_name = str(profile.get("name") or cid).strip()
                fields.append({
                    "key": foundry_sync_compendium_key(cid),
                    "label": f"Sync {comp_name}",
                    "type": "checkbox",
                    "value": str(values.get(foundry_sync_compendium_key(cid)) or "0"),
                    "help": f"Allow FoundryVTT imports into '{cid}' setting bucket.",
                })
            return fields
        return []

    def plugin_runtime_status(plugin_id: str) -> dict:
        pid = str(plugin_id or "").strip()
        if pid == "docling":
            runtime = docling_runtime_state()
            profiles = load_compendium_profiles()
            known = sorted([p for p in profiles.keys() if p != FOUNDRY_COMPENDIUM_ID])
            processed: set[str] = set()
            chunked: set[str] = set()
            pdf_status_rows: list[dict] = []
            root = docling_root()
            observed_docling_folders: set[str] = set()
            if root.exists():
                for path in root.rglob("*"):
                    if not path.is_file():
                        continue
                    lower_name = path.name.lower()
                    if not (lower_name.endswith(".md") or lower_name.endswith(".md-first-run")):
                        continue
                    rel = path.relative_to(root)
                    if rel.parts:
                        observed_docling_folders.add(str(rel.parts[0]).strip().lower())
            for cid in known:
                profile = {"id": cid, **(profiles.get(cid) or {})}
                pdf_ref = str(profile.get("pdf_relative_path") or "").strip()
                pdf_path = resolve_profile_pdf_path(profile)
                slugs = compendium_docling_slugs(profile)
                md_files = docling_markdown_files_for_compendium(profile)
                parsed_ok = bool(md_files)
                chunked_ok = vector_count_for_compendium(
                    cid,
                    aliases=[x for x in slugs if x != cid],
                ) > 0
                if parsed_ok:
                    processed.add(cid)
                if chunked_ok:
                    chunked.add(cid)
                pdf_status_rows.append({
                    "compendium_id": cid,
                    "name": str(profile.get("name") or cid),
                    "pdf_relative_path": pdf_ref,
                    "pdf_present": bool(pdf_path and pdf_path.exists()),
                    "parsed": parsed_ok,
                    "parsed_markdown_files": len(md_files),
                    "chunked": chunked_ok,
                    "docling_slugs": slugs,
                })
            return {
                "runner": runtime,
                "processed_compendiums": sorted(processed),
                "processed_count": len(processed),
                "chunked_compendiums": sorted(chunked),
                "chunked_count": len(chunked),
                "known_compendiums": known,
                "missing_compendiums": sorted([x for x in known if x not in processed]),
                "not_chunked_compendiums": sorted([x for x in known if x not in chunked]),
                "observed_docling_folders": sorted(observed_docling_folders),
                "pdf_status": pdf_status_rows,
            }
        if pid == "ollama_local":
            base = ollama_base_url()
            try:
                tags = ollama_get_json(base, "/api/tags")
                models = tags.get("models") if isinstance(tags, dict) else []
                model_names: list[str] = []
                if isinstance(models, list):
                    for model in models:
                        if not isinstance(model, dict):
                            continue
                        name = str(model.get("name") or "").strip()
                        if name:
                            model_names.append(name)
                return {
                    "base_url": base,
                    "up": True,
                    "model_count": len(models) if isinstance(models, list) else 0,
                    "models": model_names,
                    "default_model": ollama_default_model(),
                    "keep_alive": ollama_keep_alive(),
                    "system_prompt_set": bool(ollama_system_prompt()),
                }
            except Exception as exc:
                return {
                    "base_url": base,
                    "up": False,
                    "error": str(exc),
                    "default_model": ollama_default_model(),
                    "keep_alive": ollama_keep_alive(),
                    "system_prompt_set": bool(ollama_system_prompt()),
                }
        if pid == "openai_remote":
            base = openai_base_url()
            key = openai_api_key()
            if not key:
                return {
                    "base_url": base,
                    "up": False,
                    "error": "api_key is not set",
                    "default_model": openai_default_model(),
                    "system_prompt_set": bool(openai_system_prompt()),
                }
            try:
                data = openai_post_json(
                    base,
                    "/v1/chat/completions",
                    {
                        "model": openai_default_model(),
                        "messages": [
                            {"role": "user", "content": "Reply with exactly: ok"}
                        ],
                        "max_tokens": 8,
                        "temperature": 0,
                    },
                    api_key=key,
                    timeout=45,
                )
                choices = data.get("choices") if isinstance(data, dict) else []
                up = isinstance(choices, list) and len(choices) > 0
                return {
                    "base_url": base,
                    "up": bool(up),
                    "default_model": openai_default_model(),
                    "system_prompt_set": bool(openai_system_prompt()),
                }
            except Exception as exc:
                return {
                    "base_url": base,
                    "up": False,
                    "error": str(exc),
                    "default_model": openai_default_model(),
                    "system_prompt_set": bool(openai_system_prompt()),
                }
        if pid == "foundryVTT":
            settings = get_plugin_settings("foundryVTT")
            compendium_sync: dict[str, bool] = {}
            for cid in sorted(enabled_compendium_ids_for_search()):
                if cid == FOUNDRY_COMPENDIUM_ID:
                    continue
                raw = str(settings.get(foundry_sync_compendium_key(cid)) or "0").strip().lower()
                compendium_sync[cid] = raw not in {"0", "false", "off", "no"}
            return {
                "auth_required": bool(foundry_api_token()),
                "allowed_origins": foundry_allowed_origins(),
                "active_setting": current_app.config.get("LOL_SETTING_ID") or current_app.config.get("LOL_WORLD_ID"),
                "sync_compendiums": compendium_sync,
            }
        return {}

    def with_foundry_cors_headers(response):
        origin = str(request.headers.get("Origin") or "").strip()
        allowed = foundry_allowed_origins()
        if not allowed:
            # Safe default for local dev: reflect explicit origin when present.
            if origin:
                response.headers["Access-Control-Allow-Origin"] = origin
        elif "*" in allowed:
            response.headers["Access-Control-Allow-Origin"] = "*"
        elif origin and origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin

        if response.headers.get("Access-Control-Allow-Origin"):
            response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Foundry-Token"
        return response

    def foundry_auth_error_response():
        token = foundry_api_token()
        if not token:
            return None

        auth_header = str(request.headers.get("Authorization") or "").strip()
        bearer = ""
        if auth_header.lower().startswith("bearer "):
            bearer = auth_header[7:].strip()
        x_token = str(request.headers.get("X-Foundry-Token") or "").strip()

        body_token = ""
        if request.is_json:
            body = request.get_json(force=False, silent=True) or {}
            if isinstance(body, dict):
                body_token = str(body.get("token") or "").strip()

        provided = bearer or x_token or body_token
        if provided != token:
            response = jsonify({"error": "unauthorized"})
            response.status_code = 401
            return with_foundry_cors_headers(response)
        return None

    def resolve_project_relative_path(raw: str, *, default: str) -> Path:
        project_root = current_app.config["LOL_PROJECT_ROOT"]
        value = (raw or "").strip() or default
        path = Path(value)
        if path.is_absolute():
            resolved = path.resolve()
        else:
            resolved = (project_root / path).resolve()

        try:
            resolved.relative_to(project_root)
        except ValueError:
            raise ValueError("path must stay inside project root")

        if resolved.suffix.lower() not in {".yaml", ".yml"}:
            raise ValueError("output path must end with .yaml or .yml")
        return resolved

    def lock_dir() -> Path:
        path = current_app.config["LOL_STORAGE_DIR"] / ".locks"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def validate_filename(filename: str) -> bool:
        if not filename:
            return False
        if "\\" in filename:
            return False
        if ".." in filename:
            return False
        if filename.startswith("/"):
            return False
        return filename.endswith(".json")

    def normalize_image_ref(value: str) -> str:
        text = str(value or "").strip().replace("\\", "/")
        if text.startswith("/images/"):
            text = text[len("/images/"):]
        if text.startswith("images/"):
            text = text[len("images/"):]
        return text.strip("/")

    def collect_foundry_compendium_rows() -> list[dict]:
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        foundry_root = storage_dir / "foundryvtt"
        rows: list[dict] = []
        if not foundry_root.exists():
            return rows
        for path in sorted(foundry_root.rglob("*.json"), reverse=True):
            if ".trash" in path.parts or ".locks" in path.parts:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
            item_type = str(result.get("type") or "").strip().lower()
            if not item_type:
                continue
            rows.append({
                "type": item_type,
                "name": str(result.get("name") or "").strip(),
                "metadata": metadata,
            })
        return rows

    def foundry_counts_by_type() -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in collect_foundry_compendium_rows():
            item_type = str(row.get("type") or "").strip().lower()
            if not item_type:
                continue
            counts[item_type] = counts.get(item_type, 0) + 1
        if counts.get("monster"):
            counts["creature"] = counts.get("creature", 0) + counts.get("monster", 0)
        return counts

    def image_catalog_path() -> Path:
        return current_app.config["LOL_IMAGES_DIR"] / "_index.json"

    def load_image_catalog() -> dict[str, dict]:
        path = image_catalog_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        catalog: dict[str, dict] = {}
        for raw_key, raw_meta in data.items():
            key = normalize_image_ref(str(raw_key))
            if not key:
                continue
            meta = raw_meta if isinstance(raw_meta, dict) else {}
            tags = [str(x).strip() for x in (meta.get("tags") or []) if str(x).strip()]
            attached_to_raw = meta.get("attached_to") if isinstance(meta.get("attached_to"), list) else []
            attached_to: list[dict[str, str]] = []
            for row in attached_to_raw:
                if not isinstance(row, dict):
                    continue
                target = str(row.get("target") or "").strip().lower()
                target_id = str(row.get("id") or "").strip()
                if not target or not target_id:
                    continue
                attached_to.append({
                    "target": target,
                    "id": target_id,
                    "label": str(row.get("label") or "").strip(),
                    "type": str(row.get("type") or "").strip().lower(),
                })
            catalog[key] = {
                "friendly_name": str(meta.get("friendly_name") or "").strip(),
                "tags": sorted(set(tags)),
                "description": str(meta.get("description") or meta.get("notes") or "").strip(),
                "attached_to": attached_to,
                "content_hash": str(meta.get("content_hash") or "").strip(),
                "source_url": str(meta.get("source_url") or "").strip(),
            }
        return catalog

    def save_image_catalog(catalog: dict[str, dict]) -> None:
        path = image_catalog_path()
        serializable = {
            key: {
                "friendly_name": str(meta.get("friendly_name") or "").strip(),
                "tags": sorted(set(str(x).strip() for x in (meta.get("tags") or []) if str(x).strip())),
                "description": str(meta.get("description") or meta.get("notes") or "").strip(),
                "attached_to": [
                    {
                        "target": str(row.get("target") or "").strip().lower(),
                        "id": str(row.get("id") or "").strip(),
                        "label": str(row.get("label") or "").strip(),
                        "type": str(row.get("type") or "").strip().lower(),
                    }
                    for row in (meta.get("attached_to") or [])
                    if isinstance(row, dict) and str(row.get("target") or "").strip() and str(row.get("id") or "").strip()
                ],
                "content_hash": str(meta.get("content_hash") or "").strip(),
                "source_url": str(meta.get("source_url") or "").strip(),
            }
            for key, meta in sorted(catalog.items())
            if key
        }
        path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")

    def normalize_image_refs(raw: list[str] | None) -> list[str]:
        refs: list[str] = []
        for value in raw or []:
            ref = normalize_image_ref(str(value))
            if ref and ref not in refs:
                refs.append(ref)
        return refs

    def compute_image_content_hash(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def normalize_image_tag_token(value: object) -> str:
        token = _safe_slug(str(value or "").strip())
        aliases = {
            "lands_of_legends": "lands_of_legend",
            "land_of_legends": "lands_of_legend",
            "land_of_legend": "lands_of_legend",
            "highland_urukculture": "culture",
            "alfirin": "alfir",
            "alfir_sombra": "duathrim",
            "alfir_sylvani": "galadhrim",
            "alfir_sky_children": "kalaquendi",
            "sky_children": "kalaquendi",
            "alfir_wave_riders": "falthrim",
            "faltrim": "falthrim",
            "race_alfir": "alfir",
            "cyfer": "cypher",
            "cyphers_artifacts": "",
            "human_highlanders": "highland_fenmir",
            "the_other_human_tribes": "",
            "the_dead": "gurthim",
            "dangers_undead": "gurthim",
            "dangers_monsters": "monster",
            "liilim": "lilim",
        }
        return aliases.get(token, token)

    def image_catalog_entry_for_ref(catalog: dict[str, dict], ref: str) -> dict[str, object]:
        return dict(catalog.get(normalize_image_ref(ref)) or {})

    def merge_image_catalog_metadata(
        *,
        existing: dict[str, object] | None = None,
        friendly_name: str = "",
        tags: list[str] | None = None,
        description: str = "",
        attached_to: list[dict[str, str]] | None = None,
        content_hash: str = "",
        source_url: str = "",
    ) -> dict[str, object]:
        current = dict(existing or {})
        merged_tags = sorted(set(
            normalize_image_tag_token(x)
            for x in [*(current.get("tags") or []), *(tags or [])]
            if normalize_image_tag_token(x)
        ))
        return {
            "friendly_name": str(current.get("friendly_name") or "").strip() or str(friendly_name or "").strip(),
            "tags": merged_tags,
            "description": str(current.get("description") or current.get("notes") or "").strip() or str(description or "").strip(),
            "attached_to": list(attached_to or current.get("attached_to") or []),
            "content_hash": str(current.get("content_hash") or "").strip() or str(content_hash or "").strip(),
            "source_url": str(current.get("source_url") or "").strip() or str(source_url or "").strip(),
        }

    def find_catalog_ref_by_content_hash(catalog: dict[str, dict], content_hash: str, *, exclude_ref: str = "") -> str:
        target_hash = str(content_hash or "").strip()
        excluded = normalize_image_ref(exclude_ref)
        if not target_hash:
            return ""
        for ref, meta in catalog.items():
            normalized_ref = normalize_image_ref(ref)
            if excluded and normalized_ref == excluded:
                continue
            if str((meta or {}).get("content_hash") or "").strip() == target_hash:
                candidate = resolve_image_ref_path(normalized_ref)
                if candidate.exists():
                    return normalized_ref
        return ""

    def collect_image_attachment_index() -> dict[str, list[dict[str, str]]]:
        index: dict[str, list[dict[str, str]]] = {}

        def add_attachment(image_ref: str, payload: dict[str, str]) -> None:
            ref = normalize_image_ref(image_ref)
            if not ref:
                return
            target = str(payload.get("target") or "").strip().lower()
            target_id = str(payload.get("id") or "").strip()
            if not target or not target_id:
                return
            rows = index.setdefault(ref, [])
            if any(str(row.get("target") or "") == target and str(row.get("id") or "") == target_id for row in rows):
                return
            rows.append({
                "target": target,
                "id": target_id,
                "label": str(payload.get("label") or "").strip(),
                "type": str(payload.get("type") or "").strip().lower(),
            })

        def refs_from_metadata_block(metadata: dict[str, object] | None) -> list[str]:
            block = metadata if isinstance(metadata, dict) else {}
            refs: list[str] = []
            image_url = normalize_image_ref(str(block.get("image_url") or ""))
            if image_url:
                refs.append(image_url)
            refs.extend(
                normalize_image_refs(block.get("images") if isinstance(block.get("images"), list) else [])
            )
            return normalize_image_refs(refs)

        for item in list_saved_results(
            current_app.config["LOL_STORAGE_DIR"],
            default_settings=configured_default_settings(),
        ):
            filename = str(item.get("filename") or "").strip()
            if not filename or not validate_filename(filename):
                continue
            try:
                record = load_saved_result(
                    current_app.config["LOL_STORAGE_DIR"],
                    filename,
                    default_settings=configured_default_settings(),
                )
            except Exception:
                continue
            result = record.get("result") if isinstance(record.get("result"), dict) else {}
            metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
            sheet = result.get("sheet") if isinstance(result.get("sheet"), dict) else {}
            sheet_metadata = sheet.get("metadata") if isinstance(sheet.get("metadata"), dict) else {}
            refs = normalize_image_refs([
                *refs_from_metadata_block(metadata),
                *refs_from_metadata_block(sheet_metadata),
            ])
            if not refs:
                continue
            payload = {
                "target": "storage",
                "id": filename,
                "label": str(item.get("name") or item.get("filename") or "Saved Card").strip(),
                "type": str(item.get("type") or "").strip().lower(),
            }
            for ref in refs:
                add_attachment(ref, payload)

        for item in list_lore_items(
            current_app.config["LOL_LORE_DIR"],
            default_settings=configured_default_settings(),
        ):
            refs = normalize_image_refs(item.get("images") if isinstance(item.get("images"), list) else [])
            if not refs:
                continue
            payload = {
                "target": "lore",
                "id": str(item.get("slug") or "").strip(),
                "label": str(item.get("title") or item.get("slug") or "Lore").strip(),
                "type": "lore",
            }
            for ref in refs:
                add_attachment(ref, payload)

        for rows in index.values():
            rows.sort(key=lambda row: (row.get("target") != "storage", row.get("label") or row.get("id") or ""))
        return index

    def _attachment_tags_from_values(*values: object) -> list[str]:
        tags: list[str] = []
        for value in values:
            if isinstance(value, list):
                for item in value:
                    token = _safe_slug(str(item or "").strip())
                    if token and token not in tags:
                        tags.append(token)
                continue
            token = _safe_slug(str(value or "").strip())
            if token and token not in tags:
                tags.append(token)
        return tags

    def _describe_storage_image_attachment(row: dict[str, str]) -> dict[str, object]:
        filename = str(row.get("id") or "").strip()
        if not filename or not validate_filename(filename):
            return {}
        try:
            record = load_saved_result(
                current_app.config["LOL_STORAGE_DIR"],
                filename,
                default_settings=configured_default_settings(),
            )
        except Exception:
            return {}
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        sections = result.get("sections") if isinstance(result.get("sections"), dict) else {}
        friendly_name = str(
            result.get("name")
            or metadata.get("friendly_name")
            or row.get("label")
            or filename
        ).strip()
        description = str(
            result.get("description")
            or metadata.get("description")
            or sections.get("description")
            or sections.get("summary")
            or sections.get("effect")
            or ""
        ).strip()
        tags = _attachment_tags_from_values(
            "attached",
            "storage",
            result.get("type"),
            metadata.get("primarycategory"),
            metadata.get("subtype"),
            metadata.get("location_category_type"),
            metadata.get("setting"),
            metadata.get("settings") if isinstance(metadata.get("settings"), list) else [],
            metadata.get("area"),
            metadata.get("location"),
            metadata.get("race"),
            metadata.get("variant"),
            metadata.get("profession"),
            metadata.get("culture"),
        )
        return {
            "friendly_name": friendly_name,
            "description": description,
            "tags": tags,
        }

    def _describe_lore_image_attachment(row: dict[str, str]) -> dict[str, object]:
        slug = str(row.get("id") or "").strip()
        if not slug:
            return {}
        try:
            item = load_lore_item(
                current_app.config["LOL_LORE_DIR"],
                slug,
                default_settings=configured_default_settings(),
            )
        except Exception:
            return {}
        friendly_name = str(item.get("title") or row.get("label") or slug).strip()
        description = str(item.get("description") or item.get("excerpt") or "").strip()
        tags = _attachment_tags_from_values(
            "attached",
            "lore",
            item.get("categories") if isinstance(item.get("categories"), list) else [],
            item.get("settings") if isinstance(item.get("settings"), list) else [],
            item.get("setting"),
            item.get("area"),
            item.get("location"),
            item.get("location_type"),
            item.get("terms") if isinstance(item.get("terms"), list) else [],
        )
        return {
            "friendly_name": friendly_name,
            "description": description,
            "tags": tags,
        }

    def describe_image_attachment(row: dict[str, str]) -> dict[str, object]:
        target = str(row.get("target") or "").strip().lower()
        if target == "storage":
            return _describe_storage_image_attachment(row)
        if target == "lore":
            return _describe_lore_image_attachment(row)
        return {}

    def sync_image_catalog_attachments(catalog: dict[str, dict] | None = None) -> dict[str, dict]:
        current_catalog = dict(catalog or load_image_catalog())
        attachment_index = collect_image_attachment_index()
        all_keys = set(current_catalog.keys()) | set(attachment_index.keys())
        refs_by_hash: dict[str, list[str]] = {}
        content_hash_by_ref: dict[str, str] = {}
        for key in sorted(all_keys):
            meta = dict(current_catalog.get(key) or {})
            content_hash = str(meta.get("content_hash") or "").strip()
            if not content_hash:
                try:
                    path = resolve_image_ref_path(key)
                except Exception:
                    path = None
                if path and path.exists() and path.is_file():
                    try:
                        content_hash = compute_image_content_hash(path.read_bytes())
                    except Exception:
                        content_hash = ""
            if content_hash:
                content_hash_by_ref[key] = content_hash
                refs_by_hash.setdefault(content_hash, []).append(key)
        synced: dict[str, dict] = {}
        for key in sorted(all_keys):
            meta = dict(current_catalog.get(key) or {})
            content_hash = content_hash_by_ref.get(key, "")
            sibling_refs = refs_by_hash.get(content_hash, [key]) if content_hash else [key]
            attached_rows: list[dict[str, str]] = []
            seen_rows: set[tuple[str, str]] = set()
            for ref in sibling_refs:
                for row in (attachment_index.get(ref) or []):
                    marker = (str(row.get("target") or ""), str(row.get("id") or ""))
                    if not marker[0] or not marker[1] or marker in seen_rows:
                        continue
                    seen_rows.add(marker)
                    attached_rows.append(row)
            derived_infos = [info for info in (describe_image_attachment(row) for row in attached_rows) if isinstance(info, dict) and info]
            derived_name = next((str(info.get("friendly_name") or "").strip() for info in derived_infos if str(info.get("friendly_name") or "").strip()), "")
            derived_description = next((str(info.get("description") or "").strip() for info in derived_infos if str(info.get("description") or "").strip()), "")
            derived_tags: list[str] = []
            for info in derived_infos:
                for tag in (info.get("tags") or []):
                    token = normalize_image_tag_token(tag)
                    if token and token not in derived_tags:
                        derived_tags.append(token)
            synced[key] = {
                "friendly_name": str(meta.get("friendly_name") or "").strip() or derived_name,
                "tags": sorted(set(
                    normalize_image_tag_token(x)
                    for x in [*(meta.get("tags") or []), *derived_tags]
                    if normalize_image_tag_token(x)
                )),
                "description": str(meta.get("description") or meta.get("notes") or "").strip() or derived_description,
                "attached_to": attached_rows,
                "content_hash": content_hash,
                "source_url": str(meta.get("source_url") or "").strip(),
            }
        save_image_catalog(synced)
        return synced

    def mirror_remote_image(
        url: str,
        *,
        friendly_name: str = "",
        tags: list[str] | None = None,
        notes: str = "",
    ) -> str | None:
        raw_url = str(url or "").strip()
        if not raw_url.lower().startswith(("http://", "https://")):
            return None

        images_dir = current_app.config["LOL_IMAGES_DIR"]
        upload_dir = images_dir / "uploads" / "foundryvtt"
        upload_dir.mkdir(parents=True, exist_ok=True)

        req = Request(raw_url, headers={"User-Agent": "Legends-GMTools/1.0"})
        try:
            with urlopen(req, timeout=10) as response:
                content_type = str(response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if content_type and not content_type.startswith("image/"):
                    return None
                payload = response.read()
        except Exception:
            return None

        if not payload:
            return None
        content_hash = compute_image_content_hash(payload)

        parsed = urlparse(raw_url)
        guessed_ext = Path(parsed.path).suffix.lower()
        if guessed_ext not in IMAGE_SUFFIXES:
            guessed_ext = str(mimetypes.guess_extension(content_type or "") or "").lower()
        if guessed_ext == ".jpe":
            guessed_ext = ".jpg"
        if guessed_ext not in IMAGE_SUFFIXES:
            guessed_ext = ".jpg"

        catalog = load_image_catalog()
        existing_ref = find_catalog_ref_by_content_hash(catalog, content_hash)
        normalized_tags = sorted(set(str(x).strip().lower().replace(" ", "_") for x in (tags or []) if str(x).strip()))
        if existing_ref:
            catalog[existing_ref] = merge_image_catalog_metadata(
                existing=image_catalog_entry_for_ref(catalog, existing_ref),
                friendly_name=str(friendly_name or "").strip(),
                tags=normalized_tags,
                description=str(notes or "").strip(),
                content_hash=content_hash,
                source_url=raw_url,
            )
            save_image_catalog(catalog)
            return existing_ref

        stem = secure_filename(Path(parsed.path).stem or friendly_name or "foundry_image") or "foundry_image"
        final_name = f"{stem}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}{guessed_ext}"
        path = upload_dir / final_name
        path.write_bytes(payload)

        rel = str(path.relative_to(images_dir)).replace("\\", "/")
        catalog[rel] = merge_image_catalog_metadata(
            existing=image_catalog_entry_for_ref(catalog, rel),
            friendly_name=str(friendly_name or "").strip(),
            tags=normalized_tags,
            description=str(notes or "").strip(),
            content_hash=content_hash,
            source_url=raw_url,
        )
        save_image_catalog(catalog)
        return rel

    def cache_foundry_images_for_result(result: dict) -> dict:
        if not isinstance(result, dict):
            return result

        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        if str(metadata.get("source") or "").strip().lower() not in {"foundryvtt", "foundry_vtt"}:
            return result

        candidate_urls: list[str] = []
        for value in (
            metadata.get("image_url"),
            *(metadata.get("images") if isinstance(metadata.get("images"), list) else []),
        ):
            text = str(value or "").strip()
            if text and text not in candidate_urls:
                candidate_urls.append(text)

        if not candidate_urls:
            return result

        tags = [
            str(metadata.get("source") or "").strip(),
            str(metadata.get("genre") or "").strip(),
            str(metadata.get("setting") or "").strip(),
            str(metadata.get("area") or metadata.get("environment") or "").strip(),
            str(metadata.get("location") or "").strip(),
        ]
        local_images: list[str] = []
        for image_url in candidate_urls:
            local_ref = mirror_remote_image(
                image_url,
                friendly_name=str(result.get("name") or metadata.get("friendly_name") or "").strip(),
                tags=tags,
                notes="Mirrored from FoundryVTT during sync import.",
            )
            if local_ref and local_ref not in local_images:
                local_images.append(local_ref)

        if not local_images:
            return result

        next_metadata = dict(metadata)
        next_metadata["foundry_remote_image_url"] = str(metadata.get("image_url") or candidate_urls[0] or "").strip()
        next_metadata["image_url"] = local_images[0]
        next_metadata["images"] = local_images

        next_result = dict(result)
        next_result["metadata"] = next_metadata

        sheet = next_result.get("sheet") if isinstance(next_result.get("sheet"), dict) else None
        if sheet:
          next_sheet = dict(sheet)
          sheet_meta = next_sheet.get("metadata") if isinstance(next_sheet.get("metadata"), dict) else {}
          next_sheet_meta = dict(sheet_meta)
          next_sheet_meta["foundry_remote_image_url"] = next_metadata.get("foundry_remote_image_url")
          next_sheet_meta["image_url"] = local_images[0]
          next_sheet_meta["images"] = local_images
          next_sheet["metadata"] = next_sheet_meta
          next_result["sheet"] = next_sheet

        return next_result

    def resolve_image_ref_path(ref: str) -> Path:
        images_dir = current_app.config["LOL_IMAGES_DIR"].resolve()
        normalized = normalize_image_ref(ref)
        if not normalized:
            raise ValueError("image path is required")
        candidate = (images_dir / normalized).resolve()
        if not str(candidate).startswith(str(images_dir) + "/") and candidate != images_dir:
            raise ValueError("invalid image path")
        return candidate

    def list_image_assets(*, refresh_catalog: bool = False) -> list[dict]:
        images_dir = current_app.config["LOL_IMAGES_DIR"]
        catalog = sync_image_catalog_attachments() if refresh_catalog else load_image_catalog()
        files: list[dict] = []
        if not images_dir.exists():
            return files
        for path in sorted(images_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            rel = str(path.relative_to(images_dir)).replace("\\", "/")
            meta = catalog.get(rel, {})
            files.append({
                "path": rel,
                "url": f"/images/{rel}",
                "name": path.name,
                "friendly_name": str(meta.get("friendly_name") or "").strip(),
                "description": str(meta.get("description") or "").strip(),
                "tags": [str(x) for x in (meta.get("tags") or []) if str(x).strip()],
                "attached_to": [row for row in (meta.get("attached_to") or []) if isinstance(row, dict)],
                "attached_count": len(meta.get("attached_to") or []),
            })
        return files

    def update_storage_images(filename: str, image_ref: str, *, action: str) -> dict:
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        record = load_saved_result(storage_dir, filename, default_settings=configured_default_settings())
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        images = normalize_image_refs(metadata.get("images") if isinstance(metadata.get("images"), list) else [])
        target_ref = normalize_image_ref(image_ref)
        if action == "attach":
            if target_ref and target_ref not in images:
                images.append(target_ref)
        elif action == "unattach":
            images = [x for x in images if x != target_ref]
        else:
            raise ValueError("invalid image action")

        metadata = dict(metadata)
        metadata["images"] = images
        result = dict(result)
        result["metadata"] = metadata
        updated_record = dict(record)
        updated_record["result"] = result
        update_saved_result(storage_dir, filename, updated_record)
        return {"images": images}

    def update_lore_images(slug: str, image_ref: str, *, action: str) -> dict:
        lore_dir = current_app.config["LOL_LORE_DIR"]
        item = load_lore_item(lore_dir, slug, default_settings=configured_default_settings())
        images = normalize_image_refs(item.get("images") if isinstance(item.get("images"), list) else [])
        target_ref = normalize_image_ref(image_ref)
        if action == "attach":
            if target_ref and target_ref not in images:
                images.append(target_ref)
        elif action == "unattach":
            images = [x for x in images if x != target_ref]
        else:
            raise ValueError("invalid image action")

        item = dict(item)
        item["images"] = images
        update_lore_item(lore_dir, slug, item)
        return {"images": images}

    def replace_image_ref_across_records(old_ref: str, new_ref: str) -> dict[str, int]:
        old_norm = normalize_image_ref(old_ref)
        new_norm = normalize_image_ref(new_ref)
        if not old_norm or not new_norm or old_norm == new_norm:
            return {"storage_updated": 0, "lore_updated": 0}

        storage_updated = 0
        for item in list_saved_results(
            current_app.config["LOL_STORAGE_DIR"],
            default_settings=configured_default_settings(),
        ):
            filename = str(item.get("filename") or "").strip()
            if not filename or not validate_filename(filename):
                continue
            record = load_saved_result(
                current_app.config["LOL_STORAGE_DIR"],
                filename,
                default_settings=configured_default_settings(),
            )
            result = record.get("result") if isinstance(record.get("result"), dict) else {}
            metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
            sheet = result.get("sheet") if isinstance(result.get("sheet"), dict) else {}
            sheet_metadata = sheet.get("metadata") if isinstance(sheet.get("metadata"), dict) else {}
            images = normalize_image_refs(metadata.get("images") if isinstance(metadata.get("images"), list) else [])
            metadata_image_url = normalize_image_ref(str(metadata.get("image_url") or ""))
            sheet_images = normalize_image_refs(sheet_metadata.get("images") if isinstance(sheet_metadata.get("images"), list) else [])
            sheet_image_url = normalize_image_ref(str(sheet_metadata.get("image_url") or ""))
            result_image_url = normalize_image_ref(str(result.get("image_url") or ""))
            if old_norm not in images and old_norm != metadata_image_url and old_norm not in sheet_images and old_norm != sheet_image_url and old_norm != result_image_url:
                continue
            images = [new_norm if ref == old_norm else ref for ref in images]
            images = normalize_image_refs(images)
            metadata = dict(metadata)
            metadata["images"] = images
            if metadata_image_url == old_norm:
                metadata["image_url"] = new_norm

            if sheet_metadata:
                next_sheet_metadata = dict(sheet_metadata)
                if old_norm in sheet_images:
                    next_sheet_metadata["images"] = normalize_image_refs([new_norm if ref == old_norm else ref for ref in sheet_images])
                if sheet_image_url == old_norm:
                    next_sheet_metadata["image_url"] = new_norm
                sheet = dict(sheet)
                sheet["metadata"] = next_sheet_metadata

            result = dict(result)
            result["metadata"] = metadata
            if result_image_url == old_norm:
                result["image_url"] = new_norm
            if sheet:
                result["sheet"] = sheet
            updated_record = dict(record)
            updated_record["result"] = result
            update_saved_result(current_app.config["LOL_STORAGE_DIR"], filename, updated_record)
            storage_updated += 1

        lore_updated = 0
        for item in list_lore_items(
            current_app.config["LOL_LORE_DIR"],
            default_settings=configured_default_settings(),
        ):
            slug = str(item.get("slug") or "").strip()
            if not slug:
                continue
            full_item = load_lore_item(
                current_app.config["LOL_LORE_DIR"],
                slug,
                default_settings=configured_default_settings(),
            )
            images = normalize_image_refs(full_item.get("images") if isinstance(full_item.get("images"), list) else [])
            if old_norm not in images:
                continue
            images = [new_norm if ref == old_norm else ref for ref in images]
            full_item = dict(full_item)
            full_item["images"] = normalize_image_refs(images)
            update_lore_item(current_app.config["LOL_LORE_DIR"], slug, full_item)
            lore_updated += 1

        return {"storage_updated": storage_updated, "lore_updated": lore_updated}

    def dedupe_image_catalog_files() -> dict[str, object]:
        images_dir = current_app.config["LOL_IMAGES_DIR"]
        catalog = load_image_catalog()
        by_hash: dict[str, list[str]] = {}
        for path in sorted(images_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            rel = str(path.relative_to(images_dir)).replace("\\", "/")
            try:
                content_hash = compute_image_content_hash(path.read_bytes())
            except Exception:
                continue
            entry = merge_image_catalog_metadata(
                existing=image_catalog_entry_for_ref(catalog, rel),
                content_hash=content_hash,
            )
            catalog[rel] = entry
            by_hash.setdefault(content_hash, []).append(rel)

        merged_pairs: list[dict[str, object]] = []
        removed_files = 0
        for refs in by_hash.values():
            normalized_refs = sorted({normalize_image_ref(ref) for ref in refs if normalize_image_ref(ref)})
            if len(normalized_refs) < 2:
                continue
            canonical = normalized_refs[0]
            canonical_meta = dict(catalog.get(canonical) or {})
            for duplicate in normalized_refs[1:]:
                duplicate_meta = dict(catalog.get(duplicate) or {})
                canonical_meta = merge_image_catalog_metadata(
                    existing=canonical_meta,
                    friendly_name=str(duplicate_meta.get("friendly_name") or "").strip(),
                    tags=[str(x) for x in (duplicate_meta.get("tags") or []) if str(x).strip()],
                    description=str(duplicate_meta.get("description") or "").strip(),
                    content_hash=str(duplicate_meta.get("content_hash") or "").strip(),
                    source_url=str(duplicate_meta.get("source_url") or "").strip(),
                )
                replace_image_ref_across_records(duplicate, canonical)
                duplicate_path = resolve_image_ref_path(duplicate)
                if duplicate_path.exists():
                    duplicate_path.unlink()
                    removed_files += 1
                catalog.pop(duplicate, None)
                merged_pairs.append({"canonical": canonical, "removed": duplicate})
            catalog[canonical] = canonical_meta

        save_image_catalog(images_dir, catalog)
        sync_image_catalog_attachments(catalog)
        return {
            "ok": True,
            "duplicates_removed": removed_files,
            "merged_pairs": merged_pairs,
        }

    def lock_path_for(filename: str) -> Path:
        safe_name = filename.replace("/", "__").replace(".json", ".lock.json")
        return lock_dir() / safe_name

    def read_sheet_lock(filename: str) -> dict | None:
        path = lock_path_for(filename)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def is_locked_by_other(filename: str, owner: str | None) -> tuple[bool, dict | None]:
        lock = read_sheet_lock(filename)
        if not lock:
            return False, None
        if owner and lock.get("owner") == owner:
            return False, lock
        return True, lock

    def write_sheet_lock(filename: str, owner: str, mode: str) -> dict:
        data = {
            "filename": filename,
            "owner": owner,
            "mode": mode,
            "locked_at": datetime.now(timezone.utc).isoformat(),
        }
        lock_path_for(filename).write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    def release_sheet_lock(filename: str, owner: str) -> bool:
        path = lock_path_for(filename)
        if not path.exists():
            return True
        lock = read_sheet_lock(filename)
        if lock and lock.get("owner") != owner:
            return False
        path.unlink(missing_ok=True)
        return True

    def ensure_result_description(result: dict) -> dict:
        if not isinstance(result, dict):
            return result

        def compact_text(value: object, limit: int = 500) -> str:
            text = " ".join(str(value or "").strip().split())
            if len(text) > limit:
                return text[: limit - 1].rstrip() + "…"
            return text

        existing = compact_text(result.get("description"))
        if existing:
            result["description"] = existing
            return result

        metadata = result.get("metadata", {}) if isinstance(result.get("metadata"), dict) else {}
        sections = result.get("sections", {}) if isinstance(result.get("sections"), dict) else {}
        sheet = result.get("sheet", {}) if isinstance(result.get("sheet"), dict) else {}

        for candidate in (
            metadata.get("description"),
            sections.get("description"),
            sections.get("summary"),
            sections.get("effect"),
            sections.get("use"),
            result.get("excerpt"),
            sheet.get("notes"),
            result.get("text"),
        ):
            text = compact_text(candidate)
            if text:
                result["description"] = text
                break
        return result

    def _compact_text(value: object, limit: int = 500) -> str:
        text = " ".join(str(value or "").strip().split())
        if len(text) > limit:
            return text[: limit - 1].rstrip() + "…"
        return text

    def _coerce_player_character_attacks(values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        attacks: list[str] = []
        for value in values:
            if isinstance(value, dict):
                name = str(value.get("name") or "").strip()
                weapon_type = str(value.get("weapon_type") or "").strip()
                damage = str(value.get("damage") or "").strip()
                attack_range = str(value.get("range") or "").strip()
                skill_rating = str(value.get("skill_rating") or "").strip()
                details = [
                    part for part in [
                        weapon_type,
                        f"{damage} damage" if damage else "",
                        attack_range,
                        skill_rating,
                    ] if part
                ]
                text = f"{name} ({', '.join(details)})" if name and details else name or ", ".join(details)
            else:
                text = str(value or "").strip()
            text = text.strip()
            if text:
                attacks.append(text)
        return attacks

    def _coerce_player_character_skills(values: Any) -> list[dict[str, str]]:
        if not isinstance(values, list):
            return []
        skills: list[dict[str, str]] = []
        for value in values:
            if isinstance(value, dict):
                name = str(value.get("name") or "").strip()
                level = str(value.get("level") or "").strip().lower() or "trained"
            else:
                name = str(value or "").strip()
                level = "trained"
            if name:
                skills.append({"name": name, "level": level})
        return skills

    def _build_player_character_description(sheet: dict[str, Any]) -> str:
        description = _compact_text(sheet.get("description"))
        if description:
            return description

        sentence = _compact_text(sheet.get("sentence"), limit=220)
        attacks = _coerce_player_character_attacks(sheet.get("attacks"))
        equipment = [
            str(item or "").strip()
            for item in (sheet.get("starting_equipment") if isinstance(sheet.get("starting_equipment"), list) else [])
            if str(item or "").strip()
        ]
        notes = _compact_text(sheet.get("notes"), limit=220)
        parts = [part for part in [sentence, attacks[0] if attacks else "", equipment[0] if equipment else "", notes] if part]
        return _compact_text(". ".join(parts), limit=500)

    def _normalize_ai_generated_player_character(card: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        metadata = card.get("metadata") if isinstance(card.get("metadata"), dict) else {}
        name = str(card.get("name") or card.get("character_name") or metadata.get("name") or "AI Generated Character").strip() or "AI Generated Character"
        tier = card.get("tier")
        if tier in (None, ""):
            tier = metadata.get("tier") or 1

        description = _build_player_character_description(card)
        sheet_metadata = {
            "name": name,
            "race": metadata.get("race") or payload.get("race"),
            "variant": metadata.get("variant") or payload.get("variant"),
            "gender": metadata.get("gender") or payload.get("gender"),
            "profession": metadata.get("profession") or payload.get("profession"),
            "culture": metadata.get("culture") or payload.get("culture"),
            "area": metadata.get("area") or payload.get("area") or metadata.get("environment") or payload.get("environment"),
            "location": metadata.get("location") or payload.get("location"),
            "setting": metadata.get("setting") or payload.get("setting"),
            "settings": metadata.get("settings") or payload.get("settings"),
            "character_type": metadata.get("character_type") or card.get("type"),
            "flavor": metadata.get("flavor") or card.get("flavor"),
            "descriptor": metadata.get("descriptor") or card.get("descriptor"),
            "focus": metadata.get("focus") or card.get("focus"),
            "tier": tier,
            "source": "AI Generate",
            "origin": "ai_generate",
            "content_type": "player_character",
            "ai_generated": "true",
            "description": description,
        }
        sheet = dict(card)
        sheet["name"] = name
        sheet.setdefault("sentence", f"{name} is a {sheet_metadata['descriptor'] or 'capable adventurer'} who {sheet_metadata['focus'] or 'faces the unknown'}.")
        sheet.setdefault("effort", 1)
        sheet.setdefault("cypher_limit", 2)
        sheet.setdefault("damage_track", "Hale")
        sheet.setdefault("recovery_rolls_used", {
            "action": False,
            "ten_minutes": False,
            "one_hour": False,
            "ten_hours": False,
        })
        sheet["chosen_skills"] = _coerce_player_character_skills(sheet.get("chosen_skills"))
        sheet["attacks"] = _coerce_player_character_attacks(sheet.get("attacks"))
        sheet["starting_equipment"] = [
            str(item or "").strip()
            for item in (sheet.get("starting_equipment") if isinstance(sheet.get("starting_equipment"), list) else [])
            if str(item or "").strip()
        ]
        sheet["equipment"] = [
            str(item or "").strip()
            for item in (sheet.get("equipment") if isinstance(sheet.get("equipment"), list) else [])
            if str(item or "").strip()
        ]
        sheet["wizard_completed"] = True
        sheet["generated"] = "ai_generate"
        sheet["tier"] = tier
        sheet["metadata"] = sheet_metadata

        return {
            "type": "character_sheet",
            "name": name,
            "description": description,
            "sheet": sheet,
            "metadata": {
                "source": "House",
                "origin": "ai_generate",
                "content_type": "player_character",
                "ai_generated": "true",
                "setting": sheet_metadata.get("setting"),
                "settings": sheet_metadata.get("settings"),
                "area": sheet_metadata.get("area"),
                "location": sheet_metadata.get("location"),
                "environment": metadata.get("environment") or sheet_metadata.get("area"),
                "race": sheet_metadata.get("race"),
                "variant": sheet_metadata.get("variant"),
                "gender": sheet_metadata.get("gender"),
                "profession": sheet_metadata.get("profession"),
                "culture": sheet_metadata.get("culture"),
                "character_type": sheet_metadata.get("character_type"),
                "flavor": sheet_metadata.get("flavor"),
                "descriptor": sheet_metadata.get("descriptor"),
                "focus": sheet_metadata.get("focus"),
                "tier": tier,
                "description": description,
            },
        }

    def persist_result(payload, result):
        result = ensure_result_description(result)
        result = attach_settings_metadata(
            result,
            payload,
            current_app.config["LOL_CONFIG"],
        )
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        path = save_generated_result(storage_dir, result, payload)
        result["storage"] = {
            "filename": str(path.relative_to(storage_dir)).replace("\\", "/"),
            "saved": True,
        }
        try:
            sync_image_catalog_attachments()
        except Exception:
            pass
        try:
            result["vector_sync"] = sync_single_storage_card(
                storage_root=storage_dir,
                card_path=path,
                output_root=vector_index_root(),
            )
        except Exception as exc:
            result["vector_sync"] = {
                "status": "error",
                "error": str(exc),
            }
        return result

    def import_foundry_actor_to_storage(actor: dict, payload: dict | None = None) -> dict:
        payload = dict(payload or {})
        if payload.get("compendium_id"):
            payload["compendium_id"] = str(payload.get("compendium_id") or "").strip().lower()
        actor_type = str(actor.get("type") or "").strip().lower() or "pc"

        if actor_type == "pc":
            sheet = foundry_actor_to_character_sheet(actor, payload)

            metadata = sheet.get("metadata") if isinstance(sheet.get("metadata"), dict) else {}
            result = {
                "type": "character_sheet",
                "name": str(sheet.get("name") or "Imported Character").strip() or "Imported Character",
                "sheet": sheet,
                "metadata": {
                    "setting": metadata.get("setting") or payload.get("setting"),
                    "settings": metadata.get("settings") or payload.get("settings"),
                    "area": metadata.get("area") or payload.get("area") or payload.get("environment"),
                    "location": metadata.get("location") or payload.get("location"),
                    "environment": metadata.get("environment") or metadata.get("area") or payload.get("environment") or payload.get("area"),
                    "race": metadata.get("race") or payload.get("race"),
                    "profession": metadata.get("profession") or payload.get("profession"),
                    "character_type": metadata.get("character_type"),
                    "flavor": metadata.get("flavor"),
                    "descriptor": metadata.get("descriptor"),
                    "focus": metadata.get("focus"),
                    "tier": metadata.get("tier") or sheet.get("tier"),
                    "source": "FoundryVTT",
                    "origin": "foundry_import",
                    "foundry_actor_type": metadata.get("foundry_actor_type") or actor_type,
                    "foundry_actor_uuid": metadata.get("foundry_actor_uuid"),
                    "foundry_origin": metadata.get("foundry_origin") or payload.get("foundry_origin"),
                    "compendium_id": metadata.get("compendium_id") or payload.get("compendium_id"),
                    "image_url": metadata.get("image_url"),
                    "images": metadata.get("images") or [],
                },
            }
            result = attach_settings_metadata(result, payload, current_app.config["LOL_CONFIG"])
            result = cache_foundry_images_for_result(result)
            created_local_abilities = create_missing_local_abilities(
                sheet,
                str(sheet.get("name") or "Imported Character"),
                parent_settings=result.get("metadata", {}).get("settings"),
            )
            result = persist_result(payload, result)
            owner_filename = (result.get("storage") or {}).get("filename")
            if owner_filename and "/" not in str(owner_filename):
                owner_filename = f"character_sheet/{owner_filename}"
            foundry_created = create_foundry_import_records(
                actor,
                payload=payload,
                owner_name=str(sheet.get("name") or "Imported Character"),
                owner_filename=owner_filename,
                parent_settings=result.get("metadata", {}).get("settings"),
            )
            if created_local_abilities:
                result["local_abilities_created"] = created_local_abilities
            if foundry_created.get("cyphers"):
                result["local_cyphers_created"] = foundry_created["cyphers"]
            if foundry_created.get("attacks"):
                result["local_attacks_created"] = foundry_created["attacks"]
            return result

        if actor_type == "npc":
            result = foundry_actor_to_npc_result(actor, payload)
            if payload.get("compendium_id"):
                meta = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
                next_meta = dict(meta)
                next_meta["compendium_id"] = str(payload.get("compendium_id") or "").strip().lower()
                result = dict(result)
                result["metadata"] = next_meta
            result = attach_settings_metadata(result, payload, current_app.config["LOL_CONFIG"])
            result = cache_foundry_images_for_result(result)
            result = persist_result(payload, result)
            return result

        raise ValueError(f"unsupported Foundry actor type '{actor_type}'. Supported: pc, npc.")

    def import_foundry_item_to_storage(item: dict, payload: dict | None = None) -> dict:
        payload = dict(payload or {})
        if payload.get("compendium_id"):
            payload["compendium_id"] = str(payload.get("compendium_id") or "").strip().lower()
        result = foundry_item_to_result(item, payload)
        if payload.get("compendium_id"):
            meta = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
            next_meta = dict(meta)
            next_meta["compendium_id"] = str(payload.get("compendium_id") or "").strip().lower()
            result = dict(result)
            result["metadata"] = next_meta
        result = attach_settings_metadata(result, payload, current_app.config["LOL_CONFIG"])
        result = cache_foundry_images_for_result(result)
        result = persist_result(payload, result)
        return result

    def create_missing_local_abilities(
        sheet: dict,
        character_name: str,
        parent_settings: list[str] | None = None,
    ) -> list[dict]:
        """
        If an ability-like label selected in Character Studio has no compendium entry,
        create a local storage record so it shows up in Library/Search.
        """
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        compendium_dir = current_app.config["LOL_COMPENDIUM_DIR"]

        candidates: set[str] = set()

        for ability_name in sheet.get("chosen_abilities", []) or []:
            text = str(ability_name or "").strip()
            if text:
                candidates.add(text)

        descriptor_effects = sheet.get("descriptor_effects") or {}
        for skill_name in descriptor_effects.get("skills", []) or []:
            text = str(skill_name or "").strip()
            if text:
                candidates.add(text)

        if not candidates:
            return []

        compendium_titles = {
            str(item.get("title") or "").strip().lower()
            for item in list_compendium_items(compendium_dir, "ability")
            if str(item.get("title") or "").strip()
        }

        existing_local_titles = {
            str(item.get("name") or "").strip().lower()
            for item in list_saved_results(storage_dir, default_settings=configured_default_settings())
            if str(item.get("type") or "").strip().lower() == "ability"
        }

        created: list[dict] = []
        for name in sorted(candidates):
            key = name.lower()
            if key in compendium_titles or key in existing_local_titles:
                continue

            local_result = {
                "type": "ability",
                "name": name,
                "sections": {
                    "summary": "Auto-created local ability placeholder.",
                    "details": f"Created from Character Studio because no exact compendium entry exists for '{name}'.",
                },
                "metadata": {
                    "source": "character_studio",
                    "character_name": character_name,
                    "missing_from_compendium": True,
                    "settings": list(parent_settings or []),
                },
            }
            local_payload = {
                "origin": "character_sheet_save",
                "character_name": character_name,
                "ability_name": name,
            }
            local_result = attach_settings_metadata(
                local_result,
                local_payload,
                current_app.config["LOL_CONFIG"],
            )
            path = save_generated_result(storage_dir, local_result, local_payload)
            existing_local_titles.add(key)
            created.append({
                "name": name,
                "filename": path.name,
            })

        return created

    def create_foundry_import_records(
        actor: dict,
        *,
        payload: dict,
        owner_name: str,
        owner_filename: str | None,
        parent_settings: list[str] | None = None,
    ) -> dict[str, list[dict]]:
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        created_cyphers: list[dict] = []
        created_attacks: list[dict] = []

        for item in actor.get("items") or []:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            item_name = str(item.get("name") or "").strip()
            if not item_name:
                continue
            item_system = item.get("system") if isinstance(item.get("system"), dict) else {}
            basic_data = item_system.get("basic") if isinstance(item_system.get("basic"), dict) else {}
            description = str(item_system.get("description") or "").strip()
            item_img = str(item.get("img") or "").strip()

            if item_type == "cypher":
                cypher_result = {
                    "type": "cypher",
                    "name": item_name,
                    "level": basic_data.get("level"),
                    "sections": {
                        "name": item_name,
                        "level": str(basic_data.get("level") or ""),
                        "effect": description,
                    },
                    "metadata": {
                        "source": "storage",
                        "origin": "foundry_item_extracted",
                        "owner_character_name": owner_name,
                        "owner_character_filename": owner_filename,
                        "settings": list(parent_settings or []),
                        "foundry_origin": str(payload.get("foundry_origin") or ""),
                        "image_url": item_img,
                        "images": [item_img] if item_img else [],
                    },
                }
                cypher_result = attach_settings_metadata(
                    cypher_result,
                    payload,
                    current_app.config["LOL_CONFIG"],
                )
                cypher_result = cache_foundry_images_for_result(cypher_result)
                path = save_generated_result(storage_dir, cypher_result, payload)
                created_cyphers.append({
                    "name": item_name,
                    "filename": str(path.relative_to(storage_dir)).replace("\\", "/"),
                })

            if item_type == "attack":
                attack_result = {
                    "type": "attack",
                    "name": item_name,
                    "sections": {
                        "description": description,
                        "weapon_type": str(basic_data.get("type") or ""),
                        "damage": str(basic_data.get("damage") or ""),
                        "range": str(basic_data.get("range") or ""),
                        "skill_rating": str(basic_data.get("skillRating") or ""),
                    },
                    "metadata": {
                        "source": "storage",
                        "origin": "foundry_item_extracted",
                        "owner_character_name": owner_name,
                        "owner_character_filename": owner_filename,
                        "settings": list(parent_settings or []),
                        "foundry_origin": str(payload.get("foundry_origin") or ""),
                        "image_url": item_img,
                        "images": [item_img] if item_img else [],
                    },
                }
                attack_result = attach_settings_metadata(
                    attack_result,
                    payload,
                    current_app.config["LOL_CONFIG"],
                )
                attack_result = cache_foundry_images_for_result(attack_result)
                path = save_generated_result(storage_dir, attack_result, payload)
                created_attacks.append({
                    "name": item_name,
                    "filename": str(path.relative_to(storage_dir)).replace("\\", "/"),
                })

        return {
            "cyphers": created_cyphers,
            "attacks": created_attacks,
        }

    def normalize_storage_results(items: list[dict]) -> list[dict]:
        def compact_text(value: object, limit: int = 260) -> str:
            text = " ".join(str(value or "").strip().split())
            if len(text) > limit:
                return text[: limit - 1].rstrip() + "…"
            return text

        def extract_storage_description(item: dict) -> str:
            metadata = item.get("metadata", {}) or {}
            sections = item.get("sections", {}) or {}
            sheet = item.get("sheet", {}) or {}
            for candidate in (
                item.get("description"),
                metadata.get("description"),
                sections.get("description"),
                sections.get("summary"),
                sections.get("effect"),
                sections.get("use"),
                item.get("excerpt"),
                sheet.get("notes"),
                item.get("text"),
            ):
                text = compact_text(candidate)
                if text:
                    return text
            return ""

        normalized = []

        for item in items:
            meta = item.get("metadata", {}) or {}
            source_key = FOUNDRY_COMPENDIUM_ID if is_foundry_source(meta.get("source")) else "storage"
            display_type = (
                str(meta.get("primarycategory") or "").strip().lower()
                or str(meta.get("subtype") or "").strip().lower()
                or str(item.get("type") or "").strip().lower()
            )
            parts = []

            if meta.get("environment"):
                parts.append(f"environment: {meta['environment']}")
            if meta.get("area"):
                parts.append(f"area: {meta['area']}")
            if meta.get("location"):
                parts.append(f"location: {meta['location']}")
            if meta.get("race"):
                parts.append(f"race: {meta['race']}")
            if meta.get("profession"):
                parts.append(f"profession: {meta['profession']}")
            if meta.get("role"):
                parts.append(f"role: {meta['role']}")
            if meta.get("family"):
                parts.append(f"family: {meta['family']}")
            if meta.get("level"):
                parts.append(f"level: {meta['level']}")
            if meta.get("settings"):
                parts.append(f"settings: {', '.join(meta['settings'])}")
            if meta.get("from_csrd"):
                parts.append("from: csrd")
            if meta.get("compendium_slug"):
                parts.append(f"csrd_slug: {meta['compendium_slug']}")

            normalized.append({
                "source": source_key,
                "type": display_type or item.get("type"),
                "title": item.get("name") or item.get("filename"),
                "description": extract_storage_description(item),
                "subtitle": " • ".join(parts),
                "slug": item.get("filename"),
                "url": f"/storage/{item.get('filename')}",
                "raw": item,
            })

        return normalized


    def normalize_compendium_results(items: list[dict]) -> list[dict]:
        def compact_text(value: object, limit: int = 260) -> str:
            text = " ".join(str(value or "").strip().split())
            if len(text) > limit:
                return text[: limit - 1].rstrip() + "…"
            return text

        def extract_compendium_description(item: dict) -> str:
            for candidate in (
                item.get("description"),
                item.get("summary"),
                item.get("effect"),
                item.get("use"),
                item.get("excerpt"),
                item.get("text"),
            ):
                text = compact_text(candidate)
                if text:
                    return text
            return ""

        normalized = []

        for item in items:
            parts = []

            if item.get("category"):
                parts.append(f"category: {item['category']}")
            if item.get("environment"):
                parts.append(f"environment: {item['environment']}")
            if item.get("area"):
                parts.append(f"area: {item['area']}")
            if item.get("level"):
                parts.append(f"level: {item['level']}")
            if item.get("cost"):
                parts.append(f"cost: {item['cost']}")
            if item.get("alpha_section"):
                parts.append(f"section: {item['alpha_section']}")
            if item.get("settings"):
                parts.append(f"settings: {', '.join(item['settings'])}")

            normalized.append({
                "source": "compendium",
                "type": item.get("type"),
                "title": item.get("title") or item.get("slug"),
                "description": extract_compendium_description(item),
                "subtitle": " • ".join(parts),
                "slug": item.get("slug"),
                "url": f"/compendium/{item.get('type')}/{item.get('slug')}",
                "raw": item,
            })

        return normalized

    def normalize_official_compendium_results(items: list[dict]) -> list[dict]:
        def compact_text(value: object, limit: int = 260) -> str:
            text = " ".join(str(value or "").strip().split())
            if len(text) > limit:
                return text[: limit - 1].rstrip() + "…"
            return text

        def slugify_text(value: object) -> str:
            text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
            text = re.sub(r"_+", "_", text).strip("_")
            return text

        normalized = []
        for item in items:
            parts = []
            book_value = str(item.get("book") or "").strip()
            book_display = _display_sourcebook_label(book_value)
            source_value = slugify_text(book_value) or "official_pdf"
            if item.get("book"):
                parts.append(f"book: {book_display}")
            if item.get("pages"):
                parts.append(f"pages: {item['pages']}")
            if item.get("settings"):
                parts.append(f"settings: {', '.join(item['settings'])}")
            normalized.append({
                "source": source_value,
                "type": item.get("type"),
                "title": item.get("title") or item.get("slug"),
                "description": compact_text(item.get("description") or ""),
                "book": book_display,
                "pages": item.get("pages"),
                "subtitle": " • ".join(parts),
                "slug": item.get("slug"),
                "url": f"/official-compendium/{item.get('type')}/{item.get('slug')}",
                "raw": item,
            })
        return normalized

    def normalize_lore_results(items: list[dict]) -> list[dict]:
        def compact_text(value: object, limit: int = 260) -> str:
            text = " ".join(str(value or "").strip().split())
            if len(text) > limit:
                return text[: limit - 1].rstrip() + "…"
            return text

        normalized = []
        for item in items:
            settings = item.get("settings") or []
            categories = item.get("categories") or []
            parts = []
            if item.get("area") or item.get("environment"):
                parts.append(f"area: {item.get('area') or item.get('environment')}")
            if item.get("location"):
                parts.append(f"location: {item.get('location')}")
            if categories:
                parts.append(f"categories: {', '.join([str(x) for x in categories if str(x).strip()])}")
            if settings:
                parts.append(f"settings: {', '.join([str(x) for x in settings if str(x).strip()])}")

            normalized.append({
                "source": "lore",
                "type": "lore",
                "title": item.get("title") or item.get("slug"),
                "description": compact_text(item.get("description") or item.get("excerpt") or ""),
                "subtitle": " • ".join(parts),
                "slug": item.get("slug"),
                "url": f"/lore/{item.get('slug')}",
                "raw": item,
            })
        return normalized

    def build_local_variant_from_compendium(
        entry: dict,
        *,
        item_type: str,
        slug: str,
        payload: dict,
    ) -> dict:
        title = str(entry.get("title") or slug).strip() or slug
        area_value = str(entry.get("area") or entry.get("environment") or payload.get("area") or "").strip()
        location_value = str(payload.get("location") or "").strip()
        compendium_backlink = f"/compendium/{item_type}/{slug}"

        result: dict = {
            "type": item_type,
            "name": title,
            "description": str(entry.get("description") or entry.get("summary") or entry.get("effect") or "").strip(),
            "metadata": {
                "source": "house",
                "origin": "compendium_variant",
                "from_csrd": True,
                "compendium_type": item_type,
                "compendium_slug": slug,
                "compendium_title": title,
                "compendium_backlink": compendium_backlink,
                "area": area_value,
                "environment": area_value,
                "location": location_value,
            },
            "base_entry": entry,
            "text": json.dumps(entry, indent=2, ensure_ascii=False),
        }

        sections: dict[str, str] = {}
        if item_type == "cypher":
            sections = {
                "name": title,
                "level": str(entry.get("level") or ""),
                "category": str(entry.get("category") or ""),
                "manifestation": str(entry.get("form") or ""),
                "effect": str(entry.get("effect") or ""),
                "depletion": str(entry.get("depletion") or ""),
            }
        elif item_type == "artifact":
            sections = {
                "name": title,
                "level": str(entry.get("level") or ""),
                "category": str(entry.get("category") or ""),
                "manifestation": str(entry.get("form") or ""),
                "effect": str(entry.get("effect") or ""),
                "depletion": str(entry.get("depletion") or ""),
            }
        elif item_type == "creature":
            stat_block = {
                "level": entry.get("level"),
                "target_number": entry.get("target_number"),
                "health": entry.get("health"),
                "armor": entry.get("armor"),
                "damage": entry.get("damage_inflicted"),
                "movement": entry.get("movement"),
                "modifications": [],
                "combat": [],
                "interaction": [],
                "loot": [],
            }
            result["stat_block"] = stat_block
            sections = {
                "description": str(entry.get("description") or ""),
                "motive": str(entry.get("motive") or ""),
                "use": str(entry.get("use") or ""),
                "gm_intrusion": str(entry.get("gm_intrusion") or ""),
            }
        else:
            for key in ("summary", "cost", "alpha_section", "effect", "gm_intrusions"):
                value = str(entry.get(key) or "").strip()
                if value:
                    sections[key] = value

        if sections:
            result["sections"] = {k: v for k, v in sections.items() if str(v).strip()}
        entry_settings = entry.get("settings")
        if isinstance(entry_settings, list) and entry_settings:
            result["metadata"]["settings"] = [str(x).strip() for x in entry_settings if str(x).strip()]
        entry_setting = str(entry.get("setting") or "").strip()
        if entry_setting:
            result["metadata"]["setting"] = entry_setting
        return result

    def character_sheet_pdf_template_path() -> Path:
        return (
            current_app.config["LOL_PROJECT_ROOT"]
            / "PDF_Repository"
            / "FormFillableCharacterSheet"
            / "Cypher System Character Sheets-Revised-FormFillable-2019-09-10.pdf"
        )

    def load_pypdf():
        try:
            from pypdf import PdfReader, PdfWriter  # type: ignore
            from pypdf.generic import BooleanObject, NameObject  # type: ignore
        except Exception:
            return None
        return PdfReader, PdfWriter, NameObject, BooleanObject

    def read_character_sheet_pdf_field_names() -> list[str]:
        pypdf_mod = load_pypdf()
        if pypdf_mod is None:
            raise RuntimeError("pypdf is not installed")
        PdfReader, _, _, _ = pypdf_mod
        template_path = character_sheet_pdf_template_path()
        if not template_path.exists():
            raise FileNotFoundError(f"PDF template not found: {template_path}")
        reader = PdfReader(str(template_path))
        fields = reader.get_fields() or {}
        names = [str(name) for name in fields.keys() if str(name).strip()]
        names.sort(key=lambda x: x.lower())
        return names

    def normalize_pdf_field_key(value: str) -> str:
        return "".join(ch for ch in str(value or "").lower() if ch.isalnum())

    def sheet_to_pdf_values(sheet: dict) -> dict[str, str]:
        pools = sheet.get("pools") or {}
        max_pools = pools.get("max") or {}
        current_pools = pools.get("current") or {}
        edges = sheet.get("edges") or {}
        metadata = sheet.get("metadata") or {}
        recovery = sheet.get("recovery_rolls_used") or {}
        chosen_abilities = [str(x).strip() for x in (sheet.get("chosen_abilities") or []) if str(x).strip()]
        chosen_skills = []
        for entry in sheet.get("chosen_skills") or []:
            if not isinstance(entry, dict):
                continue
            skill_name = str(entry.get("name") or "").strip()
            skill_level = str(entry.get("level") or "").strip()
            if not skill_name:
                continue
            chosen_skills.append(f"{skill_level}: {skill_name}" if skill_level else skill_name)
        equipment = [str(x).strip() for x in (sheet.get("equipment") or []) if str(x).strip()]

        values = {
            "name": str(sheet.get("name") or ""),
            "character_name": str(sheet.get("name") or ""),
            "sentence": str(sheet.get("sentence") or ""),
            "type": str(sheet.get("type") or ""),
            "flavor": str(sheet.get("flavor") or ""),
            "descriptor": str(sheet.get("descriptor") or ""),
            "focus": str(sheet.get("focus") or ""),
            "tier": str((metadata.get("tier") or sheet.get("tier") or 1)),
            "effort": str(sheet.get("effort") or ""),
            "cypher_limit": str(sheet.get("cypher_limit") or ""),
            "weapons": str(sheet.get("weapons") or ""),
            "might_pool_max": str(max_pools.get("might") or ""),
            "speed_pool_max": str(max_pools.get("speed") or ""),
            "intellect_pool_max": str(max_pools.get("intellect") or ""),
            "might_pool_current": str(current_pools.get("might") or ""),
            "speed_pool_current": str(current_pools.get("speed") or ""),
            "intellect_pool_current": str(current_pools.get("intellect") or ""),
            "might_edge": str(edges.get("might") or ""),
            "speed_edge": str(edges.get("speed") or ""),
            "intellect_edge": str(edges.get("intellect") or ""),
            "damage_track": str(sheet.get("damage_track") or ""),
            "notes": str(sheet.get("notes") or ""),
            "race": str(metadata.get("race") or ""),
            "profession": str(metadata.get("profession") or ""),
            "area": str(metadata.get("area") or metadata.get("environment") or ""),
            "location": str(metadata.get("location") or ""),
            "setting": str(metadata.get("setting") or ""),
            "world": str(metadata.get("world") or ""),
            "chosen_abilities": "\n".join(chosen_abilities),
            "chosen_skills": "\n".join(chosen_skills),
            "equipment": "\n".join(equipment),
            "recovery_action": "Yes" if recovery.get("action") else "Off",
            "recovery_10_minutes": "Yes" if recovery.get("ten_minutes") else "Off",
            "recovery_1_hour": "Yes" if recovery.get("one_hour") else "Off",
            "recovery_10_hours": "Yes" if recovery.get("ten_hours") else "Off",
            "damage_hale": "Yes" if str(sheet.get("damage_track") or "").lower() == "hale" else "Off",
            "damage_impaired": "Yes" if str(sheet.get("damage_track") or "").lower() == "impaired" else "Off",
            "damage_debilitated": "Yes" if str(sheet.get("damage_track") or "").lower() == "debilitated" else "Off",
            "damage_dead": "Yes" if str(sheet.get("damage_track") or "").lower() == "dead" else "Off",
        }
        return values

    def auto_map_sheet_values_to_pdf_fields(field_names: list[str], sheet: dict) -> dict[str, str]:
        values = sheet_to_pdf_values(sheet)
        metadata = sheet.get("metadata") or {}
        descriptor_effects = sheet.get("descriptor_effects") or {}
        chosen_abilities = [str(x).strip() for x in (sheet.get("chosen_abilities") or []) if str(x).strip()]
        descriptor_skills = [str(x).strip() for x in (descriptor_effects.get("skills") or []) if str(x).strip()]
        descriptor_inabilities = [str(x).strip() for x in (descriptor_effects.get("inabilities") or []) if str(x).strip()]
        equipment = [str(x).strip() for x in (sheet.get("equipment") or []) if str(x).strip()]

        # Deterministic mapping for the official Cypher form-fillable sheet field names.
        explicit: dict[str, str] = {
            "Name": str(sheet.get("name") or ""),
            "Descriptor": str(sheet.get("descriptor") or ""),
            "Type": str(sheet.get("type") or ""),
            "Tier": str((metadata.get("tier") or sheet.get("tier") or 1)),
            "Effort": str(sheet.get("effort") or ""),
            "XP": str(metadata.get("xp") or sheet.get("xp") or ""),
            "Might": str((((sheet.get("pools") or {}).get("max") or {}).get("might")) or ""),
            "Speed": str((((sheet.get("pools") or {}).get("max") or {}).get("speed")) or ""),
            "Intellect": str((((sheet.get("pools") or {}).get("max") or {}).get("intellect")) or ""),
            "Might_Pool": str((((sheet.get("pools") or {}).get("current") or {}).get("might")) or ""),
            "Might_Edge": str((((sheet.get("edges") or {}).get("might")) or "")),
            "Speed_Pool": str((((sheet.get("pools") or {}).get("current") or {}).get("speed")) or ""),
            "Speed_Edge": str((((sheet.get("edges") or {}).get("speed")) or "")),
            "Intellect_Pool": str((((sheet.get("pools") or {}).get("current") or {}).get("intellect")) or ""),
            "Intellect_Edge": str((((sheet.get("edges") or {}).get("intellect")) or "")),
            "Recovery_Roll": str(sheet.get("recovery_roll") or ""),
            "1_ACTION": "Yes" if values.get("recovery_action") == "Yes" else "Off",
            "10_Min": "Yes" if values.get("recovery_10_minutes") == "Yes" else "Off",
            "1_Hour": "Yes" if values.get("recovery_1_hour") == "Yes" else "Off",
            "10_Hours": "Yes" if values.get("recovery_10_hours") == "Yes" else "Off",
            "Impaired": "Yes" if values.get("damage_impaired") == "Yes" else "Off",
            "Debilitated": "Yes" if values.get("damage_debilitated") == "Yes" else "Off",
            "Special_Abilities": "\n".join(chosen_abilities),
            "Focus": str(sheet.get("focus") or ""),
            "Type_Focus_or_Other": str(sheet.get("flavor") or ""),
            "Cyphers_Limit": str(sheet.get("cypher_limit") or ""),
            "Equipment": "\n".join(equipment),
            "Armor": str(sheet.get("armor") or ""),
            "Money": str(sheet.get("money") or ""),
            "Background": str(sheet.get("sentence") or ""),
            "Notes": str(sheet.get("notes") or ""),
            "Other": str(sheet.get("weapons") or ""),
        }

        # Top skill rows: descriptor skills first, then descriptor inabilities, then selected skill picks.
        skill_rows: list[tuple[str, str]] = []
        for name in descriptor_skills:
            skill_rows.append((name, "trained"))
        for name in descriptor_inabilities:
            skill_rows.append((name, "inability"))
        for entry in sheet.get("chosen_skills") or []:
            if not isinstance(entry, dict):
                continue
            skill_name = str(entry.get("name") or "").strip()
            level = str(entry.get("level") or "trained").strip().lower()
            if not skill_name:
                continue
            skill_rows.append((skill_name, level))

        marker_by_level = {
            "trained": "T",
            "expert": "S",
            "specialized": "S",
            "specialised": "S",
            "inability": "I",
            "practiced": "P",
            "practised": "P",
        }
        for idx in range(1, 15):
            explicit.setdefault(f"Skills_{idx}", "")
            explicit.setdefault(f"Skills_T_{idx}", "Off")
            explicit.setdefault(f"Skills_S_{idx}", "Off")
            explicit.setdefault(f"Skills_I_{idx}", "Off")
            explicit.setdefault(f"Skills_P_{idx}", "Off")
            if idx <= len(skill_rows):
                name, level = skill_rows[idx - 1]
                explicit[f"Skills_{idx}"] = name
                marker = marker_by_level.get(level, "T")
                explicit[f"Skills_{marker}_{idx}"] = "Yes"

        normalized_values = {
            normalize_pdf_field_key(key): str(value)
            for key, value in values.items()
            if str(value).strip() != ""
        }
        chosen_skills: list[str] = []
        for entry in sheet.get("chosen_skills") or []:
            if not isinstance(entry, dict):
                continue
            skill_name = str(entry.get("name") or "").strip()
            skill_level = str(entry.get("level") or "").strip()
            if not skill_name:
                continue
            chosen_skills.append(f"{skill_level}: {skill_name}" if skill_level else skill_name)

        alias_rules: list[tuple[str, list[list[str]]]] = [
            ("character_name", [["character", "name"], ["name"]]),
            ("sentence", [["sentence"], ["summary"]]),
            ("descriptor", [["descriptor"]]),
            ("type", [["type"]]),
            ("flavor", [["flavor"]]),
            ("focus", [["focus"]]),
            ("tier", [["tier"]]),
            ("effort", [["effort"]]),
            ("cypher_limit", [["cypher", "limit"]]),
            ("weapons", [["weapon"]]),
            ("might_pool_current", [["might", "pool", "current"], ["current", "might"]]),
            ("speed_pool_current", [["speed", "pool", "current"], ["current", "speed"]]),
            ("intellect_pool_current", [["intellect", "pool", "current"], ["current", "intellect"]]),
            ("might_pool_max", [["might", "pool", "max"], ["might", "max"], ["might", "stat"]]),
            ("speed_pool_max", [["speed", "pool", "max"], ["speed", "max"], ["speed", "stat"]]),
            ("intellect_pool_max", [["intellect", "pool", "max"], ["intellect", "max"], ["intellect", "stat"]]),
            ("might_edge", [["might", "edge"]]),
            ("speed_edge", [["speed", "edge"]]),
            ("intellect_edge", [["intellect", "edge"]]),
            ("notes", [["notes"]]),
            ("race", [["race"]]),
            ("profession", [["profession"]]),
            ("area", [["area"], ["environment"]]),
            ("location", [["location"]]),
            ("setting", [["setting"]]),
            ("world", [["world"]]),
            ("recovery_action", [["recovery", "action"]]),
            ("recovery_10_minutes", [["recovery", "10"], ["recovery", "ten", "minute"]]),
            ("recovery_1_hour", [["recovery", "1"], ["recovery", "hour"]]),
            ("recovery_10_hours", [["recovery", "10", "hour"]]),
            ("damage_hale", [["hale"]]),
            ("damage_impaired", [["impaired"]]),
            ("damage_debilitated", [["debilitated"]]),
            ("damage_dead", [["dead"]]),
        ]

        output: dict[str, str] = {}
        for field_name in field_names:
            if field_name in explicit:
                output[field_name] = str(explicit[field_name])

        for field_name in field_names:
            if field_name in output and output[field_name] != "":
                continue
            normalized_field = normalize_pdf_field_key(field_name)
            if not normalized_field:
                continue
            direct = normalized_values.get(normalized_field)
            if direct is not None:
                output[field_name] = direct
                continue

            mapped = ""
            for logical_key, token_sets in alias_rules:
                for tokens in token_sets:
                    if all(token in normalized_field for token in tokens):
                        mapped = values.get(logical_key, "")
                        break
                if mapped:
                    break

            if not mapped:
                index_tokens = [int(x) for x in field_name.split() if x.isdigit()]
                explicit_index = index_tokens[0] if index_tokens else None
                if explicit_index is None:
                    digits = "".join(ch if ch.isdigit() else " " for ch in field_name).split()
                    if digits:
                        explicit_index = int(digits[0])

                idx = max(0, int(explicit_index) - 1) if explicit_index else 0
                if "equipment" in normalized_field and idx < len(equipment):
                    mapped = equipment[idx]
                elif "abilit" in normalized_field and idx < len(chosen_abilities):
                    mapped = chosen_abilities[idx]
                elif ("skill" in normalized_field or "trained" in normalized_field) and idx < len(chosen_skills):
                    mapped = chosen_skills[idx]

            if mapped:
                output[field_name] = str(mapped)

        overrides = sheet.get("pdf_fields") or {}
        if isinstance(overrides, dict):
            for raw_key, raw_value in overrides.items():
                key = str(raw_key or "").strip()
                if not key:
                    continue
                output[key] = str(raw_value or "")
        return output

    def render_character_sheet_pdf(sheet: dict) -> tuple[bytes, str]:
        pypdf_mod = load_pypdf()
        if pypdf_mod is None:
            raise RuntimeError("pypdf is not installed")
        PdfReader, PdfWriter, NameObject, BooleanObject = pypdf_mod
        template_path = character_sheet_pdf_template_path()
        if not template_path.exists():
            raise FileNotFoundError(f"PDF template not found: {template_path}")

        reader = PdfReader(str(template_path))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        try:
            if "/AcroForm" in reader.trailer["/Root"]:
                writer._root_object.update(  # pylint: disable=protected-access
                    {NameObject("/AcroForm"): reader.trailer["/Root"]["/AcroForm"]}
                )
                writer._root_object["/AcroForm"].update(  # pylint: disable=protected-access
                    {NameObject("/NeedAppearances"): BooleanObject(True)}
                )
        except Exception:
            # If form metadata can't be copied, update_page_form_field_values may fail below.
            pass

        fields = reader.get_fields() or {}
        field_names = [str(name) for name in fields.keys() if str(name).strip()]
        values_by_field = auto_map_sheet_values_to_pdf_fields(field_names, sheet)

        for page in writer.pages:
            writer.update_page_form_field_values(page, values_by_field, auto_regenerate=False)

        # Ensure checkbox/radio button appearance states are set explicitly.
        for page in writer.pages:
            annots = page.get("/Annots")
            if not annots:
                continue
            for annot_ref in annots:
                try:
                    annot = annot_ref.get_object()
                except Exception:
                    continue
                if str(annot.get("/FT")) != "/Btn":
                    continue
                field_name = str(annot.get("/T") or "")
                if not field_name:
                    continue
                raw_value = values_by_field.get(field_name)
                if raw_value is None:
                    continue
                value_text = str(raw_value).strip().lower()
                is_on = value_text in {"yes", "/yes", "true", "1", "on"}
                annot.update({NameObject("/V"): NameObject("/Yes" if is_on else "/Off")})
                annot.update({NameObject("/AS"): NameObject("/Yes" if is_on else "/Off")})

        out = BytesIO()
        writer.write(out)
        out.seek(0)
        filename_base = secure_filename(str(sheet.get("name") or "character_sheet").strip()) or "character_sheet"
        return out.read(), f"{filename_base}.pdf"

    ## Routes 
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/generator")
    def generator():
        return render_template("generator.html")

    @app.get("/ai-generate")
    def ai_generate():
        return render_template("ai_generate.html")

    @app.post("/ai-generate/run")
    def api_ai_generate_run():
        body = request.get_json(force=True, silent=False) or {}
        provider = str(body.get("provider") or "ollama_local").strip().lower()
        content_type = str(body.get("content_type") or "free_text").strip().lower()
        brief = str(body.get("brief") or "").strip()
        setting_id = str(body.get("setting") or "").strip()
        area_id = str(body.get("area") or "").strip()
        location_id = str(body.get("location") or "").strip()
        sourcebook_id = str(body.get("sourcebook") or "").strip()
        schema = body.get("schema") if isinstance(body.get("schema"), dict) else {}
        image_data_url = str(body.get("image_data_url") or "").strip()
        recent_examples_raw = body.get("recent_examples") if isinstance(body.get("recent_examples"), dict) else {}
        recent_examples = {
            "names": [str(value or "").strip() for value in (recent_examples_raw.get("names") or []) if str(value or "").strip()],
            "name_roots": [str(value or "").strip() for value in (recent_examples_raw.get("name_roots") or []) if str(value or "").strip()],
            "surname_roots": [str(value or "").strip() for value in (recent_examples_raw.get("surname_roots") or []) if str(value or "").strip()],
            "description_openers": [str(value or "").strip() for value in (recent_examples_raw.get("description_openers") or []) if str(value or "").strip()],
        }
        generation_preferences_raw = body.get("generation_preferences") if isinstance(body.get("generation_preferences"), dict) else {}
        generation_preferences = {
            "race": str(generation_preferences_raw.get("race") or "").strip(),
            "variant": str(generation_preferences_raw.get("variant") or "").strip(),
            "gender": str(generation_preferences_raw.get("gender") or "").strip(),
            "profession": str(generation_preferences_raw.get("profession") or "").strip(),
            "culture": str(generation_preferences_raw.get("culture") or "").strip(),
        }
        allowed_compendium_ids_raw = body.get("compendium_ids")
        allowed_compendium_ids: list[str] | None = None
        if isinstance(allowed_compendium_ids_raw, list):
            allowed_compendium_ids = []
            for value in allowed_compendium_ids_raw:
                cid = str(value or "").strip().lower()
                if cid and cid not in allowed_compendium_ids:
                    allowed_compendium_ids.append(cid)
        allowed_compendium_ids = _ai_generate_allowed_compendium_ids(allowed_compendium_ids, setting_id=setting_id)

        if provider == "openai_remote":
            if not is_plugin_enabled("openai_remote"):
                return jsonify({"error": "openai_remote plugin is disabled"}), 403
        else:
            if not is_plugin_enabled("ollama_local"):
                return jsonify({"error": "ollama_local plugin is disabled"}), 403

        image_bytes: bytes | None = None
        image_mime_type = ""
        if image_data_url:
            try:
                image_mime_type, image_bytes = _parse_image_data_url(image_data_url)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400

        if not brief and image_bytes is None:
            return jsonify({"error": "either brief or image_data_url is required"}), 400

        preference_terms = [
            str(generation_preferences.get("race") or "").strip(),
            str(generation_preferences.get("variant") or "").strip(),
            str(generation_preferences.get("profession") or "").strip(),
            str(generation_preferences.get("culture") or "").strip(),
        ]
        query_text = brief
        if not query_text:
            query_text = " ".join(
                bit for bit in [
                    content_type.replace("_", " "),
                    setting_id,
                    area_id,
                    location_id,
                    sourcebook_id,
                    *preference_terms,
                    "visual reference",
                ] if bit
            ).strip() or f"{content_type.replace('_', ' ')} visual reference"

        k_raw = body.get("k")
        try:
            k = max(1, min(20, int(k_raw))) if k_raw is not None else 12
        except Exception:
            k = 12

        items: list[dict] = []
        citations: list[dict] = []
        lore_items: list[dict] = []
        lore_citations: list[dict] = []
        grounded_context = "No vector context available."
        vector_query_text = " ".join(
            bit for bit in [
                brief,
                setting_id,
                area_id,
                location_id,
                sourcebook_id,
                *preference_terms,
            ] if bit
        ).strip()
        if vector_query_text:
            try:
                items, citations, grounded_context = _build_vector_context(
                    vector_query_text,
                    compendium_ids=allowed_compendium_ids,
                    k=k,
                )
            except FileNotFoundError as exc:
                return jsonify({"error": str(exc)}), 404
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            try:
                lore_items, lore_citations, lore_context = _build_lore_context(
                    vector_query_text,
                    setting=setting_id,
                    location=location_id or area_id,
                    k=max(2, min(6, k // 2 or 2)),
                    focus_type=content_type,
                )
            except Exception:
                lore_items, lore_citations, lore_context = [], [], "No lore context available."
            if lore_context != "No lore context available.":
                if grounded_context == "No vector context available.":
                    grounded_context = lore_context
                else:
                    grounded_context = f"{lore_context}\n\n{grounded_context}"

        prompt = _ai_generate_prompt(
            content_type=content_type,
            schema=schema,
            brief=brief,
            allowed_compendium_ids=allowed_compendium_ids,
            image_supplied=image_bytes is not None,
            generation_preferences=generation_preferences,
            setting_id=setting_id,
            area_id=area_id,
            location_id=location_id,
            sourcebook_id=sourcebook_id,
            recent_examples=recent_examples,
        )

        try:
            answer, model, base_url = _ai_generate_with_provider(
                provider=provider,
                prompt=prompt,
                vector_context=grounded_context,
                image_data_url=image_data_url,
                image_bytes=image_bytes,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            provider_label = "OpenAI" if provider == "openai_remote" else "Ollama"
            return jsonify({
                "error": f"{provider_label} request failed: {exc}",
                "model": OLLAMA_VISION_MODEL if image_bytes is not None and provider != "openai_remote" else "",
            }), 502

        parsed_answer = _extract_first_json_object(answer)
        normalized_card = None
        if isinstance(parsed_answer, dict):
            normalized_card = _normalize_ai_generated_card(
                parsed_answer,
                content_type=content_type,
                setting_id=setting_id,
                area_id=area_id,
                generation_preferences=generation_preferences,
            )
            answer = json.dumps(normalized_card, ensure_ascii=False, indent=2)

        return jsonify({
            "answer": answer,
            "normalized_card": normalized_card,
            "provider": provider,
            "content_type": content_type,
            "base_url": base_url,
            "model": model,
            "image_used": image_bytes is not None,
            "image_mime_type": image_mime_type,
            "k": k,
            "compendium_ids": allowed_compendium_ids,
            "citation_count": len(citations) + len(lore_citations),
            "citations": lore_citations + citations,
            "vector_items": lore_items + items,
        })

    @app.post("/ai-generate/detect-character")
    def api_ai_generate_detect_character():
        body = request.get_json(force=True, silent=False) or {}
        provider = str(body.get("provider") or "ollama_local").strip().lower()
        content_type = str(body.get("content_type") or "npc").strip().lower()
        image_data_url = str(body.get("image_data_url") or "").strip()
        brief = str(body.get("brief") or "").strip()
        setting = str(body.get("setting") or "").strip()
        area = str(body.get("area") or "").strip()
        location = str(body.get("location") or "").strip()
        sourcebook = str(body.get("sourcebook") or "").strip()
        allowed_compendium_ids_raw = body.get("compendium_ids")
        allowed_compendium_ids: list[str] | None = None
        if isinstance(allowed_compendium_ids_raw, list):
            allowed_compendium_ids = []
            for value in allowed_compendium_ids_raw:
                cid = str(value or "").strip().lower()
                if cid and cid not in allowed_compendium_ids:
                    allowed_compendium_ids.append(cid)
        allowed_compendium_ids = _ai_generate_allowed_compendium_ids(allowed_compendium_ids, setting_id=setting)

        if content_type not in {"npc", "player_character"}:
            return jsonify({"error": "content_type must be npc or player_character"}), 400
        if provider == "openai_remote":
            if not is_plugin_enabled("openai_remote"):
                return jsonify({"error": "openai_remote plugin is disabled"}), 403
        else:
            if not is_plugin_enabled("ollama_local"):
                return jsonify({"error": "ollama_local plugin is disabled"}), 403
        if not image_data_url:
            return jsonify({"error": "image_data_url is required"}), 400

        try:
            image_mime_type, image_bytes = _parse_image_data_url(image_data_url)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        query_bits = [
            content_type.replace("_", " "),
            "portrait",
            setting,
            area,
            location,
            sourcebook,
            brief,
        ]
        query_text = " ".join(bit for bit in query_bits if bit).strip() or f"{content_type} portrait"

        try:
            items, citations, grounded_context = _build_vector_context(
                query_text,
                compendium_ids=allowed_compendium_ids,
                k=8,
            )
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        try:
            lore_items, lore_citations, lore_context = _build_lore_context(
                query_text,
                setting=setting,
                location=location or area,
                k=4,
                focus_type=content_type,
            )
        except Exception:
            lore_items, lore_citations, lore_context = [], [], "No lore context available."
        if lore_context != "No lore context available.":
            if grounded_context == "No vector context available.":
                grounded_context = lore_context
            else:
                grounded_context = f"{lore_context}\n\n{grounded_context}"

        label = "player character" if content_type == "player_character" else "npc"
        prompt = (
            f"Analyze the supplied image as a {label} portrait and return ONLY valid JSON.\n"
            "Do not include markdown fences, explanations, or extra text.\n"
            "Infer best-fit values from visible cues plus local lore context.\n"
            "Be restrained when evidence is weak; prefer empty strings over confident invention.\n"
            "Use local lore and area/setting context to map the portrait toward likely race, culture, and profession.\n"
            "JSON shape:\n"
            "{\n"
            "  \"race\": \"best-fit race or empty string\",\n"
            "  \"variant\": \"best-fit race variant or empty string\",\n"
            "  \"gender\": \"best-fit gender or empty string\",\n"
            "  \"profession\": \"best-fit profession or empty string\",\n"
            "  \"culture\": \"best-fit culture or empty string\",\n"
            "  \"appearance_summary\": \"1-2 sentence portrait read grounded in the setting\",\n"
            "  \"confidence\": \"low|medium|high\"\n"
            "}\n"
            f"Current context: setting={setting or '(none)'}, area={area or '(none)'}, location={location or '(none)'}, sourcebook={sourcebook or '(none)'}.\n"
            f"User note: {brief or '(none)'}"
        )

        try:
            answer, model, base_url = _ai_generate_with_provider(
                provider=provider,
                prompt=prompt,
                vector_context=grounded_context,
                image_data_url=image_data_url,
                image_bytes=image_bytes,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            provider_label = "OpenAI" if provider == "openai_remote" else "Ollama"
            return jsonify({"error": f"{provider_label} request failed: {exc}"}), 502

        parsed = _extract_first_json_object(answer)
        if not isinstance(parsed, dict):
            return jsonify({"error": "model did not return valid JSON", "answer": answer}), 502

        detection = {
            "race": str(parsed.get("race") or "").strip(),
            "variant": str(parsed.get("variant") or "").strip(),
            "gender": str(parsed.get("gender") or "").strip(),
            "profession": str(parsed.get("profession") or "").strip(),
            "culture": str(parsed.get("culture") or "").strip(),
            "appearance_summary": str(parsed.get("appearance_summary") or "").strip(),
            "confidence": str(parsed.get("confidence") or "").strip().lower(),
        }
        detection = _normalize_ai_generated_identity_fields(
            detection,
            content_type=content_type,
            setting_id=setting,
            area_id=area,
            generation_preferences={},
        )
        return jsonify({
            "ok": True,
            "detection": detection,
            "answer": answer,
            "provider": provider,
            "content_type": content_type,
            "base_url": base_url,
            "model": model,
            "image_used": True,
            "image_mime_type": image_mime_type,
            "citation_count": len(citations) + len(lore_citations),
            "citations": lore_citations + citations,
            "vector_items": lore_items + items,
        })

    @app.get("/setting-wizard")
    def setting_wizard():
        return render_template("setting_wizard.html")

    def _extract_first_json_object(text: str) -> dict | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            pass
        fence = re.search(r"```json\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
        if not fence:
            fence = re.search(r"```\s*([\s\S]*?)```", raw)
        if fence:
            try:
                data = json.loads(str(fence.group(1) or "").strip())
                return data if isinstance(data, dict) else None
            except Exception:
                pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
                return data if isinstance(data, dict) else None
            except Exception:
                pass
        return None

    def _parse_image_data_url(value: object) -> tuple[str, bytes]:
        raw = str(value or "").strip()
        match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", raw, flags=re.DOTALL)
        if not match:
            raise ValueError("image must be a base64 data URL")
        mime_type = match.group(1).strip().lower()
        encoded = re.sub(r"\s+", "", match.group(2) or "")
        if not encoded:
            raise ValueError("image data is empty")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError("image data is not valid base64") from exc
        if not decoded:
            raise ValueError("image data is empty")
        return mime_type, decoded

    def _image_suffix_for_mime_type(mime_type: str) -> str:
        normalized = str(mime_type or "").strip().lower()
        explicit = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/svg+xml": ".svg",
        }
        if normalized in explicit:
            return explicit[normalized]
        guessed = mimetypes.guess_extension(normalized) or ""
        if guessed == ".jpe":
            guessed = ".jpg"
        return guessed if guessed in IMAGE_SUFFIXES else ""

    def _remote_image_name_from_url(image_url: str, mime_type: str) -> str:
        parsed = urlparse(image_url)
        candidate = secure_filename(Path(parsed.path or "").name)
        suffix = _image_suffix_for_mime_type(mime_type)
        stem = Path(candidate).stem or "remote_image"
        final_suffix = Path(candidate).suffix or suffix
        if final_suffix.lower() == ".jpe":
            final_suffix = ".jpg"
        if final_suffix.lower() not in IMAGE_SUFFIXES:
            final_suffix = suffix or ".jpg"
        return f"{stem}{final_suffix}"

    def _download_image_as_data_url(image_url: object) -> tuple[str, str, str]:
        raw_url = str(image_url or "").strip()
        if not raw_url:
            raise ValueError("url is required")
        parsed = urlparse(raw_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("url must start with http:// or https://")
        req = Request(
            raw_url,
            headers={
                "User-Agent": "LandsOfLegends-GMTools/1.0",
                "Accept": "image/*,*/*;q=0.8",
            },
        )
        with urlopen(req, timeout=15) as resp:
            mime_type = str(resp.headers.get_content_type() or "").strip().lower()
            if not mime_type.startswith("image/"):
                raise ValueError("URL did not return an image")
            decoded = resp.read()
        if not decoded:
            raise ValueError("downloaded image is empty")
        if len(decoded) > 10 * 1024 * 1024:
            raise ValueError("downloaded image is too large (max 10 MB)")
        suffix = _image_suffix_for_mime_type(mime_type)
        if suffix not in IMAGE_SUFFIXES:
            raise ValueError(f"unsupported image type '{mime_type or 'unknown'}'")
        data_url = f"data:{mime_type};base64,{base64.b64encode(decoded).decode('ascii')}"
        image_name = _remote_image_name_from_url(raw_url, mime_type)
        return data_url, image_name, mime_type

    def persist_uploaded_image_data(
        image_data_url: object,
        *,
        friendly_name: str = "",
        tags: list[str] | None = None,
        notes: str = "",
        upload_subdir: str = "uploads/ai_generate",
    ) -> dict[str, str | list[str]]:
        mime_type, decoded = _parse_image_data_url(image_data_url)
        suffix = _image_suffix_for_mime_type(mime_type)
        if suffix not in IMAGE_SUFFIXES:
            raise ValueError(f"unsupported image type '{mime_type or 'unknown'}'")
        content_hash = compute_image_content_hash(decoded)

        images_dir = current_app.config["LOL_IMAGES_DIR"]
        upload_dir = images_dir / upload_subdir
        upload_dir.mkdir(parents=True, exist_ok=True)
        normalized_tags = sorted(set(
            str(tag or "").strip().lower().replace(" ", "_")
            for tag in (tags or [])
            if str(tag or "").strip()
        ))
        catalog = load_image_catalog()
        existing_ref = find_catalog_ref_by_content_hash(catalog, content_hash)
        if existing_ref:
            catalog[existing_ref] = merge_image_catalog_metadata(
                existing=image_catalog_entry_for_ref(catalog, existing_ref),
                friendly_name=str(friendly_name or "").strip(),
                tags=normalized_tags,
                description=str(notes or "").strip(),
                content_hash=content_hash,
            )
            save_image_catalog(catalog)
            existing_path = resolve_image_ref_path(existing_ref)
            return {
                "path": existing_ref,
                "url": f"/images/{existing_ref}",
                "name": existing_path.name,
                "friendly_name": str((catalog.get(existing_ref) or {}).get("friendly_name") or friendly_name or "").strip(),
                "tags": [str(x) for x in ((catalog.get(existing_ref) or {}).get("tags") or []) if str(x).strip()],
                "description": str((catalog.get(existing_ref) or {}).get("description") or notes or "").strip(),
                "attached_to": list((catalog.get(existing_ref) or {}).get("attached_to") or []),
            }

        safe_name = secure_filename(friendly_name or "")
        stem = Path(safe_name).stem or "ai_generate"
        final_name = f"{stem}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}{suffix}"
        path = upload_dir / final_name
        path.write_bytes(decoded)

        rel = str(path.relative_to(images_dir)).replace("\\", "/")
        catalog[rel] = merge_image_catalog_metadata(
            existing=image_catalog_entry_for_ref(catalog, rel),
            friendly_name=str(friendly_name or "").strip(),
            tags=normalized_tags,
            description=str(notes or "").strip(),
            content_hash=content_hash,
        )
        save_image_catalog(catalog)
        return {
            "path": rel,
            "url": f"/images/{rel}",
            "name": path.name,
            "friendly_name": str(friendly_name or "").strip(),
            "tags": normalized_tags,
            "description": str(notes or "").strip(),
            "attached_to": list((catalog.get(rel) or {}).get("attached_to") or []),
        }

    def _build_vector_context(query: str, *, compendium_id: str = "", compendium_ids: list[str] | None = None, k: int = 8) -> tuple[list[dict], list[dict], str]:
        selected_ids = [str(cid or "").strip().lower() for cid in (compendium_ids or []) if str(cid or "").strip()]
        selected_ids = list(dict.fromkeys(selected_ids))
        solo_id = str(compendium_id or "").strip().lower()
        if solo_id and solo_id not in selected_ids:
            selected_ids.append(solo_id)

        def source_priority(row: dict) -> tuple[int, float]:
            cid = str(row.get("compendium_id") or "").strip().lower()
            if cid == "local_library":
                return (0, -float(row.get("score") or 0.0))
            return (2, -float(row.get("score") or 0.0))

        try:
            if selected_ids:
                merged_items: list[dict] = []
                seen_keys: set[str] = set()
                for cid in selected_ids:
                    vec_part = vector_query_index(
                        output_root=vector_index_root(),
                        query=query,
                        k=k,
                        compendium_id=cid,
                    )
                    part_items = vec_part.get("items") if isinstance(vec_part, dict) else []
                    part_items = part_items if isinstance(part_items, list) else []
                    for item in part_items:
                        if not isinstance(item, dict):
                            continue
                        key = (
                            f"{str(item.get('compendium_id') or '')}|"
                            f"{str(item.get('source_path') or '')}|"
                            f"{str(item.get('heading') or '')}|"
                            f"{str(item.get('text') or '')[:160]}"
                        )
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        merged_items.append(item)
                merged_items.sort(key=source_priority)
                items = merged_items[:k]
            else:
                vec = vector_query_index(
                    output_root=vector_index_root(),
                    query=query,
                    k=k,
                    compendium_id=solo_id,
                )
                part_items = vec.get("items") if isinstance(vec, dict) else []
                items = part_items if isinstance(part_items, list) else []
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise ValueError(f"vector query failed: {exc}") from exc

        citations = []
        context_lines = []
        for idx, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            compendium_id = str(item.get("compendium_id") or "").strip()
            source_path = str(item.get("source_path") or "").strip()
            heading = str(item.get("heading") or "").strip()
            snippet = str(item.get("text") or "").strip()
            score = float(item.get("score") or 0.0)
            citations.append({
                "n": idx,
                "compendium_id": compendium_id,
                "source_path": source_path,
                "heading": heading,
                "score": score,
            })
            source_label = "local_lore" if compendium_id == "local_library" else compendium_id or "unknown"
            context_lines.append(f"[{idx}] compendium={source_label} source={source_path} heading={heading}\n{snippet}")

        grounded_context = "\n\n".join(context_lines) if context_lines else "No vector context available."
        return items, citations, grounded_context

    def _build_lore_context(
        query: str,
        *,
        setting: str = "",
        location: str = "",
        k: int = 4,
        focus_type: str = "",
    ) -> tuple[list[dict], list[dict], str]:
        lore_dir = current_app.config["LOL_LORE_DIR"]
        config_dir = current_app.config["LOL_CONFIG_DIR"]

        def ai_lore_focus_priorities(value: str) -> dict[str, int]:
            token = str(value or "").strip().lower()
            base = {"race": 40, "area": 30, "doctrine": 20, "role": 25}
            if token in {"npc", "creature"}:
                return {"race": 100, "role": 90, "area": 60, "doctrine": 35}
            if token == "player_character":
                return {"race": 100, "role": 95, "area": 55, "doctrine": 30}
            if token in {"settlement", "inn", "landmark", "location"}:
                return {"area": 100, "doctrine": 45, "role": 35, "race": 25}
            if token in {"lore", "religion", "myth", "faction", "doctrine"}:
                return {"doctrine": 100, "area": 75, "race": 35, "role": 30}
            if token in {"encounter"}:
                return {"area": 90, "role": 70, "race": 60, "doctrine": 35}
            return base

        def lore_blob(item: dict) -> str:
            if not isinstance(item, dict):
                return ""
            source_kind = str(item.get("source") or "").strip().lower()
            full_item = item
            if source_kind != "ai_lore":
                slug = str(item.get("slug") or "").strip()
                if slug:
                    try:
                        loaded = load_lore_item(lore_dir, slug, default_settings=configured_default_settings())
                        if isinstance(loaded, dict):
                            full_item = loaded
                    except Exception:
                        full_item = item
            return " ".join([
                str(full_item.get("title", "")),
                str(full_item.get("description", "")),
                str(full_item.get("excerpt", "")),
                str(full_item.get("content_markdown", "")),
                " ".join(full_item.get("categories", []) or []),
                " ".join(full_item.get("settings", []) or []),
                str(full_item.get("location", "")),
                str(full_item.get("location_type", "")),
                str(full_item.get("area", "")),
                str(full_item.get("source_path", "")),
            ]).strip()

        try:
            ai_lore_matches = search_ai_lore(
                lore_dir,
                query=query,
                config_dir=config_dir,
                setting=setting,
                location=location,
                default_settings=configured_default_settings(),
            ) or []
            direct_matches = search_lore(
                lore_dir,
                query=query,
                setting=setting,
                location=location,
                default_settings=configured_default_settings(),
            ) or []
            if ai_lore_matches or direct_matches:
                ai_focus = ai_lore_focus_priorities(focus_type)
                def ai_lore_sort_key(item: dict) -> tuple[int, str]:
                    kind = str(item.get("ai_lore_kind") or "").strip().lower()
                    title = str(item.get("title") or "").strip().lower()
                    return (-int(ai_focus.get(kind, 0)), title)
                ai_lore_matches = sorted(ai_lore_matches, key=ai_lore_sort_key)
                lore_items = ai_lore_matches + [
                    item for item in direct_matches
                    if str(item.get("slug") or "").strip() not in {
                        str(ai_item.get("slug") or "").strip() for ai_item in ai_lore_matches
                    }
                ]
            else:
                stopwords = {
                    "a", "an", "and", "are", "as", "at", "about", "be", "by", "for", "from", "how",
                    "in", "into", "is", "it", "me", "of", "on", "or", "tell", "that", "the", "their",
                    "there", "they", "this", "to", "what", "where", "who",
                }
                query_tokens = [
                    token for token in re.findall(r"[a-z0-9_]+", str(query or "").lower())
                    if len(token) >= 3 and token not in stopwords
                ]
                scored_items: list[tuple[int, dict]] = []
                for item in list_lore_items(lore_dir, default_settings=configured_default_settings()):
                    if not isinstance(item, dict):
                        continue
                    item_settings = [
                        str(value or "").strip().lower()
                        for value in (item.get("settings") or [])
                        if str(value or "").strip()
                    ]
                    if setting and str(setting).strip().lower() not in item_settings:
                        continue
                    item_location = " ".join([
                        str(item.get("location") or ""),
                        str(item.get("title") or ""),
                        str(item.get("area") or ""),
                    ]).strip().lower()
                    if location and str(location).strip().lower() not in item_location:
                        continue
                    hay = lore_blob(item).lower()
                    score = 0
                    for token in query_tokens:
                        if token in hay:
                            score += 3 if token in str(item.get("title", "")).lower() else 1
                    if score > 0:
                        scored_items.append((score, item))
                scored_items.sort(key=lambda row: row[0], reverse=True)
                lore_items = ai_lore_matches + [item for _, item in scored_items]
        except Exception:
            lore_items = []

        def ai_lore_section_label(item: dict) -> str:
            kind = str(item.get("ai_lore_kind") or "").strip().lower()
            return {
                "race": "Race Guide",
                "area": "Area Guide",
                "doctrine": "Doctrine Guide",
                "role": "Role Guide",
            }.get(kind, "AI Lore Guide")

        max_items = max(0, int(k or 0))
        if max_items and any(str(item.get("source") or "").strip().lower() == "ai_lore" for item in lore_items):
            ai_focus = ai_lore_focus_priorities(focus_type)
            ai_lore_matches = [item for item in lore_items if str(item.get("source") or "").strip().lower() == "ai_lore"]
            plain_lore_matches = [item for item in lore_items if str(item.get("source") or "").strip().lower() != "ai_lore"]
            ai_target = min(len(ai_lore_matches), max(2, max_items // 2))
            grouped_ai: dict[str, list[dict]] = {}
            for item in ai_lore_matches:
                grouped_ai.setdefault(str(item.get("ai_lore_kind") or "").strip().lower(), []).append(item)
            selected_items: list[dict] = []
            for section_name in sorted(grouped_ai.keys(), key=lambda kind: -int(ai_focus.get(kind, 0))):
                if len(selected_items) >= ai_target:
                    break
                section_items = grouped_ai.get(section_name) or []
                if section_items:
                    selected_items.append(section_items[0])
            for item in ai_lore_matches:
                if len(selected_items) >= ai_target:
                    break
                if item not in selected_items:
                    selected_items.append(item)
            remaining_slots = max_items - len(selected_items)
            if remaining_slots > 0:
                selected_items.extend(plain_lore_matches[:remaining_slots])
        else:
            selected_items = lore_items[:max_items]
        citations: list[dict] = []
        ai_lore_sections: dict[str, list[str]] = {}
        plain_context_lines: list[str] = []
        normalized_items: list[dict] = []
        for idx, item in enumerate(selected_items, start=1):
            if not isinstance(item, dict):
                continue
            slug = str(item.get("slug") or "").strip()
            title = str(item.get("title") or item.get("name") or slug or f"Lore {idx}").strip()
            full_blob = lore_blob(item)
            snippet = re.sub(r"\s+", " ", full_blob).strip()
            if len(snippet) > 1600:
                snippet = f"{snippet[:1597].rstrip()}..."
            source_path = str(item.get("source_path") or "").strip()
            if not source_path:
                source_path = f"/lore/{slug}" if slug else "/lore"
            compendium_id = "ai_lore" if str(item.get("source") or "").strip().lower() == "ai_lore" else "lore"
            citations.append({
                "n": idx,
                "compendium_id": compendium_id,
                "source_path": source_path,
                "heading": title,
                "score": 1.0,
            })
            context_line = f"[L{idx}] source={source_path} heading={title}\n{snippet}"
            if compendium_id == "ai_lore":
                section = ai_lore_section_label(item)
                ai_lore_sections.setdefault(section, []).append(context_line)
            else:
                plain_context_lines.append(context_line)
            normalized_items.append({
                "compendium_id": compendium_id,
                "source_path": source_path,
                "heading": title,
                "text": snippet,
                "score": 1.0,
            })

        context_lines: list[str] = []
        for section_name in ["Race Guide", "Area Guide", "Doctrine Guide", "Role Guide", "AI Lore Guide"]:
            section_lines = ai_lore_sections.get(section_name) or []
            if section_lines:
                context_lines.append(f"{section_name}:\n" + "\n\n".join(section_lines))
        context_lines.extend(plain_context_lines)
        grounded_context = "\n\n".join(context_lines) if context_lines else "No lore context available."
        return normalized_items, citations, grounded_context

    def _ai_generate_allowed_compendium_ids(requested_ids: list[str] | None, *, setting_id: str = "") -> list[str]:
        config_dir = current_app.config["LOL_CONFIG_DIR"]
        active_setting = _safe_slug(setting_id or current_app.config.get("LOL_SETTING_ID") or current_app.config.get("LOL_WORLD_ID") or "")
        active_genre = _safe_slug(infer_core_genre_for_setting(config_dir, active_setting) or active_setting)
        allowed: list[str] = []
        if active_setting:
            allowed.append("local_library")
        profiles = load_compendium_profiles()
        for cid in ["csrd", "core_rulebook"]:
            if cid == "csrd" or cid in profiles:
                if cid not in allowed:
                    allowed.append(cid)
        for cid, profile in profiles.items():
            compendium_id = str(cid or "").strip().lower()
            if not compendium_id or compendium_id in {"csrd", FOUNDRY_COMPENDIUM_ID}:
                continue
            source_kind = compendium_source_kind(compendium_id, profile)
            if source_kind not in {"official", "core_pdf"}:
                continue
            tags = compendium_taxonomy_tags(profile, source_kind=source_kind, compendium_id=compendium_id)
            tag_genre = _safe_slug(str(tags.get("genre") or "").strip().lower())
            tag_setting = _safe_slug(str(tags.get("setting") or "").strip().lower())
            if (active_genre and tag_genre == active_genre) or (active_setting and tag_setting == active_setting):
                if compendium_id not in allowed:
                    allowed.append(compendium_id)
        if requested_ids is None:
            return allowed
        return [cid for cid in requested_ids if cid in allowed]

    def _ai_generate_setting_config(setting_id: str = "") -> dict:
        config_dir = current_app.config["LOL_CONFIG_DIR"]
        active_setting = _safe_slug(setting_id or current_app.config.get("LOL_SETTING_ID") or current_app.config.get("LOL_WORLD_ID") or "")
        if active_setting:
            try:
                return load_config_dir(config_dir, setting_id=active_setting)
            except Exception:
                pass
        return current_app.config.get("LOL_CONFIG", {}) or {}

    def _ai_generate_identity_vocab(*, setting_id: str = "", area_id: str = "") -> dict[str, object]:
        config = _ai_generate_setting_config(setting_id)
        races_obj = config.get("races") if isinstance(config.get("races"), dict) else {}
        professions_obj = config.get("professions") if isinstance(config.get("professions"), dict) else {}
        areas_obj = config.get("areas") if isinstance(config.get("areas"), dict) else {}

        races = sorted(str(key).strip() for key in races_obj.keys() if str(key).strip())
        professions = sorted(str(key).strip() for key in professions_obj.keys() if str(key).strip())
        variants_by_race: dict[str, list[str]] = {}
        variant_to_race: dict[str, str] = {}
        cultures: set[str] = set()

        for race_key, race_value in races_obj.items():
            race_id = str(race_key or "").strip()
            if not race_id:
                continue
            cultures.add(race_id)
            variants_obj = race_value.get("variants") if isinstance(race_value, dict) and isinstance(race_value.get("variants"), dict) else {}
            variant_ids = sorted(str(key).strip() for key in variants_obj.keys() if str(key).strip())
            variants_by_race[race_id] = variant_ids
            for variant_id in variant_ids:
                variant_to_race[_safe_slug(variant_id)] = race_id
                cultures.add(variant_id)

        for area_value in areas_obj.values():
            if not isinstance(area_value, dict):
                continue
            culture_id = str(area_value.get("culture") or "").strip()
            if culture_id:
                cultures.add(culture_id)

        area_culture = ""
        area_id_norm = str(area_id or "").strip()
        if area_id_norm and isinstance(areas_obj.get(area_id_norm), dict):
            area_culture = str(areas_obj[area_id_norm].get("culture") or "").strip()

        return {
            "races": races,
            "professions": professions,
            "variants_by_race": variants_by_race,
            "variant_to_race": variant_to_race,
            "cultures": sorted(culture for culture in cultures if culture),
            "area_culture": area_culture,
        }

    def _ai_generate_place_name_vocab(*, setting_id: str = "", area_id: str = "") -> dict[str, object]:
        config = _ai_generate_setting_config(setting_id)
        names_obj = config.get("names") if isinstance(config.get("names"), dict) else {}
        settlement_names_obj = names_obj.get("settlement_names") if isinstance(names_obj.get("settlement_names"), dict) else {}
        inn_names_obj = names_obj.get("inn_names") if isinstance(names_obj.get("inn_names"), dict) else {}
        identity_vocab = _ai_generate_identity_vocab(setting_id=setting_id, area_id=area_id)
        area_culture = str(identity_vocab.get("area_culture") or "").strip()

        def flatten_name_values(source: object) -> list[str]:
            values: list[str] = []
            if isinstance(source, list):
                values.extend(str(item).strip() for item in source if str(item).strip())
            elif isinstance(source, dict):
                for item in source.values():
                    values.extend(flatten_name_values(item))
            elif isinstance(source, str) and str(source).strip():
                values.append(str(source).strip())
            return values

        def names_for_culture(source_obj: dict[str, object], culture_id: str) -> list[str]:
            if not culture_id:
                return []
            for key, value in source_obj.items():
                if _safe_slug(key) == _safe_slug(culture_id):
                    return flatten_name_values(value)[:12]
            return []

        return {
            "area_culture": area_culture,
            "settlement_names": names_for_culture(settlement_names_obj, area_culture),
            "inn_names": names_for_culture(inn_names_obj, area_culture),
        }

    def _ai_generate_match_allowed_value(raw_value: str, allowed_values: list[str]) -> str:
        raw = str(raw_value or "").strip()
        if not raw:
            return ""
        raw_slug = _safe_slug(raw)
        for allowed in allowed_values:
            if raw_slug == _safe_slug(allowed):
                return allowed
        return ""

    def _ai_generate_apply_identity_aliases(*, race: str = "", variant: str = "", profession: str = "", culture: str = "") -> dict[str, str]:
        race_slug = _safe_slug(race)
        variant_slug = _safe_slug(variant)
        profession_slug = _safe_slug(profession)
        culture_slug = _safe_slug(culture)

        race_aliases = {
            "elf": {"race": "alfirin"},
            "high_elf": {"race": "alfirin", "variant": "sky_children", "culture": "alfirin"},
            "sun_elf": {"race": "alfirin", "variant": "sky_children", "culture": "alfirin"},
            "wood_elf": {"race": "alfirin", "variant": "galadhrim", "culture": "alfirin_galadhrim"},
            "forest_elf": {"race": "alfirin", "variant": "galadhrim", "culture": "alfirin_galadhrim"},
            "dark_elf": {"race": "alfirin", "variant": "duathrim", "culture": "alfirin_duathrim"},
            "shadow_elf": {"race": "alfirin", "variant": "duathrim", "culture": "alfirin_duathrim"},
            "shadowed_elf": {"race": "alfirin", "variant": "duathrim", "culture": "alfirin_duathrim"},
            "drow": {"race": "alfirin", "variant": "duathrim", "culture": "alfirin_duathrim"},
            "sea_elf": {"race": "alfirin", "variant": "falthrim", "culture": "falthrim"},
        }
        culture_aliases = {
            "umbral_elves": {"race": "alfirin", "variant": "duathrim", "culture": "alfirin_duathrim"},
            "umbral_kin": {"race": "alfirin", "variant": "duathrim", "culture": "alfirin_duathrim"},
            "shadowed_kin": {"race": "alfirin", "variant": "duathrim", "culture": "alfirin_duathrim"},
            "forest_kin": {"race": "alfirin", "variant": "galadhrim", "culture": "alfirin_galadhrim"},
        }
        profession_aliases = {
            "rogue": "thief",
            "ranger": "hunter",
            "barbarian": "warrior",
        }

        result = {"race": race, "variant": variant, "profession": profession, "culture": culture}
        if race_slug in race_aliases:
            result.update({key: value for key, value in race_aliases[race_slug].items() if value})
        if variant_slug in race_aliases:
            result.update({key: value for key, value in race_aliases[variant_slug].items() if value})
        if culture_slug in culture_aliases:
            result.update({key: value for key, value in culture_aliases[culture_slug].items() if value})
        if profession_slug in profession_aliases:
            result["profession"] = profession_aliases[profession_slug]
        return result

    def _ai_generate_parse_int(raw_value, *, minimum: int | None = None, maximum: int | None = None) -> int | None:
        if raw_value is None:
            return None
        if isinstance(raw_value, bool):
            value = int(raw_value)
        elif isinstance(raw_value, (int, float)):
            value = int(raw_value)
        else:
            match = re.search(r"-?\d+", str(raw_value or "").strip())
            if not match:
                return None
            value = int(match.group(0))
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    def _normalize_ai_generated_identity_fields(
        card: dict,
        *,
        content_type: str = "",
        setting_id: str = "",
        area_id: str = "",
        generation_preferences: dict[str, str] | None = None,
    ) -> dict:
        if not isinstance(card, dict):
            return card
        prefs = generation_preferences or {}
        vocab = _ai_generate_identity_vocab(setting_id=setting_id, area_id=area_id)
        allowed_races = [str(x) for x in vocab.get("races", []) if str(x)]
        allowed_professions = [str(x) for x in vocab.get("professions", []) if str(x)]
        variants_by_race = vocab.get("variants_by_race", {}) if isinstance(vocab.get("variants_by_race"), dict) else {}
        variant_to_race = vocab.get("variant_to_race", {}) if isinstance(vocab.get("variant_to_race"), dict) else {}
        allowed_cultures = [str(x) for x in vocab.get("cultures", []) if str(x)]
        area_culture = str(vocab.get("area_culture") or "").strip()

        raw_race = str(card.get("race") or "").strip()
        raw_variant = str(card.get("variant") or "").strip()
        raw_profession = str(card.get("profession") or "").strip()
        raw_culture = str(card.get("culture") or "").strip()
        aliased = _ai_generate_apply_identity_aliases(
            race=raw_race,
            variant=raw_variant,
            profession=raw_profession,
            culture=raw_culture,
        )

        race = _ai_generate_match_allowed_value(str(prefs.get("race") or "").strip(), allowed_races)
        if not race:
            race = _ai_generate_match_allowed_value(aliased.get("race") or raw_race, allowed_races)
        if not race and raw_variant:
            mapped_race = str(variant_to_race.get(_safe_slug(aliased.get("variant") or raw_variant)) or "")
            if mapped_race in allowed_races:
                race = mapped_race

        allowed_variants = [str(x) for x in variants_by_race.get(race, []) if str(x)] if race else []
        variant = _ai_generate_match_allowed_value(str(prefs.get("variant") or "").strip(), allowed_variants)
        if not variant:
            variant = _ai_generate_match_allowed_value(aliased.get("variant") or raw_variant, allowed_variants)

        profession = _ai_generate_match_allowed_value(str(prefs.get("profession") or "").strip(), allowed_professions)
        if not profession:
            profession = _ai_generate_match_allowed_value(aliased.get("profession") or raw_profession, allowed_professions)
        if not profession and str(content_type or "").strip().lower() == "npc":
            profession = str(prefs.get("profession") or "").strip()
        if not profession and str(content_type or "").strip().lower() == "npc":
            profession = str(aliased.get("profession") or raw_profession or "").strip()

        culture = _ai_generate_match_allowed_value(str(prefs.get("culture") or "").strip(), allowed_cultures)
        if not culture:
            culture = _ai_generate_match_allowed_value(aliased.get("culture") or raw_culture, allowed_cultures)
        if not culture and area_culture and area_culture not in {"mixed", "unknown", "ancient"}:
            culture = area_culture
        if not culture and variant:
            culture = _ai_generate_match_allowed_value(variant, allowed_cultures)
        if not culture and race:
            culture = _ai_generate_match_allowed_value(race, allowed_cultures)

        next_card = dict(card)
        next_card["race"] = race
        next_card["variant"] = variant
        next_card["profession"] = profession
        next_card["culture"] = culture
        return next_card

    def _ai_generate_role_hint(card: dict) -> str:
        if not isinstance(card, dict):
            return ""
        parts = [
            str(card.get("profession") or "").strip(),
            str(card.get("motive") or "").strip(),
            str(card.get("combat") or "").strip(),
            str(card.get("description") or "").strip(),
            str(card.get("interaction") or "").strip(),
        ]
        return " ".join(part for part in parts if part).lower()

    def _normalize_ai_generated_modifications(card: dict, *, content_type: str) -> dict:
        if not isinstance(card, dict):
            return card
        if content_type not in {"npc", "creature"}:
            return card
        level = _ai_generate_parse_int(card.get("level"), minimum=1, maximum=10)
        raw_mods = card.get("modifications")
        if not raw_mods:
            return card

        if isinstance(raw_mods, list):
            mod_items = [str(item or "").strip() for item in raw_mods if str(item or "").strip()]
            join_back_as_list = True
        else:
            text = str(raw_mods or "").strip()
            mod_items = [part.strip() for part in re.split(r"\s*;\s*|\s*,\s*(?=[A-Za-z])", text) if part.strip()]
            join_back_as_list = False

        role_hint = _ai_generate_role_hint(card)
        severe_cues = {"stern", "grim", "cold", "harsh", "cruel", "threat", "menacing", "evil", "ruthless", "zealot", "fanatic"}
        filtered: list[str] = []
        for item in mod_items:
            item_text = str(item or "").strip()
            item_lower = item_text.lower()
            mod_level = _ai_generate_parse_int(item_text, minimum=1, maximum=10)
            if level is not None and mod_level is not None and mod_level <= level and " as level " in item_lower:
                if any(term in item_lower for term in ["pleasant interaction", "interaction", "persuasion", "charm", "deception"]):
                    continue
            if "pleasant interaction" in item_lower and any(cue in role_hint for cue in severe_cues):
                continue
            filtered.append(item_text)

        next_card = dict(card)
        if join_back_as_list:
            next_card["modifications"] = filtered
        else:
            next_card["modifications"] = "; ".join(filtered)
        return next_card

    def _normalize_ai_generated_cypher_stats(card: dict, *, content_type: str) -> dict:
        if not isinstance(card, dict):
            return card
        next_card = dict(card)
        level = _ai_generate_parse_int(next_card.get("level"), minimum=1, maximum=10)
        if level is None and content_type == "npc":
            role_hint = _ai_generate_role_hint(next_card)
            if any(token in role_hint for token in ["captain", "priest", "witch", "judge", "mayor", "scholar", "veteran"]):
                level = 3
            else:
                level = 2
        if level is not None:
            next_card["level"] = level
        if content_type not in {"npc", "creature"}:
            return next_card

        next_card["armor"] = _ai_generate_parse_int(next_card.get("armor"), minimum=0, maximum=5) or 0

        damage = _ai_generate_parse_int(next_card.get("damage_inflicted"), minimum=1, maximum=12)
        if damage is None and level is not None:
            damage = max(1, min(10, level))
        if damage is not None:
            next_card["damage_inflicted"] = damage

        health = _ai_generate_parse_int(next_card.get("health"), minimum=1, maximum=60)
        if level is not None:
            role_hint = _ai_generate_role_hint(next_card)
            target_health = level * 3
            if any(token in role_hint for token in ["thief", "burglar", "scout", "hunter", "assassin", "shadowblade", "stealth", "ambush"]):
                target_health -= 2
            elif any(token in role_hint for token in ["guard", "soldier", "warrior", "knight", "champion", "paladin"]):
                target_health += 2
            elif any(token in role_hint for token in ["wizard", "witch", "priest", "oracle", "seer", "mystic"]):
                target_health -= 1
            target_health = max(3, min(60, target_health))
            min_health = max(1, target_health - 2)
            max_health = min(60, target_health + 2)
            health = target_health if health is None else max(min_health, min(max_health, health))
        if health is not None:
            next_card["health"] = health
        if not str(next_card.get("movement") or "").strip():
            next_card["movement"] = "Short"
        return next_card

    def _normalize_ai_generated_settlement_fields(card: dict) -> dict:
        if not isinstance(card, dict):
            return card
        next_card = dict(card)
        description_text = str(
            next_card.get("description")
            or next_card.get("summary")
            or ""
        ).strip()
        notable_features_raw = next_card.get("notable_features")
        notable_features: list[dict[str, str]] = []
        if isinstance(notable_features_raw, list):
            for item in notable_features_raw:
                if isinstance(item, dict):
                    name = str(item.get("name") or item.get("title") or "").strip()
                    description = str(item.get("description") or item.get("summary") or "").strip()
                    if name or description:
                        notable_features.append({"name": name, "description": description})
                elif str(item or "").strip():
                    notable_features.append({"name": str(item).strip(), "description": ""})
        elif isinstance(notable_features_raw, dict):
            name = str(notable_features_raw.get("name") or notable_features_raw.get("title") or "").strip()
            description = str(notable_features_raw.get("description") or notable_features_raw.get("summary") or "").strip()
            if name or description:
                notable_features.append({"name": name, "description": description})

        environment = str(next_card.get("environment") or next_card.get("area") or "").strip()
        area = str(next_card.get("area") or environment).strip()
        location = str(next_card.get("location") or "").strip()
        economy = str(next_card.get("economy_survival_basis") or next_card.get("economy") or "").strip()
        tension = str(next_card.get("current_tension") or next_card.get("tension") or "").strip()
        landmark = str(next_card.get("landmark") or "").strip()
        local_inn = str(next_card.get("local_inn_or_tavern") or next_card.get("inn") or next_card.get("tavern") or "").strip()
        visual_feature = str(next_card.get("visual_feature") or "").strip()
        governance = str(next_card.get("governance") or "").strip()
        atmosphere = str(next_card.get("atmosphere") or "").strip()
        settlement_type = str(next_card.get("settlement_type") or "").strip()
        proprietor = str(next_card.get("proprietor") or next_card.get("innkeeper") or next_card.get("owner") or "").strip()
        population = next_card.get("population")

        if description_text:
            lower_desc = description_text.lower()
            if not settlement_type:
                if "village" in lower_desc:
                    settlement_type = "village"
                elif "city" in lower_desc:
                    settlement_type = "city"
                elif any(token in lower_desc for token in ["settlement", "hamlet", "outpost", "steading"]):
                    settlement_type = "settlement"
            if not local_inn:
                inn_match = re.search(r"\b(The [A-Z][A-Za-z' -]+)\b", description_text)
                if inn_match:
                    candidate = str(inn_match.group(1) or "").strip()
                    if re.search(r"\b(inn|tavern|pick|trout|arms|roost|house|kraken|cup|boar|stag|lion|anchor|harp|forge)\b", candidate, re.IGNORECASE):
                        local_inn = candidate
            if not proprietor:
                proprietor_match = re.search(r"\bis run by\s+([A-Z][A-Za-z' -]+?)(?:,|\swho\b|\sand\b|\.)", description_text, re.IGNORECASE)
                if proprietor_match:
                    proprietor = str(proprietor_match.group(1) or "").strip()

        if not landmark:
            inn_patterns = ("inn", "tavern", "roadhouse", "hostel", "public house")
            for item in notable_features:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                if any(token in name.lower() for token in inn_patterns):
                    if not local_inn:
                        local_inn = name
                    continue
                landmark = name
                break

        if not local_inn:
            inn_patterns = ("inn", "tavern", "roadhouse", "hostel", "public house")
            for item in notable_features:
                name = str(item.get("name") or "").strip()
                if name and any(token in name.lower() for token in inn_patterns):
                    local_inn = name
                    break

        if not visual_feature and notable_features:
            visual_feature = str(notable_features[0].get("name") or "").strip()

        next_card["type"] = "settlement"
        if area:
            next_card["area"] = area
            next_card["environment"] = environment or area
        if location:
            next_card["location"] = location
        if settlement_type:
            next_card["settlement_type"] = settlement_type
        if atmosphere:
            next_card["atmosphere"] = atmosphere
        if visual_feature:
            next_card["visual_feature"] = visual_feature
        if landmark:
            next_card["landmark"] = landmark
        if local_inn:
            next_card["local_inn_or_tavern"] = local_inn
        if proprietor:
            next_card["proprietor"] = proprietor
            next_card["innkeeper"] = proprietor
        if economy:
            next_card["economy_survival_basis"] = economy
            next_card["economy"] = economy
        if tension:
            next_card["current_tension"] = tension
        if governance:
            next_card["governance"] = governance
        if population not in {None, ""}:
            next_card["population"] = population
        if notable_features:
            next_card["notable_features"] = notable_features
        return next_card

    def _normalize_ai_generated_card(
        card: dict,
        *,
        content_type: str,
        setting_id: str = "",
        area_id: str = "",
        generation_preferences: dict[str, str] | None = None,
    ) -> dict:
        if not isinstance(card, dict):
            return card
        next_card = dict(card)
        if content_type in {"npc", "player_character"}:
            next_card = _normalize_ai_generated_identity_fields(
                next_card,
                content_type=content_type,
                setting_id=setting_id,
                area_id=area_id,
                generation_preferences=generation_preferences,
            )
        if content_type in {"npc", "creature"}:
            next_card = _normalize_ai_generated_cypher_stats(next_card, content_type=content_type)
            next_card = _normalize_ai_generated_modifications(next_card, content_type=content_type)
        if content_type == "settlement":
            next_card = _normalize_ai_generated_settlement_fields(next_card)
        return next_card

    def _ai_generate_prompt(
        *,
        content_type: str,
        schema: dict | None,
        brief: str,
        allowed_compendium_ids: list[str],
        image_supplied: bool,
        generation_preferences: dict[str, str] | None = None,
        setting_id: str = "",
        area_id: str = "",
        location_id: str = "",
        sourcebook_id: str = "",
        recent_examples: dict[str, list[str]] | None = None,
    ) -> str:
        ctype = str(content_type or "free_text").strip().lower()
        schema_text = json.dumps(schema or {}, indent=2, ensure_ascii=False)
        prefs = generation_preferences or {}
        identity_vocab = _ai_generate_identity_vocab(setting_id=setting_id, area_id=area_id)
        place_name_vocab = _ai_generate_place_name_vocab(setting_id=setting_id, area_id=area_id)
        recent = recent_examples or {}
        prompt_lines = [
            f"Generate Cypher System content of type: {ctype.replace('_', ' ').title()}.",
            "Return ONLY a valid JSON object.",
            "Do not include markdown fences, commentary, or any text outside JSON.",
            "JSON MUST include an explicit `type` field.",
            "If the user brief explicitly provides a name for a person, place, inn, settlement, or other generated entity, preserve that exact name in the returned `name` field unless the user explicitly asks for variants.",
            "Use Cypher System conventions, not D&D, Pathfinder, or 5e conventions.",
            "Do not output D&D-style classes, AC logic, hit dice, proficiency bonuses, challenge ratings, spell slots, or dice-form damage expressions such as `1d8+2` for NPCs or creatures.",
            "For Cypher NPCs and creatures, `level` should anchor the statline, `armor` should normally be a small numeric value, and `damage_inflicted` should normally be a flat numeric value rather than a die roll.",
            "Keep health, armor, and damage in tune with Cypher expectations for the chosen level and role instead of inflating them with off-system fantasy assumptions.",
            "Write richer descriptions by default: usually 3-6 sentences with concrete sensory/world details.",
            "For `description` fields, avoid one-liners unless the user explicitly asks for brevity.",
            "Avoid stock fantasy openings and repeated phrasing such as `is a striking figure`, `piercing gaze`, or other canned portrait-description filler.",
            "Vary sentence openings and lead with specific local, visual, or behavioral details instead of generic fantasy admiration language.",
            "Treat retrieved local lore as the highest-priority grounding for names, places, factions, history, materials, customs, and tone.",
            "If local lore and broader compendium material differ, prefer the local lore unless the user explicitly asks otherwise.",
            "Use broader compendium knowledge only to support or extend the local lore, not to overwrite it with generic content.",
            "When the context is thin, make restrained inferences that still feel consistent with the local lore and current setting.",
        ]
        if setting_id or area_id or location_id or sourcebook_id:
            prompt_lines.append(
                f"Current generation context: setting={setting_id or '(none)'}, area={area_id or '(none)'}, location={location_id or '(none)'}, sourcebook={sourcebook_id or '(none)' }."
            )
        selected_identity = []
        for key in ["race", "variant", "profession", "culture"]:
            value = str(prefs.get(key) or "").strip()
            if value:
                selected_identity.append(f"{key}={value}")
        if selected_identity:
            prompt_lines.append(f"Selected identity anchors: {', '.join(selected_identity)}.")
            prompt_lines.append("Use these selected identity anchors to pull in the matching local lore, naming patterns, religious context, and social details rather than treating them as cosmetic tags.")
        recent_names = [str(x).strip() for x in (recent.get("names") or []) if str(x).strip()]
        recent_name_roots = [str(x).strip() for x in (recent.get("name_roots") or []) if str(x).strip()]
        recent_surname_roots = [str(x).strip() for x in (recent.get("surname_roots") or []) if str(x).strip()]
        recent_openers = [str(x).strip() for x in (recent.get("description_openers") or []) if str(x).strip()]
        if recent_names:
            prompt_lines.append(f"Avoid reusing these recent names: {', '.join(recent_names[:12])}.")
        if recent_name_roots:
            prompt_lines.append(f"Avoid repeating these recent first names or name stems: {', '.join(recent_name_roots[:12])}.")
        if recent_surname_roots:
            prompt_lines.append(f"Avoid repeating these recent surnames or family-name stems: {', '.join(recent_surname_roots[:12])}.")
        if recent_openers:
            prompt_lines.append(f"Avoid repeating these recent description openings or beats: {'; '.join(recent_openers[:8])}.")
        if ctype == "landmark":
            prompt_lines.append("For landmark output, set `type` to `location` and include `location_category_type: \"landmark\"`.")
        if ctype in {"settlement", "inn"}:
            area_culture = str(place_name_vocab.get("area_culture") or "").strip()
            settlement_names = [str(x) for x in (place_name_vocab.get("settlement_names") or []) if str(x)]
            inn_names = [str(x) for x in (place_name_vocab.get("inn_names") or []) if str(x)]
            if area_culture:
                prompt_lines.append(f"Area culture for place naming and social texture: {area_culture}.")
            if settlement_names:
                prompt_lines.append(f"Use these culture-specific settlement naming examples as guidance, not a hard limit: {', '.join(settlement_names[:10])}.")
            if inn_names:
                prompt_lines.append(f"Use these culture-specific inn naming examples as guidance, not a hard limit: {', '.join(inn_names[:10])}.")
        if ctype == "npc":
            npc_pref_parts = []
            if str(prefs.get("race") or "").strip():
                npc_pref_parts.append(f"race: {prefs['race']}")
            if str(prefs.get("variant") or "").strip():
                npc_pref_parts.append(f"variant: {prefs['variant']}")
            if str(prefs.get("gender") or "").strip():
                npc_pref_parts.append(f"gender: {prefs['gender']}")
            if str(prefs.get("profession") or "").strip():
                npc_pref_parts.append(f"profession: {prefs['profession']}")
            if str(prefs.get("culture") or "").strip():
                npc_pref_parts.append(f"culture: {prefs['culture']}")
            if npc_pref_parts:
                prompt_lines.append(f"NPC generation preferences: {', '.join(npc_pref_parts)}.")
                prompt_lines.append("Honor these NPC preferences unless the user brief clearly asks for something else.")
            else:
                prompt_lines.append("If the user leaves race, gender, or profession unspecified and an image is supplied, infer the best-fit values from the portrait and local lore.")
            allowed_races = [str(x) for x in identity_vocab.get("races", []) if str(x)]
            allowed_professions = [str(x) for x in identity_vocab.get("professions", []) if str(x)]
            allowed_cultures = [str(x) for x in identity_vocab.get("cultures", []) if str(x)]
            variants_by_race = identity_vocab.get("variants_by_race", {}) if isinstance(identity_vocab.get("variants_by_race"), dict) else {}
            if allowed_races:
                prompt_lines.append(f"Allowed setting races: {', '.join(allowed_races)}.")
            variant_lines = []
            for race_key, variant_values in variants_by_race.items():
                if isinstance(variant_values, list) and variant_values:
                    variant_lines.append(f"{race_key}: {', '.join(str(v) for v in variant_values)}")
            if variant_lines:
                prompt_lines.append(f"Allowed race variants by race: {'; '.join(variant_lines)}.")
            if allowed_professions:
                prompt_lines.append(f"Common local professions and role labels: {', '.join(allowed_professions)}.")
            if allowed_cultures:
                prompt_lines.append(f"Allowed setting cultures/identities: {', '.join(allowed_cultures)}.")
            prompt_lines.append("Give NPCs proper in-setting personal names by default, not placeholder labels or trope names such as `Fox Lady`, `Mysterious Woman`, or `Dark Stranger` unless the user explicitly asks for an epithet-only figure.")
            prompt_lines.append("When local lore includes race- or culture-specific naming patterns, use those patterns instead of generic fantasy names plus stock epithets like `the Cunning`.")
            prompt_lines.append("When the brief does not specify an NPC name, invent a fresh personal name that is distinct from recent generated NPC names; do not reuse a recent innkeeper or tavernkeeper name unless the brief explicitly asks for that same person.")
            prompt_lines.append("When useful, include a `culture` field if the subject reads as belonging to a distinct local culture, ancestry branch, or regional tradition.")
            prompt_lines.append("For race, variant, profession, and culture, prefer explicit local-lore terms and setting-valid identities over generic fantasy defaults; do not invent unsupported ancestries or culture labels.")
            prompt_lines.append("For NPC professions specifically, you may use broader in-world social roles, trades, offices, titles, faith roles, military ranks, criminal callings, or occupational labels even when they are not part of the player-character profession list.")
            prompt_lines.append("If the portrait suggests a familiar fantasy trope but the local lore does not support that exact label, translate it into the nearest valid local race, variant, culture, or profession instead of using terms like dark elf, rogue, or assassin by default.")
            prompt_lines.append("If no valid local race, variant, profession, or culture can be supported, return an empty string for that field rather than inventing a new label.")
            prompt_lines.append("Do not infer thief, burglar, or similar stealth professions merely because the subject carries a dagger or wears dark clothing; rely on stronger contextual cues.")
            prompt_lines.append("Do not infer pleasant, charming, or kindly interaction modifiers merely because the subject is female, a priest, or well-dressed; demeanor must come from image evidence, local lore, and the written concept.")
            prompt_lines.append("If the portrait reads stern, severe, fanatical, cold, dangerous, or hostile, make the interaction notes and modifiers reflect that read instead of softening the subject into a pleasant counselor.")
            prompt_lines.append("Do not default innkeepers, tavernkeepers, or proprietors to 'prefers to avoid conflict' or 'uses wit to diffuse tensions among rowdy patrons' unless the brief, portrait, or lore explicitly supports that exact temperament.")
            prompt_lines.append("Use `modifications` only for meaningful deviations from the base level. Avoid redundant entries such as `pleasant interaction as level 5` on a level 5 NPC.")
            prompt_lines.append("NPC `armor` should be numeric, and `damage_inflicted` should usually be a flat numeric value tied to the NPC's level, weapons, and role.")
            prompt_lines.append("Keep NPC health in a believable Cypher range for the chosen level and concept rather than treating it like hit points from another system; level 5 NPCs should not all have the same health, and tougher or frailer roles should vary modestly around the norm.")
            prompt_lines.append("Choose NPC level to fit the concept, role, and lore; do not default to level 4 unless the idea truly reads as a solid mid-tier standard NPC.")
        if ctype == "creature":
            prompt_lines.extend([
                "Generate a non-player creature, beast, monster, horror, or animal threat rather than a social NPC.",
                "Choose creature level to fit the concept, role, and lore; do not default to level 4 unless the idea truly reads as a mid-tier standard threat.",
                "Keep creature stats Cypher-native: numeric armor, flat numeric `damage_inflicted`, and health that suits the level and resilience rather than another system's monster math.",
                "Use motive, environment, combat behavior, interaction pattern, use, and GM intrusion to make the creature table-ready.",
            ])
        if ctype == "inn":
            prompt_lines.extend([
                "Generate a real inn, tavern, roadhouse, hostel, or public house card, not a settlement or lore essay.",
                "If the brief specifies the inn's name, keep that exact inn name in the `name` field.",
                "Use a culturally grounded establishment name that fits the area's naming patterns rather than generic names like The Prancing Pony.",
                "If you include a `proprietor`, `innkeeper`, or owner figure inside the inn card and the brief does not explicitly name them, invent a fresh personal name that is distinct from recent generated innkeeper or proprietor names.",
                "Do not fall back to stock tavernkeeper names like Mira unless the brief or retrieved lore explicitly supports that exact person; prefer a culture-appropriate personal name that feels local to the current area.",
                "Do not default the proprietor to a genial conflict-diffuser who calms rowdy patrons with wit unless the brief or retrieved lore points there; vary proprietor temperament, methods, and flaws.",
                "Include atmosphere, clientele, a notable feature, proprietor, and a rumor or hook that connect naturally to the current settlement, area, and local lore.",
            ])
        if ctype == "player_character":
            pc_pref_parts = []
            if str(prefs.get("race") or "").strip():
                pc_pref_parts.append(f"race: {prefs['race']}")
            if str(prefs.get("variant") or "").strip():
                pc_pref_parts.append(f"variant: {prefs['variant']}")
            if str(prefs.get("gender") or "").strip():
                pc_pref_parts.append(f"gender: {prefs['gender']}")
            if str(prefs.get("profession") or "").strip():
                pc_pref_parts.append(f"profession: {prefs['profession']}")
            if str(prefs.get("culture") or "").strip():
                pc_pref_parts.append(f"culture: {prefs['culture']}")
            if pc_pref_parts:
                prompt_lines.append(f"Player character generation preferences: {', '.join(pc_pref_parts)}.")
                prompt_lines.append("Honor these player character preferences unless the user brief clearly asks for something else.")
            else:
                prompt_lines.append("If the user leaves race, gender, or profession unspecified and an image is supplied, infer the best-fit values from the portrait and local lore.")
            prompt_lines.extend([
                "Generate a complete tier 1 Cypher System player character suitable as a starting campaign pregen.",
                "Give the player character a proper in-setting personal name, not a descriptive placeholder or joke label.",
                "The build must be rules-aware: pools, edges, effort, cypher limit, practiced weapons, chosen abilities, and chosen skills should stay internally consistent.",
                "Include attacks that match the character's practiced weapons and starting equipment.",
                "Include a concrete `starting_equipment` list and an `equipment` list that reflect what the character actually begins play carrying.",
                "Prefer concise but playable attack entries such as weapon name, weapon class, and damage.",
                "Write a short evocative description or notes block that helps the GM or player understand the character at a glance.",
                "Include a `culture` field when the portrait and local lore support a meaningful cultural read such as Fenmir, Caldoran, Xanthir, Galadhrim, or another specific local identity.",
            ])
        if ctype == "rollable_table":
            prompt_lines.extend([
                "For rollable tables, set `primarycategory` to `rollable_table`.",
                "Each row must include `roll` and `result`.",
                "Only include `card_ref` when you know a real existing saved card path from the provided context or user brief.",
                "Never invent filenames, timestamps, or storage paths for `card_ref`.",
                "If a linked card is not explicitly known, omit `card_ref` and `card_label` entirely.",
                "If you do include `card_ref`, it must match the correct card type such as `cypher/...json`, `artifact/...json`, `npc/...json`, or `location/...json`.",
            ])
        if image_supplied and ctype in AI_GENERATE_VISION_TYPES:
            prompt_lines.append(ai_generate_vision_prompt(ctype))
            prompt_lines.append("Base your answer on the image evidence first, then reconcile it with retrieved local lore, then fill small gaps with restrained RPG inference.")
        elif image_supplied:
            prompt_lines.append("Use the uploaded image as a primary source of inspiration, but keep the final result aligned with retrieved local lore.")
        prompt_lines.extend([
            f"Follow this JSON shape exactly (keys may be added if useful):\n{schema_text}",
            f"Allowed vector sources/compendiums: {allowed_compendium_ids if allowed_compendium_ids else 'all indexed sources'}",
        ])
        if brief:
            prompt_lines.extend(["", "User brief:", brief])
        elif image_supplied:
            prompt_lines.extend(["", "User brief:", "No text brief provided. Infer the concept from the image."])
        return "\n".join(prompt_lines)

    def _ai_generate_with_provider(
        *,
        provider: str,
        prompt: str,
        vector_context: str,
        image_data_url: str = "",
        image_bytes: bytes | None = None,
    ) -> tuple[str, str, str]:
        provider_norm = str(provider or "ollama_local").strip().lower()
        image_present = bool(image_data_url and image_bytes)
        if provider_norm == "openai_remote":
            model = openai_default_model()
            base_url = openai_base_url()
            api_key = openai_api_key()
            if not api_key:
                raise ValueError("api_key is required in plugin settings or request")
            system_prompt = openai_system_prompt()
            messages: list[dict] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            if image_present:
                user_content: list[dict] = [{"type": "text", "text": f"{prompt}\n\nContext:\n{vector_context}\n\nAnswer:"}]
                user_content.append({"type": "image_url", "image_url": {"url": image_data_url}})
                messages.append({"role": "user", "content": user_content})
            else:
                messages.append({"role": "user", "content": f"{prompt}\n\nContext:\n{vector_context}\n\nAnswer:"})
            reply = openai_post_json(
                base_url,
                "/v1/chat/completions",
                {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.2,
                },
                api_key=api_key,
                timeout=300,
            )
            choices = reply.get("choices") if isinstance(reply, dict) else []
            answer = ""
            if isinstance(choices, list) and choices:
                first = choices[0] if isinstance(choices[0], dict) else {}
                message = first.get("message") if isinstance(first.get("message"), dict) else {}
                answer = str(message.get("content") or "").strip()
            return answer, model, base_url

        model = OLLAMA_VISION_MODEL if image_present else ollama_default_model()
        base_url = ollama_base_url()
        keep_alive = ollama_keep_alive()
        system_prompt = ollama_system_prompt()
        payload = {
            "model": model,
            "prompt": f"{system_prompt}\n\n{prompt}\n\nContext:\n{vector_context}\n\nAnswer:".strip() if system_prompt else f"{prompt}\n\nContext:\n{vector_context}\n\nAnswer:",
            "stream": False,
            "keep_alive": keep_alive,
            "options": {"temperature": 0.2},
        }
        if image_present and image_bytes is not None:
            payload["images"] = [base64.b64encode(image_bytes).decode("ascii")]
        reply = ollama_post_json(base_url, "/api/generate", payload, timeout=300)
        answer = str(reply.get("response") or "").strip()
        return answer, model, base_url

    def _setting_wizard_skeleton_files(setting_id: str, setting_label: str, genre_id: str, brief: str) -> dict[str, str]:
        summary = brief.strip() or f"A new {genre_id.replace('_', ' ')} setting."
        files_obj = {
            "00_world.yaml": {
                "world": {
                    "id": setting_id,
                    "label": setting_label,
                    "core_genre": genre_id,
                    "core_setting": genre_id,
                    "description": summary,
                }
            },
            "01_setting.yaml": {
                "setting": {
                    "name": setting_label,
                    "summary": summary,
                    "tone_style": "Grounded, evocative, playable.",
                    "core_world_truths": [
                        f"{setting_label} has unresolved ancient tensions.",
                        "Local myths conflict and no single version is absolute.",
                    ],
                    "cultural_themes": [
                        "survival and adaptation",
                        "memory versus ambition",
                        "local identity under pressure",
                    ],
                    "output_guidelines": [
                        "Use sensory details and local texture.",
                        "Avoid absolute good-versus-evil framing.",
                    ],
                }
            },
            "10_races.yaml": {
                "races": {}
            },
            "12_areas.yaml": {
                "areas": {
                    setting_id: {
                        "name": setting_label,
                        "type": "region",
                        "culture": "mixed",
                        "description": summary,
                        "visual_traits": [
                            f"landmarks tied to {setting_label}",
                            "lore-derived terrain cues pending curation",
                        ],
                        "mood": ["mysterious", "volatile", "adventurous"],
                    }
                }
            },
            "20_settlements.yaml": {
                "settlements": {
                    setting_id: {
                        "settlement_types": [f"{setting_id} outpost", f"{setting_id} trade camp"],
                        "visual_features": ["architecture adapted to local terrain", "visible local iconography"],
                        "landmarks": ["a central historic site", "a contested crossing"],
                        "economies": ["survival trade", "local craft"],
                        "tensions": ["outside pressure on local tradition"],
                        "atmospheres": ["uneasy but resilient"],
                    }
                }
            },
            "21_encounters.yaml": {
                "encounters": {
                    setting_id: {
                        "first_impressions": [f"the party enters a tense moment in {setting_label}"],
                        "subjects": ["a local authority", "a witness with partial truth"],
                        "truths": ["the visible conflict hides a deeper cause"],
                        "complications": ["time pressure narrows safe choices"],
                        "hooks": ["stabilize the situation before it escalates"],
                    }
                }
            },
            "22_cyphers.yaml": {
                "cyphers": {
                    setting_id: {
                        "forms": ["strange token", "etched shard"],
                        "appearances": ["weathered and symbolic"],
                        "effects": ["reveals hidden danger", "briefly shifts local conditions"],
                        "limits": ["single-use", "becomes inert after activation"],
                        "quirks": ["faint hum near important places"],
                    }
                }
            },
            "90_lore_enrichment.yaml": {
                "areas": {},
                "settlements": {},
                "encounters": {},
            },
        }
        rendered: dict[str, str] = {}
        for filename, data in files_obj.items():
            rendered[filename] = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        return rendered

    def _setting_wizard_flavor_context(setting_id: str, setting_label: str, genre_id: str, brief: str, base_setting_id: str) -> tuple[str, list[str]]:
        query = " ".join(
            token for token in [
                setting_label,
                brief,
                "setting tone culture themes areas settlements encounters cyphers",
            ] if token
        ).strip()
        profiles = load_compendium_profiles()
        enabled_ids = enabled_compendium_ids_for_search()
        selected_compendiums: list[str] = []

        if "core_rulebook" in profiles and "core_rulebook" in enabled_ids:
            selected_compendiums.append("core_rulebook")

        for pid, profile in sorted(profiles.items(), key=lambda kv: kv[0]):
            cid = str(pid or "").strip().lower()
            if not cid or cid in {"csrd", FOUNDRY_COMPENDIUM_ID, "core_rulebook"}:
                continue
            if cid not in enabled_ids:
                continue
            source_kind = compendium_source_kind(cid, profile)
            if source_kind not in {"official", "core_pdf"}:
                continue
            tags = compendium_taxonomy_tags(profile, source_kind=source_kind, compendium_id=cid)
            tag_genre = _safe_slug(str(tags.get("genre") or "").strip().lower())
            if tag_genre == genre_id and cid not in selected_compendiums:
                selected_compendiums.append(cid)

        if base_setting_id and base_setting_id in profiles and base_setting_id in enabled_ids:
            if base_setting_id not in selected_compendiums:
                selected_compendiums.append(base_setting_id)

        context_sections: list[str] = []
        for cid in selected_compendiums:
            try:
                vec = vector_query_index(
                    output_root=vector_index_root(),
                    query=query or setting_label,
                    k=3,
                    compendium_id=cid,
                )
            except Exception:
                continue
            items = vec.get("items") if isinstance(vec, dict) else []
            items = items if isinstance(items, list) else []
            snippets: list[str] = []
            for item in items[:3]:
                if not isinstance(item, dict):
                    continue
                heading = str(item.get("heading") or "").strip()
                text = " ".join(str(item.get("text") or "").split())
                if len(text) > 700:
                    text = text[:699].rstrip() + "…"
                if not text:
                    continue
                snippets.append(f"- {heading}: {text}" if heading else f"- {text}")
            if snippets:
                context_sections.append(f"[{cid}]\n" + "\n".join(snippets))

        if base_setting_id:
            try:
                base_world = load_world_layer(current_app.config["LOL_CONFIG_DIR"], base_setting_id)
            except Exception:
                base_world = {}
            if isinstance(base_world, dict) and base_world:
                setting_block = base_world.get("setting") if isinstance(base_world.get("setting"), dict) else {}
                world_block = base_world.get("world") if isinstance(base_world.get("world"), dict) else {}
                areas = base_world.get("areas") if isinstance(base_world.get("areas"), dict) else {}
                area_names = list(areas.keys())[:8]
                context_sections.append(
                    "[existing_setting_world_yaml]\n"
                    f"- world.label: {world_block.get('label') or base_setting_id}\n"
                    f"- world.description: {world_block.get('description') or ''}\n"
                    f"- setting.summary: {setting_block.get('summary') or ''}\n"
                    f"- setting.tone_style: {setting_block.get('tone_style') or ''}\n"
                    f"- area_ids_sample: {', '.join(area_names)}"
                )
        return ("\n\n".join(context_sections).strip(), selected_compendiums)

    def _setting_wizard_generate_with_ai(
        setting_id: str,
        setting_label: str,
        genre_id: str,
        brief: str,
        base_setting_id: str = "",
        provider: str = "ollama_local",
    ) -> tuple[dict[str, str] | None, str, list[str]]:
        provider_norm = str(provider or "ollama_local").strip().lower()
        if provider_norm == "openai_remote" and not is_plugin_enabled("openai_remote"):
            return None, "openai_remote plugin disabled; returned skeleton files.", []
        if provider_norm != "openai_remote" and not is_plugin_enabled("ollama_local"):
            return None, "ollama_local plugin disabled; returned skeleton files.", []

        required_files = [
            "00_world.yaml",
            "01_setting.yaml",
            "10_races.yaml",
            "12_areas.yaml",
            "20_settlements.yaml",
            "21_encounters.yaml",
            "22_cyphers.yaml",
            "90_lore_enrichment.yaml",
        ]
        flavor_context, selected_compendiums = _setting_wizard_flavor_context(
            setting_id=setting_id,
            setting_label=setting_label,
            genre_id=genre_id,
            brief=brief,
            base_setting_id=base_setting_id,
        )

        prompt = (
            "Task: Generate a complete starter Cypher setting YAML pack.\n"
            "Return ONLY valid JSON.\n"
            "JSON shape:\n"
            "{\n"
            "  \"files\": {\n"
            "    \"00_world.yaml\": \"<yaml>\",\n"
            "    \"01_setting.yaml\": \"<yaml>\",\n"
            "    \"10_races.yaml\": \"<yaml>\",\n"
            "    \"12_areas.yaml\": \"<yaml>\",\n"
            "    \"20_settlements.yaml\": \"<yaml>\",\n"
            "    \"21_encounters.yaml\": \"<yaml>\",\n"
            "    \"22_cyphers.yaml\": \"<yaml>\",\n"
            "    \"90_lore_enrichment.yaml\": \"<yaml>\"\n"
            "  }\n"
            "}\n\n"
            f"Inputs:\n"
            f"- setting_id: {setting_id}\n"
            f"- setting_label: {setting_label}\n"
            f"- genre_id: {genre_id}\n"
            f"- base_setting_id: {base_setting_id or '(none)'}\n"
            f"- brief: {brief or '(none)'}\n"
            f"- flavor_compendiums_used: {', '.join(selected_compendiums) if selected_compendiums else '(none)'}\n"
            f"- flavor_context:\n{flavor_context or '(none available)'}\n"
            "Constraints:\n"
            "- Use top-level keys that match each file purpose (world, setting, races, areas, settlements, encounters, cyphers).\n"
            "- Keep YAML concise and valid.\n"
            "- Pull style/flavor from provided flavor_context when available.\n"
            "- Do not include markdown fences or commentary."
        )

        try:
            answer = ""
            if provider_norm == "openai_remote":
                base_url = openai_base_url()
                model = openai_default_model()
                api_key = openai_api_key()
                if not api_key:
                    return None, "OpenAI api_key is not set; returned skeleton files.", selected_compendiums
                system_prompt = openai_system_prompt()
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                reply = openai_post_json(
                    base_url,
                    "/v1/chat/completions",
                    {
                        "model": model,
                        "messages": messages,
                        "temperature": 0.2,
                    },
                    api_key=api_key,
                    timeout=300,
                )
                choices = reply.get("choices") if isinstance(reply, dict) else []
                if isinstance(choices, list) and choices:
                    first = choices[0] if isinstance(choices[0], dict) else {}
                    message = first.get("message") if isinstance(first.get("message"), dict) else {}
                    answer = str(message.get("content") or "").strip()
            else:
                model = ollama_default_model()
                base_url = ollama_base_url()
                keep_alive = ollama_keep_alive()
                system_prompt = ollama_system_prompt()
                if not system_prompt:
                    return None, "No Ollama system prompt set; returned skeleton files.", selected_compendiums
                reply = ollama_post_json(
                    base_url,
                    "/api/generate",
                    {
                        "model": model,
                        "prompt": f"{system_prompt}\n\n{prompt}",
                        "stream": False,
                        "keep_alive": keep_alive,
                        "options": {"temperature": 0.2},
                    },
                    timeout=300,
                )
                answer = str(reply.get("response") or "").strip()
            parsed = _extract_first_json_object(answer)
            files = parsed.get("files") if isinstance(parsed, dict) else None
            if not isinstance(files, dict):
                return None, "AI response missing files map; returned skeleton files.", selected_compendiums
            out: dict[str, str] = {}
            for filename in required_files:
                text = str(files.get(filename) or "").strip()
                if not text:
                    return None, f"AI response missing '{filename}'; returned skeleton files.", selected_compendiums
                out[filename] = text
            return out, "", selected_compendiums
        except Exception as exc:
            provider_label = "OpenAI" if provider_norm == "openai_remote" else "Ollama"
            return None, f"{provider_label} request failed ({exc}); returned skeleton files.", selected_compendiums

    def _parse_mapping_text(text: str) -> dict[str, Any]:
        raw = str(text or "").strip()
        if not raw:
            return {}
        for parser in (
            lambda s: json.loads(s),
            lambda s: ast.literal_eval(s),
            lambda s: yaml.safe_load(s),
        ):
            try:
                data = parser(raw)
            except Exception:
                continue
            if isinstance(data, dict):
                return data
        raise ValueError("file content must parse into a mapping/object")

    def _normalize_setting_wizard_doc(
        filename: str,
        data: dict[str, Any],
        *,
        setting_id: str,
        setting_label: str,
        genre_id: str,
    ) -> dict[str, Any]:
        name = str(filename or "").strip().lower()
        obj = data if isinstance(data, dict) else {}

        if name == "00_world.yaml":
            world = obj.get("world") if isinstance(obj.get("world"), dict) else None
            if world is None:
                world = {
                    "id": setting_id,
                    "label": str(obj.get("label") or obj.get("name") or setting_label).strip() or setting_label,
                    "core_genre": str(obj.get("core_genre") or obj.get("genre") or genre_id).strip() or genre_id,
                    "core_setting": str(obj.get("core_setting") or obj.get("genre") or genre_id).strip() or genre_id,
                    "description": str(obj.get("description") or "").strip(),
                }
            world.setdefault("id", setting_id)
            world.setdefault("label", setting_label)
            world.setdefault("core_genre", genre_id)
            world.setdefault("core_setting", genre_id)
            return {"world": world}

        if name == "01_setting.yaml":
            setting = obj.get("setting") if isinstance(obj.get("setting"), dict) else None
            if setting is None:
                setting = {
                    "name": str(obj.get("name") or setting_label).strip() or setting_label,
                    "summary": str(obj.get("summary") or obj.get("description") or "").strip(),
                    "tone_style": str(obj.get("tone_style") or obj.get("tone") or "").strip(),
                }
            setting.setdefault("name", setting_label)
            return {"setting": setting}

        if name == "10_races.yaml":
            races = obj.get("races") if isinstance(obj.get("races"), dict) else obj
            return {"races": races if isinstance(races, dict) else {}}

        if name == "12_areas.yaml":
            areas = obj.get("areas") if isinstance(obj.get("areas"), dict) else obj
            return {"areas": areas if isinstance(areas, dict) else {}}

        if name == "20_settlements.yaml":
            settlements = obj.get("settlements") if isinstance(obj.get("settlements"), dict) else obj
            return {"settlements": settlements if isinstance(settlements, dict) else {}}

        if name == "21_encounters.yaml":
            encounters = obj.get("encounters") if isinstance(obj.get("encounters"), dict) else obj
            return {"encounters": encounters if isinstance(encounters, dict) else {}}

        if name == "22_cyphers.yaml":
            cyphers = obj.get("cyphers") if isinstance(obj.get("cyphers"), dict) else obj
            return {"cyphers": cyphers if isinstance(cyphers, dict) else {}}

        if name == "90_lore_enrichment.yaml":
            return {
                "areas": obj.get("areas") if isinstance(obj.get("areas"), dict) else {},
                "settlements": obj.get("settlements") if isinstance(obj.get("settlements"), dict) else {},
                "encounters": obj.get("encounters") if isinstance(obj.get("encounters"), dict) else {},
            }

        return obj

    @app.post("/setting-wizard/generate")
    def api_setting_wizard_generate():
        body = request.get_json(force=True, silent=False) or {}
        provider = str(body.get("provider") or "ollama_local").strip().lower()
        setting_label = str(body.get("setting_label") or "").strip()
        genre_id = _safe_slug(str(body.get("genre_id") or "").strip().lower())
        setting_id_raw = str(body.get("setting_id") or "").strip().lower()
        setting_id = _safe_slug(setting_id_raw or setting_label)
        brief = str(body.get("brief") or "").strip()
        base_setting_raw = str(body.get("base_setting_id") or "").strip().lower()
        if base_setting_raw.startswith("compendium:"):
            base_setting_id = _safe_slug(base_setting_raw.split(":", 1)[1])
        else:
            base_setting_id = _safe_slug(base_setting_raw)

        if not setting_label:
            return jsonify({"error": "setting_label is required"}), 400
        if not genre_id:
            return jsonify({"error": "genre_id is required"}), 400
        if not setting_id:
            return jsonify({"error": "setting_id is required"}), 400

        files, warning, flavor_compendiums_used = _setting_wizard_generate_with_ai(
            setting_id,
            setting_label,
            genre_id,
            brief,
            base_setting_id=base_setting_id,
            provider=provider,
        )
        if not files:
            files = _setting_wizard_skeleton_files(setting_id, setting_label, genre_id, brief)

        return jsonify({
            "ok": True,
            "setting_id": setting_id,
            "setting_label": setting_label,
            "genre_id": genre_id,
            "files": files,
            "warning": warning,
            "provider": provider,
            "base_setting_id": base_setting_id,
            "flavor_compendiums_used": flavor_compendiums_used,
        })

    @app.post("/setting-wizard/create")
    def api_setting_wizard_create():
        body = request.get_json(force=True, silent=False) or {}
        setting_label = str(body.get("setting_label") or "").strip()
        genre_id = _safe_slug(str(body.get("genre_id") or "").strip().lower())
        setting_id = _safe_slug(str(body.get("setting_id") or "").strip().lower())
        files = body.get("files")
        overwrite = str(body.get("overwrite") or "0").strip().lower() in {"1", "true", "yes", "on"}
        if not setting_label or not genre_id or not setting_id:
            return jsonify({"error": "setting_label, genre_id, and setting_id are required"}), 400
        if not isinstance(files, dict):
            return jsonify({"error": "files must be an object"}), 400

        config_dir = current_app.config["LOL_CONFIG_DIR"]
        world_dir = config_dir / "worlds" / setting_id
        if world_dir.exists() and not overwrite:
            return jsonify({"error": f"setting folder already exists: {world_dir}. Pass overwrite=true to replace files."}), 409
        world_dir.mkdir(parents=True, exist_ok=True)

        required_files = [
            "00_world.yaml",
            "01_setting.yaml",
            "10_races.yaml",
            "12_areas.yaml",
            "20_settlements.yaml",
            "21_encounters.yaml",
            "22_cyphers.yaml",
            "90_lore_enrichment.yaml",
        ]
        written: list[str] = []
        for filename in required_files:
            content = str(files.get(filename) or "").strip()
            if not content:
                continue
            parsed = _parse_mapping_text(content)
            normalized = _normalize_setting_wizard_doc(
                filename,
                parsed,
                setting_id=setting_id,
                setting_label=setting_label,
                genre_id=genre_id,
            )
            path = world_dir / filename
            yaml_text = yaml.safe_dump(normalized, sort_keys=False, allow_unicode=True)
            path.write_text(yaml_text, encoding="utf-8")
            written.append(str(path.relative_to(config_dir)).replace("\\", "/"))

        settings_path = config_dir / "02_settings.yaml"
        settings_data = {}
        if settings_path.exists():
            try:
                settings_data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
            except Exception:
                settings_data = {}
        if not isinstance(settings_data, dict):
            settings_data = {}

        settings_block = settings_data.setdefault("settings", {})
        genres_block = settings_data.setdefault("genres", {})
        if not isinstance(settings_block, dict):
            settings_block = {}
            settings_data["settings"] = settings_block
        if not isinstance(genres_block, dict):
            genres_block = {}
            settings_data["genres"] = genres_block

        def ensure_catalog_entry(root: dict, group_key: str, item_key: str, list_key: str) -> None:
            catalog = root.setdefault("catalog", {})
            if not isinstance(catalog, dict):
                catalog = {}
                root["catalog"] = catalog
            entry = catalog.setdefault(group_key, {})
            if not isinstance(entry, dict):
                entry = {}
                catalog[group_key] = entry
            if not entry.get("label"):
                entry["label"] = group_key.replace("_", " ").title()
            items = entry.setdefault(list_key, [])
            if not isinstance(items, list):
                items = []
                entry[list_key] = items
            if item_key not in items:
                items.append(item_key)

        ensure_catalog_entry(settings_block, genre_id, setting_id, "worlds")
        ensure_catalog_entry(genres_block, genre_id, setting_id, "settings")

        defaults = settings_block.setdefault("defaults", [])
        if isinstance(defaults, list):
            if not defaults:
                defaults.extend([genre_id, setting_id])
        else:
            settings_block["defaults"] = [genre_id, setting_id]
        gdefaults = genres_block.setdefault("defaults", [])
        if isinstance(gdefaults, list):
            if not gdefaults:
                gdefaults.extend([genre_id, setting_id])
        else:
            genres_block["defaults"] = [genre_id, setting_id]

        settings_path.write_text(yaml.safe_dump(settings_data, sort_keys=False, allow_unicode=True), encoding="utf-8")

        return jsonify({
            "ok": True,
            "setting_id": setting_id,
            "genre_id": genre_id,
            "world_dir": str(world_dir.relative_to(config_dir)).replace("\\", "/"),
            "written_files": written,
            "settings_updated": str(settings_path.relative_to(config_dir)).replace("\\", "/"),
        })

    @app.post("/ai-generate/save")
    def ai_generate_save():
        body = request.get_json(force=True, silent=False) or {}
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        content_type = str(body.get("content_type") or "").strip().lower()
        card = body.get("card")
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
        image_data_url = str(body.get("image_data_url") or "").strip()
        image_name = str(body.get("image_name") or "").strip()
        if not content_type:
            return jsonify({"error": "content_type is required"}), 400
        if not isinstance(card, dict):
            return jsonify({"error": "card must be an object"}), 400

        card = _normalize_ai_generated_card(
            card,
            content_type=content_type,
            setting_id=str(payload.get("setting") or "").strip(),
            area_id=str(payload.get("area") or "").strip(),
            generation_preferences={
                "race": str(payload.get("race") or "").strip(),
                "variant": str(payload.get("variant") or "").strip(),
                "gender": str(payload.get("gender") or "").strip(),
                "profession": str(payload.get("profession") or "").strip(),
                "culture": str(payload.get("culture") or "").strip(),
            },
        )

        if content_type == "rollable_table":
            rows = card.get("rows")
            if isinstance(rows, list):
                sanitized_rows: list[dict] = []
                for row in rows:
                    if not isinstance(row, dict):
                        sanitized_rows.append(row)
                        continue
                    next_row = dict(row)
                    ref_value = next_row.get("card_ref") or next_row.get("ref") or next_row.get("target_ref")
                    if ref_value and not _storage_card_ref_exists(storage_dir, ref_value):
                        next_row.pop("card_ref", None)
                        next_row.pop("ref", None)
                        next_row.pop("target_ref", None)
                        next_row.pop("card_label", None)
                        next_row.pop("label", None)
                    sanitized_rows.append(next_row)
                card = dict(card)
                card["rows"] = sanitized_rows

        type_map = {
            "free_text": "lore",
            "lore": "lore",
            "rollable_table": "rollable_table",
            "cypher": "cypher",
            "artifact": "artifact",
            "encounter": "encounter",
            "settlement": "settlement",
            "inn": "inn",
            "landmark": "location",
            "creature": "creature",
            "npc": "npc",
            "player_character": "character_sheet",
        }
        result_type = type_map.get(content_type)
        if not result_type:
            return jsonify({"error": f"unsupported content_type '{content_type}'"}), 400

        name = str(
            card.get("name")
            or card.get("title")
            or card.get("encounter_title")
            or card.get("settlement_name")
            or card.get("npc_name")
            or "AI Generated Entry"
        ).strip() or "AI Generated Entry"

        description = str(
            card.get("description")
            or card.get("situation")
            or card.get("summary")
            or card.get("effect")
            or card.get("combat")
            or ""
        ).strip()

        metadata = card.get("metadata") if isinstance(card.get("metadata"), dict) else {}
        if content_type == "player_character":
            result = _normalize_ai_generated_player_character(card, payload)
        else:
            result = {
                "type": result_type,
                "name": name,
                "description": description,
                "sections": dict(card),
                "metadata": {
                    "source": "House",
                    "origin": "ai_generate",
                    "content_type": content_type,
                    "ai_generated": "true",
                    "setting": metadata.get("setting") or payload.get("setting"),
                    "settings": metadata.get("settings") or payload.get("settings"),
                    "area": metadata.get("area") or payload.get("area") or metadata.get("environment") or payload.get("environment"),
                    "location": metadata.get("location") or payload.get("location"),
                    "environment": metadata.get("environment") or metadata.get("area") or payload.get("environment") or payload.get("area"),
                    "race": metadata.get("race") or payload.get("race"),
                    "variant": metadata.get("variant") or payload.get("variant"),
                    "gender": metadata.get("gender") or payload.get("gender"),
                    "profession": metadata.get("profession") or payload.get("profession"),
                    "culture": metadata.get("culture") or payload.get("culture"),
                    "sourcebook": metadata.get("sourcebook") or payload.get("sourcebook"),
                    "page": metadata.get("page") or payload.get("page"),
                },
            }
        if content_type in {"npc", "creature"}:
            level = _ai_generate_parse_int(card.get("level"), minimum=1, maximum=10)
            stat_block = {
                "level": level,
                "target_number": level * 3 if level is not None else None,
                "health": _ai_generate_parse_int(card.get("health"), minimum=1, maximum=60),
                "armor": _ai_generate_parse_int(card.get("armor"), minimum=0, maximum=5),
                "damage": _ai_generate_parse_int(card.get("damage_inflicted"), minimum=1, maximum=12),
                "movement": str(card.get("movement") or "").strip(),
                "modifications": [str(card.get("modifications") or "").strip()] if str(card.get("modifications") or "").strip() else [],
                "combat": [str(card.get("combat") or "").strip()] if str(card.get("combat") or "").strip() else [],
                "interaction": [str(card.get("interaction") or "").strip()] if str(card.get("interaction") or "").strip() else [],
                "loot": [str(card.get("loot") or "").strip()] if str(card.get("loot") or "").strip() else [],
            }
            result["stat_block"] = stat_block
        if content_type == "rollable_table":
            result["metadata"]["subtype"] = "rollable_table"
            result["metadata"]["primarycategory"] = "rollable_table"
            result["primarycategory"] = "rollable_table"
        elif content_type == "landmark":
            # Canonicalize landmark payloads even if the model omits type markers.
            sections = result.get("sections") if isinstance(result.get("sections"), dict) else {}
            if isinstance(sections, dict):
                sections.setdefault("type", "location")
                sections.setdefault("location_category_type", "landmark")
                sections.setdefault("content_type", "landmark")
            result["metadata"]["subtype"] = "landmark"
            result["metadata"]["location_category_type"] = "landmark"
        elif content_type == "settlement":
            sections = result.get("sections") if isinstance(result.get("sections"), dict) else {}
            if isinstance(sections, dict):
                area_value = str(sections.get("area") or result["metadata"].get("area") or payload.get("area") or "").strip()
                environment_value = str(
                    sections.get("environment")
                    or result["metadata"].get("environment")
                    or payload.get("environment")
                    or area_value
                    or ""
                ).strip()
                location_value = str(sections.get("location") or result["metadata"].get("location") or payload.get("location") or "").strip()
                if area_value:
                    sections.setdefault("area", area_value)
                if environment_value:
                    sections.setdefault("environment", environment_value)
                if location_value:
                    sections.setdefault("location", location_value)

        if image_data_url:
            try:
                stored_image = persist_uploaded_image_data(
                    image_data_url,
                    friendly_name=image_name or name,
                    tags=["ai_generate", content_type, result_type],
                    notes=f"Saved from AI Generate for {name}",
                )
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            image_ref = str(stored_image.get("path") or "").strip()
            if image_ref:
                result["metadata"]["image_url"] = image_ref
                result["metadata"]["images"] = [image_ref]
                sections = result.get("sections") if isinstance(result.get("sections"), dict) else {}
                if isinstance(sections, dict):
                    meta = sections.get("metadata") if isinstance(sections.get("metadata"), dict) else {}
                    meta["image_url"] = image_ref
                    meta["images"] = [image_ref]
                    sections["metadata"] = meta
                sheet = result.get("sheet") if isinstance(result.get("sheet"), dict) else {}
                if isinstance(sheet, dict):
                    meta = sheet.get("metadata") if isinstance(sheet.get("metadata"), dict) else {}
                    meta["image_url"] = image_ref
                    meta["images"] = [image_ref]
                    sheet["metadata"] = meta
                result["image"] = {
                    "path": image_ref,
                    "url": str(stored_image.get("url") or ""),
                    "name": str(stored_image.get("name") or ""),
                }

        stored = persist_result(payload, result)
        return jsonify({
            "ok": True,
            "result": stored,
        })

    @app.get("/map-tools")
    @app.get("/map-editor")
    def map_tools():
        return render_template("map_editor.html")

    @app.get("/map-projects")
    def api_map_projects_list():
        items = list_map_projects()
        return jsonify({"items": items, "count": len(items)})

    @app.get("/map-projects/location-cards")
    def api_map_projects_location_cards():
        setting = str(request.args.get("setting") or "").strip()
        area = str(request.args.get("area") or "").strip()
        marker_type = str(request.args.get("marker_type") or request.args.get("type") or "").strip()
        query = str(request.args.get("q") or request.args.get("name") or "").strip()
        items = _map_location_card_entries(setting=setting, area=area, marker_type=marker_type, query=query)
        return jsonify({
            "items": items,
            "count": len(items),
            "filters": {
                "setting": normalize_setting_token(setting) if setting else "",
                "area": area,
                "marker_type": marker_type,
                "q": query,
            },
        })

    @app.get("/map-projects/placements")
    def api_map_projects_placements():
        storage_filename = str(request.args.get("filename") or "").strip()
        card_name = str(request.args.get("name") or "").strip()
        placements = find_map_project_placements(storage_filename=storage_filename, card_name=card_name)
        return jsonify({
            "items": placements,
            "count": len(placements),
            "filters": {
                "filename": storage_filename,
                "name": card_name,
            },
        })

    @app.get("/map-projects/<project_id>")
    def api_map_projects_load(project_id: str):
        try:
            project = load_map_project(project_id)
        except FileNotFoundError:
            return jsonify({"error": f"map project not found: {project_id}"}), 404
        return jsonify({"project": project})

    @app.post("/map-projects/save")
    def api_map_projects_save():
        body = request.get_json(force=True, silent=False) or {}
        project_raw = body.get("project") if isinstance(body.get("project"), dict) else body
        project = save_map_project(project_raw)
        return jsonify({"ok": True, "project": project})

    @app.post("/map-projects/delete")
    def api_map_projects_delete():
        body = request.get_json(force=True, silent=False) or {}
        project_id = _safe_slug(str(body.get("id") or "").strip())
        if not project_id:
            return jsonify({"error": "id is required"}), 400
        path = map_project_path(project_id)
        if not path.exists():
            return jsonify({"error": f"map project not found: {project_id}"}), 404
        path.unlink()
        return jsonify({"ok": True, "deleted": project_id})

    @app.get("/dice-roller")
    def dice_roller():
        return render_template("dice_roller.html")

    @app.get("/cypher-roller")
    def cypher_roller():
        return render_template("cypher_roller.html")

    @app.get("/plugins")
    def api_plugins_list():
        plugins = discover_plugins()
        return jsonify({"items": plugins, "count": len(plugins)})

    @app.post("/plugins/toggle")
    def api_plugins_toggle():
        body = request.get_json(force=True, silent=False) or {}
        plugin_id = str(body.get("id") or "").strip()
        enabled = bool(body.get("enabled"))
        if not plugin_id:
            return jsonify({"error": "id is required"}), 400

        plugins = discover_plugins()
        if not any(item.get("id") == plugin_id for item in plugins):
            return jsonify({"error": f"unknown plugin '{plugin_id}'"}), 404

        state = load_plugin_state()
        state[plugin_id] = enabled
        save_plugin_state(state)
        return jsonify({"ok": True, "id": plugin_id, "enabled": enabled})

    @app.get("/plugins/<plugin_id>/settings")
    def plugin_settings_page(plugin_id: str):
        pid = str(plugin_id or "").strip()
        plugins = discover_plugins()
        if not any(item.get("id") == pid for item in plugins):
            return jsonify({"error": f"unknown plugin '{plugin_id}'"}), 404
        return render_template("plugin_settings.html", plugin_id=pid)

    @app.get("/plugins/<plugin_id>/settings/data")
    def api_plugin_settings_data(plugin_id: str):
        pid = str(plugin_id or "").strip()
        plugins = discover_plugins()
        plugin = next((p for p in plugins if p.get("id") == pid), None)
        if not plugin:
            return jsonify({"error": f"unknown plugin '{plugin_id}'"}), 404
        values = get_plugin_settings(pid)
        fields = plugin_settings_fields(pid, values)
        status = plugin_runtime_status(pid)
        return jsonify({
            "plugin": plugin,
            "fields": fields,
            "values": values,
            "status": status,
        })

    @app.post("/plugins/<plugin_id>/settings/save")
    def api_plugin_settings_save(plugin_id: str):
        pid = str(plugin_id or "").strip()
        plugins = discover_plugins()
        if not any(item.get("id") == pid for item in plugins):
            return jsonify({"error": f"unknown plugin '{plugin_id}'"}), 404
        body = request.get_json(force=True, silent=False) or {}
        values = body.get("values")
        if not isinstance(values, dict):
            return jsonify({"error": "values object is required"}), 400
        try:
            saved = update_plugin_settings(pid, values)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        fields = plugin_settings_fields(pid, saved)
        status = plugin_runtime_status(pid)
        return jsonify({"ok": True, "values": saved, "fields": fields, "status": status})

    @app.route("/plugins/foundryvtt/health", methods=["GET", "OPTIONS"])
    def api_foundryvtt_health():
        if request.method == "OPTIONS":
            response = jsonify({"ok": True})
            response.status_code = 204
            return with_foundry_cors_headers(response)

        if not is_plugin_enabled("foundryVTT"):
            response = jsonify({"error": "foundryVTT plugin is disabled"})
            response.status_code = 403
            return with_foundry_cors_headers(response)

        response = jsonify({
            "status": "ok",
            "plugin": "foundryVTT",
            "api_version": "1.0.0",
            "auth_required": bool(foundry_api_token()),
            "active_setting": current_app.config.get("LOL_SETTING_ID") or current_app.config.get("LOL_WORLD_ID"),
            "time_utc": datetime.now(timezone.utc).isoformat(),
        })
        return with_foundry_cors_headers(response)

    @app.route("/plugins/foundryvtt/handshake", methods=["POST", "OPTIONS"])
    def api_foundryvtt_handshake():
        if request.method == "OPTIONS":
            response = jsonify({"ok": True})
            response.status_code = 204
            return with_foundry_cors_headers(response)

        if not is_plugin_enabled("foundryVTT"):
            response = jsonify({"error": "foundryVTT plugin is disabled"})
            response.status_code = 403
            return with_foundry_cors_headers(response)

        auth_error = foundry_auth_error_response()
        if auth_error is not None:
            return auth_error

        body = request.get_json(force=True, silent=True) or {}
        client = body if isinstance(body, dict) else {}

        response = jsonify({
            "status": "ok",
            "message": "handshake accepted",
            "api_version": "1.0.0",
            "auth_required": bool(foundry_api_token()),
            "server": {
                "name": "Legends RPG GMTools",
                "active_setting": current_app.config.get("LOL_SETTING_ID") or current_app.config.get("LOL_WORLD_ID"),
                "time_utc": datetime.now(timezone.utc).isoformat(),
            },
            "capabilities": {
                "import_actor": True,
                "export_actor": True,
                "import_item": False,
                "import_journal": False,
            },
            "client_echo": {
                "module_id": str(client.get("module_id") or "").strip(),
                "module_version": str(client.get("module_version") or "").strip(),
                "foundry_version": str(client.get("foundry_version") or "").strip(),
                "system_id": str(client.get("system_id") or "").strip(),
                "system_version": str(client.get("system_version") or "").strip(),
                "world_id": str(client.get("world_id") or "").strip(),
            },
        })
        return with_foundry_cors_headers(response)

    @app.get("/plugins/ollama-local/health")
    def api_ollama_local_health():
        if not is_plugin_enabled("ollama_local"):
            return jsonify({"error": "ollama_local plugin is disabled"}), 403
        base_url = normalize_http_base_url(request.args.get("base_url"), ollama_base_url())
        try:
            tags = ollama_get_json(base_url, "/api/tags")
            models = tags.get("models") if isinstance(tags, dict) else []
            count = len(models) if isinstance(models, list) else 0
            return jsonify({
                "status": "ok",
                "plugin": "ollama_local",
                "base_url": base_url,
                "model_count": count,
                "default_model": ollama_default_model(),
                "keep_alive": ollama_keep_alive(),
                "system_prompt_set": bool(ollama_system_prompt()),
            })
        except Exception as exc:
            return jsonify({
                "status": "error",
                "plugin": "ollama_local",
                "base_url": base_url,
                "error": str(exc),
            }), 502

    @app.post("/plugins/ollama-local/query")
    def api_ollama_local_query():
        if not is_plugin_enabled("ollama_local"):
            return jsonify({"error": "ollama_local plugin is disabled"}), 403
        body = request.get_json(force=True, silent=False) or {}
        q = str(body.get("q") or "").strip()
        if not q:
            return jsonify({"error": "q is required"}), 400
        model = str(body.get("model") or ollama_default_model()).strip()
        keep_alive = str(body.get("keep_alive") or ollama_keep_alive()).strip()
        system_prompt = str(body.get("system_prompt") or ollama_system_prompt()).strip()
        base_url = normalize_http_base_url(body.get("base_url"), ollama_base_url())
        include_local = bool(body.get("include_local", True))
        include_lore = bool(body.get("include_lore", False))
        setting = str(body.get("setting") or "").strip()
        location = str(body.get("location") or "").strip()
        compendium_id = str(body.get("compendium_id") or "").strip().lower()
        compendium_ids_raw = body.get("compendium_ids")
        compendium_ids: list[str] = []
        if isinstance(compendium_ids_raw, list):
            for value in compendium_ids_raw:
                cid = str(value or "").strip().lower()
                if cid and cid not in compendium_ids:
                    compendium_ids.append(cid)
        if compendium_id and compendium_id not in compendium_ids:
            compendium_ids.append(compendium_id)
        if include_local and "local_library" not in compendium_ids:
            compendium_ids.append("local_library")
        k_raw = body.get("k")
        try:
            k = max(1, min(20, int(k_raw))) if k_raw is not None else 8
        except Exception:
            k = 8

        def source_priority(row: dict) -> tuple[int, float]:
            cid = str(row.get("compendium_id") or "").strip().lower()
            if cid == "local_library":
                return (0, -float(row.get("score") or 0.0))
            return (2, -float(row.get("score") or 0.0))

        try:
            if compendium_ids:
                merged_items: list[dict] = []
                seen_keys: set[str] = set()
                for cid in compendium_ids:
                    vec_part = vector_query_index(
                        output_root=vector_index_root(),
                        query=q,
                        k=k,
                        compendium_id=cid,
                    )
                    part_items = vec_part.get("items") if isinstance(vec_part, dict) else []
                    part_items = part_items if isinstance(part_items, list) else []
                    for item in part_items:
                        if not isinstance(item, dict):
                            continue
                        key = (
                            f"{str(item.get('compendium_id') or '')}|"
                            f"{str(item.get('source_path') or '')}|"
                            f"{str(item.get('heading') or '')}|"
                            f"{str(item.get('text') or '')[:160]}"
                        )
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        merged_items.append(item)
                merged_items.sort(key=source_priority)
                vec = {"items": merged_items[:k]}
            else:
                vec = vector_query_index(
                    output_root=vector_index_root(),
                    query=q,
                    k=k,
                    compendium_id=compendium_id,
                )
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:
            return jsonify({"error": f"vector query failed: {exc}"}), 400

        items = vec.get("items") if isinstance(vec, dict) else []
        items = items if isinstance(items, list) else []
        citations = []
        context_lines = []
        for idx, item in enumerate(items, start=1):
            source_path = str(item.get("source_path") or "").strip()
            heading = str(item.get("heading") or "").strip()
            snippet = str(item.get("text") or "").strip()
            score = float(item.get("score") or 0.0)
            citations.append({
                "n": idx,
                "compendium_id": str(item.get("compendium_id") or ""),
                "source_path": source_path,
                "heading": heading,
                "score": score,
            })
            context_lines.append(
                f"[{idx}] source={source_path} heading={heading}\n{snippet}"
            )

        lore_items: list[dict] = []
        lore_citations: list[dict] = []
        lore_context = "No lore context available."
        if include_lore:
            lore_items, lore_citations, lore_context = _build_lore_context(
                q,
                setting=setting,
                location=location,
                k=max(2, min(6, k // 2 or 2)),
                focus_type="lore",
            )
            if lore_context != "No lore context available.":
                context_lines.insert(0, lore_context)

        grounded_context = "\n\n".join(context_lines) if context_lines else "No vector context available."
        grounding_instruction = (
            "Answer only from the supplied context. Do not invent facts, pantheons, deities, practices, or setting details that are not supported by the cited chunks. "
            "If the context is ambiguous or insufficient, say so plainly. Treat place names, cultures, factions, and religions as distinct unless the context explicitly equates them. "
            "Prefer short, specific answers over generic fantasy filler, and cite claims with [n] where possible."
        )
        prompt = (
            f"{system_prompt}\n\n"
            f"Instructions:\n{grounding_instruction}\n\n"
            f"Question:\n{q}\n\n"
            f"Context:\n{grounded_context}\n\n"
            "Answer:"
        ).strip()

        try:
            reply = ollama_post_json(
                base_url,
                "/api/generate",
                {
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": keep_alive,
                    "options": {
                        "temperature": 0.2,
                    },
                },
                timeout=240,
            )
            answer = str(reply.get("response") or "").strip()
        except Exception as exc:
            return jsonify({
                "error": f"ollama request failed: {exc}",
                "base_url": base_url,
                "model": model,
            }), 502

        return jsonify({
            "answer": answer,
            "query": q,
            "base_url": base_url,
            "model": model,
            "keep_alive": keep_alive,
            "system_prompt_set": bool(system_prompt),
            "k": k,
            "compendium_ids": compendium_ids,
            "citation_count": len(citations) + len(lore_citations),
            "citations": citations + lore_citations,
            "vector_items": items + lore_items,
        })

    @app.get("/plugins/openai-remote/health")
    def api_openai_remote_health():
        if not is_plugin_enabled("openai_remote"):
            return jsonify({"error": "openai_remote plugin is disabled"}), 403
        base_url = normalize_http_base_url(request.args.get("base_url"), openai_base_url())
        model = openai_default_model()
        key = openai_api_key()
        if not key:
            return jsonify({
                "plugin": "openai_remote",
                "base_url": base_url,
                "up": False,
                "error": "api_key is not set",
                "default_model": model,
                "system_prompt_set": bool(openai_system_prompt()),
            }), 400
        try:
            data = openai_post_json(
                base_url,
                "/v1/chat/completions",
                {
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
                    "max_tokens": 8,
                    "temperature": 0,
                },
                api_key=key,
                timeout=45,
            )
            choices = data.get("choices") if isinstance(data, dict) else []
            up = isinstance(choices, list) and len(choices) > 0
            return jsonify({
                "plugin": "openai_remote",
                "base_url": base_url,
                "up": bool(up),
                "default_model": model,
                "system_prompt_set": bool(openai_system_prompt()),
            })
        except Exception as exc:
            return jsonify({
                "plugin": "openai_remote",
                "base_url": base_url,
                "up": False,
                "error": str(exc),
                "default_model": model,
                "system_prompt_set": bool(openai_system_prompt()),
            }), 502

    @app.post("/plugins/openai-remote/query")
    def api_openai_remote_query():
        if not is_plugin_enabled("openai_remote"):
            return jsonify({"error": "openai_remote plugin is disabled"}), 403
        body = request.get_json(force=True, silent=False) or {}
        q = str(body.get("q") or "").strip()
        if not q:
            return jsonify({"error": "q is required"}), 400
        model = str(body.get("model") or openai_default_model()).strip()
        system_prompt = str(body.get("system_prompt") or openai_system_prompt()).strip()
        base_url = normalize_http_base_url(body.get("base_url"), openai_base_url())
        api_key = str(body.get("api_key") or openai_api_key()).strip()
        if not api_key:
            return jsonify({"error": "api_key is required in plugin settings or request"}), 400
        include_local = bool(body.get("include_local", True))
        include_lore = bool(body.get("include_lore", False))
        setting = str(body.get("setting") or "").strip()
        location = str(body.get("location") or "").strip()

        compendium_id = str(body.get("compendium_id") or "").strip().lower()
        compendium_ids_raw = body.get("compendium_ids")
        compendium_ids: list[str] = []
        if isinstance(compendium_ids_raw, list):
            for value in compendium_ids_raw:
                cid = str(value or "").strip().lower()
                if cid and cid not in compendium_ids:
                    compendium_ids.append(cid)
        if compendium_id and compendium_id not in compendium_ids:
            compendium_ids.append(compendium_id)
        if include_local and "local_library" not in compendium_ids:
            compendium_ids.append("local_library")
        k_raw = body.get("k")
        try:
            k = max(1, min(20, int(k_raw))) if k_raw is not None else 8
        except Exception:
            k = 8

        def source_priority(row: dict) -> tuple[int, float]:
            cid = str(row.get("compendium_id") or "").strip().lower()
            if cid == "local_library":
                return (0, -float(row.get("score") or 0.0))
            return (2, -float(row.get("score") or 0.0))

        try:
            if compendium_ids:
                merged_items: list[dict] = []
                seen_keys: set[str] = set()
                for cid in compendium_ids:
                    vec_part = vector_query_index(
                        output_root=vector_index_root(),
                        query=q,
                        k=k,
                        compendium_id=cid,
                    )
                    part_items = vec_part.get("items") if isinstance(vec_part, dict) else []
                    part_items = part_items if isinstance(part_items, list) else []
                    for item in part_items:
                        if not isinstance(item, dict):
                            continue
                        key = (
                            f"{str(item.get('compendium_id') or '')}|"
                            f"{str(item.get('source_path') or '')}|"
                            f"{str(item.get('heading') or '')}|"
                            f"{str(item.get('text') or '')[:160]}"
                        )
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        merged_items.append(item)
                merged_items.sort(key=source_priority)
                vec = {"items": merged_items[:k]}
            else:
                vec = vector_query_index(
                    output_root=vector_index_root(),
                    query=q,
                    k=k,
                    compendium_id=compendium_id,
                )
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:
            return jsonify({"error": f"vector query failed: {exc}"}), 400

        items = vec.get("items") if isinstance(vec, dict) else []
        items = items if isinstance(items, list) else []
        citations = []
        context_lines = []
        for idx, item in enumerate(items, start=1):
            source_path = str(item.get("source_path") or "").strip()
            heading = str(item.get("heading") or "").strip()
            snippet = str(item.get("text") or "").strip()
            score = float(item.get("score") or 0.0)
            citations.append({
                "n": idx,
                "compendium_id": str(item.get("compendium_id") or ""),
                "source_path": source_path,
                "heading": heading,
                "score": score,
            })
            context_lines.append(f"[{idx}] source={source_path} heading={heading}\n{snippet}")

        lore_items: list[dict] = []
        lore_citations: list[dict] = []
        lore_context = "No lore context available."
        if include_lore:
            lore_items, lore_citations, lore_context = _build_lore_context(
                q,
                setting=setting,
                location=location,
                k=max(2, min(6, k // 2 or 2)),
                focus_type="lore",
            )
            if lore_context != "No lore context available.":
                context_lines.insert(0, lore_context)

        grounded_context = "\n\n".join(context_lines) if context_lines else "No vector context available."
        grounding_instruction = (
            "Answer only from the supplied context. Do not invent facts, pantheons, deities, practices, or setting details that are not supported by the cited chunks. "
            "If the context is ambiguous or insufficient, say so plainly. Treat place names, cultures, factions, and religions as distinct unless the context explicitly equates them. "
            "Prefer short, specific answers over generic fantasy filler, and cite claims with [n]."
        )
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({
            "role": "user",
            "content": (
                f"Instructions:\n{grounding_instruction}\n\n"
                f"Question:\n{q}\n\n"
                f"Context:\n{grounded_context}\n\n"
                "Answer with citations like [n] where possible."
            ),
        })

        try:
            reply = openai_post_json(
                base_url,
                "/v1/chat/completions",
                {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.2,
                },
                api_key=api_key,
                timeout=240,
            )
            choices = reply.get("choices") if isinstance(reply, dict) else []
            answer = ""
            if isinstance(choices, list) and choices:
                first = choices[0] if isinstance(choices[0], dict) else {}
                message = first.get("message") if isinstance(first.get("message"), dict) else {}
                answer = str(message.get("content") or "").strip()
        except Exception as exc:
            return jsonify({
                "error": f"openai request failed: {exc}",
                "base_url": base_url,
                "model": model,
            }), 502

        return jsonify({
            "answer": answer,
            "query": q,
            "base_url": base_url,
            "model": model,
            "system_prompt_set": bool(system_prompt),
            "k": k,
            "compendium_ids": compendium_ids,
            "citation_count": len(citations) + len(lore_citations),
            "citations": citations + lore_citations,
            "vector_items": items + lore_items,
        })

    @app.get("/compendiums")
    def api_compendiums_list():
        compendium_dir = current_app.config["LOL_COMPENDIUM_DIR"]
        official_dir = current_app.config["LOL_OFFICIAL_COMPENDIUM_DIR"]

        def bucket_count(value: object) -> int:
            if value is None:
                return 0
            if isinstance(value, int):
                return value
            if isinstance(value, (list, tuple, set, dict)):
                return len(value)
            return 0

        csrd_index = load_compendium_index(compendium_dir) or {}
        csrd_stats = {
            "foci": bucket_count(csrd_index.get("foci")),
            "types": bucket_count(csrd_index.get("types")),
            "descriptors": bucket_count(csrd_index.get("descriptors")),
            "creatures": bucket_count(csrd_index.get("creatures")),
            "cyphers": bucket_count(csrd_index.get("cyphers")),
            "artifacts": bucket_count(csrd_index.get("artifacts")),
        }

        def book_stats(items: list[dict], *, compendium_id: str, book_title: str, profile_name: str) -> dict[str, int]:
            aliases = {
                str(compendium_id or "").strip().lower(),
                _safe_slug(compendium_id),
                str(book_title or "").strip().lower(),
                _safe_slug(book_title),
                str(profile_name or "").strip().lower(),
                _safe_slug(profile_name),
            }
            aliases = {x for x in aliases if x}
            subset = [
                row for row in items
                if (
                    str(row.get("book") or "").strip().lower() in aliases
                    or _safe_slug(str(row.get("book") or "")) in aliases
                )
            ]
            counts: dict[str, int] = {}
            for row in subset:
                t = str(row.get("type") or "").strip().lower()
                if not t:
                    continue
                counts[t] = counts.get(t, 0) + 1
            return {
                "npcs": int(counts.get("npc") or 0),
                "creatures": int(counts.get("creature") or 0),
                "foci": int(counts.get("focus") or 0),
                "descriptors": int(counts.get("descriptor") or 0),
                "cyphers": int(counts.get("cypher") or 0),
                "artifacts": int(counts.get("artifact") or 0),
            }

        def foundry_stats() -> dict[str, int]:
            counts = foundry_counts_by_type()
            return {
                "characters": int(counts.get("character") or 0),
                "character_sheets": int(counts.get("character_sheet") or 0),
                "npcs": int(counts.get("npc") or 0),
                "creatures": int(counts.get("creature") or 0),
                "cyphers": int(counts.get("cypher") or 0),
                "artifacts": int(counts.get("artifact") or 0),
                "attacks": int(counts.get("attack") or 0),
                "abilities": int(counts.get("ability") or 0),
                "skills": int(counts.get("skill") or 0),
                "equipment": int(counts.get("equipment") or 0),
            }

        official_index = load_official_compendium_index(official_dir) or {}
        official_items = official_index.get("items") or []
        profiles = load_compendium_profiles()
        official_counts_by_cid = official_book_item_count_by_compendium_id()
        csrd_profile = profiles.get("csrd", {})
        csrd_pipeline = compendium_pipeline_status(
            {"id": "csrd", **csrd_profile},
            source_kind="csrd",
            auto_start=False,
        )
        nav = configured_settings_nav() or {}
        genre_options = [
            row for row in (nav.get("genre_options") or nav.get("core_options") or [])
            if str((row or {}).get("value") or "").strip().lower() != "all_settings"
        ]
        settings_by_genre = nav.get("settings_by_genre") or nav.get("worlds_by_core") or {}
        total_child_settings = 0
        if isinstance(settings_by_genre, dict):
            for values in settings_by_genre.values():
                if isinstance(values, list):
                    total_child_settings += len(values)
        items = [
            {
                "id": "csrd",
                "name": csrd_profile.get("name") or "CSRD",
                "subtitle": csrd_profile.get("subtitle") or "Cypher System Reference Document",
                "thumbnail_url": csrd_profile.get("thumbnail_url") or "/images/CypherLogo/CSOL%20Logo-Cypher%20System%20Compatible-Color%20with%20White-Small.png",
                "stats": csrd_stats,
                "landing_url": "/compendiums/csrd",
                "search_url": "/search?include_local=0&include_lore=0&compendiums=csrd",
                "profile_path": csrd_profile.get("profile_path") or "",
                "pdf_relative_path": csrd_profile.get("pdf_relative_path") or "",
                "source_kind": "csrd",
                "tags": compendium_taxonomy_tags(csrd_profile, source_kind="csrd", compendium_id="csrd"),
                "enabled": bool(csrd_pipeline.get("enabled", True)),
                "pipeline": csrd_pipeline,
            },
            {
                "id": "settings_catalog",
                "name": "Settings Catalog",
                "subtitle": "Genres and settings available in this workspace",
                "thumbnail_url": "/images/CypherLogo/CSOL%20Logo-Cypher%20System%20Compatible-Color%20with%20White-Small.png",
                "stats": {
                    "genres": len(genre_options),
                    "settings": int(total_child_settings),
                },
                "landing_url": "/settings",
                "search_url": "/search?include_local=1&include_lore=0&include_csrd=0&include_official=0&include_foundry=0",
                "profile_path": "",
                "pdf_relative_path": "",
                "source_kind": "settings_catalog",
                "tags": compendium_taxonomy_tags({}, source_kind="settings_catalog", compendium_id="settings_catalog"),
                "enabled": True,
                "searchable": False,
                "pipeline": {
                    "enabled": True,
                    "pdf_present": False,
                    "docling_processed": False,
                    "parser_processed": True,
                },
            },
        ]
        official_profiles = [
            p for pid, p in sorted(profiles.items(), key=lambda kv: kv[1].get("name", kv[0]).lower())
            if pid not in {"csrd", FOUNDRY_COMPENDIUM_ID}
        ]
        for profile in official_profiles:
            pid = str(profile.get("id") or "").strip().lower()
            if not pid:
                continue
            book_title = str(profile.get("book_title") or profile.get("name") or "").strip()
            stats = book_stats(
                official_items,
                compendium_id=pid,
                book_title=book_title,
                profile_name=str(profile.get("name") or ""),
            )
            source_kind = compendium_source_kind(pid, profile)
            pipeline = compendium_pipeline_status(
                profile,
                source_kind=source_kind,
                parser_count=official_counts_by_cid.get(pid, 0),
                auto_start=False,
            )
            if not pipeline.get("enabled", True):
                continue
            items.append({
                "id": pid,
                "name": _display_sourcebook_label(profile.get("name") or pid.title()),
                "subtitle": profile.get("subtitle") or "Official Sourcebook (Private Import)",
                "thumbnail_url": profile.get("thumbnail_url") or "/images/CypherLogo/CSOL%20Logo-Cypher%20System%20Compatible-Color%20with%20White-Small.png",
                "stats": stats,
                "landing_url": f"/compendiums/{pid}",
                "search_url": f"/search?include_local=0&include_lore=0&compendiums={pid}",
                "profile_path": profile.get("profile_path") or "",
                "pdf_relative_path": profile.get("pdf_relative_path") or "",
                "source_kind": source_kind,
                "tags": compendium_taxonomy_tags(profile, source_kind=source_kind, compendium_id=pid),
                "enabled": True,
                "pipeline": pipeline,
            })

        foundry_profile = profiles.get(FOUNDRY_COMPENDIUM_ID, {})
        items.append({
            "id": FOUNDRY_COMPENDIUM_ID,
            "name": foundry_profile.get("name") or "FoundryVTT",
            "subtitle": foundry_profile.get("subtitle") or "Synced Foundry imports",
            "thumbnail_url": foundry_profile.get("thumbnail_url") or "/images/CypherLogo/CSOL%20Logo-Cypher%20System%20Compatible-Color%20with%20White-Small.png",
            "stats": foundry_stats(),
            "landing_url": f"/compendiums/{FOUNDRY_COMPENDIUM_ID}",
            "search_url": f"/search?include_local=0&include_lore=0&include_csrd=0&include_official=0&include_foundry=1&compendiums={FOUNDRY_COMPENDIUM_ID}",
            "profile_path": foundry_profile.get("profile_path") or "",
            "pdf_relative_path": foundry_profile.get("pdf_relative_path") or "",
            "source_kind": "foundry",
            "tags": compendium_taxonomy_tags(foundry_profile, source_kind="foundry", compendium_id=FOUNDRY_COMPENDIUM_ID),
            "enabled": True,
            "pipeline": {
                "enabled": True,
                "pdf_present": False,
                "docling_processed": False,
                "parser_processed": True,
            },
        })

        return jsonify({"items": items, "count": len(items)})

    @app.get("/compendiums/<compendium_id>")
    def compendium_landing_page(compendium_id: str):
        cid = str(compendium_id or "").strip().lower()
        project_root = current_app.config["LOL_PROJECT_ROOT"]
        profile_path = project_root / "PDF_Repository" / "private_compendium" / "compendiums" / f"{cid}.json"
        if cid not in {"csrd", FOUNDRY_COMPENDIUM_ID} and not profile_path.exists():
            return jsonify({"error": f"unknown compendium '{compendium_id}'"}), 404
        return render_template("compendium_landing.html", compendium_id=cid)

    @app.get("/compendiums/<compendium_id>/details")
    def api_compendium_details(compendium_id: str):
        cid = str(compendium_id or "").strip().lower()
        project_root = current_app.config["LOL_PROJECT_ROOT"]
        compendium_dir = current_app.config["LOL_COMPENDIUM_DIR"]
        official_dir = current_app.config["LOL_OFFICIAL_COMPENDIUM_DIR"]
        official_counts_by_cid = official_book_item_count_by_compendium_id()

        def load_profile(profile_id: str) -> dict:
            path = project_root / "PDF_Repository" / "private_compendium" / "compendiums" / f"{profile_id}.json"
            if not path.exists():
                return {}
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
            if not isinstance(data, dict):
                return {}
            data["profile_path"] = str(path.relative_to(project_root)).replace("\\", "/")
            return data

        def file_url_if_exists(rel_path: str) -> str:
            rel = str(rel_path or "").strip().replace("\\", "/").lstrip("/")
            if not rel:
                return ""
            path = (project_root / "PDF_Repository" / rel).resolve()
            root = (project_root / "PDF_Repository").resolve()
            if not str(path).startswith(str(root)) or not path.exists():
                return ""
            return f"/pdf-repository/{rel}"

        if cid == "csrd":
            profile = load_profile("csrd")
            profile.setdefault("id", "csrd")
            csrd_index = load_compendium_index(compendium_dir) or {}
            stats = {
                "abilities": int(csrd_index.get("abilities") or 0),
                "skills": int(csrd_index.get("skills") or 0),
                "foci": int(csrd_index.get("foci") or 0),
                "descriptors": int(csrd_index.get("descriptors") or 0),
                "types": int(csrd_index.get("types") or 0),
                "flavors": int(csrd_index.get("flavors") or 0),
                "creatures": int(csrd_index.get("creatures") or 0),
                "cyphers": int(csrd_index.get("cyphers") or 0),
                "artifacts": int(csrd_index.get("artifacts") or 0),
            }
            summary = profile.get("summary") or [
                "The CSRD compendium contains core Cypher System reference material organized by rules category.",
                "Use this as the baseline source for abilities, skills, foci, descriptors, creatures, cyphers, and artifacts.",
            ]
            contents = profile.get("contents") or [
                {"label": "Rules Content", "items": ["Abilities", "Skills", "Types", "Flavors", "Descriptors", "Foci"]},
                {"label": "Game Elements", "items": ["Creatures", "Cyphers", "Artifacts"]},
            ]
            pipeline = compendium_pipeline_status(profile, source_kind="csrd", auto_start=False)
            return jsonify({
                "id": "csrd",
                "name": profile.get("name") or "CSRD",
                "subtitle": profile.get("subtitle") or "Cypher System Reference Document",
                "thumbnail_url": profile.get("thumbnail_url") or "/images/CypherLogo/CSOL%20Logo-Cypher%20System%20Compatible-Color%20with%20White-Small.png",
                "stats": stats,
                "summary": summary,
                "contents": contents,
                "pdf_url": file_url_if_exists(str(profile.get("pdf_relative_path") or "")),
                "search_url": "/search?include_local=0&include_lore=0&compendiums=csrd",
                "profile_path": profile.get("profile_path") or "",
                "enabled": bool(pipeline.get("enabled", True)),
                "pipeline": pipeline,
                "raw_text_url": pipeline.get("raw_text_url") or "",
                "tags": compendium_taxonomy_tags(profile, source_kind="csrd", compendium_id="csrd"),
                "foundry_sync": compendium_foundry_sync_state("csrd"),
            })

        if cid == FOUNDRY_COMPENDIUM_ID:
            profile = load_profile(FOUNDRY_COMPENDIUM_ID)
            foundry_items = collect_foundry_compendium_rows()
            counts_by_type = foundry_counts_by_type()
            names_by_type: dict[str, list[str]] = {}
            for row in foundry_items:
                item_type = str(row.get("type") or "").strip().lower()
                title = str(row.get("name") or "").strip()
                if not item_type:
                    continue
                if title:
                    names_by_type.setdefault(item_type, []).append(title)
                    if item_type == "monster":
                        names_by_type.setdefault("creature", []).append(title)

            for key in names_by_type:
                names_by_type[key] = sorted(names_by_type[key])[:12]

            stats = {
                "characters": int(counts_by_type.get("character") or 0),
                "character_sheets": int(counts_by_type.get("character_sheet") or 0),
                "npcs": int(counts_by_type.get("npc") or 0),
                "creatures": int(counts_by_type.get("creature") or 0),
                "cyphers": int(counts_by_type.get("cypher") or 0),
                "artifacts": int(counts_by_type.get("artifact") or 0),
                "attacks": int(counts_by_type.get("attack") or 0),
                "abilities": int(counts_by_type.get("ability") or 0),
                "skills": int(counts_by_type.get("skill") or 0),
                "equipment": int(counts_by_type.get("equipment") or 0),
            }

            type_label_map = {
                "character": "Player Characters",
                "character_sheet": "Player Characters",
                "npc": "NPCs",
                "creature": "Creatures",
                "cypher": "Cyphers",
                "artifact": "Artifacts",
                "attack": "Attacks",
                "ability": "Abilities",
                "skill": "Skills",
                "equipment": "Equipment",
            }
            contents = []
            for key in ("character", "character_sheet", "npc", "creature", "cypher", "artifact", "attack", "ability", "skill", "equipment"):
                entries = names_by_type.get(key) or []
                if entries:
                    contents.append({"label": type_label_map.get(key, key.title()), "items": entries})

            summary = profile.get("summary") or [
                "FoundryVTT sync imports are stored as a private compendium inside GMTools.",
                "Use this source to search and manage data imported from your Foundry world.",
            ]
            return jsonify({
                "id": FOUNDRY_COMPENDIUM_ID,
                "name": profile.get("name") or "FoundryVTT",
                "subtitle": profile.get("subtitle") or "Synced Foundry imports",
                "thumbnail_url": profile.get("thumbnail_url") or "/images/CypherLogo/CSOL%20Logo-Cypher%20System%20Compatible-Color%20with%20White-Small.png",
                "stats": stats,
                "summary": summary,
                "contents": profile.get("contents") or contents,
                "pdf_url": "",
                "search_url": f"/search?include_local=0&include_lore=0&include_csrd=0&include_official=0&include_foundry=1&compendiums={FOUNDRY_COMPENDIUM_ID}",
                "profile_path": profile.get("profile_path") or "",
                "source_kind": "foundry",
                "enabled": True,
                "pipeline": {
                    "enabled": True,
                    "pdf_present": False,
                    "docling_processed": False,
                    "parser_processed": True,
                },
                "raw_text_url": "",
                "tags": compendium_taxonomy_tags(profile, source_kind="foundry", compendium_id=FOUNDRY_COMPENDIUM_ID),
                "foundry_sync": compendium_foundry_sync_state(FOUNDRY_COMPENDIUM_ID),
            })

        if cid != "csrd":
            profile = load_profile(cid)
            if not profile:
                return jsonify({"error": f"unknown compendium '{compendium_id}'"}), 404
            official_index = load_official_compendium_index(official_dir) or {}
            items = official_index.get("items") or []
            book_title = str(profile.get("book_title") or profile.get("name") or "").strip()
            items = [
                row for row in items
                if str(row.get("book") or "").strip().lower() == book_title.lower()
            ]
            counts_by_type: dict[str, int] = {}
            for row in items:
                t = str(row.get("type") or "").strip().lower()
                if not t:
                    continue
                counts_by_type[t] = counts_by_type.get(t, 0) + 1
            by_type: dict[str, list[str]] = {}
            for row in items:
                item_type = str(row.get("type") or "").strip().lower()
                title = str(row.get("title") or "").strip()
                if not item_type or not title:
                    continue
                by_type.setdefault(item_type, []).append(title)
            for key in by_type:
                by_type[key] = sorted(by_type[key])[:12]

            stats = {
                "npcs": int(counts_by_type.get("npc") or 0),
                "creatures": int(counts_by_type.get("creature") or 0),
                "foci": int(counts_by_type.get("focus") or 0),
                "descriptors": int(counts_by_type.get("descriptor") or 0),
                "cyphers": int(counts_by_type.get("cypher") or 0),
                "artifacts": int(counts_by_type.get("artifact") or 0),
            }
            contents = []
            type_label_map = {
                "npc": "NPCs",
                "creature": "Creatures",
                "focus": "Foci",
                "descriptor": "Descriptors",
                "cypher": "Cyphers",
                "artifact": "Artifacts",
            }
            for key in ("npc", "creature", "focus", "descriptor", "cypher", "artifact"):
                names = by_type.get(key) or []
                if names:
                    contents.append({"label": type_label_map.get(key, key.title()), "items": names})

            summary = profile.get("summary") or [
                f"{book_title} is an official sourcebook imported into private local storage.",
                "Entries remain local and are searchable alongside house and CSRD sources.",
            ]
            source_kind = compendium_source_kind(cid, profile)
            pipeline = compendium_pipeline_status(
                profile,
                source_kind=source_kind,
                parser_count=official_counts_by_cid.get(cid, 0),
                auto_start=True,
            )
            return jsonify({
                "id": cid,
                "name": profile.get("name") or book_title,
                "subtitle": profile.get("subtitle") or "Official Fantasy Sourcebook (Private Import)",
                "thumbnail_url": profile.get("thumbnail_url") or "/images/CypherLogo/CSOL%20Logo-Cypher%20System%20Compatible-Color%20with%20White-Small.png",
                "stats": stats,
                "summary": summary,
                "contents": profile.get("contents") or contents,
                "pdf_url": file_url_if_exists(str(profile.get("pdf_relative_path") or "")),
                "search_url": f"/search?include_local=0&include_lore=0&compendiums={cid}",
                "profile_path": profile.get("profile_path") or "",
                "source_kind": source_kind,
                "enabled": bool(pipeline.get("enabled", True)),
                "pipeline": pipeline,
                "raw_text_url": pipeline.get("raw_text_url") or "",
                "tags": compendium_taxonomy_tags(profile, source_kind=source_kind, compendium_id=cid),
                "foundry_sync": compendium_foundry_sync_state(cid),
            })

        return jsonify({"error": f"unknown compendium '{compendium_id}'"}), 404

    @app.get("/compendiums/<compendium_id>/raw-text")
    def api_compendium_raw_text(compendium_id: str):
        cid = str(compendium_id or "").strip().lower()
        rel = str(request.args.get("path") or "").strip().replace("\\", "/")
        if not rel:
            return jsonify({"error": "path query parameter is required"}), 400
        root = docling_root().resolve()
        target = (root / rel).resolve()
        if not str(target).startswith(str(root)):
            return jsonify({"error": "invalid raw text path"}), 400
        if not target.exists() or not target.is_file() or target.suffix.lower() != ".md":
            return jsonify({"error": "raw text file not found"}), 404
        if cid and cid not in target.parts:
            # Keep the check loose for backward compat, but ensure we're still inside _docling root.
            pass
        return send_file(target, mimetype="text/markdown")

    @app.post("/compendiums/<compendium_id>/foundry-sync")
    def api_compendium_foundry_sync(compendium_id: str):
        cid = str(compendium_id or "").strip().lower()
        if not cid:
            return jsonify({"error": "compendium_id is required"}), 400
        if cid in {"settings_catalog", FOUNDRY_COMPENDIUM_ID}:
            return jsonify({"error": f"foundry sync is not configurable for '{cid}'"}), 400

        foundry_plugin = next(
            (item for item in discover_plugins() if str(item.get("id") or "").strip() == "foundryVTT"),
            None,
        )
        if not foundry_plugin:
            return jsonify({"error": "foundryVTT plugin is not present"}), 404

        body = request.get_json(force=True, silent=True) or {}
        enabled = bool(body.get("enabled"))
        key = foundry_sync_compendium_key(cid)
        settings = update_plugin_settings("foundryVTT", {key: "1" if enabled else "0"})
        raw = str(settings.get(key) or "0").strip().lower()
        current = raw not in {"0", "false", "off", "no"}
        return jsonify({
            "compendium_id": cid,
            "foundry_sync_enabled": current,
            "key": key,
        })

    @app.get("/vector/stats")
    def api_vector_stats():
        stats = vector_stats_index(output_root=vector_index_root())
        return jsonify(stats)

    @app.get("/vector/query")
    def api_vector_query():
        q = str(request.args.get("q") or "").strip()
        if not q:
            return jsonify({"error": "q is required"}), 400
        k_raw = str(request.args.get("k") or "8").strip()
        k = 8
        if k_raw.isdigit():
            k = max(1, min(50, int(k_raw)))
        compendium_id = str(request.args.get("compendium_id") or "").strip().lower()
        result = vector_query_index(
            output_root=vector_index_root(),
            query=q,
            k=k,
            compendium_id=compendium_id,
        )
        return jsonify(result)

    @app.post("/vector/storage/sync")
    def api_vector_storage_sync():
        summary = sync_storage_index(
            storage_root=current_app.config["LOL_STORAGE_DIR"],
            output_root=vector_index_root(),
        )
        return jsonify({"ok": True, **summary})

    @app.get("/pdf-repository/<path:filename>")
    def pdf_repository_file(filename: str):
        rel = str(filename or "").replace("\\", "/").lstrip("/")
        if not rel.lower().endswith(".pdf"):
            return jsonify({"error": "only PDF files are supported"}), 400
        root = (current_app.config["LOL_PROJECT_ROOT"] / "PDF_Repository").resolve()
        target = (root / rel).resolve()
        if not str(target).startswith(str(root)) or not target.exists():
            return jsonify({"error": "pdf not found"}), 404
        return send_from_directory(root, rel)

    @app.get("/character-studio")
    def character_studio():
        return render_template("character_studio.html")

    @app.get("/media/images")
    def api_media_images_list():
        q = str(request.args.get("q") or "").strip().lower()
        tag = str(request.args.get("tag") or "").strip().lower()
        normalized_tag = normalize_setting_token(tag) if tag else ""
        path_filter = normalize_image_ref(str(request.args.get("path") or ""))
        refresh_catalog = str(request.args.get("refresh") or "").strip().lower() in {"1", "true", "yes"}
        files = list_image_assets(refresh_catalog=refresh_catalog)
        if path_filter:
            files = [item for item in files if normalize_image_ref(str(item.get("path") or "")) == path_filter]
        if q:
            files = [
                item for item in files
                if q in " ".join([
                    str(item.get("path") or ""),
                    str(item.get("friendly_name") or ""),
                    str(item.get("description") or ""),
                    " ".join(item.get("tags") or []),
                    " ".join(
                        str(row.get("label") or row.get("id") or "")
                        for row in (item.get("attached_to") or [])
                        if isinstance(row, dict)
                    ),
                ]).lower()
            ]
        if tag:
            files = [
                item for item in files
                if any(
                    tag == str(x).strip().lower() or normalized_tag == normalize_setting_token(x)
                    for x in (item.get("tags") or [])
                )
            ]
        return jsonify({"items": files, "count": len(files), "filters": {"q": q, "tag": normalized_tag or tag, "path": path_filter, "refresh": refresh_catalog}})

    @app.post("/media/images/upload")
    def api_media_images_upload():
        uploaded = request.files.get("file")
        if uploaded is None:
            return jsonify({"error": "file is required"}), 400
        raw_name = secure_filename(uploaded.filename or "")
        suffix = Path(raw_name).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            return jsonify({"error": f"unsupported image type '{suffix or 'unknown'}'"}), 400

        images_dir = current_app.config["LOL_IMAGES_DIR"]
        upload_dir = images_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(raw_name).stem or "image"
        final_name = f"{stem}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}{suffix}"
        path = upload_dir / final_name
        uploaded.save(path)

        rel = str(path.relative_to(images_dir)).replace("\\", "/")
        catalog = load_image_catalog()
        friendly_name = str(request.form.get("friendly_name") or "").strip()
        tags_raw = str(request.form.get("tags") or "")
        tags = sorted(set(
            str(x).strip().lower().replace(" ", "_")
            for x in tags_raw.split(",")
            if str(x).strip()
        ))
        description = str(request.form.get("description") or request.form.get("notes") or "").strip()
        catalog[rel] = {
            "friendly_name": friendly_name,
            "tags": tags,
            "description": description,
            "attached_to": [],
        }
        save_image_catalog(catalog)
        return jsonify({
            "ok": True,
            "path": rel,
            "url": f"/images/{rel}",
            "name": path.name,
            "friendly_name": friendly_name,
            "tags": tags,
            "description": description,
            "attached_to": [],
        })

    @app.post("/media/images/meta")
    def api_media_images_meta_update():
        body = request.get_json(force=True, silent=False) or {}
        image_ref = normalize_image_ref(str(body.get("image") or ""))
        if not image_ref:
            return jsonify({"error": "image is required"}), 400
        image_path = resolve_image_ref_path(image_ref)
        if not image_path.exists():
            return jsonify({"error": f"image not found: {image_ref}"}), 404

        tags_raw = body.get("tags") if isinstance(body.get("tags"), list) else str(body.get("tags") or "").split(",")
        tags = sorted(set(str(x).strip().lower().replace(" ", "_") for x in tags_raw if str(x).strip()))
        friendly_name = str(body.get("friendly_name") or "").strip()
        description = str(body.get("description") or body.get("notes") or "").strip()

        catalog = load_image_catalog()
        catalog[image_ref] = {
            "friendly_name": friendly_name,
            "tags": tags,
            "description": description,
            "attached_to": list((catalog.get(image_ref) or {}).get("attached_to") or []),
        }
        save_image_catalog(catalog)
        return jsonify({
            "ok": True,
            "item": {
                "path": image_ref,
                "url": f"/images/{image_ref}",
                "name": image_path.name,
                "friendly_name": friendly_name,
                "tags": tags,
                "description": description,
                "attached_to": list((catalog.get(image_ref) or {}).get("attached_to") or []),
            },
        })

    @app.post("/ai-generate/image-from-url")
    def api_ai_generate_image_from_url():
        body = request.get_json(force=True, silent=False) or {}
        try:
            image_data_url, image_name, mime_type = _download_image_as_data_url(body.get("url"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"failed to download image: {exc}"}), 400

        return jsonify({
            "ok": True,
            "image_data_url": image_data_url,
            "image_name": image_name,
            "mime_type": mime_type,
            "source_url": str(body.get("url") or "").strip(),
        })

    @app.post("/media/images/attach")
    def api_media_images_attach():
        body = request.get_json(force=True, silent=False) or {}
        target = str(body.get("target") or "").strip().lower()
        target_id = str(body.get("id") or "").strip()
        image_ref = normalize_image_ref(str(body.get("image") or ""))
        if target not in {"storage", "lore"}:
            return jsonify({"error": "target must be 'storage' or 'lore'"}), 400
        if not target_id:
            return jsonify({"error": "id is required"}), 400
        if not image_ref:
            return jsonify({"error": "image is required"}), 400
        path = resolve_image_ref_path(image_ref)
        if not path.exists():
            return jsonify({"error": f"image not found: {image_ref}"}), 404

        if target == "storage":
            if not validate_filename(target_id):
                return jsonify({"error": "invalid storage filename"}), 400
            payload = update_storage_images(target_id, image_ref, action="attach")
        else:
            payload = update_lore_images(target_id, image_ref, action="attach")
        sync_image_catalog_attachments()
        return jsonify({"ok": True, **payload})

    @app.post("/media/images/unattach")
    def api_media_images_unattach():
        body = request.get_json(force=True, silent=False) or {}
        target = str(body.get("target") or "").strip().lower()
        target_id = str(body.get("id") or "").strip()
        image_ref = normalize_image_ref(str(body.get("image") or ""))
        if target not in {"storage", "lore"}:
            return jsonify({"error": "target must be 'storage' or 'lore'"}), 400
        if not target_id:
            return jsonify({"error": "id is required"}), 400
        if not image_ref:
            return jsonify({"error": "image is required"}), 400

        if target == "storage":
            if not validate_filename(target_id):
                return jsonify({"error": "invalid storage filename"}), 400
            payload = update_storage_images(target_id, image_ref, action="unattach")
        else:
            payload = update_lore_images(target_id, image_ref, action="unattach")
        sync_image_catalog_attachments()
        return jsonify({"ok": True, **payload})

    @app.post("/media/images/delete")
    def api_media_images_delete():
        body = request.get_json(force=True, silent=False) or {}
        target = str(body.get("target") or "").strip().lower()
        target_id = str(body.get("id") or "").strip()
        image_ref = normalize_image_ref(str(body.get("image") or ""))
        if not image_ref:
            return jsonify({"error": "image is required"}), 400

        image_path = resolve_image_ref_path(image_ref)
        images_dir = current_app.config["LOL_IMAGES_DIR"].resolve()
        uploads_root = (images_dir / "uploads").resolve()
        if not str(image_path).startswith(str(uploads_root) + "/") and image_path != uploads_root:
            return jsonify({"error": "only images under /images/uploads can be deleted"}), 400

        detached_from: list[dict[str, str]] = []
        if target or target_id:
            if target not in {"storage", "lore"}:
                return jsonify({"error": "target must be 'storage' or 'lore'"}), 400
            if not target_id:
                return jsonify({"error": "id is required"}), 400
            if target == "storage":
                if not validate_filename(target_id):
                    return jsonify({"error": "invalid storage filename"}), 400
                payload = update_storage_images(target_id, image_ref, action="unattach")
            else:
                payload = update_lore_images(target_id, image_ref, action="unattach")
            detached_from.append({"target": target, "id": target_id})
        else:
            payload = {"images": []}
            for row in collect_image_attachment_index().get(image_ref, []):
                row_target = str(row.get("target") or "").strip().lower()
                row_id = str(row.get("id") or "").strip()
                if row_target == "storage":
                    if not validate_filename(row_id):
                        continue
                    update_storage_images(row_id, image_ref, action="unattach")
                    detached_from.append({"target": row_target, "id": row_id})
                elif row_target == "lore":
                    update_lore_images(row_id, image_ref, action="unattach")
                    detached_from.append({"target": row_target, "id": row_id})

        if image_path.exists():
            image_path.unlink()
        catalog = load_image_catalog()
        catalog.pop(image_ref, None)
        save_image_catalog(catalog)
        sync_image_catalog_attachments()
        return jsonify({"ok": True, **payload, "deleted": image_ref, "detached_from": detached_from})

    @app.post("/media/images/dedupe")
    def api_media_images_dedupe():
        summary = dedupe_image_catalog_files()
        return jsonify(summary)

    @app.get("/images/<path:filename>")
    def image_assets(filename: str):
        images_dir = current_app.config["LOL_IMAGES_DIR"]
        return send_from_directory(images_dir, filename)

    @app.get("/meta/races")
    def meta_races():
        config = current_app.config["LOL_CONFIG"]
        return jsonify({"races": config.get("races", {})})

    @app.get("/health")
    def health():
        config = current_app.config["LOL_CONFIG"]
        return jsonify({
            "status": "ok",
            "setting": config.get("setting", {}).get("name", "unknown"),
        })
 
    @app.get("/meta")
    def meta():
        config = current_app.config["LOL_CONFIG"]

        gender_terms = config.get("gender_terms", {})
        genders = sorted(list(gender_terms.keys()))
        if not genders:
            genders = ["female", "male", "nonbinary"]

        all_areas = sorted(list(config.get("areas", {}).keys()))
        monster_area_map = config.get("monster_traits", {}).get("areas", {}) or config.get("monster_traits", {}).get("environments", {})
        monster_environments = sorted(list(monster_area_map.keys()))
        artifact_depletion_table = (
            (
                (config.get("setting", {}) or {})
                .get("cypher_system", {}) or {}
            ).get("artifact_depletion_table", [])
        )
        if not isinstance(artifact_depletion_table, list):
            artifact_depletion_table = []

        return jsonify({
            "types": ["character", "character_sheet", "npc", "creature", "monster", "settlement", "encounter", "cypher", "artifact", "attack", "inn", "skill"],
            "genders": genders,
            "settings": configured_settings_catalog(),
            "genres": configured_settings_catalog(),
            "settings_nav": configured_settings_nav(),
            "active_world": current_app.config.get("LOL_SETTING_ID") or current_app.config.get("LOL_WORLD_ID"),
            "active_setting": current_app.config.get("LOL_SETTING_ID") or current_app.config.get("LOL_WORLD_ID"),
            "available_worlds": current_app.config.get("LOL_AVAILABLE_WORLDS", []),
            "available_settings": current_app.config.get("LOL_AVAILABLE_SETTINGS", current_app.config.get("LOL_AVAILABLE_WORLDS", [])),
            "available_world_descriptors": current_app.config.get("LOL_AVAILABLE_WORLD_DESCRIPTORS", []),
            "available_setting_descriptors": current_app.config.get("LOL_AVAILABLE_SETTING_DESCRIPTORS", current_app.config.get("LOL_AVAILABLE_WORLD_DESCRIPTORS", [])),
            "races": sorted(list(config.get("races", {}).keys())),
            "professions": sorted(list(config.get("professions", {}).keys())),
            "areas": all_areas,
            "environments": all_areas,
            "monster_environments": monster_environments,
            "monster_areas": monster_environments,
            "monster_roles": sorted(list(config.get("monster_roles", {}).keys())),
            "monster_families": sorted(list(config.get("monster_traits", {}).get("families", {}).keys())),
            "styles": sorted(list(config.get("styles", {}).keys())),
            "artifact_depletion_table": artifact_depletion_table,
            "location_category_types": LOCATION_CATEGORY_PRIORITY,
        })
    
    @app.get("/storage")
    def api_storage_list():
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        return jsonify({
            "items": list_saved_results(storage_dir, default_settings=configured_default_settings())
        })
    @app.get("/library")
    def library():
        return redirect("/search")

    @app.get("/trash")
    def trash():
        return render_template("trash.html")

    @app.get("/image-browser")
    def image_browser():
        return render_template("image_browser.html")

    @app.get("/docs-browser")
    def docs_browser():
        return render_template("docs_browser.html")

    def _players_guide_inline(text: str) -> str:
        if not text:
            return ""
        out: list[str] = []
        last = 0
        for match in re.finditer(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", text):
            out.append(html.escape(text[last:match.start()]))
            label = html.escape(match.group(1).strip() or match.group(2).strip())
            href = html.escape(match.group(2).strip(), quote=True)
            out.append(f'<a href="{href}" target="_blank" rel="noopener">{label}</a>')
            last = match.end()
        out.append(html.escape(text[last:]))
        return "".join(out)

    def _preprocess_players_guide_markdown(markdown_text: str) -> str:
        text = markdown_text or ""
        lines = text.splitlines()
        if len(lines) > 5:
            # Front page extraction includes duplicated header lines; drop them.
            lines = lines[5:]
        text = "\n".join(lines)

        # Strip large inline image blobs from Docling output.
        text = DATA_IMAGE_MARKDOWN_RE.sub("", text)

        # Remove full TOC block.
        text = re.sub(
            r"##\s*TABLE OF CONTENTS\b.*?(?=\n##\s+)",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # Remove trailing character sheet section (including everything after it).
        cut_markers = [
            "\n## CHARACTER SHEET\n",
            "\nCHARACTER SHEET\n",
        ]
        cut_index = -1
        for marker in cut_markers:
            idx = text.rfind(marker)
            if idx > cut_index:
                cut_index = idx
        if cut_index >= 0:
            text = text[:cut_index]
        return text.strip()

    def _players_guide_to_html(markdown_text: str) -> str:
        clean_text = _preprocess_players_guide_markdown(markdown_text)
        lines = clean_text.splitlines()
        blocks: list[str] = []
        in_list = False

        def close_list() -> None:
            nonlocal in_list
            if in_list:
                blocks.append("</ul>")
                in_list = False

        for raw_line in lines:
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                close_list()
                continue

            heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            if heading_match:
                close_list()
                level = min(len(heading_match.group(1)), 4)
                title = _players_guide_inline(heading_match.group(2).strip())
                if title:
                    blocks.append(f"<h{level}>{title}</h{level}>")
                continue

            list_match = re.match(r"^[-*]\s+(.*)$", stripped)
            if list_match:
                if not in_list:
                    blocks.append("<ul>")
                    in_list = True
                blocks.append(f"<li>{_players_guide_inline(list_match.group(1).strip())}</li>")
                continue

            close_list()
            blocks.append(f"<p>{_players_guide_inline(stripped)}</p>")

        close_list()
        return "\n".join(blocks)

    @app.get("/players-guide")
    def players_guide_page():
        project_root = current_app.config["LOL_PROJECT_ROOT"]
        source_path = (project_root / PLAYERS_GUIDE_DOC_PATH).resolve()
        source_rel = PLAYERS_GUIDE_DOC_PATH.replace("\\", "/")
        source_exists = source_path.exists() and source_path.is_file()
        rendered_html = ""
        if source_exists:
            markdown_text = source_path.read_text(encoding="utf-8", errors="replace")
            rendered_html = _players_guide_to_html(markdown_text)
        return render_template(
            "players_guide.html",
            source_exists=source_exists,
            source_rel=source_rel,
            players_guide_html=rendered_html,
            old_gus_url="https://callmepartario.github.io/og-csrd/",
        )

    @app.get("/docs/list")
    def api_docs_list():
        docs_dir = current_app.config["LOL_DOCS_DIR"].resolve()
        if not docs_dir.exists():
            return jsonify({"items": [], "count": 0})

        items: list[dict] = []
        for path in sorted(docs_dir.rglob("*"), key=lambda p: str(p).lower()):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(docs_dir).parts):
                continue
            if path.suffix.lower() not in DOCS_SUFFIXES:
                continue
            rel = str(path.relative_to(docs_dir)).replace("\\", "/")
            items.append({
                "path": rel,
                "name": path.name,
                "suffix": path.suffix.lower(),
                "size": path.stat().st_size,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            })

        return jsonify({"items": items, "count": len(items)})

    @app.get("/docs/file")
    def api_docs_file():
        docs_dir = current_app.config["LOL_DOCS_DIR"].resolve()
        rel = str(request.args.get("path") or "").strip()
        if not rel:
            return jsonify({"error": "path query parameter is required"}), 400
        if rel.startswith("/") or ".." in rel.replace("\\", "/").split("/"):
            return jsonify({"error": "invalid docs path"}), 400

        target = (docs_dir / rel).resolve()
        try:
            target.relative_to(docs_dir)
        except ValueError:
            return jsonify({"error": "invalid docs path"}), 400
        if not target.exists() or not target.is_file():
            return jsonify({"error": "document not found"}), 404
        if target.suffix.lower() not in DOCS_SUFFIXES:
            return jsonify({"error": "unsupported document type"}), 400

        text = target.read_text(encoding="utf-8", errors="replace")
        return jsonify({
            "path": str(target.relative_to(docs_dir)).replace("\\", "/"),
            "name": target.name,
            "suffix": target.suffix.lower(),
            "content": text,
            "size": target.stat().st_size,
        })
        
    @app.get("/storage/<path:filename>")
    def api_storage_get(filename: str):
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        return jsonify(load_saved_result(storage_dir, filename, default_settings=configured_default_settings()))

    @app.post("/storage/update")
    def api_storage_update():
        body = request.get_json(force=True, silent=False) or {}
        filename = str(body.get("filename") or "").strip()
        record = body.get("record")
        if not validate_filename(filename):
            return jsonify({"error": "invalid filename"}), 400
        if not isinstance(record, dict):
            return jsonify({"error": "record must be an object"}), 400

        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        try:
            updated = update_saved_result(storage_dir, filename, record)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        vector_sync = sync_saved_record_to_vector(filename)
        return jsonify({"ok": True, "record": updated, "vector_sync": vector_sync})

    @app.post("/storage/mirror-foundry-images")
    def api_storage_mirror_foundry_images():
        body = request.get_json(force=True, silent=False) or {}
        filename = str(body.get("filename") or "").strip()
        if not validate_filename(filename):
            return jsonify({"error": "invalid filename"}), 400

        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        try:
            record = load_saved_result(storage_dir, filename, default_settings=configured_default_settings())
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404

        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        source = str(metadata.get("source") or "").strip().lower()
        if source not in {"foundryvtt", "foundry_vtt"}:
            return jsonify({
                "mirrored": False,
                "reason": "not_foundry_source",
                "record": record,
            })

        before_images = normalize_image_refs(
            metadata.get("images") if isinstance(metadata.get("images"), list) else []
        )
        before_image_url = str(metadata.get("image_url") or "").strip()

        cached_result = cache_foundry_images_for_result(result)
        cached_meta = cached_result.get("metadata") if isinstance(cached_result.get("metadata"), dict) else {}
        after_images = normalize_image_refs(
            cached_meta.get("images") if isinstance(cached_meta.get("images"), list) else []
        )
        after_image_url = str(cached_meta.get("image_url") or "").strip()

        changed = (after_images != before_images) or (after_image_url != before_image_url)
        if not changed:
            return jsonify({
                "mirrored": False,
                "reason": "no_new_local_images",
                "record": record,
            })

        updated_record = dict(record)
        updated_record["result"] = cached_result
        update_saved_result(storage_dir, filename, updated_record)
        refreshed = load_saved_result(storage_dir, filename, default_settings=configured_default_settings())
        vector_sync = sync_saved_record_to_vector(filename)
        return jsonify({
            "mirrored": True,
            "reason": "updated",
            "record": refreshed,
            "vector_sync": vector_sync,
        })

    @app.get("/storage/trash")
    def api_storage_trash_list():
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        items = list_trashed_results(storage_dir)
        return jsonify({"items": items, "count": len(items)})

    @app.get("/storage/trash/<path:filename>")
    def api_storage_trash_get(filename: str):
        if not validate_filename(filename):
            return jsonify({"error": "invalid filename"}), 400
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        try:
            data = load_trashed_result(storage_dir, filename)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify(data)

    @app.post("/storage/trash")
    def api_storage_trash():
        body = request.get_json(force=True, silent=False) or {}
        filename = str(body.get("filename") or "").strip()
        if not validate_filename(filename):
            return jsonify({"error": "invalid filename"}), 400
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        try:
            result = trash_saved_result(storage_dir, filename)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        vector_sync = remove_saved_record_from_vector(filename)
        return jsonify({"ok": True, **result, "vector_sync": vector_sync})

    @app.post("/storage/trash/restore")
    def api_storage_trash_restore():
        body = request.get_json(force=True, silent=False) or {}
        filename = str(body.get("filename") or "").strip()
        if not validate_filename(filename):
            return jsonify({"error": "invalid filename"}), 400
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        try:
            result = restore_trashed_result(storage_dir, filename)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        vector_sync = sync_saved_record_to_vector(str(result.get("filename") or ""))
        return jsonify({"ok": True, **result, "vector_sync": vector_sync})

    @app.post("/storage/trash/expunge")
    def api_storage_trash_expunge():
        body = request.get_json(force=True, silent=False) or {}
        filename = str(body.get("filename") or "").strip()
        if not validate_filename(filename):
            return jsonify({"error": "invalid filename"}), 400
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        try:
            result = expunge_trashed_result(storage_dir, filename)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify({"ok": True, **result})

    @app.post("/storage/trash/empty")
    def api_storage_trash_empty():
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        items = list_trashed_results(storage_dir)
        expunged: list[str] = []
        for item in items:
            filename = str(item.get("filename") or "").strip()
            if not validate_filename(filename):
                continue
            try:
                expunge_trashed_result(storage_dir, filename)
                expunged.append(filename)
            except FileNotFoundError:
                continue
        return jsonify({"ok": True, "count": len(expunged), "items": expunged})

    @app.get("/character-sheet/<path:filename>")
    def api_character_sheet_get(filename: str):
        if not validate_filename(filename):
            return jsonify({"error": "invalid filename"}), 400

        owner = request.args.get("owner", "").strip()
        blocked, lock = is_locked_by_other(filename, owner)
        if blocked:
            return jsonify({
                "error": "sheet is locked",
                "lock": lock,
            }), 423

        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        try:
            data = load_saved_result(storage_dir, filename, default_settings=configured_default_settings())
        except FileNotFoundError:
            return jsonify({"error": "sheet not found"}), 404
        return jsonify(data)

    @app.post("/character-sheet/lock")
    def api_character_sheet_lock():
        body = request.get_json(force=True, silent=False) or {}
        filename = str(body.get("filename") or "").strip()
        owner = str(body.get("owner") or "").strip()
        mode = str(body.get("mode") or "edit").strip().lower()

        if not validate_filename(filename):
            return jsonify({"error": "invalid filename"}), 400
        if not owner:
            return jsonify({"error": "owner is required"}), 400
        if mode not in {"edit", "play"}:
            return jsonify({"error": "mode must be 'edit' or 'play'"}), 400

        blocked, lock = is_locked_by_other(filename, owner)
        if blocked:
            return jsonify({
                "error": "sheet is locked",
                "lock": lock,
            }), 423

        lock = write_sheet_lock(filename, owner, mode)
        return jsonify({"ok": True, "lock": lock})

    @app.post("/character-sheet/unlock")
    def api_character_sheet_unlock():
        body = request.get_json(force=True, silent=False) or {}
        filename = str(body.get("filename") or "").strip()
        owner = str(body.get("owner") or "").strip()

        if not validate_filename(filename):
            return jsonify({"error": "invalid filename"}), 400
        if not owner:
            return jsonify({"error": "owner is required"}), 400

        ok = release_sheet_lock(filename, owner)
        if not ok:
            return jsonify({"error": "sheet is locked by another owner"}), 409
        return jsonify({"ok": True})

    @app.post("/character-sheet/import-foundry")
    def api_character_sheet_import_foundry():
        if not is_plugin_enabled("foundryVTT"):
            return jsonify({"error": "foundryVTT plugin is disabled"}), 403
        actor: dict | None = None
        payload: dict = {}

        uploaded = request.files.get("file")
        if uploaded is not None:
            try:
                actor = json.loads(uploaded.read().decode("utf-8"))
            except Exception:
                return jsonify({"error": "invalid Foundry JSON file"}), 400
            payload = {
                "area": str(request.form.get("area") or "").strip(),
                "environment": str(request.form.get("environment") or "").strip(),
                "location": str(request.form.get("location") or "").strip(),
                "race": str(request.form.get("race") or "").strip(),
                "profession": str(request.form.get("profession") or "").strip(),
                "setting": str(request.form.get("setting") or "").strip(),
            }
        else:
            body = request.get_json(force=True, silent=False) or {}
            candidate = body.get("actor")
            if isinstance(candidate, dict):
                actor = candidate
            payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}

        if not isinstance(actor, dict):
            return jsonify({"error": "actor object is required"}), 400
        try:
            result = import_foundry_actor_to_storage(actor, payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"failed to parse Foundry actor: {exc}"}), 400
        return jsonify(result)

    @app.route("/plugins/foundryvtt/import/actor", methods=["POST", "OPTIONS"])
    def api_foundryvtt_import_actor():
        if request.method == "OPTIONS":
            response = jsonify({"ok": True})
            response.status_code = 204
            return with_foundry_cors_headers(response)

        if not is_plugin_enabled("foundryVTT"):
            response = jsonify({"error": "foundryVTT plugin is disabled"})
            response.status_code = 403
            return with_foundry_cors_headers(response)

        auth_error = foundry_auth_error_response()
        if auth_error is not None:
            return auth_error

        body = request.get_json(force=True, silent=False) or {}
        actor = body.get("actor")
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
        target_compendium_id = find_foundry_target_compendium_id(payload)
        if target_compendium_id:
            payload["compendium_id"] = target_compendium_id
            if not foundry_sync_enabled_for_compendium(target_compendium_id):
                response = jsonify({"error": f"sync disabled for compendium '{target_compendium_id}'"})
                response.status_code = 403
                return with_foundry_cors_headers(response)
        if not isinstance(actor, dict):
            response = jsonify({"error": "actor object is required"})
            response.status_code = 400
            return with_foundry_cors_headers(response)

        try:
            result = import_foundry_actor_to_storage(actor, payload)
        except ValueError as exc:
            response = jsonify({"error": str(exc)})
            response.status_code = 400
            return with_foundry_cors_headers(response)
        except Exception as exc:
            response = jsonify({"error": f"failed to parse Foundry actor: {exc}"})
            response.status_code = 400
            return with_foundry_cors_headers(response)

        response = jsonify(result)
        return with_foundry_cors_headers(response)

    @app.route("/plugins/foundryvtt/import/item", methods=["POST", "OPTIONS"])
    def api_foundryvtt_import_item():
        if request.method == "OPTIONS":
            response = jsonify({"ok": True})
            response.status_code = 204
            return with_foundry_cors_headers(response)

        if not is_plugin_enabled("foundryVTT"):
            response = jsonify({"error": "foundryVTT plugin is disabled"})
            response.status_code = 403
            return with_foundry_cors_headers(response)

        auth_error = foundry_auth_error_response()
        if auth_error is not None:
            return auth_error

        body = request.get_json(force=True, silent=False) or {}
        item = body.get("item")
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
        target_compendium_id = find_foundry_target_compendium_id(payload)
        if target_compendium_id:
            payload["compendium_id"] = target_compendium_id
            if not foundry_sync_enabled_for_compendium(target_compendium_id):
                response = jsonify({"error": f"sync disabled for compendium '{target_compendium_id}'"})
                response.status_code = 403
                return with_foundry_cors_headers(response)
        if not isinstance(item, dict):
            response = jsonify({"error": "item object is required"})
            response.status_code = 400
            return with_foundry_cors_headers(response)

        try:
            result = import_foundry_item_to_storage(item, payload)
        except ValueError as exc:
            response = jsonify({"error": str(exc)})
            response.status_code = 400
            return with_foundry_cors_headers(response)
        except Exception as exc:
            response = jsonify({"error": f"failed to parse Foundry item: {exc}"})
            response.status_code = 400
            return with_foundry_cors_headers(response)

        response = jsonify(result)
        return with_foundry_cors_headers(response)

    @app.route("/plugins/foundryvtt/export/sync", methods=["POST", "OPTIONS"])
    def api_foundryvtt_export_sync():
        if request.method == "OPTIONS":
            response = jsonify({"ok": True})
            response.status_code = 204
            return with_foundry_cors_headers(response)

        if not is_plugin_enabled("foundryVTT"):
            response = jsonify({"error": "foundryVTT plugin is disabled"})
            response.status_code = 403
            return with_foundry_cors_headers(response)

        auth_error = foundry_auth_error_response()
        if auth_error is not None:
            return auth_error

        body = request.get_json(force=True, silent=False) or {}
        requested_types = body.get("types")
        if not isinstance(requested_types, list) or not requested_types:
            requested_types = ["npc", "creature", "cypher", "artifact"]
        allowed_types = {"npc", "creature", "cypher", "artifact"}
        requested = []
        for row in requested_types:
            t = str(row or "").strip().lower()
            if t in allowed_types and t not in requested:
                requested.append(t)
        if not requested:
            response = jsonify({"error": "no supported types requested"})
            response.status_code = 400
            return with_foundry_cors_headers(response)

        requested_setting = str(body.get("setting") or "").strip().lower()
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        entries: list[dict] = []

        for item_type in requested:
            summaries = search_saved_results(
                storage_dir,
                item_type=item_type,
                setting=requested_setting or None,
                default_settings=configured_default_settings(),
            )
            for summary in summaries:
                filename = str(summary.get("filename") or "").strip()
                if not filename:
                    continue
                try:
                    record = load_saved_result(
                        storage_dir,
                        filename,
                        default_settings=configured_default_settings(),
                    )
                except Exception:
                    continue
                result = record.get("result") if isinstance(record.get("result"), dict) else {}
                payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
                metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
                source = str(metadata.get("source") or "").strip().lower()
                if source == "foundryvtt":
                    continue

                resolved_type = str(result.get("type") or "").strip().lower()
                if resolved_type not in allowed_types:
                    continue

                if resolved_type in {"npc", "creature"}:
                    foundry_data = npc_or_creature_result_to_foundry_actor(result, payload)
                    doc_type = "Actor"
                    folder_name = "NPCs" if resolved_type == "npc" else "Creatures"
                elif resolved_type == "cypher":
                    foundry_data = cypher_result_to_foundry_item(result, payload)
                    doc_type = "Item"
                    folder_name = "Cyphers"
                else:
                    foundry_data = artifact_result_to_foundry_item(result, payload)
                    doc_type = "Item"
                    folder_name = "Artifacts"

                effective_settings = metadata.get("settings")
                if not isinstance(effective_settings, list) or not effective_settings:
                    single = metadata.get("setting")
                    effective_settings = [single] if single else []
                effective_setting = str((effective_settings[0] if effective_settings else "") or "").strip().lower()
                if requested_setting and effective_setting and effective_setting != requested_setting:
                    continue

                entries.append({
                    "filename": filename,
                    "saved_at": record.get("saved_at"),
                    "type": resolved_type,
                    "name": str(result.get("name") or "").strip(),
                    "setting": effective_setting or requested_setting,
                    "source": "gmtools",
                    "foundry_doc_type": doc_type,
                    "foundry_folder": folder_name,
                    "foundry_data": foundry_data,
                })

        entries.sort(key=lambda row: str(row.get("saved_at") or ""), reverse=True)
        response = jsonify({
            "count": len(entries),
            "setting": requested_setting,
            "types": requested,
            "entries": entries,
        })
        return with_foundry_cors_headers(response)

    @app.get("/foundry/export")
    def api_foundry_export():
        if not is_plugin_enabled("foundryVTT"):
            return jsonify({"error": "foundryVTT plugin is disabled"}), 403
        filename = str(request.args.get("filename") or "").strip()
        if not validate_filename(filename):
            return jsonify({"error": "invalid filename"}), 400

        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        try:
            record = load_saved_result(storage_dir, filename, default_settings=configured_default_settings())
        except FileNotFoundError:
            return jsonify({"error": "saved item not found"}), 404

        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        result_type = str(result.get("type") or "").strip().lower()

        if result_type == "character_sheet":
            actor = character_sheet_result_to_foundry_actor(result, payload)
        elif result_type in {"npc", "creature"}:
            actor = npc_or_creature_result_to_foundry_actor(result, payload)
        else:
            return jsonify({
                "error": f"Foundry export is not supported for type '{result_type or 'unknown'}'"
            }), 400

        actor_name = secure_filename(str(actor.get("name") or "actor")) or "actor"
        actor_id = str((actor.get("_stats") or {}).get("exportSource", {}).get("uuid") or f"Actor.{uuid.uuid4().hex[:16]}")
        actor_id = actor_id.split(".")[-1]
        download_name = f"fvtt-Actor-{actor_name}-{actor_id}.json"
        data = json.dumps(actor, indent=2, ensure_ascii=False).encode("utf-8")
        return send_file(
            BytesIO(data),
            mimetype="application/json",
            as_attachment=True,
            download_name=download_name,
        )

    @app.get("/character-sheet/pdf-fields")
    def api_character_sheet_pdf_fields():
        try:
            field_names = read_character_sheet_pdf_field_names()
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except RuntimeError as exc:
            return jsonify({
                "error": str(exc),
                "hint": "Install dependencies from requirements.txt to enable PDF generation.",
            }), 503
        except Exception as exc:
            return jsonify({"error": f"unable to read PDF fields: {exc}"}), 500

        return jsonify({
            "fields": field_names,
            "count": len(field_names),
        })

    @app.post("/character-sheet/pdf")
    def api_character_sheet_pdf():
        body = request.get_json(force=True, silent=False) or {}
        sheet = body.get("sheet")
        filename = str(body.get("filename") or "").strip()
        action = str(body.get("action") or "download").strip().lower()
        owner = str(body.get("owner") or "").strip()

        if action not in {"download", "print"}:
            action = "download"

        if sheet is None and filename:
            if not validate_filename(filename):
                return jsonify({"error": "invalid filename"}), 400
            blocked, lock = is_locked_by_other(filename, owner)
            if blocked:
                return jsonify({
                    "error": "sheet is locked",
                    "lock": lock,
                }), 423
            storage_dir = current_app.config["LOL_STORAGE_DIR"]
            try:
                record = load_saved_result(storage_dir, filename, default_settings=configured_default_settings())
            except FileNotFoundError:
                return jsonify({"error": "sheet not found"}), 404
            sheet = (record.get("result") or {}).get("sheet")

        if not isinstance(sheet, dict):
            return jsonify({"error": "sheet must be an object or resolvable by filename"}), 400

        try:
            pdf_bytes, download_name = render_character_sheet_pdf(sheet)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except RuntimeError as exc:
            return jsonify({
                "error": str(exc),
                "hint": "Install dependencies from requirements.txt to enable PDF generation.",
            }), 503
        except Exception as exc:
            return jsonify({"error": f"unable to fill character sheet PDF: {exc}"}), 500

        return send_file(
            BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=(action == "download"),
            download_name=download_name,
        )

    @app.get("/storage/search")
    def api_storage_search():
        storage_dir = current_app.config["LOL_STORAGE_DIR"]

        item_type = request.args.get("type")
        setting = request.args.get("setting")
        area = request.args.get("area")
        location = request.args.get("location")
        environment = request.args.get("environment")
        race = request.args.get("race")
        profession = request.args.get("profession")
        name_contains = request.args.get("name")

        results = search_saved_results(
            storage_dir,
            item_type=item_type,
            setting=setting,
            area=area,
            location=location,
            environment=environment,
            race=race,
            profession=profession,
            name_contains=name_contains,
            default_settings=configured_default_settings(),
        )

        return jsonify({
            "items": results,
            "filters": {
                "type": item_type,
                "setting": setting,
                "area": area or environment,
                "location": location,
                "environment": environment,
                "race": race,
                "profession": profession,
                "name": name_contains,
            },
            "count": len(results),
        })

    @app.post("/generate/monster")
    def api_generate_monster():
        config = current_app.config["LOL_CONFIG"]
        payload = request.get_json(force=True, silent=False) or {}
        rng = deterministic_rng(payload, request.args.get("seed"))
        result = generate_monster(payload, config, rng)
        result = persist_result(payload, result)
        return jsonify(result)

    @app.post("/generate/character")
    def api_generate_character():
        config = current_app.config["LOL_CONFIG"]
        payload = request.get_json(force=True, silent=False) or {}
        rng = deterministic_rng(payload, request.args.get("seed"))
        result = generate_character(payload, config, rng)
        result = persist_result(payload, result)
        return jsonify(result)

    @app.post("/generate/npc")
    def api_generate_npc():
        config = current_app.config["LOL_CONFIG"]
        payload = request.get_json(force=True, silent=False) or {}
        rng = deterministic_rng(payload, request.args.get("seed"))
        result = generate_npc(payload, config, rng)
        result = persist_result(payload, result)
        return jsonify(result)

    @app.post("/generate/settlement")
    def api_generate_settlement():
        config = current_app.config["LOL_CONFIG"]
        payload = request.get_json(force=True, silent=False) or {}
        rng = deterministic_rng(payload, request.args.get("seed"))
        result = generate_settlement(payload, config, rng)
        result = persist_result(payload, result)
        return jsonify(result)

    @app.post("/generate/encounter")
    def api_generate_encounter():
        config = current_app.config["LOL_CONFIG"]
        payload = request.get_json(force=True, silent=False) or {}
        rng = deterministic_rng(payload, request.args.get("seed"))
        result = generate_encounter(payload, config, rng)
        result = persist_result(payload, result)
        return jsonify(result)

    @app.post("/generate/cypher")
    def api_generate_cypher():
        config = current_app.config["LOL_CONFIG"]
        payload = request.get_json(force=True, silent=False) or {}
        rng = deterministic_rng(payload, request.args.get("seed"))
        result = generate_cypher(payload, config, rng)
        result = persist_result(payload, result)
        return jsonify(result)

    @app.post("/generate/artifact")
    def api_generate_artifact():
        config = current_app.config["LOL_CONFIG"]
        payload = request.get_json(force=True, silent=False) or {}
        rng = deterministic_rng(payload, request.args.get("seed"))
        result = generate_artifact(payload, config, rng)
        result = persist_result(payload, result)
        return jsonify(result)

    @app.post("/generate/inn")
    def api_generate_inn():
        config = current_app.config["LOL_CONFIG"]
        payload = request.get_json(force=True, silent=False) or {}
        rng = deterministic_rng(payload, request.args.get("seed"))
        result = generate_inn(payload, config, rng)
        result = persist_result(payload, result)
        return jsonify(result)

    @app.post("/generate/parse-raw")
    def api_generate_parse_raw():
        config = current_app.config["LOL_CONFIG"]
        payload = request.get_json(force=True, silent=False) or {}
        # Backward-compatible single-save endpoint: save first parsed item.
        parsed = parse_raw_text_entries(payload, config)
        if not parsed:
            return jsonify({"error": "No parsable items found"}), 400
        result = parsed[0]
        result = persist_result(payload, result)
        return jsonify(result)

    @app.post("/generate/parse-raw/preview")
    def api_generate_parse_raw_preview():
        config = current_app.config["LOL_CONFIG"]
        payload = request.get_json(force=True, silent=False) or {}
        items = parse_raw_text_entries(payload, config)
        return jsonify({
            "count": len(items),
            "items": items,
        })

    @app.post("/generate/parse-raw/save")
    def api_generate_parse_raw_save():
        body = request.get_json(force=True, silent=False) or {}
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
        parsed = body.get("parsed") if isinstance(body.get("parsed"), dict) else {}
        if not parsed:
            return jsonify({"error": "parsed item is required"}), 400
        result = persist_result(payload, parsed)
        return jsonify(result)

    @app.post("/character-sheet/save")
    def api_character_sheet_save():
        body = request.get_json(force=True, silent=False) or {}
        payload = body.get("payload") or {}
        sheet = body.get("sheet") or {}
        filename = str(body.get("filename") or "").strip()
        owner = str(body.get("owner") or "").strip()

        if not isinstance(payload, dict):
            return jsonify({"error": "payload must be an object"}), 400
        if not isinstance(sheet, dict):
            return jsonify({"error": "sheet must be an object"}), 400
        if filename and not validate_filename(filename):
            return jsonify({"error": "invalid filename"}), 400

        metadata = sheet.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}

        sheet["wizard_completed"] = True

        name = str(
            sheet.get("name")
            or sheet.get("character_name")
            or metadata.get("name")
            or "Unnamed Character"
        ).strip() or "Unnamed Character"

        result = {
            "type": "character_sheet",
            "name": name,
            "description": str(sheet.get("notes") or "").strip(),
            "sheet": sheet,
            "metadata": {
                "setting": metadata.get("setting") or payload.get("setting"),
                "settings": metadata.get("settings") or payload.get("settings"),
                "area": metadata.get("area") or payload.get("area") or metadata.get("environment") or payload.get("environment"),
                "location": metadata.get("location") or payload.get("location"),
                "environment": metadata.get("environment") or payload.get("environment") or metadata.get("area") or payload.get("area"),
                "race": metadata.get("race") or payload.get("race"),
                "profession": metadata.get("profession") or payload.get("profession"),
                "character_type": metadata.get("character_type"),
                "flavor": metadata.get("flavor"),
                "descriptor": metadata.get("descriptor"),
                "focus": metadata.get("focus"),
                "tier": sheet.get("tier"),
            },
        }
        result = attach_settings_metadata(result, payload, current_app.config["LOL_CONFIG"])
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        created_local_abilities = create_missing_local_abilities(
            sheet,
            name,
            parent_settings=result.get("metadata", {}).get("settings"),
        )

        if filename:
            blocked, lock = is_locked_by_other(filename, owner)
            if blocked:
                return jsonify({
                    "error": "sheet is locked",
                    "lock": lock,
                }), 423
            path = (storage_dir / filename).resolve()
            storage_root = storage_dir.resolve()
            if not str(path).startswith(str(storage_root) + "/") and path != storage_root:
                return jsonify({"error": "invalid filename"}), 400
            if not path.exists():
                return jsonify({"error": "sheet not found"}), 404

            existing = load_saved_result(storage_dir, filename, default_settings=configured_default_settings())
            existing_payload = existing.get("payload") if isinstance(existing, dict) else {}
            record = {
                "schema_version": STORAGE_SCHEMA_VERSION,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "filename": filename,
                "payload": payload or (existing_payload if isinstance(existing_payload, dict) else {}),
                "result": result,
            }
            path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            result["storage"] = {"filename": filename, "saved": True}
            if created_local_abilities:
                result["local_abilities_created"] = created_local_abilities
            return jsonify(result)

        result = persist_result(payload, result)
        if created_local_abilities:
            result["local_abilities_created"] = created_local_abilities
        return jsonify(result)

    @app.post("/generate/batch")
    def api_generate_batch():
        config = current_app.config["LOL_CONFIG"]
        payload = request.get_json(force=True, silent=False) or {}
        items = payload.get("items", [])
        global_seed = payload.get("seed")

        if not isinstance(items, list):
            return jsonify({"error": "items must be a list"}), 400

        results = []
        errors = []

        for idx, item in enumerate(items):
            try:
                if not isinstance(item, dict):
                    raise ValueError("each batch item must be an object")

                item_type = str(item.get("type", "")).lower()
                rng = deterministic_rng(item, global_seed)

                if item_type == "character":
                    generated_result = generate_character(item, config, rng)
                elif item_type == "npc":
                    generated_result = generate_npc(item, config, rng)
                elif item_type == "monster":
                    generated_result = generate_monster(item, config, rng)
                elif item_type == "settlement":
                    generated_result = generate_settlement(item, config, rng)
                elif item_type == "encounter":
                    generated_result = generate_encounter(item, config, rng)
                elif item_type == "cypher":
                    generated_result = generate_cypher(item, config, rng)
                elif item_type == "artifact":
                    generated_result = generate_artifact(item, config, rng)
                elif item_type == "inn":
                    generated_result = generate_inn(item, config, rng)
                else:
                    raise ValueError(f"unknown type '{item_type}'")

                stored_result = persist_result(item, generated_result)
                results.append(stored_result)

            except Exception as exc:
                errors.append({
                    "index": idx,
                    "error": str(exc),
                    "item": item,
                })

        status = 207 if errors else 200
        return jsonify({
            "results": results,
            "errors": errors,
        }), status

    @app.post("/reload")
    def api_reload_config():
        config_dir = current_app.config["LOL_CONFIG_DIR"]
        settings_descriptors = list_setting_descriptors(config_dir)
        current_app.config["LOL_AVAILABLE_SETTINGS"] = [w["id"] for w in settings_descriptors]
        current_app.config["LOL_AVAILABLE_SETTING_DESCRIPTORS"] = settings_descriptors
        current_app.config["LOL_AVAILABLE_WORLDS"] = [w["id"] for w in settings_descriptors]
        current_app.config["LOL_AVAILABLE_WORLD_DESCRIPTORS"] = settings_descriptors
        current_app.config["LOL_CONFIG"] = load_config_dir(
            config_dir,
            setting_id=current_app.config.get("LOL_SETTING_ID") or current_app.config.get("LOL_WORLD_ID"),
        )
        return jsonify({
            "status": "reloaded",
            "top_level_keys": sorted(current_app.config["LOL_CONFIG"].keys()),
        })

    def _settings_payload() -> dict[str, Any]:
        config_dir = current_app.config["LOL_CONFIG_DIR"]
        settings = list_setting_descriptors(config_dir)
        project_root = current_app.config["LOL_PROJECT_ROOT"]
        images_root = (project_root / "images").resolve()

        def resolve_cover_url(setting_row: dict) -> str:
            row = setting_row if isinstance(setting_row, dict) else {}
            raw = str(row.get("cover_image") or "").strip()
            sid = str(row.get("id") or "").strip().lower()

            def rel_to_url(rel: str) -> str:
                value = str(rel or "").strip().replace("\\", "/").lstrip("/")
                return f"/{value}" if value else ""

            if raw:
                low = raw.lower()
                if low.startswith("http://") or low.startswith("https://"):
                    return raw
                if raw.startswith("/"):
                    return raw
                # Backward compatibility: earlier setting cover saves stored
                # "uploads/<file>" while media serving lives under /images/*.
                if low.startswith("uploads/"):
                    mapped = f"images/{raw.lstrip('/')}"
                    candidate = (project_root / mapped).resolve()
                    if candidate.exists() and candidate.is_file():
                        return rel_to_url(mapped)
                candidate = (project_root / raw).resolve()
                try:
                    rel = str(candidate.relative_to(project_root)).replace("\\", "/")
                except Exception:
                    rel = ""
                if rel and candidate.exists() and candidate.is_file():
                    if rel.startswith("images/"):
                        return rel_to_url(rel)
                    try:
                        rel_from_images = str(candidate.relative_to(images_root)).replace("\\", "/")
                    except Exception:
                        rel_from_images = ""
                    if rel_from_images:
                        return rel_to_url(f"images/{rel_from_images}")
                return rel_to_url(raw)

            # fallback convention: images/book_covers/<setting_id>.<ext>
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                candidate_rel = f"images/book_covers/{sid}{ext}"
                candidate = project_root / candidate_rel
                if candidate.exists() and candidate.is_file():
                    return rel_to_url(candidate_rel)
            return "/images/CypherLogo/CSOL%20Logo-Cypher%20System%20Compatible-Color%20with%20White-Small.png"

        enriched_settings = []
        for row in settings:
            item = dict(row) if isinstance(row, dict) else {"id": str(row)}
            item["cover_url"] = resolve_cover_url(item)
            enriched_settings.append(item)

        active_setting = current_app.config.get("LOL_SETTING_ID") or current_app.config.get("LOL_WORLD_ID")
        default_setting = infer_default_setting_id(config_dir) or infer_default_world_id(config_dir)
        return {
            "active_world": active_setting,
            "active_setting": active_setting,
            "default_world": default_setting,
            "default_setting": default_setting,
            "worlds": enriched_settings,
            "settings": enriched_settings,
        }

    @app.get("/settings")
    def settings_page():
        return render_template("settings.html")

    @app.get("/api/settings")
    def api_settings():
        return jsonify(_settings_payload())

    @app.get("/settings/<setting_id>")
    def settings_detail_page(setting_id: str):
        sid = _safe_slug(str(setting_id or "").strip().lower())
        return render_template("settings_detail.html", setting_id=sid)

    @app.get("/api/settings/<setting_id>")
    def api_setting_detail(setting_id: str):
        sid = _safe_slug(str(setting_id or "").strip().lower())
        config_dir = current_app.config["LOL_CONFIG_DIR"]
        available = {w["id"] for w in list_setting_descriptors(config_dir)}
        if sid not in available:
            return jsonify({"error": f"unknown setting_id '{sid}'"}), 404

        desc = next((w for w in list_setting_descriptors(config_dir) if str(w.get("id") or "").strip().lower() == sid), {})
        world_layer = load_world_layer(config_dir, sid)
        world_block = world_layer.get("world") if isinstance(world_layer.get("world"), dict) else {}
        setting_block = world_layer.get("setting") if isinstance(world_layer.get("setting"), dict) else {}
        areas = world_layer.get("areas") if isinstance(world_layer.get("areas"), dict) else {}
        races = world_layer.get("races") if isinstance(world_layer.get("races"), dict) else {}
        settlements = world_layer.get("settlements") if isinstance(world_layer.get("settlements"), dict) else {}
        encounters = world_layer.get("encounters") if isinstance(world_layer.get("encounters"), dict) else {}
        cyphers = world_layer.get("cyphers") if isinstance(world_layer.get("cyphers"), dict) else {}
        lore_enrichment = world_layer.get("lore_enrichment") if isinstance(world_layer.get("lore_enrichment"), dict) else {}

        def count_obj(value: object) -> int:
            if isinstance(value, dict):
                return len(value)
            if isinstance(value, list):
                return len(value)
            return 0

        # Resolve cover URL with same logic as list payload.
        project_root = current_app.config["LOL_PROJECT_ROOT"]
        images_root = (project_root / "images").resolve()
        raw_cover = str((desc or {}).get("cover_image") or world_block.get("cover_image") or "").strip()
        cover_url = "/images/CypherLogo/CSOL%20Logo-Cypher%20System%20Compatible-Color%20with%20White-Small.png"
        if raw_cover:
            low = raw_cover.lower()
            if low.startswith("http://") or low.startswith("https://") or raw_cover.startswith("/"):
                cover_url = raw_cover
            else:
                if low.startswith("uploads/"):
                    mapped_rel = f"images/{raw_cover.lstrip('/')}"
                    mapped_candidate = (project_root / mapped_rel).resolve()
                    if mapped_candidate.exists() and mapped_candidate.is_file():
                        cover_url = f"/{mapped_rel}"
                candidate = (project_root / raw_cover).resolve()
                try:
                    rel = str(candidate.relative_to(project_root)).replace("\\", "/")
                except Exception:
                    rel = ""
                if rel and candidate.exists() and candidate.is_file():
                    if rel.startswith("images/"):
                        cover_url = f"/{rel}"
                    else:
                        try:
                            rel_from_images = str(candidate.relative_to(images_root)).replace("\\", "/")
                        except Exception:
                            rel_from_images = ""
                        if rel_from_images:
                            cover_url = f"/images/{rel_from_images}"
                        else:
                            cover_url = f"/{rel}"
                else:
                    raw_rel = raw_cover.strip().replace('\\', '/').lstrip('/')
                    if raw_rel.startswith("uploads/"):
                        cover_url = f"/images/{raw_rel}"
                    else:
                        cover_url = f"/{raw_rel}"
        else:
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                candidate_rel = f"images/book_covers/{sid}{ext}"
                candidate = project_root / candidate_rel
                if candidate.exists() and candidate.is_file():
                    cover_url = f"/{candidate_rel}"
                    break

        world_dir = config_dir / "worlds" / sid
        files = sorted([
            str(p.relative_to(config_dir)).replace("\\", "/")
            for p in world_dir.glob("*")
            if p.is_file()
        ])

        return jsonify({
            "id": sid,
            "label": str(world_block.get("label") or (desc or {}).get("label") or sid),
            "description": str(world_block.get("description") or (desc or {}).get("description") or ""),
            "core_genre": str(world_block.get("core_genre") or world_block.get("core_setting") or (desc or {}).get("core_genre") or (desc or {}).get("core_setting") or ""),
            "summary": str(setting_block.get("summary") or ""),
            "tone_style": str(setting_block.get("tone_style") or ""),
            "cover_url": cover_url,
            "stats": {
                "races": count_obj(races),
                "areas": count_obj(areas),
                "settlements": count_obj(settlements),
                "encounters": count_obj(encounters),
                "cyphers": count_obj(cyphers),
                "lore_areas": count_obj(lore_enrichment.get("areas")) if isinstance(lore_enrichment, dict) else 0,
                "lore_settlements": count_obj(lore_enrichment.get("settlements")) if isinstance(lore_enrichment, dict) else 0,
                "lore_encounters": count_obj(lore_enrichment.get("encounters")) if isinstance(lore_enrichment, dict) else 0,
            },
            "files": files,
        })

    @app.get("/worlds")
    def api_worlds():
        return jsonify(_settings_payload())

    @app.post("/settings/select")
    def api_settings_select():
        body = request.get_json(force=True, silent=False) or {}
        world_id_raw = body.get("setting_id")
        if world_id_raw is None:
            world_id_raw = body.get("world_id")
        world_id = str(world_id_raw or "").strip() or None

        config_dir = current_app.config["LOL_CONFIG_DIR"]
        available = {w["id"] for w in list_setting_descriptors(config_dir)}
        if world_id is not None and world_id not in available:
            return jsonify({"error": f"unknown setting_id '{world_id}'"}), 400

        # If setting_id is omitted/blank, fall back to inferred default setting.
        target_world = world_id or infer_default_setting_id(config_dir) or infer_default_world_id(config_dir)

        current_app.config["LOL_SETTING_ID"] = target_world
        current_app.config["LOL_WORLD_ID"] = target_world
        current_app.config["LOL_CONFIG"] = load_config_dir(
            config_dir,
            setting_id=target_world,
        )
        worlds = list_setting_descriptors(config_dir)
        current_app.config["LOL_AVAILABLE_SETTINGS"] = [w["id"] for w in worlds]
        current_app.config["LOL_AVAILABLE_SETTING_DESCRIPTORS"] = worlds
        current_app.config["LOL_AVAILABLE_WORLDS"] = [w["id"] for w in worlds]
        current_app.config["LOL_AVAILABLE_WORLD_DESCRIPTORS"] = worlds

        return jsonify({
            "status": "ok",
            "active_world": target_world,
            "active_setting": target_world,
            "worlds": worlds,
            "settings": worlds,
        })

    @app.post("/settings/delete")
    def api_settings_delete():
        body = request.get_json(force=True, silent=False) or {}
        setting_id = normalize_setting_token(str(body.get("setting_id") or "").strip().lower())
        if not setting_id:
            return jsonify({"error": "setting_id is required"}), 400
        if setting_id == "lands_of_legend":
            return jsonify({"error": "Refusing to delete protected baseline setting 'lands_of_legend'"}), 403

        config_dir = current_app.config["LOL_CONFIG_DIR"]
        resolved_world_dir = resolve_world_dir(config_dir, setting_id)
        world_dir = (resolved_world_dir or (config_dir / "worlds" / setting_id)).resolve()
        worlds_root = (config_dir / "worlds").resolve()
        if not str(world_dir).startswith(str(worlds_root) + os.sep):
            return jsonify({"error": "invalid setting path"}), 400
        if not world_dir.exists() or not world_dir.is_dir():
            return jsonify({"error": f"setting folder not found: {setting_id}"}), 404

        settings_path = config_dir / "02_settings.yaml"
        settings_data = {}
        if settings_path.exists():
            try:
                settings_data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
            except Exception:
                settings_data = {}
        if not isinstance(settings_data, dict):
            settings_data = {}

        def remove_from_catalog(root: dict, list_key: str) -> None:
            if not isinstance(root, dict):
                return
            catalog = root.get("catalog")
            if not isinstance(catalog, dict):
                return
            for _, entry in catalog.items():
                if not isinstance(entry, dict):
                    continue
                values = entry.get(list_key)
                if not isinstance(values, list):
                    continue
                entry[list_key] = [v for v in values if str(v).strip().lower() != setting_id]

        settings_block = settings_data.get("settings")
        genres_block = settings_data.get("genres")
        if isinstance(settings_block, dict):
            remove_from_catalog(settings_block, "worlds")
            defaults = settings_block.get("defaults")
            if isinstance(defaults, list):
                settings_block["defaults"] = [v for v in defaults if str(v).strip().lower() != setting_id]
        if isinstance(genres_block, dict):
            remove_from_catalog(genres_block, "settings")
            defaults = genres_block.get("defaults")
            if isinstance(defaults, list):
                genres_block["defaults"] = [v for v in defaults if str(v).strip().lower() != setting_id]

        shutil.rmtree(world_dir)
        settings_path.write_text(yaml.safe_dump(settings_data, sort_keys=False, allow_unicode=True), encoding="utf-8")

        active_setting = (current_app.config.get("LOL_SETTING_ID") or current_app.config.get("LOL_WORLD_ID") or "").strip()
        if active_setting == setting_id:
            next_setting = infer_default_setting_id(config_dir) or infer_default_world_id(config_dir)
            current_app.config["LOL_SETTING_ID"] = next_setting
            current_app.config["LOL_WORLD_ID"] = next_setting

        current_app.config["LOL_CONFIG"] = load_config_dir(
            config_dir,
            setting_id=current_app.config.get("LOL_SETTING_ID") or current_app.config.get("LOL_WORLD_ID"),
        )
        worlds = list_setting_descriptors(config_dir)
        current_app.config["LOL_AVAILABLE_SETTINGS"] = [w["id"] for w in worlds]
        current_app.config["LOL_AVAILABLE_SETTING_DESCRIPTORS"] = worlds
        current_app.config["LOL_AVAILABLE_WORLDS"] = [w["id"] for w in worlds]
        current_app.config["LOL_AVAILABLE_WORLD_DESCRIPTORS"] = worlds

        return jsonify({
            "status": "deleted",
            "deleted_setting": setting_id,
            "active_world": current_app.config.get("LOL_SETTING_ID") or current_app.config.get("LOL_WORLD_ID"),
            "active_setting": current_app.config.get("LOL_SETTING_ID") or current_app.config.get("LOL_WORLD_ID"),
            "worlds": worlds,
            "settings": worlds,
        })

    @app.post("/settings/cover")
    def api_settings_cover():
        body = request.get_json(force=True, silent=False) or {}
        setting_id = _safe_slug(str(body.get("setting_id") or "").strip().lower())
        cover_image = str(body.get("cover_image") or "").strip()
        if not setting_id:
            return jsonify({"error": "setting_id is required"}), 400

        config_dir = current_app.config["LOL_CONFIG_DIR"]
        world_dir = config_dir / "worlds" / setting_id
        if not world_dir.exists() or not world_dir.is_dir():
            return jsonify({"error": f"setting folder not found: {setting_id}"}), 404

        world_file = world_dir / "00_world.yaml"
        if not world_file.exists():
            return jsonify({"error": f"missing world file: {world_file}"}), 404

        try:
            doc = yaml.safe_load(world_file.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            return jsonify({"error": f"failed to read world file: {exc}"}), 400
        if not isinstance(doc, dict):
            doc = {}
        world_block = doc.get("world")
        if not isinstance(world_block, dict):
            world_block = {}
            doc["world"] = world_block
        if cover_image:
            # Normalize to a stable project-relative path under images/.
            raw = cover_image.strip().replace("\\", "/")
            low = raw.lower()
            if low.startswith("http://") or low.startswith("https://"):
                normalized = raw
            else:
                normalized = raw.lstrip("/")
                if normalized.startswith("images/"):
                    pass
                elif normalized.startswith("uploads/"):
                    normalized = f"images/{normalized}"
                else:
                    project_root = current_app.config["LOL_PROJECT_ROOT"]
                    images_root = (project_root / "images").resolve()
                    candidate = (project_root / normalized).resolve()
                    try:
                        rel_from_images = str(candidate.relative_to(images_root)).replace("\\", "/")
                    except Exception:
                        rel_from_images = ""
                    if rel_from_images:
                        normalized = f"images/{rel_from_images}"
            world_block["cover_image"] = normalized
        else:
            world_block.pop("cover_image", None)

        world_file.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return jsonify({"status": "ok", "setting_id": setting_id, "cover_image": world_block.get("cover_image", "")})

    @app.post("/worlds/select")
    def api_worlds_select():
        return api_settings_select()

    @app.get("/compendium")
    def api_compendium_index():
        compendium_dir = current_app.config["LOL_COMPENDIUM_DIR"]
        return jsonify(load_compendium_index(compendium_dir))

    @app.get("/compendium/<item_type>")
    def api_compendium_list(item_type: str):
        if item_type not in SUPPORTED_COMPENDIUM_TYPES:
            allowed = ", ".join(sorted(SUPPORTED_COMPENDIUM_TYPES))
            return jsonify({"error": f"item_type must be one of: {allowed}"}), 400

        compendium_dir = current_app.config["LOL_COMPENDIUM_DIR"]
        items = list_compendium_items(compendium_dir, item_type)
        return jsonify({
            "items": items,
            "count": len(items),
        })

    @app.get("/compendium/<item_type>/<slug>")
    def api_compendium_get(item_type: str, slug: str):
        if item_type not in SUPPORTED_COMPENDIUM_TYPES:
            allowed = ", ".join(sorted(SUPPORTED_COMPENDIUM_TYPES))
            return jsonify({"error": f"item_type must be one of: {allowed}"}), 400

        compendium_dir = current_app.config["LOL_COMPENDIUM_DIR"]
        return jsonify(load_compendium_item(compendium_dir, item_type, slug))

    @app.post("/compendium/make-local")
    def api_compendium_make_local():
        body = request.get_json(force=True, silent=False) or {}
        item_type = str(body.get("type") or "").strip()
        slug = str(body.get("slug") or "").strip()

        if item_type not in SUPPORTED_COMPENDIUM_TYPES:
            allowed = ", ".join(sorted(SUPPORTED_COMPENDIUM_TYPES))
            return jsonify({"error": f"type must be one of: {allowed}"}), 400
        if not slug:
            return jsonify({"error": "slug is required"}), 400

        compendium_dir = current_app.config["LOL_COMPENDIUM_DIR"]
        entry = load_compendium_item(compendium_dir, item_type, slug)

        requested_setting = str(body.get("setting") or "").strip()
        requested_area = str(body.get("area") or body.get("environment") or "").strip()
        requested_location = str(body.get("location") or "").strip()

        payload: dict = {
            "origin": "compendium_variant",
            "setting": requested_setting,
            "settings": [requested_setting] if requested_setting else [],
            "area": requested_area,
            "environment": requested_area,
            "location": requested_location,
        }
        result = build_local_variant_from_compendium(
            entry,
            item_type=item_type,
            slug=slug,
            payload=payload,
        )
        result = attach_settings_metadata(result, payload, current_app.config["LOL_CONFIG"])
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        path = save_generated_result(storage_dir, result, payload)
        result["storage"] = {"filename": str(path.relative_to(storage_dir)).replace("\\", "/"), "saved": True}
        return jsonify(result)

    @app.get("/compendium/search")
    def api_compendium_search():
        compendium_dir = current_app.config["LOL_COMPENDIUM_DIR"]
        item_type = request.args.get("type")
        setting = request.args.get("setting")
        query = request.args.get("q")

        results = search_compendium(
            compendium_dir,
            item_type=item_type,
            setting=setting,
            query=query,
        )

        return jsonify({
            "items": results,
            "count": len(results),
            "filters": {
                "type": item_type,
                "setting": setting,
                "q": query,
            },
        })

    @app.get("/official-compendium")
    def api_official_compendium_index():
        official_dir = current_app.config["LOL_OFFICIAL_COMPENDIUM_DIR"]
        return jsonify(load_official_compendium_index(official_dir))

    @app.get("/official-compendium/<item_type>")
    def api_official_compendium_list(item_type: str):
        if item_type not in SUPPORTED_OFFICIAL_COMPENDIUM_TYPES:
            allowed = ", ".join(sorted(SUPPORTED_OFFICIAL_COMPENDIUM_TYPES))
            return jsonify({"error": f"type must be one of: {allowed}"}), 400
        official_dir = current_app.config["LOL_OFFICIAL_COMPENDIUM_DIR"]
        items = [_with_display_sourcebook_label(item) for item in list_official_items(official_dir, item_type)]
        return jsonify({"type": item_type, "count": len(items), "items": items})

    @app.get("/official-compendium/<item_type>/<slug>")
    def api_official_compendium_get(item_type: str, slug: str):
        if item_type not in SUPPORTED_OFFICIAL_COMPENDIUM_TYPES:
            allowed = ", ".join(sorted(SUPPORTED_OFFICIAL_COMPENDIUM_TYPES))
            return jsonify({"error": f"type must be one of: {allowed}"}), 400
        official_dir = current_app.config["LOL_OFFICIAL_COMPENDIUM_DIR"]
        return jsonify(_with_display_sourcebook_label(load_official_item(official_dir, item_type, slug)))

    @app.get("/official-compendium/search")
    def api_official_compendium_search():
        official_dir = current_app.config["LOL_OFFICIAL_COMPENDIUM_DIR"]
        item_type = request.args.get("type")
        setting = request.args.get("setting")
        query = request.args.get("q")
        results = search_official_compendium(
            official_dir,
            item_type=item_type,
            setting=setting,
            query=query,
        )
        return jsonify({
            "items": results,
            "count": len(results),
            "filters": {
                "type": item_type,
                "setting": setting,
                "q": query,
            },
        })

    @app.post("/official-compendium/make-local")
    def api_official_compendium_make_local():
        body = request.get_json(force=True, silent=False) or {}
        item_type = str(body.get("type") or "").strip()
        slug = str(body.get("slug") or "").strip()

        if item_type not in SUPPORTED_OFFICIAL_COMPENDIUM_TYPES:
            allowed = ", ".join(sorted(SUPPORTED_OFFICIAL_COMPENDIUM_TYPES))
            return jsonify({"error": f"type must be one of: {allowed}"}), 400
        if not slug:
            return jsonify({"error": "slug is required"}), 400

        official_dir = current_app.config["LOL_OFFICIAL_COMPENDIUM_DIR"]
        entry = load_official_item(official_dir, item_type, slug)

        requested_setting = str(body.get("setting") or "").strip()
        requested_area = str(body.get("area") or body.get("environment") or "").strip()
        requested_location = str(body.get("location") or "").strip()

        payload: dict = {
            "origin": "official_compendium_variant",
            "setting": requested_setting,
            "settings": [requested_setting] if requested_setting else [],
            "area": requested_area,
            "environment": requested_area,
            "location": requested_location,
        }
        result = build_local_variant_from_compendium(
            entry,
            item_type=item_type,
            slug=slug,
            payload=payload,
        )
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        metadata["origin"] = "official_compendium_variant"
        metadata["source"] = "house"
        metadata["from_official_pdf"] = True
        metadata["official_type"] = item_type
        metadata["official_slug"] = slug
        metadata["official_title"] = str(entry.get("title") or slug)
        metadata["official_book"] = str(entry.get("book") or "")
        metadata["official_backlink"] = f"/official-compendium/{item_type}/{slug}"
        metadata.pop("from_csrd", None)
        metadata.pop("compendium_type", None)
        metadata.pop("compendium_slug", None)
        metadata.pop("compendium_title", None)
        metadata.pop("compendium_backlink", None)
        result["metadata"] = metadata
        result = attach_settings_metadata(result, payload, current_app.config["LOL_CONFIG"])
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        path = save_generated_result(storage_dir, result, payload)
        result["storage"] = {"filename": str(path.relative_to(storage_dir)).replace("\\", "/"), "saved": True}
        return jsonify(result)

    @app.get("/compendium-browser")
    def compendium_browser():
        return redirect("/search")

    @app.get("/lore-browser")
    def lore_browser():
        return render_template("ai_lore_browser.html")

    @app.get("/ai-lore-browser")
    def ai_lore_browser():
        return render_template("ai_lore_browser.html")

    @app.get("/prompt-browser")
    def prompt_browser():
        return redirect("/search")

    @app.get("/lore")
    def api_lore_index():
        lore_dir = current_app.config["LOL_LORE_DIR"]
        return jsonify(load_lore_index(lore_dir, default_settings=configured_default_settings()))

    @app.get("/lore/ai")
    def api_ai_lore_index():
        lore_dir = current_app.config["LOL_LORE_DIR"]
        config_dir = current_app.config["LOL_CONFIG_DIR"]
        setting = request.args.get("setting")
        items = list_ai_lore_items(
            lore_dir,
            config_dir=config_dir,
            setting=setting,
            default_settings=configured_default_settings(),
        )
        return jsonify({
            "items": items,
            "count": len(items),
            "filters": {"setting": setting},
        })

    @app.get("/lore/ai/search")
    def api_ai_lore_search():
        lore_dir = current_app.config["LOL_LORE_DIR"]
        config_dir = current_app.config["LOL_CONFIG_DIR"]
        query = request.args.get("q")
        setting = request.args.get("setting")
        location = request.args.get("location")
        items = search_ai_lore(
            lore_dir,
            query=query,
            config_dir=config_dir,
            setting=setting,
            location=location,
            default_settings=configured_default_settings(),
        )
        return jsonify({
            "items": items,
            "count": len(items),
            "filters": {"q": query, "setting": setting, "location": location},
        })

    @app.get("/lore/search")
    def api_lore_search():
        lore_dir = current_app.config["LOL_LORE_DIR"]
        query = request.args.get("q")
        setting = request.args.get("setting")
        location = request.args.get("location")
        items = search_lore(
            lore_dir,
            query=query,
            setting=setting,
            location=location,
            default_settings=configured_default_settings(),
        )
        return jsonify({
            "items": items,
            "count": len(items),
            "filters": {"q": query, "setting": setting, "location": location},
        })

    @app.get("/lore/<slug>")
    def api_lore_get(slug: str):
        lore_dir = current_app.config["LOL_LORE_DIR"]
        return jsonify(load_lore_item(lore_dir, slug, default_settings=configured_default_settings()))

    @app.post("/lore/update")
    def api_lore_update():
        body = request.get_json(force=True, silent=False) or {}
        slug = str(body.get("slug") or "").strip()
        item = body.get("item")
        if not slug:
            return jsonify({"error": "slug is required"}), 400
        if not isinstance(item, dict):
            return jsonify({"error": "item must be an object"}), 400
        lore_dir = current_app.config["LOL_LORE_DIR"]
        try:
            updated = update_lore_item(lore_dir, slug, item)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "item": updated})

    @app.get("/lore/trash")
    def api_lore_trash_list():
        lore_dir = current_app.config["LOL_LORE_DIR"]
        items = list_trashed_lore_items(lore_dir)
        return jsonify({"items": items, "count": len(items)})

    @app.get("/lore/trash/<slug>")
    def api_lore_trash_get(slug: str):
        lore_dir = current_app.config["LOL_LORE_DIR"]
        try:
            data = load_trashed_lore_item(lore_dir, slug)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify(data)

    @app.post("/lore/trash")
    def api_lore_trash():
        body = request.get_json(force=True, silent=False) or {}
        slug = str(body.get("slug") or "").strip()
        if not slug:
            return jsonify({"error": "slug is required"}), 400
        lore_dir = current_app.config["LOL_LORE_DIR"]
        try:
            result = trash_lore_item(lore_dir, slug)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify({"ok": True, **result})

    @app.post("/lore/trash/restore")
    def api_lore_trash_restore():
        body = request.get_json(force=True, silent=False) or {}
        slug = str(body.get("slug") or "").strip()
        if not slug:
            return jsonify({"error": "slug is required"}), 400
        lore_dir = current_app.config["LOL_LORE_DIR"]
        try:
            result = restore_trashed_lore_item(lore_dir, slug)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify({"ok": True, **result})

    @app.post("/lore/trash/expunge")
    def api_lore_trash_expunge():
        body = request.get_json(force=True, silent=False) or {}
        slug = str(body.get("slug") or "").strip()
        if not slug:
            return jsonify({"error": "slug is required"}), 400
        lore_dir = current_app.config["LOL_LORE_DIR"]
        try:
            result = expunge_trashed_lore_item(lore_dir, slug)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify({"ok": True, **result})

    @app.get("/prompts")
    def api_prompts_index():
        prompts_file = current_app.config["LOL_PROMPTS_FILE"]
        return jsonify(load_prompts_index(prompts_file, default_settings=configured_default_settings()))

    @app.get("/prompts/search")
    def api_prompts_search():
        prompts_file = current_app.config["LOL_PROMPTS_FILE"]
        query = request.args.get("q")
        category = request.args.get("category")
        setting = request.args.get("setting")
        items = search_prompts(
            prompts_file,
            query=query,
            category=category,
            setting=setting,
            default_settings=configured_default_settings(),
        )
        return jsonify({
            "items": items,
            "count": len(items),
            "filters": {
                "q": query,
                "category": category,
                "setting": setting,
            },
        })

    @app.post("/prompts/update")
    def api_prompts_update():
        body = request.get_json(force=True, silent=False) or {}
        prompt_id = str(body.get("id") or "").strip()
        item = body.get("item")
        if not prompt_id:
            return jsonify({"error": "id is required"}), 400
        if not isinstance(item, dict):
            return jsonify({"error": "item must be an object"}), 400
        prompts_file = current_app.config["LOL_PROMPTS_FILE"]
        try:
            updated = update_prompt(prompts_file, prompt_id, item)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "item": updated})

    @app.post("/prompts/trash")
    def api_prompts_trash():
        body = request.get_json(force=True, silent=False) or {}
        prompt_id = str(body.get("id") or "").strip()
        if not prompt_id:
            return jsonify({"error": "id is required"}), 400
        prompts_file = current_app.config["LOL_PROMPTS_FILE"]
        try:
            result = trash_prompt(prompts_file, prompt_id)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, **result})

    @app.get("/config-enrichment")
    def config_enrichment_page():
        return render_template("config_enrichment.html")

    @app.get("/config-enrichment/candidates")
    def api_config_enrichment_candidates():
        docs_dir = current_app.config["LOL_DOCS_DIR"]
        path = docs_dir / "lore_config_enrichment_candidates.json"
        data = load_candidates(path)
        return jsonify(curated_candidates(data))

    @app.post("/config-enrichment/apply")
    def api_config_enrichment_apply():
        payload = request.get_json(force=True, silent=False) or {}
        race_keys = payload.get("race_keys", []) or []
        area_keys = payload.get("area_keys", []) or payload.get("environment_keys", []) or []
        output_path_raw = str(payload.get("output_path", "config/worlds/lands_of_legends/90_lore_enrichment.yaml"))

        docs_dir = current_app.config["LOL_DOCS_DIR"]
        generated_path = docs_dir / "lore_config_enrichment.generated.yaml"
        generated_doc = load_generated_yaml(generated_path)
        selected_doc = select_yaml_sections(
            generated_doc,
            race_keys=[str(x) for x in race_keys],
            area_keys=[str(x) for x in area_keys],
        )

        output_path = resolve_project_relative_path(
            output_path_raw,
            default="config/worlds/lands_of_legends/90_lore_enrichment.yaml",
        )
        write_yaml(output_path, selected_doc)
        return jsonify({
            "status": "ok",
            "output_path": str(output_path.relative_to(current_app.config["LOL_PROJECT_ROOT"])),
            "counts": {
                "races": len(selected_doc.get("races", {}) or {}),
                "areas": len(selected_doc.get("areas", {}) or selected_doc.get("environments", {}) or {}),
                "environments": len(selected_doc.get("areas", {}) or selected_doc.get("environments", {}) or {}),
                "settlements": len(selected_doc.get("settlements", {}) or {}),
                "encounters": len(selected_doc.get("encounters", {}) or {}),
            },
        })

    @app.get("/unified-search")
    def api_unified_search():
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        compendium_dir = current_app.config["LOL_COMPENDIUM_DIR"]
        enabled_compendiums = enabled_compendium_ids_for_search()

        def result_source_priority(item: dict) -> tuple[int, str]:
            source = str(item.get("source") or "").strip().lower()
            if source == "storage":
                return (0, str(item.get("name") or "").lower())
            if source == "lore":
                return (1, str(item.get("name") or "").lower())
            if source in {FOUNDRY_COMPENDIUM_ID, "foundry_vtt"}:
                return (2, str(item.get("name") or "").lower())
            if source == "compendium" or source == "csrd":
                return (3, str(item.get("name") or "").lower())
            return (4, str(item.get("name") or "").lower())

        raw_item_type = str(request.args.get("type") or "").strip().lower()
        item_type_aliases = {
            "artifacts": "artifact",
            "cyphers": "cypher",
            "landmarks": "landmark",
        }
        item_type = item_type_aliases.get(raw_item_type, raw_item_type) or None
        storage_item_type = item_type
        compendium_item_type = item_type
        if item_type == "player_character":
            storage_item_type = "player_character"
            compendium_item_type = "character"
        q = request.args.get("q")
        area = request.args.get("area")
        location = request.args.get("location")
        environment = request.args.get("environment")
        race = request.args.get("race")
        profession = request.args.get("profession")
        setting = request.args.get("setting")
        include_local = str(request.args.get("include_local", "1")).strip().lower() not in {"0", "false", "no", "off"}
        include_lore = str(request.args.get("include_lore", "1")).strip().lower() not in {"0", "false", "no", "off"}
        include_csrd = str(request.args.get("include_csrd", "1")).strip().lower() not in {"0", "false", "no", "off"}
        include_official = str(request.args.get("include_official", "1")).strip().lower() not in {"0", "false", "no", "off"}
        include_foundry = str(request.args.get("include_foundry", "1")).strip().lower() not in {"0", "false", "no", "off"}
        include_godforsaken = str(request.args.get("include_godforsaken", "1")).strip().lower() not in {"0", "false", "no", "off"}
        compendiums_raw = str(request.args.get("compendiums") or "").strip()
        selected_compendiums: list[str] | None = None
        selected_official_compendiums: set[str] = set()
        if compendiums_raw:
            selected = [
                part.strip().lower()
                for part in compendiums_raw.split(",")
                if part.strip()
            ]
            selected_compendiums = list(dict.fromkeys(selected))
            include_csrd = "csrd" in selected_compendiums
            include_foundry = FOUNDRY_COMPENDIUM_ID in selected_compendiums
            selected_official_compendiums = {
                s for s in selected_compendiums
                if s not in {"csrd", FOUNDRY_COMPENDIUM_ID}
            }
            include_official = bool(selected_official_compendiums)
            include_godforsaken = "godforsaken" in selected_official_compendiums

        if "csrd" not in enabled_compendiums:
            include_csrd = False
        if FOUNDRY_COMPENDIUM_ID not in enabled_compendiums:
            include_foundry = False
        if selected_official_compendiums:
            selected_official_compendiums = {s for s in selected_official_compendiums if s in enabled_compendiums}
            include_official = bool(selected_official_compendiums)
            include_godforsaken = "godforsaken" in selected_official_compendiums
        elif include_official or include_godforsaken:
            include_official = bool(enabled_compendiums - {"csrd", FOUNDRY_COMPENDIUM_ID})
            include_godforsaken = include_godforsaken and ("godforsaken" in enabled_compendiums)

        if include_local or include_foundry:
            storage_results = search_saved_results(
                storage_dir,
                item_type=storage_item_type,
                setting=setting,
                area=area,
                location=location,
                environment=environment,
                race=race,
                profession=profession,
                name_contains=q,
                default_settings=configured_default_settings(),
            ) or []
        else:
            storage_results = []

        if include_csrd:
            if compendium_item_type:
                # If user selected a non-compendium type (e.g. character_sheet),
                # do not include compendium results.
                if compendium_item_type in SUPPORTED_COMPENDIUM_TYPES:
                    compendium_results = search_compendium(
                        compendium_dir,
                        item_type=compendium_item_type,
                        setting=setting,
                        query=q,
                    ) or []
                else:
                    compendium_results = []
            else:
                # No explicit type filter: include all compendium types.
                compendium_results = search_compendium(
                    compendium_dir,
                    item_type=None,
                    setting=setting,
                    query=q,
                ) or []
        else:
            compendium_results = []

        if include_lore and (not compendium_item_type or compendium_item_type == "lore"):
            lore_dir = current_app.config["LOL_LORE_DIR"]
            lore_results = search_lore(
                lore_dir,
                query=q,
                setting=setting,
                location=location,
                default_settings=configured_default_settings(),
            ) or []
        else:
            lore_results = []

        if include_official or include_godforsaken:
            official_dir = current_app.config["LOL_OFFICIAL_COMPENDIUM_DIR"]
            if compendium_item_type:
                if compendium_item_type in SUPPORTED_OFFICIAL_COMPENDIUM_TYPES:
                    official_results = search_official_compendium(
                        official_dir,
                        item_type=compendium_item_type,
                        setting=setting,
                        query=q,
                    ) or []
                else:
                    official_results = []
            else:
                official_results = search_official_compendium(
                    official_dir,
                    item_type=None,
                    setting=setting,
                    query=q,
                ) or []
        else:
            official_results = []

        normalized_official_results = normalize_official_compendium_results(official_results)
        if selected_compendiums is not None:
            normalized_official_results = [
                x for x in normalized_official_results
                if str(x.get("source") or "").strip().lower() in selected_official_compendiums
            ]
        elif include_official and not include_godforsaken:
            normalized_official_results = [x for x in normalized_official_results if x.get("source") != "godforsaken"]
        elif include_godforsaken and not include_official:
            normalized_official_results = [x for x in normalized_official_results if x.get("source") == "godforsaken"]
        normalized_official_results = [
            x for x in normalized_official_results
            if str(x.get("source") or "").strip().lower() in enabled_compendiums
        ]

        normalized_storage_results = normalize_storage_results(storage_results)
        if not include_local:
            normalized_storage_results = [
                x for x in normalized_storage_results
                if str(x.get("source") or "").strip().lower() == FOUNDRY_COMPENDIUM_ID
            ]
        if not include_foundry:
            normalized_storage_results = [
                x for x in normalized_storage_results
                if str(x.get("source") or "").strip().lower() == "storage"
            ]

        items = (
            normalized_storage_results
            + normalize_lore_results(lore_results)
            + normalize_compendium_results(compendium_results)
            + normalized_official_results
        )
        items.sort(key=result_source_priority)

        return jsonify({
            "items": items,
            "count": len(items),
            "filters": {
                "q": q,
                "type": item_type,
                "setting": setting,
                "area": area or environment,
                "location": location,
                "environment": environment,
                "race": race,
                "profession": profession,
                "include_local": include_local,
                "include_lore": include_lore,
                "include_csrd": include_csrd,
                "include_official": include_official,
                "include_foundry": include_foundry,
                "include_godforsaken": include_godforsaken,
                "compendiums": selected_compendiums or [],
            },
        })
    
    @app.get("/search")
    def unified_search_page():
        return render_template("search.html")

    @app.errorhandler(Exception)
    def handle_exception(exc: Exception):
        return jsonify({"error": str(exc)}), 400
