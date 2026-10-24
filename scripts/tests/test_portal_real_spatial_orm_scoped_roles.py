"""Offline safety contracts for the real-spatial-ORM disposable least-privilege test."""
import json
import subprocess
import unittest
from pathlib import Path
FILE=Path(__file__).resolve().parents[1]/"portal_real_spatial_orm_scoped_roles.sh"

class RealSchemaScopedRoles(unittest.TestCase):
    def test_safe_default_calls_no_docker(self):
        p=subprocess.run(["bash",str(FILE)],capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,3)
        data=json.loads(p.stdout)
        self.assertEqual(data["status"],"DRY_RUN_NO_DOCKER_ACCESS")
        self.assertFalse(data["safe_to_cutover"])

    def test_extra_args_denied(self):
        p=subprocess.run(["bash",str(FILE),"--execute","again"],capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,3)

    def test_pins_exact_running_spatial_images(self):
        s=FILE.read_text()
        self.assertIn("sha256:1624c272977968a700ca6f4b37107c46ec5bd35c7122cd6566fa7b7c8674a8e8",s)
        self.assertIn("sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5",s)
        self.assertIn('[[ "$(hostname)" == "x1-370" ]]',s)
        self.assertIn('"$(docker context show)" == "default"',s)

    def test_no_production_network_or_mounts(self):
        s=FILE.read_text()
        self.assertIn("docker network create --internal --driver bridge",s)
        self.assertIn("--read-only",s)
        self.assertIn("--tmpfs /var/lib/postgresql/data",s)
        self.assertNotIn("--network host",s)
        self.assertNotIn("--privileged",s)
        self.assertNotIn("--mount ",s)
        self.assertNotIn("--publish",s)
        self.assertNotIn("tailscale",s)
        self.assertNotIn("ssh ",s)

    def test_cleanup_and_random_secrets(self):
        s=FILE.read_text()
        self.assertIn("trap cleanup EXIT",s)
        self.assertIn('docker rm -f "$postgres"',s)
        self.assertIn('docker network rm "$network"',s)
        for var in ("admin_password","api_password","worker_password"):
            self.assertIn(var+"=$(openssl rand -hex 20)",s)

    def test_actual_orm_models_not_mock_tables(self):
        s=FILE.read_text()
        self.assertIn("from kipnerter_api.models import Base",s)
        self.assertIn("from kipnerter_api.models import DeviceModel, OutboxEventModel",s)
        self.assertIn("await connection.run_sync(Base.metadata.create_all)",s)
        self.assertIn("len(Base.metadata.tables) == 12",s)
        self.assertIn("sqlalchemy",s)

    def test_negative_cross_service_and_admin_controls(self):
        s=FILE.read_text()
        for fragment in ("SELECT * FROM public.outbox_events", "SELECT * FROM public.devices",
                         "CREATE TABLE public.synthetic_escalation", "CREATE ROLE synthetic_unwanted_role"):
            self.assertIn(fragment,s)
        self.assertIn("NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS",s)

    def test_never_certifies_production_fence(self):
        s=FILE.read_text()
        self.assertIn('"production_modified":False',s)
        self.assertIn('"writer_fence_proven":False',s)
        self.assertIn('"safe_to_cutover":False',s)
        self.assertIn('"release_gate":"NO_GO"',s)
