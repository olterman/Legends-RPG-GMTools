from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.campaigns import CampaignService


class CampaignServiceTests(unittest.TestCase):
    def test_create_campaign_writes_setting_and_campaign_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            service = CampaignService(Path(td))
            campaign = service.create_campaign(
                system_id="cypher",
                setting_id="lands_of_legends",
                campaign_id="campaign_alpha",
                campaign_label="Campaign Alpha",
                summary="Primary test campaign",
            )

            self.assertEqual(campaign["id"], "campaign_alpha")
            items = service.list_campaigns(
                system_id="cypher",
                setting_id="lands_of_legends",
            )
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["label"], "Campaign Alpha")

    def test_create_campaign_rejects_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            service = CampaignService(Path(td))
            service.create_campaign(
                system_id="cypher",
                setting_id="lands_of_legends",
                campaign_id="campaign_alpha",
            )
            with self.assertRaises(FileExistsError):
                service.create_campaign(
                    system_id="cypher",
                    setting_id="lands_of_legends",
                    campaign_id="campaign_alpha",
                )
