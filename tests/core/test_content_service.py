from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.auth import AuthService
from app.core.content import ContentService
from app.core.contracts import build_record


class ContentServiceTests(unittest.TestCase):
    def test_create_record_syncs_storage_audit_and_tags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "gmforge.db"
            auth = AuthService(db_path)
            user = auth.create_user(
                username="gm_one",
                email="gm@example.com",
                display_name="GM One",
                password="verysecurepass",
                role="gm",
            )
            content = ContentService(data_root=root / "data", db_path=db_path)
            record = build_record(
                record_type="lore_entry",
                title="The Red Gate",
                system_id="cypher",
                setting_id="lands_of_legends",
                campaign_id="campaign_alpha",
                metadata={"tags": ["gate", "ruins"], "summary": "Ancient gate ruin"},
                content={"body": "A broken gate watches the hills."},
            )

            created = content.create_record(
                record,
                actor_user_id=user.id,
                request_kind="manual_form",
            )
            self.assertEqual(content.get_record(created["id"])["title"], "The Red Gate")

            tagged = content.list_records_for_tag(tag="gate")
            self.assertEqual(len(tagged), 1)
            self.assertEqual(tagged[0]["id"], created["id"])

            events = content.audit.list_events(target_id=created["id"])
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].actor_user_id, user.id)
            self.assertEqual(events[0].action_type, "create_record")

    def test_update_record_syncs_links_and_backlinks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "gmforge.db"
            content = ContentService(data_root=root / "data", db_path=db_path)

            target = content.create_record(
                build_record(
                    record_type="npc_record",
                    title="Aurora",
                    system_id="cypher",
                    setting_id="lands_of_legends",
                    campaign_id="campaign_alpha",
                    metadata={"tags": ["npc"]},
                    content={"body": "A wary guard."},
                )
            )
            source = content.create_record(
                build_record(
                    record_type="lore_entry",
                    title="Red Gate Rumors",
                    system_id="cypher",
                    setting_id="lands_of_legends",
                    campaign_id="campaign_alpha",
                    metadata={"tags": ["rumor"]},
                    links=[{"link_type": "mentions", "target_type": "record", "target_id": target["id"]}],
                    content={"body": "Stories mention Aurora at the gate."},
                )
            )

            backlinks = content.list_backlinks(record_id=target["id"])
            self.assertEqual(len(backlinks), 1)
            self.assertEqual(backlinks[0]["record"]["id"], source["id"])

            updated = dict(source)
            updated["metadata"] = dict(source["metadata"])
            updated["metadata"]["tags"] = ["rumor", "gate"]
            updated["links"] = []
            content.update_record(source["id"], updated)

            self.assertEqual(len(content.list_backlinks(record_id=target["id"])), 0)
            gate_records = content.list_records_for_tag(tag="gate")
            self.assertEqual(len(gate_records), 1)
            self.assertEqual(gate_records[0]["id"], source["id"])
