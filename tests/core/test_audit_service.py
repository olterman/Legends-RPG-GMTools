from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.audit import AuditService
from app.core.auth import AuthService


class AuditServiceTests(unittest.TestCase):
    def test_log_event_and_get_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "gmforge.db"
            auth = AuthService(db_path)
            audit = AuditService(db_path)
            user = auth.create_user(
                username="gm_one",
                email="gm@example.com",
                display_name="GM One",
                password="verysecurepass",
                role="gm",
            )

            event = audit.log_event(
                actor_user_id=user.id,
                action_type="create_character",
                target_type="character_record",
                target_id="char_001",
                system_id="cypher",
                setting_id="land_of_legends",
                campaign_id="campaign_alpha",
                request_kind="manual_form",
                payload={"name": "Aurora"},
                result={"record_id": "rec_character_001"},
            )

            loaded = audit.get_event(event.id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.id, event.id)
            self.assertEqual(loaded.actor_user_id, user.id)
            self.assertEqual(loaded.action_type, "create_character")
            self.assertEqual(loaded.target_type, "character_record")
            self.assertEqual(loaded.payload["name"], "Aurora")
            self.assertEqual(loaded.result["record_id"], "rec_character_001")

    def test_list_events_supports_filters(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "gmforge.db"
            auth = AuthService(db_path)
            audit = AuditService(db_path)
            gm = auth.create_user(
                username="gm_one",
                email="gm@example.com",
                display_name="GM One",
                password="verysecurepass",
                role="gm",
            )

            audit.log_event(
                actor_user_id=gm.id,
                action_type="create_npc",
                target_type="npc_record",
                target_id="npc_001",
                system_id="cypher",
                setting_id="land_of_legends",
                campaign_id="campaign_alpha",
                provider_id="openai_remote",
                prompt_text="Create a wary village guard.",
                payload={"seed": "abc"},
                result={"record_id": "rec_npc_001"},
            )
            audit.log_event(
                actor_user_id=gm.id,
                action_type="create_item",
                target_type="item_record",
                target_id="item_001",
                system_id="cypher",
                setting_id="land_of_legends",
                campaign_id="campaign_alpha",
                payload={"name": "Odd Key"},
                result={"record_id": "rec_item_001"},
            )

            ai_events = audit.list_events(provider_id="openai_remote")
            self.assertEqual(len(ai_events), 1)
            self.assertEqual(ai_events[0].action_type, "create_npc")
            self.assertEqual(ai_events[0].prompt_text, "Create a wary village guard.")

            npc_events = audit.list_events(target_type="npc_record")
            self.assertEqual(len(npc_events), 1)
            self.assertEqual(npc_events[0].target_id, "npc_001")

            campaign_events = audit.list_events(campaign_id="campaign_alpha")
            self.assertEqual(len(campaign_events), 2)

    def test_log_event_requires_core_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit = AuditService(Path(td) / "gmforge.db")
            with self.assertRaisesRegex(ValueError, "action_type is required"):
                audit.log_event(action_type="", target_type="item_record", target_id="item_001")
            with self.assertRaisesRegex(ValueError, "target_type is required"):
                audit.log_event(action_type="create_item", target_type="", target_id="item_001")
            with self.assertRaisesRegex(ValueError, "target_id is required"):
                audit.log_event(action_type="create_item", target_type="item_record", target_id="")


if __name__ == "__main__":
    unittest.main()
