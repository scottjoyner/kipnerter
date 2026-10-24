"""Offline safety constraints for real four-migration scoped-identity rehearsal."""
import json
import subprocess
import unittest
from pathlib import Path
FILE=Path(__file__).resolve().parents[1]/"portal_real_spatial_alembic_migrator_rehearsal.sh"

class MigrationIdentityIsolation(unittest.TestCase):
    def test_default_no_docker(self):
        p=subprocess.run(["bash",str(FILE)],capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,3)
        self.assertEqual(json.loads(p.stdout)["status"],"DRY_RUN_NO_DOCKER_ACCESS")

    def test_incorrect_argument_no_docker(self):
        p=subprocess.run(["bash",str(FILE),"--production"],capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,3)

    def test_more_arguments_refused(self):
        p=subprocess.run(["bash",str(FILE),"--execute","extra"],capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,3)

    def test_pinned_exact_production_image_identity(self):
        s=FILE.read_text()
        self.assertIn("sha256:1624c272977968a700ca6f4b37107c46ec5bd35c7122cd6566fa7b7c8674a8e8",s)
        self.assertIn("sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5",s)
        self.assertIn("docker image inspect",s)

    def test_no_access_to_host_network_or_production_mount(self):
        s=FILE.read_text()
        self.assertIn("docker network create --internal --driver bridge",s)
        self.assertIn("--read-only",s)
        self.assertIn("--tmpfs /var/lib/postgresql/data",s)
        for banned in ("--privileged","--network host","--mount ","-v /","ssh ","tailscale","--publish"):
            self.assertNotIn(banned,s)

    def test_local_only_and_fresh_synthetic_credentials(self):
        s=FILE.read_text()
        self.assertIn('[[ "$(hostname)" == "x1-370" ]]',s)
        self.assertIn('[[ ! -v DOCKER_HOST && ! -v DOCKER_CONTEXT ]]',s)
        for name in ("admin_pw","api_pw","worker_pw"):
            self.assertIn(name+"=$(openssl rand -hex 20)",s)

    def test_only_separate_migrator_executes_alembic(self):
        s=FILE.read_text()
        self.assertIn("-e POSTGRES_USER=spatial_migrator",s)
        self.assertIn('KIPNERTER_DATABASE_URL=postgresql+asyncpg://spatial_migrator:',s)
        self.assertIn('--entrypoint alembic "$app" upgrade head',s)
        self.assertIn('[[ "$head" == "20260817_0004" ]]',s)

    def test_nonprivileged_app_and_worker_actual_models(self):
        s=FILE.read_text()
        self.assertIn("CREATE ROLE synthetic_api LOGIN NOINHERIT NOSUPERUSER",s)
        self.assertIn("CREATE ROLE synthetic_worker LOGIN NOINHERIT NOSUPERUSER",s)
        self.assertIn("from kipnerter_api.models import DeviceModel,OutboxEventModel",s)
        self.assertIn("insert(DeviceModel)",s)
        self.assertIn("insert(OutboxEventModel)",s)

    def test_negative_controls_cover_tampering_and_admin_bypass(self):
        s=FILE.read_text()
        for check in ("SELECT count(*) FROM public.outbox_events","SELECT count(*) FROM public.devices",
          "ALTER TABLE public.devices","DROP TABLE public.outbox_events",
          "CREATE ROLE synthetic_admin_escalation","SET ROLE spatial_migrator",
          "UPDATE alembic_version SET"):
            self.assertIn(check,s)

    def test_cleanup_and_strict_no_go(self):
        s=FILE.read_text()
        self.assertIn("trap cleanup EXIT",s)
        self.assertIn('docker rm -f "$pg"',s)
        self.assertIn('docker network rm "$net"',s)
        self.assertIn('"migration_authority_separated":True',s)
        self.assertIn('"source_writes_fenced":False',s)
        self.assertIn('"safe_to_cutover":False',s)
        self.assertIn('"release_gate":"NO_GO"',s)
