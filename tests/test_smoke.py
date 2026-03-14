from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lol_api.lore import (
    expunge_trashed_lore_item,
    list_trashed_lore_items,
    load_lore_index,
    restore_trashed_lore_item,
    trash_lore_item,
    update_lore_item,
)
from lol_api.config_loader import load_config_dir
from lol_api.storage import (
    expunge_trashed_result,
    list_saved_results,
    list_trashed_results,
    restore_trashed_result,
    save_generated_result,
    search_saved_results,
    trash_saved_result,
    update_saved_result,
)


class SmokeTests(unittest.TestCase):
    def test_plugin_discovery_accepts_metadata_only_folders(self) -> None:
        try:
            from lol_api.api import discover_plugins_from_roots
        except ModuleNotFoundError as exc:
            self.skipTest(f"plugin discovery test requires app dependencies: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugins_dir = root / "Plugins"
            plugins_dir.mkdir(parents=True, exist_ok=True)

            metadata_only = plugins_dir / "openai_remote"
            metadata_only.mkdir()
            (metadata_only / "plugin.json").write_text(
                json.dumps(
                    {
                        "name": "OpenAI Remote RAG",
                        "summary": "Queries OpenAI API with vector-indexed private compendium context.",
                    }
                ),
                encoding="utf-8",
            )

            package_only = plugins_dir / "foundryVTT"
            package_only.mkdir()
            (package_only / "__init__.py").write_text("", encoding="utf-8")

            items = discover_plugins_from_roots([plugins_dir], project_root=root)

            by_id = {item["id"]: item for item in items}
            self.assertIn("openai_remote", by_id)
            self.assertEqual(by_id["openai_remote"]["name"], "OpenAI Remote RAG")
            self.assertIn("foundryVTT", by_id)

    def test_ai_generate_vision_prompt_and_model_constants(self) -> None:
        try:
            from lol_api.api import AI_GENERATE_VISION_TYPES, OLLAMA_VISION_MODEL, ai_generate_vision_prompt
        except ModuleNotFoundError as exc:
            self.skipTest(f"ai generate vision test requires app dependencies: {exc}")

        self.assertEqual(OLLAMA_VISION_MODEL, "llama3.2-vision")
        self.assertEqual(
            AI_GENERATE_VISION_TYPES,
            {"encounter", "npc", "creature", "player_character", "artifact", "cypher", "landmark", "settlement", "inn"},
        )
        self.assertIn("RPG encounter seed", ai_generate_vision_prompt("encounter"))
        self.assertIn("local lore", ai_generate_vision_prompt("encounter").lower())
        self.assertIn("character portrait", ai_generate_vision_prompt("npc"))
        self.assertIn("creature", ai_generate_vision_prompt("creature").lower())
        self.assertIn("player character portrait", ai_generate_vision_prompt("player_character").lower())
        self.assertIn("settlement", ai_generate_vision_prompt("settlement").lower())
        self.assertIn("inn", ai_generate_vision_prompt("inn").lower())

    def test_ai_generate_prompt_discourages_default_level_four_npcs(self) -> None:
        source = Path(PROJECT_ROOT / "lol_api" / "api.py").read_text(encoding="utf-8")
        self.assertIn("do not default to level 4", source)

    def test_ai_generate_prompt_reinforces_cypher_not_dnd(self) -> None:
        source = Path(PROJECT_ROOT / "lol_api" / "api.py").read_text(encoding="utf-8")
        self.assertIn("Use Cypher System conventions, not D&D, Pathfinder, or 5e conventions.", source)
        self.assertIn("damage expressions such as `1d8+2`", source)
        self.assertIn("Avoid stock fantasy openings", source)
        self.assertIn("proper in-setting personal names", source)
        self.assertIn("race- or culture-specific naming patterns", source)
        self.assertIn("Do not infer pleasant, charming, or kindly interaction modifiers merely because the subject is female, a priest, or well-dressed", source)

    def test_ai_generate_prompt_uses_setting_identity_vocab(self) -> None:
        source = Path(PROJECT_ROOT / "lol_api" / "api.py").read_text(encoding="utf-8")
        self.assertIn("Allowed setting races:", source)
        self.assertIn("If no valid local race, variant, profession, or culture can be supported", source)
        self.assertIn("Treat place names, cultures, factions, and religions as distinct unless the context explicitly equates them.", source)
        self.assertIn("def _build_lore_context(", source)
        self.assertIn('if cid == "local_library"', source)
        self.assertIn("query_tokens =", source)
        self.assertIn('str(full_item.get("content_markdown", ""))', source)
        self.assertIn("If the user brief explicitly provides a name", source)
        self.assertIn("do not reuse a recent innkeeper or tavernkeeper name", source)
        self.assertIn("If the brief specifies the inn's name, keep that exact inn name", source)
        self.assertIn("If you include a `proprietor`, `innkeeper`, or owner figure inside the inn card", source)
        self.assertIn("Do not fall back to stock tavernkeeper names like Mira", source)
        self.assertIn("Avoid repeating these recent surnames or family-name stems", source)
        self.assertIn("Do not default innkeepers, tavernkeepers, or proprietors to 'prefers to avoid conflict'", source)
        self.assertIn("Do not default the proprietor to a genial conflict-diffuser who calms rowdy patrons with wit", source)

    def test_ai_generate_ui_allows_local_library_sourcebook(self) -> None:
        source = Path(PROJECT_ROOT / "lol_api" / "templates" / "ai_generate.html").read_text(encoding="utf-8")
        self.assertIn('<option value="inn">Inn</option>', source)
        self.assertIn("row.compendium_ids?.length === 1", source)
        self.assertNotIn(".filter((row) => row.compendium_ids && !row.compendium_ids.includes('local_library'))", source)
        self.assertIn("AI_GENERATE_RECENTS_KEY", source)
        self.assertIn("recent_examples: loadRecentGenerationHints()", source)
        self.assertIn("name_roots", source)
        self.assertIn("surname_roots", source)
        self.assertIn('list="ai-npc-profession-list"', source)
        self.assertIn("fillDatalist(els.npcProfessionList, data.professions || []);", source)
        self.assertIn("deriveCardSuggestions", source)
        self.assertIn("generateSuggestedCard", source)
        self.assertIn("saveLinkedCard", source)
        self.assertIn("ai-suggest-generate-btn", source)
        self.assertIn("rememberGeneratedCard(normalizedCard);", source)
        self.assertIn('Keep the inn name exactly as', source)
        self.assertIn('Invent a fresh personal name that is not one of the recently generated innkeeper names', source)
        self.assertIn("String(card.proprietor || '').trim()", source)

    def test_ai_generate_routes_prepend_lore_context(self) -> None:
        source = Path(PROJECT_ROOT / "lol_api" / "api.py").read_text(encoding="utf-8")
        self.assertIn("lore_items, lore_citations, lore_context = _build_lore_context(", source)
        self.assertIn('location=location_id or area_id', source)
        self.assertIn('location=location or area', source)
        self.assertIn('grounded_context = f\"{lore_context}\\n\\n{grounded_context}\"', source)
        self.assertIn('"citations": lore_citations + citations', source)
        self.assertIn('"vector_items": lore_items + items', source)

    def test_ai_generate_npc_professions_are_not_limited_to_player_character_list(self) -> None:
        source = Path(PROJECT_ROOT / "lol_api" / "api.py").read_text(encoding="utf-8")
        self.assertIn("For NPC professions specifically, you may use broader in-world social roles", source)
        self.assertIn('str(content_type or "").strip().lower() == "npc"', source)

    def test_ai_generate_prompt_uses_culture_name_tables_for_places(self) -> None:
        source = Path(PROJECT_ROOT / "lol_api" / "api.py").read_text(encoding="utf-8")
        self.assertIn("def _ai_generate_place_name_vocab(", source)
        self.assertIn("Use these culture-specific settlement naming examples as guidance", source)
        self.assertIn("Use these culture-specific inn naming examples as guidance", source)
        self.assertIn('"inn": "inn"', source)

    def test_search_template_storage_editor_preserves_variant_and_culture(self) -> None:
        source = Path(PROJECT_ROOT / "lol_api" / "templates" / "search.html").read_text(encoding="utf-8")
        self.assertIn("storage-edit-variant", source)
        self.assertIn("storage-edit-culture", source)
        self.assertIn("state.selectedResultKey = `storage:/storage/${encodeURIComponent(filename)}`", source)
        self.assertIn("Cards At This Location", source)
        self.assertIn("loadRelatedLocationCards", source)
        self.assertIn("related-location-open-btn", source)
        self.assertIn("fetchJson(`/storage/${encodeURIComponent(filename)}`)", source)
        self.assertIn("renderSearchTag", source)
        self.assertIn("applyTagSearch", source)
        self.assertIn("clickable-tag", source)
        self.assertIn("els.environment.value = '';", source)
        self.assertIn("els.location.value = '';", source)
        self.assertIn('if (itemType === "inn") {', source)
        self.assertIn('push("Clientele"', source)
        self.assertIn('push("Proprietor"', source)

    def test_search_ai_query_sends_multiple_compendium_ids(self) -> None:
        source = Path(PROJECT_ROOT / "lol_api" / "templates" / "search.html").read_text(encoding="utf-8")
        self.assertIn("body.compendium_ids = selectedCompendiums;", source)
        self.assertIn("include_lore: Boolean(els.includeLore?.checked)", source)
        self.assertIn("include_local: Boolean(els.includeLocal?.checked)", source)

    def test_api_unified_search_prioritizes_local_and_lore(self) -> None:
        source = Path(PROJECT_ROOT / "lol_api" / "api.py").read_text(encoding="utf-8")
        self.assertIn('if source == "storage"', source)
        self.assertIn('if source == "lore"', source)
        self.assertIn("items.sort(key=result_source_priority)", source)

    def test_setting_world_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save_generated_result(
                root,
                {
                    "type": "npc",
                    "name": "Fenmir Scout",
                    "metadata": {
                        "settings": ["fantasy", "lands_of_legends"],
                        "area": "fenmir_highlands",
                    },
                },
                {},
            )
            save_generated_result(
                root,
                {
                    "type": "npc",
                    "name": "Neon Agent",
                    "metadata": {
                        "settings": ["cyberpunk"],
                        "area": "neon_district",
                    },
                },
                {},
            )

            filtered = search_saved_results(
                root,
                setting="fantasy",
                area="fenmir_highlands",
            )
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0]["name"], "Fenmir Scout")

            legacy_alias = search_saved_results(
                root,
                setting="fantasy",
                environment="fenmir_highlands",
            )
            self.assertEqual(len(legacy_alias), 1)
            self.assertEqual(legacy_alias[0]["name"], "Fenmir Scout")

    def test_storage_search_matches_landmarks_and_description_text(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save_generated_result(
                root,
                {
                    "type": "location",
                    "name": "The Black Spire",
                    "description": "A haunted watchtower above the Fenmir road.",
                    "metadata": {
                        "subtype": "landmark",
                        "location_category_type": "landmark",
                        "settings": ["lands_of_legends"],
                        "area": "fenmir_highlands",
                    },
                },
                {},
            )

            by_landmark = search_saved_results(root, item_type="landmark")
            self.assertEqual(len(by_landmark), 1)
            self.assertEqual(by_landmark[0]["name"], "The Black Spire")

            by_description = search_saved_results(root, name_contains="haunted watchtower")
            self.assertEqual(len(by_description), 1)
            self.assertEqual(by_description[0]["name"], "The Black Spire")

    def test_storage_search_matches_spaced_area_query_against_slugged_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save_generated_result(
                root,
                {
                    "type": "location",
                    "name": "The Whispering Cliffs",
                    "description": "Wind-carved cliffs above the old Fenmir trail.",
                    "metadata": {
                        "subtype": "landmark",
                        "location_category_type": "landmark",
                        "settings": ["lands_of_legends"],
                        "area": "fenmir_wilds",
                    },
                },
                {},
            )

            by_spaced_area = search_saved_results(root, name_contains="fenmir wilds")
            self.assertEqual(len(by_spaced_area), 1)
            self.assertEqual(by_spaced_area[0]["name"], "The Whispering Cliffs")

    def test_storage_search_matches_rollable_table_primarycategory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            saved_path = save_generated_result(
                root,
                {
                    "type": "lore",
                    "primarycategory": "rollable_table",
                    "name": "Roadside Omens",
                    "description": "A d20 table of uncanny omens.",
                    "sections": {
                        "name": "Roadside Omens",
                        "dice": "d20",
                        "rows": [
                            {"roll": "1-2", "result": "A black dog crosses the path."},
                            {"roll": "3-4", "result": "The milestone bleeds rust."},
                        ],
                    },
                    "metadata": {
                        "primarycategory": "rollable_table",
                        "subtype": "rollable_table",
                        "settings": ["lands_of_legends"],
                    },
                },
                {},
            )

            self.assertIn("rollable_table/", str(saved_path.relative_to(root)).replace("\\", "/"))
            self.assertTrue(saved_path.name.startswith("rollable_table_"))

            matches = search_saved_results(root, item_type="rollable_table")
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["name"], "Roadside Omens")

    def test_storage_search_player_character_alias_matches_character_and_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save_generated_result(
                root,
                {
                    "type": "character",
                    "name": "Legacy Hero",
                    "metadata": {"settings": ["lands_of_legends"]},
                },
                {},
            )
            save_generated_result(
                root,
                {
                    "type": "character_sheet",
                    "name": "Sheet Hero",
                    "metadata": {"settings": ["lands_of_legends"]},
                },
                {},
            )

            matches = search_saved_results(root, item_type="player_character")
            self.assertEqual(len(matches), 2)
            self.assertEqual({item["name"] for item in matches}, {"Legacy Hero", "Sheet Hero"})

    def test_lands_of_legends_includes_fantasy_type_profession_aliases(self) -> None:
        config = load_config_dir(PROJECT_ROOT / "config", world_id="lands_of_legends")
        professions = config.get("professions", {}) if isinstance(config, dict) else {}

        for key in [
            "warrior",
            "adept",
            "explorer",
            "speaker",
            "paladin",
            "cleric",
            "scout",
            "law_speaker",
            "merchant",
        ]:
            self.assertIn(key, professions)

        self.assertIn("barbarian", professions)
        self.assertIn("mage", professions)
        self.assertIn("ranger", professions)
        self.assertEqual(professions["paladin"]["role"], "paladin")
        self.assertEqual(professions["law_speaker"]["role"], "law-speaker")

    def test_lands_of_legends_includes_lhainim_race(self) -> None:
        config = load_config_dir(PROJECT_ROOT / "config", world_id="lands_of_legends")
        races = config.get("races", {}) if isinstance(config, dict) else {}

        self.assertIn("lhainim", races)
        self.assertEqual(races["lhainim"]["character_base"], "lhainim")
        self.assertIn("pixie", races["lhainim"].get("variants", {}))
        self.assertIn("redcap", races["lhainim"].get("variants", {}))

    def test_ai_generate_save_strips_nonexistent_rolltable_card_refs(self) -> None:
        try:
            from lol_api.api import register_routes
        except ModuleNotFoundError as exc:
            self.skipTest(f"ai generate save test requires app dependencies: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app = Flask(__name__, template_folder=str(PROJECT_ROOT / "lol_api" / "templates"))
            app.config.update(
                TESTING=True,
                LOL_STORAGE_DIR=root,
                LOL_PROJECT_ROOT=PROJECT_ROOT,
                LOL_CONFIG={},
                LOL_CONFIG_DIR=PROJECT_ROOT / "config",
                LOL_OFFICIAL_COMPENDIUM_DIR=PROJECT_ROOT / "official_compendium",
                LOL_COMPENDIUM_DIR=PROJECT_ROOT / "CSRD" / "compendium",
            )
            register_routes(app)
            client = app.test_client()

            response = client.post(
                "/ai-generate/save",
                json={
                    "content_type": "rollable_table",
                    "card": {
                        "primarycategory": "rollable_table",
                        "name": "Quirky Cyphers",
                        "dice": "d20",
                        "rows": [
                            {
                                "roll": "1-2",
                                "result": "A curious cypher.",
                                "card_ref": "cypher/cypher_20990101T000000.json",
                                "card_label": "Open fake card",
                            }
                        ],
                    },
                    "payload": {},
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            filename = str(data["result"]["storage"]["filename"])
            saved = json.loads((root / filename).read_text(encoding="utf-8"))
            self.assertEqual(saved["result"]["type"], "rollable_table")
            rows = saved["result"]["sections"]["rows"]
            self.assertEqual(len(rows), 1)
            self.assertNotIn("card_ref", rows[0])
            self.assertNotIn("card_label", rows[0])

    def test_ai_generate_save_player_character_creates_character_sheet(self) -> None:
        try:
            from lol_api.api import register_routes
        except ModuleNotFoundError as exc:
            self.skipTest(f"ai generate save test requires app dependencies: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app = Flask(__name__, template_folder=str(PROJECT_ROOT / "lol_api" / "templates"))
            app.config.update(
                TESTING=True,
                LOL_STORAGE_DIR=root,
                LOL_PROJECT_ROOT=PROJECT_ROOT,
                LOL_CONFIG={},
                LOL_CONFIG_DIR=PROJECT_ROOT / "config",
                LOL_OFFICIAL_COMPENDIUM_DIR=PROJECT_ROOT / "official_compendium",
                LOL_COMPENDIUM_DIR=PROJECT_ROOT / "CSRD" / "compendium",
            )
            register_routes(app)
            client = app.test_client()

            response = client.post(
                "/ai-generate/save",
                json={
                    "content_type": "player_character",
                    "card": {
                        "name": "Aurora-of-Ash",
                        "sentence": "Aurora-of-Ash is an Impulsive Lhainim who Uses Wild Magic.",
                        "type": "Trixter (Adept)",
                        "descriptor": "Impulsive",
                        "focus": "Uses Wild Magic",
                        "effort": 1,
                        "cypher_limit": 3,
                        "weapons": "Practiced with light weapons; medium and heavy attacks are hindered.",
                        "pools": {
                            "max": {"might": 8, "speed": 13, "intellect": 14},
                            "current": {"might": 8, "speed": 13, "intellect": 14},
                        },
                        "edges": {"might": 0, "speed": 1, "intellect": 1},
                        "chosen_abilities": ["Magic Training", "Scan"],
                        "chosen_skills": [
                            {"name": "Initiative", "level": "trained"},
                            {"name": "Stealth", "level": "inability"},
                        ],
                        "attacks": [
                            {
                                "name": "Needle Rapier",
                                "weapon_type": "light weapon",
                                "damage": 2,
                                "range": "immediate",
                                "skill_rating": "practiced",
                            }
                        ],
                        "starting_equipment": ["Fine clothing", "Needle Rapier", "Traveler's satchel"],
                        "equipment": ["Fine clothing", "Needle Rapier", "Traveler's satchel", "Glow-moth charm"],
                        "notes": "A volatile pixie wanderer from Fenmir with too much magic and too little restraint.",
                        "metadata": {
                            "race": "lhainim",
                            "variant": "pixie",
                            "gender": "female",
                            "profession": "witch",
                            "culture": "fenmir",
                            "area": "fenmir_wilds",
                            "setting": "lands_of_legend",
                            "settings": ["lands_of_legend"],
                            "tier": 1,
                        },
                    },
                    "payload": {
                        "setting": "lands_of_legend",
                        "settings": ["lands_of_legend"],
                        "area": "fenmir_wilds",
                        "race": "lhainim",
                        "profession": "witch",
                    },
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            filename = str(data["result"]["storage"]["filename"])
            saved = json.loads((root / filename).read_text(encoding="utf-8"))
            result = saved["result"]

            self.assertEqual(result["type"], "character_sheet")
            self.assertEqual(result["metadata"]["content_type"], "player_character")
            self.assertEqual(result["sheet"]["name"], "Aurora-of-Ash")
            self.assertTrue(result["sheet"]["wizard_completed"])
            self.assertEqual(result["sheet"]["metadata"]["race"], "lhainim")
            self.assertEqual(result["sheet"]["metadata"]["variant"], "pixie")
            self.assertEqual(result["sheet"]["metadata"]["profession"], "witch")
            self.assertEqual(result["sheet"]["metadata"]["culture"], "fenmir")
            self.assertEqual(result["sheet"]["attacks"], ["Needle Rapier (light weapon, 2 damage, immediate, practiced)"])
            self.assertEqual(result["sheet"]["starting_equipment"], ["Fine clothing", "Needle Rapier", "Traveler's satchel"])
            self.assertIn("Impulsive Lhainim", result["description"])

    def test_ai_generate_save_creature_creates_creature_record(self) -> None:
        try:
            from lol_api.api import register_routes
        except ModuleNotFoundError as exc:
            self.skipTest(f"ai generate save test requires app dependencies: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app = Flask(__name__, template_folder=str(PROJECT_ROOT / "lol_api" / "templates"))
            app.config.update(
                TESTING=True,
                LOL_STORAGE_DIR=root,
                LOL_PROJECT_ROOT=PROJECT_ROOT,
                LOL_CONFIG={},
                LOL_CONFIG_DIR=PROJECT_ROOT / "config",
                LOL_OFFICIAL_COMPENDIUM_DIR=PROJECT_ROOT / "official_compendium",
                LOL_COMPENDIUM_DIR=PROJECT_ROOT / "CSRD" / "compendium",
            )
            register_routes(app)
            client = app.test_client()

            response = client.post(
                "/ai-generate/save",
                json={
                    "content_type": "creature",
                    "card": {
                        "type": "creature",
                        "name": "Fenmir Moss-Wolf",
                        "level": 3,
                        "health": 9,
                        "armor": 0,
                        "damage_inflicted": 3,
                        "movement": "Long",
                        "motive": "Hunt intruders",
                        "environment": "Fenmir forests",
                        "combat": "Packs circle prey before lunging in turn.",
                        "interaction": "Skittish unless cornered or starving.",
                        "use": "A stalking wilderness threat or omen of imbalance.",
                        "description": "A lean green-furred predator with moss tangled in its coat.",
                        "metadata": {
                            "setting": "lands_of_legend",
                            "settings": ["lands_of_legend"],
                            "area": "fenmir_wilds",
                        },
                    },
                    "payload": {
                        "setting": "lands_of_legend",
                        "settings": ["lands_of_legend"],
                        "area": "fenmir_wilds",
                    },
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            filename = str(data["result"]["storage"]["filename"])
            saved = json.loads((root / filename).read_text(encoding="utf-8"))
            self.assertEqual(saved["result"]["type"], "creature")
            self.assertEqual(saved["result"]["name"], "Fenmir Moss-Wolf")

    def test_ai_generate_save_npc_without_explicit_stats_gets_stat_block(self) -> None:
        try:
            from lol_api.api import register_routes
        except ModuleNotFoundError as exc:
            self.skipTest(f"ai generate save test requires app dependencies: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app = Flask(__name__, template_folder=str(PROJECT_ROOT / "lol_api" / "templates"))
            app.config.update(
                TESTING=True,
                LOL_STORAGE_DIR=root,
                LOL_PROJECT_ROOT=PROJECT_ROOT,
                LOL_CONFIG={},
                LOL_CONFIG_DIR=PROJECT_ROOT / "config",
                LOL_OFFICIAL_COMPENDIUM_DIR=PROJECT_ROOT / "official_compendium",
                LOL_COMPENDIUM_DIR=PROJECT_ROOT / "CSRD" / "compendium",
            )
            register_routes(app)
            client = app.test_client()

            response = client.post(
                "/ai-generate/save",
                json={
                    "content_type": "npc",
                    "card": {
                        "type": "npc",
                        "name": "Mira Lark",
                        "profession": "innkeeper",
                        "culture": "fenmir",
                        "description": "Mira Lark keeps the hearth warm and the rumors warmer.",
                        "interaction": "Friendly until trouble threatens her guests.",
                        "metadata": {
                            "setting": "lands_of_legends",
                            "settings": ["lands_of_legends"],
                            "area": "fenmir_highlands",
                            "location": "The Heather Cup",
                        },
                    },
                    "payload": {
                        "setting": "lands_of_legends",
                        "settings": ["lands_of_legends"],
                        "area": "fenmir_highlands",
                        "location": "The Heather Cup",
                        "profession": "innkeeper",
                    },
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            filename = str(data["result"]["storage"]["filename"])
            saved = json.loads((root / filename).read_text(encoding="utf-8"))
            stat_block = saved["result"]["stat_block"]
            self.assertEqual(saved["result"]["type"], "npc")
            self.assertEqual(saved["result"]["name"], "Mira Lark")
            self.assertEqual(stat_block["level"], 2)
            self.assertEqual(stat_block["target_number"], 6)
            self.assertEqual(stat_block["health"], 6)
            self.assertEqual(stat_block["damage"], 2)
            self.assertEqual(stat_block["movement"], "Short")

    def test_storage_save_and_trash_sync_vector_index(self) -> None:
        try:
            from lol_api.api import register_routes
        except ModuleNotFoundError as exc:
            self.skipTest(f"vector sync test requires app dependencies: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app = Flask(__name__, template_folder=str(PROJECT_ROOT / "lol_api" / "templates"))
            app.config.update(
                TESTING=True,
                LOL_STORAGE_DIR=root,
                LOL_PROJECT_ROOT=PROJECT_ROOT,
                LOL_CONFIG={},
                LOL_CONFIG_DIR=PROJECT_ROOT / "config",
                LOL_OFFICIAL_COMPENDIUM_DIR=PROJECT_ROOT / "official_compendium",
                LOL_COMPENDIUM_DIR=PROJECT_ROOT / "CSRD" / "compendium",
            )
            register_routes(app)
            client = app.test_client()

            save_response = client.post(
                "/ai-generate/save",
                json={
                    "content_type": "lore",
                    "card": {
                        "type": "lore",
                        "name": "Whisper Salt Oath",
                        "description": "A Fenmir rite sworn over black salt and river water.",
                        "metadata": {
                            "setting": "lands_of_legend",
                            "settings": ["lands_of_legend"],
                            "area": "fenmir_wilds",
                        },
                    },
                    "payload": {
                        "setting": "lands_of_legend",
                        "settings": ["lands_of_legend"],
                        "area": "fenmir_wilds",
                    },
                },
            )
            self.assertEqual(save_response.status_code, 200)
            save_data = save_response.get_json()
            filename = str(save_data["result"]["storage"]["filename"])
            self.assertEqual(save_data["result"]["vector_sync"]["status"], "ok")

            query_response = client.get("/vector/query?q=Whisper%20Salt%20Oath&k=5&compendium_id=local_library")
            self.assertEqual(query_response.status_code, 200)
            query_data = query_response.get_json()
            self.assertTrue(any("Whisper Salt Oath" in str(item.get("heading") or "") or "Whisper Salt Oath" in str(item.get("text") or "") for item in query_data.get("items", [])))

            trash_response = client.post("/storage/trash", json={"filename": filename})
            self.assertEqual(trash_response.status_code, 200)
            trash_data = trash_response.get_json()
            self.assertEqual(trash_data["vector_sync"]["status"], "ok")

            query_after_response = client.get("/vector/query?q=Whisper%20Salt%20Oath&k=5&compendium_id=local_library")
            self.assertEqual(query_after_response.status_code, 200)
            query_after = query_after_response.get_json()
            self.assertFalse(any("Whisper Salt Oath" in str(item.get("heading") or "") or "Whisper Salt Oath" in str(item.get("text") or "") for item in query_after.get("items", [])))

    def test_ai_generate_image_from_url_returns_data_url(self) -> None:
        try:
            from lol_api.api import register_routes
        except ModuleNotFoundError as exc:
            self.skipTest(f"ai generate image url test requires app dependencies: {exc}")

        class FakeHeaders:
            def get_content_type(self) -> str:
                return "image/png"

        class FakeResponse:
            headers = FakeHeaders()

            def read(self) -> bytes:
                return b"\x89PNG\r\n\x1a\nfakepng"

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app = Flask(__name__, template_folder=str(PROJECT_ROOT / "lol_api" / "templates"))
            app.config.update(
                TESTING=True,
                LOL_STORAGE_DIR=root,
                LOL_PROJECT_ROOT=PROJECT_ROOT,
                LOL_CONFIG={},
                LOL_CONFIG_DIR=PROJECT_ROOT / "config",
                LOL_OFFICIAL_COMPENDIUM_DIR=PROJECT_ROOT / "official_compendium",
                LOL_COMPENDIUM_DIR=PROJECT_ROOT / "CSRD" / "compendium",
            )
            register_routes(app)
            client = app.test_client()

            with patch("lol_api.api.urlopen", return_value=FakeResponse()):
                response = client.post(
                    "/ai-generate/image-from-url",
                    json={"url": "https://example.com/fenmir-cliffs.png"},
                )

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(str(data["image_data_url"]).startswith("data:image/png;base64,"))
            self.assertEqual(data["image_name"], "fenmir-cliffs.png")
            self.assertEqual(data["mime_type"], "image/png")

    def test_ai_generate_detect_character_returns_structured_fields(self) -> None:
        try:
            from lol_api.api import register_routes
        except ModuleNotFoundError as exc:
            self.skipTest(f"ai detect character test requires app dependencies: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app = Flask(__name__, template_folder=str(PROJECT_ROOT / "lol_api" / "templates"))
            app.config.update(
                TESTING=True,
                LOL_STORAGE_DIR=root,
                LOL_PROJECT_ROOT=PROJECT_ROOT,
                LOL_CONFIG={},
                LOL_CONFIG_DIR=PROJECT_ROOT / "config",
                LOL_OFFICIAL_COMPENDIUM_DIR=PROJECT_ROOT / "official_compendium",
                LOL_COMPENDIUM_DIR=PROJECT_ROOT / "CSRD" / "compendium",
            )
            register_routes(app)
            client = app.test_client()

            fake_answer = json.dumps(
                {
                    "race": "lhainim",
                    "variant": "pixie",
                    "gender": "female",
                    "profession": "witch",
                    "culture": "fenmir",
                    "appearance_summary": "A winged hedge-witch from the Fenmir wilds.",
                    "confidence": "medium",
                }
            )

            class FakeResponse:
                def read(self) -> bytes:
                    return json.dumps({"response": fake_answer}).encode("utf-8")

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            with patch("lol_api.api.vector_query_index", return_value={"items": []}), patch(
                "lol_api.api.urlopen",
                return_value=FakeResponse(),
            ):
                response = client.post(
                    "/ai-generate/detect-character",
                    json={
                        "provider": "ollama_local",
                        "content_type": "player_character",
                        "image_data_url": "data:image/png;base64,aGVsbG8=",
                        "setting": "lands_of_legends",
                        "area": "fenmir_wilds",
                    },
                )

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["detection"]["race"], "lhainim")
            self.assertEqual(data["detection"]["variant"], "pixie")
            self.assertEqual(data["detection"]["gender"], "female")
            self.assertEqual(data["detection"]["profession"], "witch")
            self.assertEqual(data["detection"]["culture"], "fenmir")
            self.assertEqual(data["detection"]["confidence"], "medium")

    def test_ai_generate_run_restricts_compendiums_to_active_genre(self) -> None:
        try:
            from lol_api.api import register_routes
        except ModuleNotFoundError as exc:
            self.skipTest(f"ai generate restriction test requires app dependencies: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app = Flask(__name__, template_folder=str(PROJECT_ROOT / "lol_api" / "templates"))
            app.config.update(
                TESTING=True,
                LOL_STORAGE_DIR=root,
                LOL_PROJECT_ROOT=PROJECT_ROOT,
                LOL_CONFIG={},
                LOL_CONFIG_DIR=PROJECT_ROOT / "config",
                LOL_SETTING_ID="lands_of_legends",
                LOL_WORLD_ID="lands_of_legends",
                LOL_OFFICIAL_COMPENDIUM_DIR=PROJECT_ROOT / "official_compendium",
                LOL_COMPENDIUM_DIR=PROJECT_ROOT / "CSRD" / "compendium",
            )
            register_routes(app)
            client = app.test_client()

            class FakeResponse:
                def read(self) -> bytes:
                    return json.dumps({"response": "{\"name\":\"Test\",\"description\":\"ok\"}"}).encode("utf-8")

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            with patch("lol_api.api.vector_query_index", return_value={"items": []}), patch(
                "lol_api.api.urlopen",
                return_value=FakeResponse(),
            ):
                response = client.post(
                    "/ai-generate/run",
                    json={
                        "provider": "ollama_local",
                        "content_type": "lore",
                        "brief": "Test fantasy lore",
                        "setting": "lands_of_legends",
                        "schema": {"name": "Title", "description": "Text"},
                        "compendium_ids": ["godforsaken", "neon_rain"],
                    },
                )

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["compendium_ids"], ["godforsaken"])

    def test_ai_generate_run_uses_identity_preferences_in_vector_query(self) -> None:
        try:
            from lol_api.api import register_routes
        except ModuleNotFoundError as exc:
            self.skipTest(f"ai generate vector query test requires app dependencies: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app = Flask(__name__, template_folder=str(PROJECT_ROOT / "lol_api" / "templates"))
            app.config.update(
                TESTING=True,
                LOL_STORAGE_DIR=root,
                LOL_PROJECT_ROOT=PROJECT_ROOT,
                LOL_CONFIG={},
                LOL_CONFIG_DIR=PROJECT_ROOT / "config",
                LOL_SETTING_ID="lands_of_legends",
                LOL_WORLD_ID="lands_of_legends",
                LOL_OFFICIAL_COMPENDIUM_DIR=PROJECT_ROOT / "official_compendium",
                LOL_COMPENDIUM_DIR=PROJECT_ROOT / "CSRD" / "compendium",
            )
            register_routes(app)
            client = app.test_client()

            class FakeResponse:
                def read(self) -> bytes:
                    return json.dumps({"response": "{\"name\":\"Test Priest\",\"description\":\"ok\"}"}).encode("utf-8")

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            with patch("lol_api.api.vector_query_index", return_value={"items": []}) as mocked_vector_query, patch(
                "lol_api.api.urlopen",
                return_value=FakeResponse(),
            ):
                response = client.post(
                    "/ai-generate/run",
                    json={
                        "provider": "ollama_local",
                        "content_type": "npc",
                        "setting": "lands_of_legends",
                        "image_data_url": "data:image/png;base64,aGVsbG8=",
                        "generation_preferences": {
                            "race": "human",
                            "variant": "xanthir",
                            "profession": "priest",
                        },
                        "schema": {"type": "npc", "name": "NPC Name"},
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertTrue(mocked_vector_query.called)
            query_value = str(mocked_vector_query.call_args.kwargs.get("query") or "")
            self.assertIn("xanthir", query_value)
            self.assertIn("priest", query_value)

    def test_ai_generate_run_normalizes_npc_health_to_cypher_band(self) -> None:
        try:
            from lol_api.api import register_routes
        except ModuleNotFoundError as exc:
            self.skipTest(f"ai generate normalization test requires app dependencies: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app = Flask(__name__, template_folder=str(PROJECT_ROOT / "lol_api" / "templates"))
            app.config.update(
                TESTING=True,
                LOL_STORAGE_DIR=root,
                LOL_PROJECT_ROOT=PROJECT_ROOT,
                LOL_CONFIG={},
                LOL_CONFIG_DIR=PROJECT_ROOT / "config",
                LOL_SETTING_ID="lands_of_legends",
                LOL_WORLD_ID="lands_of_legends",
                LOL_OFFICIAL_COMPENDIUM_DIR=PROJECT_ROOT / "official_compendium",
                LOL_COMPENDIUM_DIR=PROJECT_ROOT / "CSRD" / "compendium",
            )
            register_routes(app)
            client = app.test_client()

            fake_answer = json.dumps(
                {
                    "type": "npc",
                    "name": "Elysia Shadowthorn",
                    "description": "Elysia Shadowthorn is a striking figure in dark armor.",
                    "race": "shadowed elf",
                    "variant": "duskblade",
                    "profession": "shadowblade",
                    "culture": "umbral kin",
                    "level": 5,
                    "health": 20,
                    "armor": 2,
                    "damage_inflicted": 6,
                }
            )

            class FakeResponse:
                def read(self) -> bytes:
                    return json.dumps({"response": fake_answer}).encode("utf-8")

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            with patch("lol_api.api.vector_query_index", return_value={"items": []}), patch(
                "lol_api.api.urlopen",
                return_value=FakeResponse(),
            ):
                response = client.post(
                    "/ai-generate/run",
                    json={
                        "provider": "ollama_local",
                        "content_type": "npc",
                        "setting": "lands_of_legends",
                        "schema": {"type": "npc", "name": "NPC Name"},
                        "image_data_url": "data:image/png;base64,aGVsbG8=",
                    },
                )

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["normalized_card"]["race"], "alfirin")
            self.assertEqual(data["normalized_card"]["variant"], "duathrim")
            self.assertEqual(data["normalized_card"]["profession"], "shadowblade")
            self.assertEqual(data["normalized_card"]["health"], 15)

    def test_ai_generate_run_drops_redundant_pleasant_interaction_modifier(self) -> None:
        try:
            from lol_api.api import register_routes
        except ModuleNotFoundError as exc:
            self.skipTest(f"ai generate normalization test requires app dependencies: {exc}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app = Flask(__name__, template_folder=str(PROJECT_ROOT / "lol_api" / "templates"))
            app.config.update(
                TESTING=True,
                LOL_STORAGE_DIR=root,
                LOL_PROJECT_ROOT=PROJECT_ROOT,
                LOL_CONFIG={},
                LOL_CONFIG_DIR=PROJECT_ROOT / "config",
                LOL_SETTING_ID="lands_of_legends",
                LOL_WORLD_ID="lands_of_legends",
                LOL_OFFICIAL_COMPENDIUM_DIR=PROJECT_ROOT / "official_compendium",
                LOL_COMPENDIUM_DIR=PROJECT_ROOT / "CSRD" / "compendium",
            )
            register_routes(app)
            client = app.test_client()

            fake_answer = json.dumps(
                {
                    "type": "npc",
                    "name": "Father Malek",
                    "description": "Father Malek is a stern priest in crimson robes.",
                    "race": "human",
                    "variant": "xanthir",
                    "profession": "priest",
                    "culture": "human",
                    "level": 5,
                    "health": 16,
                    "armor": 2,
                    "damage_inflicted": 5,
                    "modifications": "pleasant interaction as level 5",
                    "interaction": "Cold and severe, he judges weakness harshly.",
                }
            )

            class FakeResponse:
                def read(self) -> bytes:
                    return json.dumps({"response": fake_answer}).encode("utf-8")

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            with patch("lol_api.api.vector_query_index", return_value={"items": []}), patch(
                "lol_api.api.urlopen",
                return_value=FakeResponse(),
            ):
                response = client.post(
                    "/ai-generate/run",
                    json={
                        "provider": "ollama_local",
                        "content_type": "npc",
                        "setting": "lands_of_legends",
                        "image_data_url": "data:image/png;base64,aGVsbG8=",
                        "generation_preferences": {
                            "race": "human",
                            "variant": "xanthir",
                            "profession": "priest",
                        },
                        "schema": {"type": "npc", "name": "NPC Name"},
                    },
                )

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["normalized_card"]["modifications"], "")

    def test_storage_edit_delete_trash_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            saved_path = save_generated_result(
                root,
                {
                    "type": "monster",
                    "name": "Ash Warden",
                    "metadata": {"settings": ["fantasy"], "area": "caldor"},
                },
                {"seed": "abc"},
            )
            filename = str(saved_path.relative_to(root)).replace("\\", "/")

            record = json.loads(saved_path.read_text(encoding="utf-8"))
            record["result"]["name"] = "Ash Warden Prime"
            update_saved_result(root, filename, record)

            listed = list_saved_results(root)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["name"], "Ash Warden Prime")

            moved = trash_saved_result(root, filename)
            self.assertTrue(moved["trash_filename"].endswith(".json"))
            self.assertEqual(len(list_saved_results(root)), 0)
            self.assertEqual(len(list_trashed_results(root)), 1)

            restore_trashed_result(root, moved["trash_filename"])
            self.assertEqual(len(list_saved_results(root)), 1)

            moved_again = trash_saved_result(root, filename)
            expunge_trashed_result(root, moved_again["trash_filename"])
            self.assertEqual(len(list_trashed_results(root)), 0)

    def test_lore_index_consistency_after_edits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lore_root = Path(td)
            entries_dir = lore_root / "entries"
            entries_dir.mkdir(parents=True, exist_ok=True)

            entry = {
                "type": "lore",
                "title": "Ancient Gate",
                "slug": "ancient_gate",
                "source": "local",
                "source_path": "logseq/pages/Ancient Gate.md",
                "excerpt": "Old and mysterious.",
                "categories": ["area"],
                "mentions_total": 1,
                "content_markdown": "# Ancient Gate",
                "settings": ["fantasy", "lands_of_legends"],
                "setting": "lands_of_legends",
            }
            (entries_dir / "ancient_gate.json").write_text(
                json.dumps(entry, indent=2),
                encoding="utf-8",
            )
            (lore_root / "index.json").write_text(
                json.dumps(
                    {
                        "count": 1,
                        "items": [
                            {
                                "title": entry["title"],
                                "slug": entry["slug"],
                                "source_path": entry["source_path"],
                                "excerpt": entry["excerpt"],
                                "categories": entry["categories"],
                                "mentions_total": entry["mentions_total"],
                                "settings": entry["settings"],
                                "setting": entry["setting"],
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            updated = update_lore_item(lore_root, "ancient_gate", {**entry, "title": "Ancient Gate Revised"})
            self.assertEqual(updated["title"], "Ancient Gate Revised")
            idx = load_lore_index(lore_root)
            self.assertEqual(idx["count"], 1)
            self.assertEqual(idx["items"][0]["title"], "Ancient Gate Revised")

            trash_lore_item(lore_root, "ancient_gate")
            self.assertEqual(load_lore_index(lore_root)["count"], 0)
            self.assertEqual(len(list_trashed_lore_items(lore_root)), 1)

            restore_trashed_lore_item(lore_root, "ancient_gate")
            self.assertEqual(load_lore_index(lore_root)["count"], 1)

            trash_lore_item(lore_root, "ancient_gate")
            expunge_trashed_lore_item(lore_root, "ancient_gate")
            self.assertEqual(len(list_trashed_lore_items(lore_root)), 0)

    def test_location_lore_requires_area(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lore_root = Path(td)
            entries_dir = lore_root / "entries"
            entries_dir.mkdir(parents=True, exist_ok=True)
            entry = {
                "type": "lore",
                "title": "Starfall Keep",
                "slug": "starfall_keep",
                "categories": ["city", "location"],
                "content_markdown": "# Starfall Keep",
            }
            (entries_dir / "starfall_keep.json").write_text(
                json.dumps(entry, indent=2),
                encoding="utf-8",
            )
            (lore_root / "index.json").write_text(json.dumps({"count": 0, "items": []}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "location entries require area"):
                update_lore_item(lore_root, "starfall_keep", entry)


if __name__ == "__main__":
    unittest.main()
