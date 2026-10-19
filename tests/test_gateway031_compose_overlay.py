"""Opt-in 0.3.1 overlay can never silently change public routes or volumes."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/"compose.gateway-031.yml"


class Gateway031OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=OVERLAY.read_text()

    def test_source_pinning_does_not_use_a_moving_ref(self):
        self.assertIn("88fcebbcbf951e966996c778321a6cfaaeae2298", self.text)
        self.assertIn("context: ./gateway-api", self.text)
        self.assertNotIn("image: latest", self.text)

    def test_preserve_existing_internal_api_port(self):
        self.assertIn('"--port", "8000"', self.text)
        self.assertIn('/ready', self.text)
        self.assertIn('http://127.0.0.1:8000/ready', self.text)
        self.assertNotIn("8080:8000", self.text)
        self.assertNotIn("ports:", self.text)

    def test_require_explicit_secrets_fail_closed(self):
        for key in ("KIPNERTER_GATEWAY_TOKEN", "KIPNERTER_LOCATION_HMAC_SECRET",
                    "KIPNERTER_GATEWAY_SOURCE_SHA"):
            self.assertIn("${"+key+":?", self.text)

    def test_location_state_is_independent_named_volume(self):
        self.assertIn("gateway_location_events:/data", self.text)
        self.assertIn("/data/kipnerter-api.sqlite3", self.text)
        self.assertNotIn("spatial_postgres_data",self.text)
        self.assertNotIn("spatial_minio_data",self.text)
        self.assertNotIn("docker compose up",self.text)

    def test_not_automatically_enabled_in_existing_deploy_workflow(self):
        workflow=(ROOT/".github/workflows/deploy.yml").read_text()
        self.assertNotIn("compose.gateway-031.yml", workflow)
        self.assertNotIn("gateway_location_events", workflow)


if __name__=="__main__":
    unittest.main()
