from __future__ import annotations

import tempfile
import sys
import unittest
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
        self.assertIn("Cypher System Reference Document 2025-08-22", text)

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
                    "campaign_id": "alpha",
                    "campaign_label": "Alpha",
                    "summary": "First campaign",
                },
            )
            self.assertEqual(create_response.status_code, 200)
            text = create_response.get_data(as_text=True)
            self.assertIn("Campaign created.", text)
            self.assertIn("Alpha", text)

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
            self.assertEqual(create_response.status_code, 200)
            text = create_response.get_data(as_text=True)
            self.assertIn("Record created.", text)
            self.assertIn("Red Gate", text)
            self.assertIn("gate", text)

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
