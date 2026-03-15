from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.graph import GraphService


class GraphServiceTests(unittest.TestCase):
    def test_upsert_and_list_tags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            graph = GraphService(Path(td) / "gmforge.db")
            tag = graph.upsert_tag(tag="Lands of Legends")
            self.assertEqual(tag.tag_key, "lands_of_legends")
            self.assertEqual(tag.label, "Lands Of Legends")

            updated = graph.upsert_tag(tag="lands_of_legends", label="Lands of Legends")
            self.assertEqual(updated.id, tag.id)
            self.assertEqual(updated.label, "Lands of Legends")

            tags = graph.list_tags(query="legend")
            self.assertEqual(len(tags), 1)
            self.assertEqual(tags[0].tag_key, "lands_of_legends")

    def test_tag_entity_and_query_by_tag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            graph = GraphService(Path(td) / "gmforge.db")
            graph.tag_entity(entity_type="character_record", entity_id="char_001", tag="guard")
            graph.tag_entity(entity_type="character_record", entity_id="char_001", tag="fenmir")
            graph.tag_entity(entity_type="npc_record", entity_id="npc_001", tag="guard")

            guard_entities = graph.list_entities_for_tag(tag="guard")
            self.assertEqual(len(guard_entities), 2)

            character_guard = graph.list_entities_for_tag(tag="guard", entity_type="character_record")
            self.assertEqual(len(character_guard), 1)
            self.assertEqual(character_guard[0].entity_id, "char_001")

            tags = graph.list_tags_for_entity(entity_type="character_record", entity_id="char_001")
            self.assertEqual([tag.tag_key for tag in tags], ["fenmir", "guard"])

    def test_link_entities_and_backlinks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            graph = GraphService(Path(td) / "gmforge.db")
            link = graph.link_entities(
                source_type="lore_entry",
                source_id="red_gate",
                link_type="mentions",
                target_type="npc_record",
                target_id="npc_001",
            )
            self.assertEqual(link.link_type, "mentions")

            outgoing = graph.list_links_from(source_type="lore_entry", source_id="red_gate")
            self.assertEqual(len(outgoing), 1)
            self.assertEqual(outgoing[0].target_id, "npc_001")

            backlinks = graph.list_backlinks_for(target_type="npc_record", target_id="npc_001")
            self.assertEqual(len(backlinks), 1)
            self.assertEqual(backlinks[0].source_id, "red_gate")

    def test_graph_methods_validate_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            graph = GraphService(Path(td) / "gmforge.db")
            with self.assertRaisesRegex(ValueError, "tag is required"):
                graph.upsert_tag(tag="")
            with self.assertRaisesRegex(ValueError, "entity_type is required"):
                graph.tag_entity(entity_type="", entity_id="char_001", tag="guard")
            with self.assertRaisesRegex(ValueError, "source_type is required"):
                graph.link_entities(
                    source_type="",
                    source_id="red_gate",
                    link_type="mentions",
                    target_type="npc_record",
                    target_id="npc_001",
                )


if __name__ == "__main__":
    unittest.main()
