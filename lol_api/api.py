from __future__ import annotations

import json
import uuid
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, current_app, jsonify, request, render_template, send_from_directory, send_file
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
)

from .compendium import (
    load_compendium_index,
    list_compendium_items,
    load_compendium_item,
    search_compendium,
    SUPPORTED_COMPENDIUM_TYPES,
)
from .lore import (
    LOCATION_CATEGORY_PRIORITY,
    load_lore_index,
    list_lore_items,
    load_lore_item,
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
    settings_catalog,
    settings_nav_model,
)
from Plugins.foundryVTT.importer import foundry_actor_to_character_sheet, foundry_actor_to_npc_result
from Plugins.foundryVTT.exporter import (
    character_sheet_result_to_foundry_actor,
    npc_or_creature_result_to_foundry_actor,
)
 
def register_routes(app: Flask) -> None:
    ## Helpers 
    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

    def configured_settings_catalog() -> list[str]:
        return settings_catalog(current_app.config["LOL_CONFIG"])

    def configured_default_settings() -> list[str]:
        return default_settings(current_app.config["LOL_CONFIG"])

    def configured_settings_nav() -> dict:
        return settings_nav_model(current_app.config["LOL_CONFIG"])

    def plugin_roots() -> list[Path]:
        project_root = current_app.config["LOL_PROJECT_ROOT"]
        roots = []
        for name in ("plugins", "Plugins"):
            path = project_root / name
            if path.exists() and path.is_dir():
                roots.append(path)
        return roots

    def plugin_state_path() -> Path:
        return current_app.config["LOL_CONFIG_DIR"] / "plugins_state.json"

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
        state = load_plugin_state()
        seen: set[str] = set()
        items: list[dict] = []
        for root in plugin_roots():
            for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
                if not child.is_dir():
                    continue
                if child.name.startswith(".") or child.name == "__pycache__":
                    continue
                if not (child / "__init__.py").exists():
                    continue
                plugin_id = child.name
                if plugin_id in seen:
                    continue
                seen.add(plugin_id)
                items.append({
                    "id": plugin_id,
                    "name": plugin_id,
                    "path": str(child.relative_to(current_app.config["LOL_PROJECT_ROOT"])).replace("\\", "/"),
                    "enabled": state.get(plugin_id, True),
                })
        return items

    def is_plugin_enabled(plugin_id: str) -> bool:
        for item in discover_plugins():
            if item.get("id") == plugin_id:
                return bool(item.get("enabled"))
        return False

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
            catalog[key] = {
                "friendly_name": str(meta.get("friendly_name") or "").strip(),
                "tags": sorted(set(tags)),
                "notes": str(meta.get("notes") or "").strip(),
            }
        return catalog

    def save_image_catalog(catalog: dict[str, dict]) -> None:
        path = image_catalog_path()
        serializable = {
            key: {
                "friendly_name": str(meta.get("friendly_name") or "").strip(),
                "tags": sorted(set(str(x).strip() for x in (meta.get("tags") or []) if str(x).strip())),
                "notes": str(meta.get("notes") or "").strip(),
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

    def resolve_image_ref_path(ref: str) -> Path:
        images_dir = current_app.config["LOL_IMAGES_DIR"].resolve()
        normalized = normalize_image_ref(ref)
        if not normalized:
            raise ValueError("image path is required")
        candidate = (images_dir / normalized).resolve()
        if not str(candidate).startswith(str(images_dir) + "/") and candidate != images_dir:
            raise ValueError("invalid image path")
        return candidate

    def list_image_assets() -> list[dict]:
        images_dir = current_app.config["LOL_IMAGES_DIR"]
        catalog = load_image_catalog()
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
                "tags": [str(x) for x in (meta.get("tags") or []) if str(x).strip()],
                "notes": str(meta.get("notes") or "").strip(),
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
            "filename": path.name,
            "saved": True,
        }
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
                        "source": "foundry_vtt",
                        "origin": "foundry_import",
                        "owner_character_name": owner_name,
                        "owner_character_filename": owner_filename,
                        "settings": list(parent_settings or []),
                    },
                }
                cypher_result = attach_settings_metadata(
                    cypher_result,
                    payload,
                    current_app.config["LOL_CONFIG"],
                )
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
                        "source": "foundry_vtt",
                        "origin": "foundry_import",
                        "owner_character_name": owner_name,
                        "owner_character_filename": owner_filename,
                        "settings": list(parent_settings or []),
                    },
                }
                attack_result = attach_settings_metadata(
                    attack_result,
                    payload,
                    current_app.config["LOL_CONFIG"],
                )
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
                "source": "storage",
                "type": item.get("type"),
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

    @app.get("/map-tools")
    def map_tools():
        return render_template("map_tools.html")

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

    @app.get("/character-studio")
    def character_studio():
        return render_template("character_studio.html")

    @app.get("/media/images")
    def api_media_images_list():
        q = str(request.args.get("q") or "").strip().lower()
        tag = str(request.args.get("tag") or "").strip().lower()
        files = list_image_assets()
        if q:
            files = [
                item for item in files
                if q in " ".join([
                    str(item.get("path") or ""),
                    str(item.get("friendly_name") or ""),
                    str(item.get("notes") or ""),
                    " ".join(item.get("tags") or []),
                ]).lower()
            ]
        if tag:
            files = [
                item for item in files
                if tag in [str(x).strip().lower() for x in (item.get("tags") or [])]
            ]
        return jsonify({"items": files, "count": len(files), "filters": {"q": q, "tag": tag}})

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
        notes = str(request.form.get("notes") or "").strip()
        catalog[rel] = {
            "friendly_name": friendly_name,
            "tags": tags,
            "notes": notes,
        }
        save_image_catalog(catalog)
        return jsonify({
            "ok": True,
            "path": rel,
            "url": f"/images/{rel}",
            "name": path.name,
            "friendly_name": friendly_name,
            "tags": tags,
            "notes": notes,
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
        notes = str(body.get("notes") or "").strip()

        catalog = load_image_catalog()
        catalog[image_ref] = {
            "friendly_name": friendly_name,
            "tags": tags,
            "notes": notes,
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
                "notes": notes,
            },
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
        return jsonify({"ok": True, **payload})

    @app.post("/media/images/delete")
    def api_media_images_delete():
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

        image_path = resolve_image_ref_path(image_ref)
        images_dir = current_app.config["LOL_IMAGES_DIR"].resolve()
        uploads_root = (images_dir / "uploads").resolve()
        if not str(image_path).startswith(str(uploads_root) + "/") and image_path != uploads_root:
            return jsonify({"error": "only images under /images/uploads can be deleted"}), 400

        # Always unattach first from current target.
        if target == "storage":
            if not validate_filename(target_id):
                return jsonify({"error": "invalid storage filename"}), 400
            payload = update_storage_images(target_id, image_ref, action="unattach")
        else:
            payload = update_lore_images(target_id, image_ref, action="unattach")

        if image_path.exists():
            image_path.unlink()
        return jsonify({"ok": True, **payload, "deleted": image_ref})

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
            "settings_nav": configured_settings_nav(),
            "active_world": current_app.config.get("LOL_WORLD_ID"),
            "available_worlds": current_app.config.get("LOL_AVAILABLE_WORLDS", []),
            "available_world_descriptors": current_app.config.get("LOL_AVAILABLE_WORLD_DESCRIPTORS", []),
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
        return render_template("library.html")

    @app.get("/trash")
    def trash():
        return render_template("trash.html")

    @app.get("/image-browser")
    def image_browser():
        return render_template("image_browser.html")
        
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
        return jsonify({"ok": True, "record": updated})

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
        return jsonify({"ok": True, **result})

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
        return jsonify({"ok": True, **result})

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

        actor_type = str(actor.get("type") or "").strip().lower() or "pc"

        if actor_type == "pc":
            try:
                sheet = foundry_actor_to_character_sheet(actor, payload)
            except Exception as exc:
                return jsonify({"error": f"failed to parse Foundry PC actor: {exc}"}), 400

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
                    "source": "foundry_vtt",
                    "origin": "foundry_import",
                    "foundry_actor_type": metadata.get("foundry_actor_type") or actor_type,
                    "foundry_actor_uuid": metadata.get("foundry_actor_uuid"),
                },
            }
            result = attach_settings_metadata(result, payload, current_app.config["LOL_CONFIG"])
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
            return jsonify(result)

        if actor_type == "npc":
            try:
                result = foundry_actor_to_npc_result(actor, payload)
            except Exception as exc:
                return jsonify({"error": f"failed to parse Foundry NPC actor: {exc}"}), 400
            result = attach_settings_metadata(result, payload, current_app.config["LOL_CONFIG"])
            result = persist_result(payload, result)
            return jsonify(result)

        return jsonify({
            "error": f"unsupported Foundry actor type '{actor_type}'. Supported: pc, npc."
        }), 400

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
        current_app.config["LOL_AVAILABLE_WORLDS"] = [
            w["id"] for w in list_world_descriptors(config_dir)
        ]
        current_app.config["LOL_AVAILABLE_WORLD_DESCRIPTORS"] = list_world_descriptors(config_dir)
        current_app.config["LOL_CONFIG"] = load_config_dir(
            config_dir,
            world_id=current_app.config.get("LOL_WORLD_ID"),
        )
        return jsonify({
            "status": "reloaded",
            "top_level_keys": sorted(current_app.config["LOL_CONFIG"].keys()),
        })

    @app.get("/worlds")
    def api_worlds():
        config_dir = current_app.config["LOL_CONFIG_DIR"]
        worlds = list_world_descriptors(config_dir)
        return jsonify({
            "active_world": current_app.config.get("LOL_WORLD_ID"),
            "default_world": infer_default_world_id(config_dir),
            "worlds": worlds,
        })

    @app.post("/worlds/select")
    def api_worlds_select():
        body = request.get_json(force=True, silent=False) or {}
        world_id_raw = body.get("world_id")
        world_id = str(world_id_raw or "").strip() or None

        config_dir = current_app.config["LOL_CONFIG_DIR"]
        available = {w["id"] for w in list_world_descriptors(config_dir)}
        if world_id is not None and world_id not in available:
            return jsonify({"error": f"unknown world_id '{world_id}'"}), 400

        # If world_id is omitted/blank, fall back to inferred default world.
        target_world = world_id or infer_default_world_id(config_dir)

        current_app.config["LOL_WORLD_ID"] = target_world
        current_app.config["LOL_CONFIG"] = load_config_dir(
            config_dir,
            world_id=target_world,
        )
        worlds = list_world_descriptors(config_dir)
        current_app.config["LOL_AVAILABLE_WORLDS"] = [w["id"] for w in worlds]
        current_app.config["LOL_AVAILABLE_WORLD_DESCRIPTORS"] = worlds

        return jsonify({
            "status": "ok",
            "active_world": target_world,
            "worlds": worlds,
        })

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

    @app.get("/compendium-browser")
    def compendium_browser():
        return render_template("compendium_browser.html")

    @app.get("/lore-browser")
    def lore_browser():
        return render_template("lore_browser.html")

    @app.get("/prompt-browser")
    def prompt_browser():
        return render_template("prompt_browser.html")

    @app.get("/lore")
    def api_lore_index():
        lore_dir = current_app.config["LOL_LORE_DIR"]
        return jsonify(load_lore_index(lore_dir, default_settings=configured_default_settings()))

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

        item_type = request.args.get("type")
        q = request.args.get("q")
        area = request.args.get("area")
        location = request.args.get("location")
        environment = request.args.get("environment")
        race = request.args.get("race")
        profession = request.args.get("profession")
        setting = request.args.get("setting")

        storage_results = search_saved_results(
            storage_dir,
            item_type=item_type,
            setting=setting,
            area=area,
            location=location,
            environment=environment,
            race=race,
            profession=profession,
            name_contains=q,
            default_settings=configured_default_settings(),
        ) or []

        if item_type:
            # If user selected a non-compendium type (e.g. character_sheet),
            # do not include compendium results.
            if item_type in SUPPORTED_COMPENDIUM_TYPES:
                compendium_results = search_compendium(
                    compendium_dir,
                    item_type=item_type,
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

        items = normalize_storage_results(storage_results) + normalize_compendium_results(compendium_results)

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
            },
        })
    
    @app.get("/search")
    def unified_search_page():
        return render_template("search.html")

    @app.errorhandler(Exception)
    def handle_exception(exc: Exception):
        return jsonify({"error": str(exc)}), 400
