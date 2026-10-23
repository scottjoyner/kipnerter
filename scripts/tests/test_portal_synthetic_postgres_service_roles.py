"""Offline controls for disposable, separately scoped PostgreSQL service logins."""
import json
import subprocess
import unittest
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "portal_synthetic_postgres_service_roles.sh"

class SeparateServiceRolesTests(unittest.TestCase):
    def test_default_is_no_docker(self):
        p = subprocess.run(["bash",str(FILE)],text=True,capture_output=True,timeout=5)
        self.assertEqual(p.returncode,3)
        d=json.loads(p.stdout)
        self.assertEqual(d["status"],"DRY_RUN_NO_DOCKER_ACCESS")
        self.assertEqual(d["release_gate"],"NO_GO")

    def test_invalid_invocation_denied(self):
        p = subprocess.run(["bash",str(FILE),"--prod"],text=True,capture_output=True,timeout=5)
        self.assertEqual(p.returncode,3)

    def test_exact_image_and_host(self):
        s=FILE.read_text()
        self.assertIn("sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5",s)
        self.assertIn('[[ "$(hostname)" == "x1-370" ]]',s)
        self.assertIn('"$(docker context show)" == "default"',s)
        self.assertIn('"$(docker image inspect "$image"',s)

    def test_networkless_ephemeral_isolation(self):
        s=FILE.read_text()
        self.assertIn("--network none",s)
        self.assertIn("--read-only",s)
        self.assertIn("--tmpfs /var/lib/postgresql/data",s)
        self.assertIn("trap cleanup EXIT",s)
        for forbidden in ("--privileged","--network host","--mount","ssh ","tailscale"):
            self.assertNotIn(forbidden,s)

    def test_credentials_are_not_static(self):
        s=FILE.read_text()
        for name in ("root_secret","api_secret","worker_secret"):
            self.assertIn(name+"=$(openssl rand -hex 20)",s)
        self.assertNotIn("syntheticAppOnlyPass",s)
        self.assertNotIn("syntheticOnlyPass",s)

    def test_distinct_nonprivileged_accounts(self):
        s=FILE.read_text()
        self.assertIn("CREATE ROLE synthetic_api LOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS",s)
        self.assertIn("CREATE ROLE synthetic_worker LOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS",s)
        self.assertIn("GRANT USAGE ON SCHEMA api_data TO synthetic_api",s)
        self.assertIn("GRANT USAGE ON SCHEMA worker_data TO synthetic_worker",s)

    def test_cross_service_and_admin_denials(self):
        s=FILE.read_text()
        for snippet in ("SELECT count(*) FROM worker_data.events", "SELECT count(*) FROM api_data.jobs",
                        "INSERT INTO worker_data.events", "INSERT INTO api_data.jobs",
                        "CREATE ROLE unwanted_role", "SET ROLE postgres",
                        "ALTER ROLE synthetic_worker SUPERUSER"):
            self.assertIn(snippet,s)

    def test_positive_authorized_activity_and_cleanup(self):
        s=FILE.read_text()
        self.assertIn("INSERT INTO api_data.jobs VALUES",s)
        self.assertIn("INSERT INTO worker_data.events VALUES",s)
        self.assertIn('docker rm -f "$name"',s)
        self.assertIn('"production_modified":false',s)
        self.assertIn('"source_writes_fenced":false',s)
        self.assertIn('"safe_to_cutover":false',s)
