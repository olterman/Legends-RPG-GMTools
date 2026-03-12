from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, current_app, jsonify, request, render_template, send_from_directory
from .storage import (
    save_generated_result,
    list_saved_results,
    load_saved_result,
    search_saved_results,
)

from .config_loader import load_config_dir
from .generator import (
    deterministic_rng,
    generate_character,
    generate_npc,
    generate_monster,
    generate_cypher,
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
    load_lore_index,
    list_lore_items,
    load_lore_item,
    search_lore,
)
from .prompts import (
    load_prompts_index,
    search_prompts,
)
from .config_enrichment import (
    load_candidates,
    curated_candidates,
    load_generated_yaml,
    select_yaml_sections,
    write_yaml,
)
 
def register_routes(app: Flask) -> None:
    ## Helpers 
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

    def persist_result(payload, result):
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        path = save_generated_result(storage_dir, result, payload)
        result["storage"] = {
            "filename": path.name,
            "saved": True,
        }
        return result

    def create_missing_local_abilities(sheet: dict, character_name: str) -> list[dict]:
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
            for item in list_saved_results(storage_dir)
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
                },
            }
            local_payload = {
                "origin": "character_sheet_save",
                "character_name": character_name,
                "ability_name": name,
            }
            path = save_generated_result(storage_dir, local_result, local_payload)
            existing_local_titles.add(key)
            created.append({
                "name": name,
                "filename": path.name,
            })

        return created

    def normalize_storage_results(items: list[dict]) -> list[dict]:
        normalized = []

        for item in items:
            meta = item.get("metadata", {}) or {}
            parts = []

            if meta.get("environment"):
                parts.append(f"environment: {meta['environment']}")
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

            normalized.append({
                "source": "storage",
                "type": item.get("type"),
                "title": item.get("name") or item.get("filename"),
                "subtitle": " • ".join(parts),
                "slug": item.get("filename"),
                "url": f"/storage/{item.get('filename')}",
                "raw": item,
            })

        return normalized


    def normalize_compendium_results(items: list[dict]) -> list[dict]:
        normalized = []

        for item in items:
            parts = []

            if item.get("category"):
                parts.append(f"category: {item['category']}")
            if item.get("environment"):
                parts.append(f"environment: {item['environment']}")
            if item.get("level"):
                parts.append(f"level: {item['level']}")
            if item.get("cost"):
                parts.append(f"cost: {item['cost']}")
            if item.get("alpha_section"):
                parts.append(f"section: {item['alpha_section']}")

            normalized.append({
                "source": "compendium",
                "type": item.get("type"),
                "title": item.get("title") or item.get("slug"),
                "subtitle": " • ".join(parts),
                "slug": item.get("slug"),
                "url": f"/compendium/{item.get('type')}/{item.get('slug')}",
                "raw": item,
            })

        return normalized

    ## Routes 
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/map-tools")
    def map_tools():
        return render_template("map_tools.html")

    @app.get("/character-studio")
    def character_studio():
        return render_template("character_studio.html")

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

        all_environments = sorted(list(config.get("environments", {}).keys()))
        monster_environments = sorted(
            list(config.get("monster_traits", {}).get("environments", {}).keys())
        )

        return jsonify({
            "types": ["character", "character_sheet", "npc", "monster", "settlement", "encounter", "cypher", "inn", "skill"],
            "genders": genders,
            "races": sorted(list(config.get("races", {}).keys())),
            "professions": sorted(list(config.get("professions", {}).keys())),
            "environments": all_environments,
            "monster_environments": monster_environments,
            "monster_roles": sorted(list(config.get("monster_roles", {}).keys())),
            "monster_families": sorted(list(config.get("monster_traits", {}).get("families", {}).keys())),
            "styles": sorted(list(config.get("styles", {}).keys())),
        })
    
    @app.get("/storage")
    def api_storage_list():
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        return jsonify({
            "items": list_saved_results(storage_dir)
        })
    @app.get("/library")
    def library():
        return render_template("library.html")
        
    @app.get("/storage/<path:filename>")
    def api_storage_get(filename: str):
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        return jsonify(load_saved_result(storage_dir, filename))

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
            data = load_saved_result(storage_dir, filename)
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

    @app.get("/storage/search")
    def api_storage_search():
        storage_dir = current_app.config["LOL_STORAGE_DIR"]

        item_type = request.args.get("type")
        environment = request.args.get("environment")
        race = request.args.get("race")
        profession = request.args.get("profession")
        name_contains = request.args.get("name")

        results = search_saved_results(
            storage_dir,
            item_type=item_type,
            environment=environment,
            race=race,
            profession=profession,
            name_contains=name_contains,
        )

        return jsonify({
            "items": results,
            "filters": {
                "type": item_type,
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
            "sheet": sheet,
            "metadata": {
                "environment": metadata.get("environment") or payload.get("environment"),
                "race": metadata.get("race") or payload.get("race"),
                "profession": metadata.get("profession") or payload.get("profession"),
                "character_type": metadata.get("character_type"),
                "flavor": metadata.get("flavor"),
                "descriptor": metadata.get("descriptor"),
                "focus": metadata.get("focus"),
                "tier": sheet.get("tier"),
            },
        }
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        created_local_abilities = create_missing_local_abilities(sheet, name)

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

            existing = load_saved_result(storage_dir, filename)
            existing_payload = existing.get("payload") if isinstance(existing, dict) else {}
            record = {
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
        current_app.config["LOL_CONFIG"] = load_config_dir(config_dir)
        return jsonify({
            "status": "reloaded",
            "top_level_keys": sorted(current_app.config["LOL_CONFIG"].keys()),
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

    @app.get("/compendium/search")
    def api_compendium_search():
        compendium_dir = current_app.config["LOL_COMPENDIUM_DIR"]
        item_type = request.args.get("type")
        query = request.args.get("q")

        results = search_compendium(
            compendium_dir,
            item_type=item_type,
            query=query,
        )

        return jsonify({
            "items": results,
            "count": len(results),
            "filters": {
                "type": item_type,
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
        return jsonify(load_lore_index(lore_dir))

    @app.get("/lore/search")
    def api_lore_search():
        lore_dir = current_app.config["LOL_LORE_DIR"]
        query = request.args.get("q")
        items = search_lore(lore_dir, query=query)
        return jsonify({
            "items": items,
            "count": len(items),
            "filters": {"q": query},
        })

    @app.get("/lore/<slug>")
    def api_lore_get(slug: str):
        lore_dir = current_app.config["LOL_LORE_DIR"]
        return jsonify(load_lore_item(lore_dir, slug))

    @app.get("/prompts")
    def api_prompts_index():
        prompts_file = current_app.config["LOL_PROMPTS_FILE"]
        return jsonify(load_prompts_index(prompts_file))

    @app.get("/prompts/search")
    def api_prompts_search():
        prompts_file = current_app.config["LOL_PROMPTS_FILE"]
        query = request.args.get("q")
        category = request.args.get("category")
        items = search_prompts(prompts_file, query=query, category=category)
        return jsonify({
            "items": items,
            "count": len(items),
            "filters": {
                "q": query,
                "category": category,
            },
        })

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
        environment_keys = payload.get("environment_keys", []) or []
        output_path_raw = str(payload.get("output_path", "config/90_lore_enrichment.yaml"))

        docs_dir = current_app.config["LOL_DOCS_DIR"]
        generated_path = docs_dir / "lore_config_enrichment.generated.yaml"
        generated_doc = load_generated_yaml(generated_path)
        selected_doc = select_yaml_sections(
            generated_doc,
            race_keys=[str(x) for x in race_keys],
            environment_keys=[str(x) for x in environment_keys],
        )

        output_path = resolve_project_relative_path(
            output_path_raw,
            default="config/90_lore_enrichment.yaml",
        )
        write_yaml(output_path, selected_doc)
        return jsonify({
            "status": "ok",
            "output_path": str(output_path.relative_to(current_app.config["LOL_PROJECT_ROOT"])),
            "counts": {
                "races": len(selected_doc.get("races", {}) or {}),
                "environments": len(selected_doc.get("environments", {}) or {}),
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
        environment = request.args.get("environment")
        race = request.args.get("race")
        profession = request.args.get("profession")

        storage_results = search_saved_results(
            storage_dir,
            item_type=item_type,
            environment=environment,
            race=race,
            profession=profession,
            name_contains=q,
        ) or []

        if item_type:
            # If user selected a non-compendium type (e.g. character_sheet),
            # do not include compendium results.
            if item_type in SUPPORTED_COMPENDIUM_TYPES:
                compendium_results = search_compendium(
                    compendium_dir,
                    item_type=item_type,
                    query=q,
                ) or []
            else:
                compendium_results = []
        else:
            # No explicit type filter: include all compendium types.
            compendium_results = search_compendium(
                compendium_dir,
                item_type=None,
                query=q,
            ) or []

        items = normalize_storage_results(storage_results) + normalize_compendium_results(compendium_results)

        return jsonify({
            "items": items,
            "count": len(items),
            "filters": {
                "q": q,
                "type": item_type,
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
