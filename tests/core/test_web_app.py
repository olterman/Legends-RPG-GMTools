from __future__ import annotations

import tempfile
import sys
import unittest
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.web import create_app


class WebAppTests(unittest.TestCase):
    def login_owner(self, client) -> None:
        response = client.post(
            "/login",
            data={"username": "olterman", "password": "changeme"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def api_login_owner(self, client) -> dict[str, str]:
        response = client.post(
            "/api/session/login",
            json={"username": "olterman", "password": "changeme"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        return {"Authorization": f"Bearer {payload['access_token']}"}

    def test_index_requires_login(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()

        response = client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_api_requires_login(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()

        response = client.get("/api/systems")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "bearer token required")

    def test_seeded_owner_can_login_and_fetch_session(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()

        login_response = client.post(
            "/api/session/login",
            json={"username": "olterman", "password": "changeme"},
        )

        self.assertEqual(login_response.status_code, 200)
        payload = login_response.get_json()
        self.assertIn("access_token", payload)
        self.assertEqual(payload["token_type"], "Bearer")
        self.assertEqual(payload["user"]["username"], "olterman")
        self.assertEqual(payload["user"]["email"], "patrik@olterman.se")
        self.assertEqual(payload["user"]["role"], "owner")

        session_response = client.get(
            "/api/session",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )
        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.get_json()["user"]["username"], "olterman")

    def test_index_route_lists_systems_and_rulebook(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("GMForge", text)
        self.assertIn("Cypher System", text)
        self.assertIn("Core Rules", text)
        self.assertIn("Expansions", text)
        self.assertIn("Godforsaken", text)
        self.assertIn("Module:", text)
        self.assertIn("Land of Legends", text)
        self.assertIn("Cypher System Reference Document 2025-08-22", text)
        self.assertNotIn("Expansion: Cypher System Reference Document", text)

    def test_workspace_setting_options_include_system_modules(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/workspace/campaigns?system_id=cypher&expansion_id=godforsaken")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Land of Legends", text)

    def test_generate_workspace_lists_plugin_providers(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/workspace/generate")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Local Structured Draft", text)
        self.assertIn("OpenAI Remote", text)
        self.assertIn("Ollama Local", text)

    def test_generate_workspace_shows_village_publish_targets(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/workspace/generate?record_type=village")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Target Region", text)
        self.assertIn("Target Subregion", text)
        self.assertIn("Caldor Island", text)

    def test_generate_workspace_shows_subregion_publish_targets(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/workspace/generate?record_type=subregion")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Target Region", text)
        self.assertNotIn("Target Subregion", text)
        self.assertIn("Caldor Island", text)

    def test_generate_workspace_shows_city_publish_targets(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/workspace/generate?record_type=city")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Target Region", text)
        self.assertIn("Target Subregion", text)

    def test_generate_workspace_shows_inn_publish_targets(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/workspace/generate?record_type=inn")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Inn Parent Type", text)
        self.assertIn("Inn Parent", text)

    def test_rulebook_route_renders_toc_and_content(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/systems/cypher/addons/csrd/rulebooks/cypher_system_reference_document")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Contents", text)
        self.assertIn("How to Play the Cypher System", text)
        self.assertIn("id=\"descriptor\"", text)
        self.assertIn("This is the new GMForge rulebook reader.", text)

    def test_missing_rulebook_returns_404(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/systems/cypher/addons/csrd/rulebooks/not_real")

        self.assertEqual(response.status_code, 404)

    def test_api_systems_lists_discovered_systems(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        headers = self.api_login_owner(client)

        response = client.get("/api/systems", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("systems", payload)
        ids = {item["id"] for item in payload["systems"]}
        self.assertIn("cypher", ids)

    def test_api_vector_stats_and_query_work(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        headers = self.api_login_owner(client)

        build_response = client.post("/api/vector/reindex", headers=headers)

        self.assertEqual(build_response.status_code, 200)
        build_payload = build_response.get_json()
        self.assertEqual(build_payload["status"], "ok")
        self.assertGreater(build_payload["index"]["document_count"], 0)
        self.assertIn("module_lore", build_payload["index"]["source_counts"])

        stats_response = client.get("/api/vector/stats", headers=headers)
        self.assertEqual(stats_response.status_code, 200)
        stats_payload = stats_response.get_json()
        self.assertTrue(stats_payload["index"]["exists"])

        query_response = client.get(
            "/api/vector/query?q=Old%20Gods&k=5&system_id=cypher&addon_id=godforsaken&module_id=land_of_legends&source_kind=module_lore",
            headers=headers,
        )
        self.assertEqual(query_response.status_code, 200)
        query_payload = query_response.get_json()
        self.assertTrue(query_payload["items"])
        self.assertTrue(any(item["source_kind"] == "module_lore" for item in query_payload["items"]))

    def test_records_workspace_creates_record_and_redirects_to_detail(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.post(
            "/workspace/records",
            data={
                "record_type": "lore_entry",
                "title": "Iron Hollow",
                "slug": "iron_hollow",
                "system_id": "cypher",
                "expansion_id": "godforsaken",
                "setting_id": "land_of_legends",
                "campaign_id": "",
                "summary": "A hard-bitten mining hamlet in the shadow of old stone.",
                "tags": "mine, village",
                "body": "Iron Hollow survives on ore, grit, and stubborn memory.",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        detail_url = response.headers["Location"]
        self.assertIn("/workspace/records/", detail_url)

        detail_response = client.get(detail_url)
        self.assertEqual(detail_response.status_code, 200)
        text = detail_response.get_data(as_text=True)
        self.assertIn("Iron Hollow", text)
        self.assertIn("Iron Hollow survives on ore, grit, and stubborn memory.", text)

    def test_api_create_record_returns_vector_sync_and_record_is_queryable(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        headers = self.api_login_owner(client)

        create_response = client.post(
            "/api/records",
            headers=headers,
            json={
                "record_type": "lore_entry",
                "title": "Whisper Bridge",
                "slug": "whisper_bridge",
                "system_id": "cypher",
                "addon_id": "godforsaken",
                "setting_id": "land_of_legends",
                "content": {"body": "Whisper Bridge is watched by old river vows and lantern smoke."},
                "metadata": {"summary": "A haunted crossing in Land of Legends.", "tags": ["bridge", "river"]},
            },
        )

        self.assertEqual(create_response.status_code, 201)
        payload = create_response.get_json()
        self.assertIn("vector_sync", payload)
        self.assertGreater(payload["vector_sync"]["document_count"], 0)

        query_response = client.get(
            "/api/vector/query?q=Whisper%20Bridge&k=5&source_kind=record&system_id=cypher&setting_id=land_of_legends",
            headers=headers,
        )
        self.assertEqual(query_response.status_code, 200)
        query_payload = query_response.get_json()
        self.assertTrue(any(item["title"] == "Whisper Bridge" for item in query_payload["items"]))

    def test_api_rulebook_returns_toc_and_rendered_content(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        headers = self.api_login_owner(client)

        response = client.get(
            "/api/systems/cypher/addons/csrd/rulebooks/cypher_system_reference_document",
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["system"]["id"], "cypher")
        self.assertEqual(payload["addon"]["id"], "csrd")
        self.assertEqual(payload["rulebook"]["id"], "cypher_system_reference_document")
        self.assertGreater(len(payload["document"]["toc"]), 10)
        self.assertIn("How to Play the Cypher System", payload["document"]["rendered_html"])

    def test_api_module_returns_module_metadata(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        headers = self.api_login_owner(client)

        response = client.get(
            "/api/systems/cypher/addons/godforsaken/modules/land_of_legends",
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["system"]["id"], "cypher")
        self.assertEqual(payload["addon"]["id"], "godforsaken")
        self.assertEqual(payload["module"]["id"], "land_of_legends")
        self.assertEqual(payload["module"]["label"], "Land of Legends")
        self.assertEqual(payload["module"]["theme"], "epic fantasy")
        self.assertTrue(payload["module"]["ui_url"].endswith("/systems/cypher/addons/godforsaken/modules/land_of_legends"))
        self.assertEqual(len(payload["regions"]), 14)
        self.assertEqual(len(payload["peoples"]), 7)
        self.assertEqual(len(payload["creatures"]), 5)
        self.assertEqual(len(payload["items"]), 7)
        self.assertEqual(len(payload["system_categories"]), 9)
        self.assertEqual(len(payload["lore"]), 13)
        self.assertEqual(payload["regions"][0]["status"], "proposed")
        self.assertEqual(payload["peoples"][0]["status"], "proposed")

    def test_api_module_region_returns_region_metadata(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        headers = self.api_login_owner(client)

        response = client.get(
            "/api/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/cirdion",
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["region"]["id"], "cirdion")
        self.assertEqual(payload["region"]["label"], "Cirdion")
        self.assertTrue(payload["region"]["ui_url"].endswith("/regions/cirdion"))

    def test_fenmir_free_cities_region_view_renders_migrated_cities(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/fenmir_free_cities")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Fenmir Free Cities", text)
        self.assertIn("Free Accords", text)
        self.assertIn("Authored Region Entries", text)
        self.assertIn("Freeport", text)
        self.assertIn("Xul", text)
        self.assertIn("Kahn", text)

    def test_top_level_city_views_render_inns(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/fenmir_free_cities/cities/freeport")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("The Gilded Harpoon", text)
        self.assertIn("The Drunken Kraken", text)
        self.assertIn("City Entries", text)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/fenmir_free_cities/cities/xul")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("The Kraken&#39;s Embrace Tavern", text)

    def test_top_level_city_inn_pages_render(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        examples = [
            (
                "/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/fenmir_free_cities/cities/freeport/inns/the_gilded_harpoon",
                "The Gilded Harpoon",
                "Back to Freeport",
            ),
            (
                "/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/fenmir_free_cities/cities/freeport/inns/the_drunken_kraken",
                "The Drunken Kraken",
                "Back to Freeport",
            ),
        ]

        for path, expected, back_label in examples:
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            text = response.get_data(as_text=True)
            self.assertIn(expected, text)
            self.assertIn("Kind: inn", text)
            self.assertIn("Migration Sources", text)
            self.assertIn(back_label, text)

    def test_api_module_people_returns_people_metadata(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        headers = self.api_login_owner(client)

        response = client.get(
            "/api/systems/cypher/addons/godforsaken/modules/land_of_legends/peoples/fellic",
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["people"]["id"], "fellic")
        self.assertEqual(payload["people"]["label"], "Fellic")
        self.assertIn("chelonian", payload["people"]["subgroups"])

    def test_module_view_renders_module_overview(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Land of Legends", text)
        self.assertIn("epic fantasy", text)
        self.assertIn("heroic sandbox", text)
        self.assertIn("Category Guide", text)
        self.assertIn("Regions", text)
        self.assertIn("Peoples", text)
        self.assertIn("Creatures", text)
        self.assertIn("Items", text)
        self.assertIn("System", text)
        self.assertIn("Lore", text)
        self.assertIn("Open Regions", text)
        self.assertIn("Open Peoples", text)
        self.assertIn("Cirdion", text)
        self.assertIn("Fenmir Highlands", text)
        self.assertIn("Fenmir Lowlands", text)
        self.assertIn("Fenmir Wilds", text)
        self.assertIn("Fenmir Free Cities", text)
        self.assertIn("Caldor", text)
        self.assertIn("Caldor Island", text)
        self.assertIn("Xanthir", text)
        self.assertIn("Almadir", text)
        self.assertIn("Ered Engrin", text)
        self.assertIn("Xanthir Wilds", text)
        self.assertIn("The Sands", text)
        self.assertIn("Lomeanor", text)
        self.assertIn("The Pirate Seas", text)
        self.assertIn("Human", text)
        self.assertIn("Small Folk", text)
        self.assertIn("Fellic", text)
        self.assertIn("Lhainîm", text)
        self.assertIn("The Others", text)
        self.assertIn("Alfir", text)
        self.assertIn("Uruk", text)
        self.assertNotIn("caldoran", text)
        self.assertNotIn("vaettyr", text)
        self.assertNotIn("faltrim", text)
        self.assertNotIn("highland_uruk", text)
        self.assertNotIn("bovine", text)
        self.assertNotIn("chelonian", text)
        self.assertNotIn("avian", text)
        self.assertNotIn("anatine", text)
        self.assertNotIn("velim", text)
        self.assertIn("Animals", text)
        self.assertIn("Beasts", text)
        self.assertIn("Monsters", text)
        self.assertIn("Gurthim", text)
        self.assertIn("Gorthim", text)
        self.assertIn("Artifacts", text)
        self.assertIn("Cyphers", text)
        self.assertIn("Components", text)
        self.assertIn("Equipment", text)
        self.assertIn("Ingredients", text)
        self.assertIn("Weapons", text)
        self.assertIn("Armor", text)
        self.assertIn("Abilities", text)
        self.assertIn("Skills", text)
        self.assertIn("Focus", text)
        self.assertIn("Descriptors", text)
        self.assertIn("Types", text)
        self.assertIn("Flavors", text)
        self.assertIn("Attacks", text)
        self.assertIn("Cantrips", text)
        self.assertIn("Spells", text)
        self.assertIn("Overview", text)
        self.assertIn("History", text)
        self.assertIn("Religion", text)
        self.assertIn("Status: planned", text)

    def test_module_collection_pages_render_clean_category_views(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/regions")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Regions", text)
        self.assertIn("Top-level lands, coasts, wilderness", text)
        self.assertIn("Caldor Island", text)
        self.assertIn("Fenmir Free Cities", text)
        self.assertIn("The Vale", text)
        self.assertIn("Back to Land of Legends", text)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/peoples")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Peoples", text)
        self.assertIn("Alfir", text)
        self.assertIn("Human", text)
        self.assertIn("kalaquendi", text)
        self.assertIn("highland_uruk", text)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/lore")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Lore", text)
        self.assertIn("Overview", text)
        self.assertIn("History", text)
        self.assertIn("AI Lore", text)
        self.assertIn("Peoples", text)
        self.assertIn("Regions", text)
        self.assertIn("alfir", text)
        self.assertIn("cirdion", text)
        self.assertIn("gorthim", text)
        self.assertIn("gurthim", text)
        self.assertIn("The Lands of Legends is a mythic fantasy world shaped by ancient passage", text)
        self.assertIn("The Alfirin do not worship in the mortal sense", text)
        self.assertIn("The Old Gods", text)
        self.assertIn("The Black Affirmation", text)
        self.assertIn("The Breath of the World", text)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/overview")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Canonical lore document", text)
        self.assertIn("Back to Lore", text)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/peoples")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Canonical lore branch", text)
        self.assertIn("Alfir", text)
        self.assertIn("Human", text)
        self.assertIn("kalaquendi", text)
        self.assertIn("highland uruk", text)
        self.assertIn("The peoples of the Lands of Legends are not variations on one civilization", text)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/regions")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("The regions of the Lands of Legends are not just locations", text)
        self.assertIn("the vale", text)
        self.assertIn("freeport", text)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/ai_lore")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("AI Lore", text)
        self.assertIn("staging ground for machine-assisted working material", text)
        self.assertIn("Art Prompts", text)
        self.assertIn("Drift Tests", text)
        self.assertIn("Doctrine", text)
        self.assertIn("Identity", text)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/ai_lore/doctrine")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Doctrine Guides", text)
        self.assertIn("cosmology", text)
        self.assertIn("xanthir", text)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/lore/ai_lore/identity")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Identity Guides", text)
        self.assertIn("gorthim", text)
        self.assertIn("gurthim", text)

    def test_generate_workspace_shows_ollama_warmup_note(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/workspace/generate?provider_id=ollama_local")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("First request may be slower while the local model loads.", text)

    def test_region_detail_view_renders_review_item(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/cirdion")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Cirdion", text)
        self.assertIn("Oldest Alfirin realm", text)
        self.assertIn("Starter Categories", text)
        self.assertIn("Subregions", text)
        self.assertIn("Cities", text)
        self.assertIn("Villages", text)
        self.assertIn("Settlements", text)
        self.assertIn("Landmarks", text)
        self.assertIn("Forests", text)
        self.assertIn("Rivers", text)
        self.assertIn("Lakes", text)
        self.assertIn("Islands", text)
        self.assertIn("Mountains", text)
        self.assertIn("Caves", text)
        self.assertIn("Dungeons", text)
        self.assertIn("Ruins", text)
        self.assertIn("Back to Land of Legends", text)

    def test_caldor_island_region_view_renders_authored_entries(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/caldor_island")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Caldor Island", text)
        self.assertIn("Official maps show roads and settlements that do not exist", text)
        self.assertIn("Authored Region Entries", text)
        self.assertIn("South Point", text)
        self.assertIn("Dragon", text)
        self.assertIn("Lake Caldin", text)
        self.assertIn("The Vale", text)
        self.assertIn("The Rolling Hills", text)
        self.assertIn("Mountain Home", text)
        self.assertIn("Lake Home", text)
        self.assertIn("Edge", text)
        self.assertIn("Southridge", text)
        self.assertIn("Northridge", text)
        self.assertIn("The Lake", text)
        self.assertIn("The Mosey", text)

    def test_the_vale_subregion_view_renders_nested_entries(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get(
            "/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/caldor_island/subregions/the_vale"
        )

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("The Vale", text)
        self.assertIn("Subregion Entries", text)
        self.assertIn("The water remembers. The mountains decide.", text)
        self.assertIn("Mountain Home", text)
        self.assertIn("Lake Home", text)
        self.assertIn("Edge", text)
        self.assertIn("Southridge", text)
        self.assertIn("Northridge", text)
        self.assertIn("The Lake", text)
        self.assertIn("The Mosey", text)
        self.assertIn("Back to Caldor Island", text)

    def test_subregion_village_views_render_inns(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        examples = [
            (
                "/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/caldor_island/subregions/the_vale/villages/mountain_home",
                "The Lucky Pick",
            ),
            (
                "/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/caldor_island/subregions/the_vale/villages/lake_home",
                "The Sizzling Trout",
            ),
        ]

        for path, expected in examples:
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            text = response.get_data(as_text=True)
            self.assertIn(expected, text)
            self.assertIn("Village Entries", text)
            self.assertIn("Migration Sources", text)

    def test_top_level_village_views_render_inns(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        examples = [
            (
                "/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/caldor_island/villages/south_point",
                "The Salty Seagull",
            ),
            (
                "/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/caldor_island/villages/dragons_maw",
                "Black Tooth",
            ),
        ]

        for path, expected in examples:
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            text = response.get_data(as_text=True)
            self.assertIn(expected, text)
            self.assertIn("Village Entries", text)

    def test_inn_pages_render_for_top_level_and_subregion_villages(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        examples = [
            (
                "/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/caldor_island/villages/south_point/inns/the_salty_seagull",
                "The Salty Seagull",
                "Back to South Point",
                True,
            ),
            (
                "/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/caldor_island/subregions/the_vale/villages/mountain_home/inns/the_lucky_pick",
                "The Lucky Pick",
                "Back to Mountain Home",
                True,
            ),
        ]

        for path, expected, back_label, expects_migration_sources in examples:
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            text = response.get_data(as_text=True)
            self.assertIn(expected, text)
            self.assertIn("Kind: inn", text)
            if expects_migration_sources:
                self.assertIn("Migration Sources", text)
            self.assertIn(back_label, text)

    def test_detail_pages_render_rich_lore_documents(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get(
            "/systems/cypher/addons/godforsaken/modules/land_of_legends/regions/caldor_island/subregions/the_vale/villages/lake_home/inns/the_sizzling_trout"
        )

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Lore", text)
        self.assertIn("The Sizzling Trout Overview", text)
        self.assertIn("warm social heart", text)

    def test_invalid_authored_manifest_fails_fast_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            systems_root = root / "app" / "systems" / "cypher" / "addons" / "godforsaken" / "modules" / "demo" / "regions" / "demo_region" / "villages" / "bad_village" / "inns" / "bad_inn"
            systems_root.mkdir(parents=True)
            (root / "app" / "systems" / "cypher").mkdir(parents=True, exist_ok=True)
            (root / "app" / "systems" / "cypher" / "system.json").write_text(
                json.dumps({"id": "cypher", "name": "Cypher System"}),
                encoding="utf-8",
            )
            addon_root = root / "app" / "systems" / "cypher" / "addons" / "godforsaken"
            addon_root.mkdir(parents=True, exist_ok=True)
            (addon_root / "addon.json").write_text(
                json.dumps({"id": "godforsaken", "system_id": "cypher", "name": "Godforsaken"}),
                encoding="utf-8",
            )
            module_root = addon_root / "modules" / "demo"
            module_root.mkdir(parents=True, exist_ok=True)
            (module_root / "module.json").write_text(
                json.dumps({"id": "demo", "system_id": "cypher", "addon_id": "godforsaken", "label": "Demo"}),
                encoding="utf-8",
            )
            region_root = module_root / "regions" / "demo_region"
            region_root.mkdir(parents=True, exist_ok=True)
            (region_root / "manifest.json").write_text(
                json.dumps({"id": "demo_region", "label": "Demo Region", "kind": "top_level_region", "status": "draft"}),
                encoding="utf-8",
            )
            village_root = region_root / "villages" / "bad_village"
            village_root.mkdir(parents=True, exist_ok=True)
            (village_root / "manifest.json").write_text(
                json.dumps({"id": "bad_village", "label": "Bad Village", "kind": "village", "status": "draft"}),
                encoding="utf-8",
            )
            (systems_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "bad_inn",
                        "label": "Bad Inn",
                        "kind": "inn",
                        "status": "draft",
                        "details": {"reputation": "wrong shape"},
                    }
                ),
                encoding="utf-8",
            )

            app = create_app(project_root=root)
            client = app.test_client()
            self.login_owner(client)

            response = client.get(
                "/systems/cypher/addons/godforsaken/modules/demo/regions/demo_region/villages/bad_village/inns/bad_inn"
            )

            self.assertEqual(response.status_code, 500)

    def test_people_detail_view_renders_review_item(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/peoples/fellic")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Fellic", text)
        self.assertIn("Chelonian", text)
        self.assertIn("Back to Land of Legends", text)

    def test_people_detail_view_renders_authored_child_groups(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/peoples/alfir")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Faltrim", text)
        self.assertIn("Kalaquendi", text)
        self.assertIn("Duathrim", text)
        self.assertIn("Galadhrim", text)
        self.assertIn("The Alfir are the Immortal Ones", text)
        self.assertIn("/systems/cypher/addons/godforsaken/modules/land_of_legends/peoples/alfir/subgroups/kalaquendi", text)

    def test_other_people_detail_views_render_authored_child_groups(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        examples = [
            ("/systems/cypher/addons/godforsaken/modules/land_of_legends/peoples/uruk", "Highland Uruk"),
            ("/systems/cypher/addons/godforsaken/modules/land_of_legends/peoples/human", "Caldoran"),
            ("/systems/cypher/addons/godforsaken/modules/land_of_legends/peoples/small_folk", "Vaettyr"),
            ("/systems/cypher/addons/godforsaken/modules/land_of_legends/peoples/fellic", "Chelonian"),
            ("/systems/cypher/addons/godforsaken/modules/land_of_legends/peoples/lhainim", "Pixie"),
            ("/systems/cypher/addons/godforsaken/modules/land_of_legends/peoples/the_others", "Velim"),
        ]

        for path, expected in examples:
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            text = response.get_data(as_text=True)
            self.assertIn(expected, text)

    def test_human_people_page_renders_rich_lore(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get("/systems/cypher/addons/godforsaken/modules/land_of_legends/peoples/human")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Among the elder races, humans are often dismissed as brief sparks", text)

    def test_people_subgroup_page_renders_rich_lore(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.get(
            "/systems/cypher/addons/godforsaken/modules/land_of_legends/peoples/alfir/subgroups/kalaquendi"
        )

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Kalaquendi", text)
        self.assertIn("The Kalaquendi are the most visible and widely recognized branch of the Alfir", text)
        self.assertIn("Back to Alfir", text)

    def test_campaign_api_can_create_and_list_campaigns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app" / "systems").mkdir(parents=True)
            app = create_app(project_root=root)
            client = app.test_client()
            headers = self.api_login_owner(client)

            create_response = client.post(
                "/api/campaigns",
                json={
                    "system_id": "none",
                    "setting_id": "demo_setting",
                    "campaign_id": "alpha",
                    "campaign_label": "Alpha",
                    "summary": "First campaign",
                },
                headers=headers,
            )

            self.assertEqual(create_response.status_code, 201)
            list_response = client.get(
                "/api/campaigns?system_id=none&setting_id=demo_setting",
                headers=headers,
            )
            self.assertEqual(list_response.status_code, 200)
            payload = list_response.get_json()
            self.assertEqual(len(payload["campaigns"]), 1)
            self.assertEqual(payload["campaigns"][0]["id"], "alpha")

    def test_records_api_crud_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app" / "systems").mkdir(parents=True)
            app = create_app(project_root=root)
            client = app.test_client()
            headers = self.api_login_owner(client)

            create_response = client.post(
                "/api/records",
                json={
                    "record_type": "lore_entry",
                    "title": "Red Gate",
                    "system_id": "none",
                    "setting_id": "demo_setting",
                    "campaign_id": "alpha",
                    "content": {"body": "A broken red gate."},
                    "metadata": {"tags": ["gate", "ruin"], "summary": "A ruin"},
                },
                headers=headers,
            )
            self.assertEqual(create_response.status_code, 201)
            created = create_response.get_json()["record"]
            record_id = created["id"]

            fetch_response = client.get(f"/api/records/{record_id}", headers=headers)
            self.assertEqual(fetch_response.status_code, 200)
            self.assertEqual(fetch_response.get_json()["record"]["title"], "Red Gate")

            list_response = client.get("/api/records?q=red", headers=headers)
            self.assertEqual(list_response.status_code, 200)
            self.assertEqual(len(list_response.get_json()["records"]), 1)

            update_response = client.put(
                f"/api/records/{record_id}",
                json={
                    "title": "Red Gate Ruin",
                    "metadata": {"summary": "Updated summary", "tags": ["gate", "ruin", "ancient"]},
                },
                headers=headers,
            )
            self.assertEqual(update_response.status_code, 200)
            self.assertEqual(update_response.get_json()["record"]["title"], "Red Gate Ruin")

            delete_response = client.delete(f"/api/records/{record_id}", json={}, headers=headers)
            self.assertEqual(delete_response.status_code, 200)
            self.assertEqual(delete_response.get_json()["status"], "trashed")

    def test_campaign_workspace_renders_and_accepts_form_post(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app" / "systems").mkdir(parents=True)
            app = create_app(project_root=root)
            client = app.test_client()
            self.login_owner(client)

            create_response = client.post(
                "/workspace/campaigns",
                data={
                    "system_id": "none",
                    "setting_id": "demo_setting",
                    "campaign_id": "",
                    "campaign_label": "Alpha Squad",
                    "summary": "First campaign",
                },
            )
            self.assertEqual(create_response.status_code, 200)
            text = create_response.get_data(as_text=True)
            self.assertIn("Campaign created.", text)
            self.assertIn("Alpha Squad", text)
            self.assertIn("alpha_squad", text)

    def test_records_workspace_renders_created_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app" / "systems").mkdir(parents=True)
            app = create_app(project_root=root)
            client = app.test_client()
            self.login_owner(client)

            create_response = client.post(
                "/workspace/records",
                data={
                    "record_type": "lore_entry",
                    "title": "Red Gate",
                    "system_id": "none",
                    "setting_id": "demo_setting",
                    "campaign_id": "alpha",
                    "summary": "A ruin",
                    "tags": "gate, ruin",
                    "body": "A broken red gate.",
                },
            )
            self.assertEqual(create_response.status_code, 302)
            detail_response = client.get(create_response.headers["Location"])
            self.assertEqual(detail_response.status_code, 200)
            text = detail_response.get_data(as_text=True)
            self.assertIn("Record created.", text)
            self.assertIn("Red Gate", text)
            self.assertIn("gate", text)

    def test_record_edit_workspace_updates_record(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        create_response = client.post(
            "/workspace/records",
            data={
                "record_type": "lore_entry",
                "title": "Stone Ford",
                "system_id": "cypher",
                "expansion_id": "godforsaken",
                "setting_id": "land_of_legends",
                "summary": "Old crossing",
                "tags": "river",
                "body": "The first draft body.",
            },
            follow_redirects=False,
        )
        record_id = create_response.headers["Location"].rstrip("/").split("/")[-1].split("?")[0]

        update_response = client.post(
            f"/workspace/records/{record_id}/edit",
            data={
                "record_type": "lore_entry",
                "title": "Stone Ford",
                "slug": "stone_ford",
                "summary": "Updated crossing summary",
                "tags": "river, crossing",
                "body": "The crossing is watched by lantern keepers.",
            },
            follow_redirects=False,
        )

        self.assertEqual(update_response.status_code, 302)
        detail_response = client.get(update_response.headers["Location"])
        text = detail_response.get_data(as_text=True)
        self.assertIn("Updated crossing summary", text)
        self.assertIn("The crossing is watched by lantern keepers.", text)
        self.assertIn("crossing", text)

    def test_generate_workspace_builds_packet_and_can_create_draft_record(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        preview_response = client.post(
            "/workspace/generate",
            data={
                "title": "Old Gods Draft",
                "record_type": "lore_entry",
                "system_id": "cypher",
                "expansion_id": "godforsaken",
                "setting_id": "land_of_legends",
                "focus_query": "Old Gods",
                "notes": "Focus on religion and hidden costs.",
                "source_kind": "module_lore",
                "action": "preview",
            },
        )

        self.assertEqual(preview_response.status_code, 200)
        preview_text = preview_response.get_data(as_text=True)
        self.assertIn("Draft title: Old Gods Draft", preview_text)
        self.assertIn("Retrieved context:", preview_text)

        create_response = client.post(
            "/workspace/generate",
            data={
                "title": "Old Gods Draft",
                "record_type": "lore_entry",
                "system_id": "cypher",
                "expansion_id": "godforsaken",
                "setting_id": "land_of_legends",
                "focus_query": "Old Gods",
                "notes": "Focus on religion and hidden costs.",
                "source_kind": "module_lore",
                "action": "create_record",
            },
            follow_redirects=False,
        )

        self.assertEqual(create_response.status_code, 302)
        self.assertIn("/workspace/records/", create_response.headers["Location"])

    def test_logout_clears_session(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        self.login_owner(client)

        response = client.post("/logout", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        session_response = client.get("/api/session")
        self.assertEqual(session_response.status_code, 401)

    def test_api_logout_revokes_bearer_token(self) -> None:
        app = create_app(project_root=PROJECT_ROOT)
        client = app.test_client()
        headers = self.api_login_owner(client)

        response = client.post("/api/session/logout", headers=headers)

        self.assertEqual(response.status_code, 200)
        followup = client.get("/api/session", headers=headers)
        self.assertEqual(followup.status_code, 401)

    def test_branding_asset_and_favicon_routes_serve_logo(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app" / "systems").mkdir(parents=True)
            branding = root / "data" / "assets" / "branding"
            branding.mkdir(parents=True)
            (branding / "gmf-logo.png").write_bytes(b"fakepng")
            app = create_app(project_root=root)
            client = app.test_client()
            self.login_owner(client)

            asset_response = client.get("/assets/branding/gmf-logo.png")
            self.assertEqual(asset_response.status_code, 200)
            asset_response.close()

            favicon_response = client.get("/favicon.ico")
            self.assertEqual(favicon_response.status_code, 200)
            favicon_response.close()


if __name__ == "__main__":
    unittest.main()
