from __future__ import annotations

from flask import Flask, current_app, jsonify, request, render_template
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

 
def register_routes(app: Flask) -> None:

    def persist_result(payload, result):
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        path = save_generated_result(storage_dir, result, payload)
        result["storage"] = {
            "filename": path.name,
            "saved": True,
        }
        return result

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/map_tools")
    def map_tools():
        return render_template("map_tools.html")

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
            "types": ["character", "npc", "monster", "settlement", "encounter", "cypher", "inn"],
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
        
    @app.get("/storage/<filename>")
    def api_storage_get(filename: str):
        storage_dir = current_app.config["LOL_STORAGE_DIR"]
        return jsonify(load_saved_result(storage_dir, filename))

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

    @app.errorhandler(Exception)
    def handle_exception(exc: Exception):
        return jsonify({"error": str(exc)}), 400