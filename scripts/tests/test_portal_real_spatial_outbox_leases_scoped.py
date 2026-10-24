"""Offline safety assertions for exact deployed OutboxDispatcher under a scoped worker."""
import json
import subprocess
import unittest
from pathlib import Path
FILE=Path(__file__).resolve().parents[1]/"portal_real_spatial_outbox_leases_scoped.sh"

class OutboxPrivilegeControls(unittest.TestCase):
    def test_default_denies_docker(self):
        p=subprocess.run(["bash",str(FILE)],capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,3)
        self.assertEqual(json.loads(p.stdout)["status"],"DRY_RUN_NO_DOCKER_ACCESS")

    def test_extra_or_unexpected_args_denied(self):
        for args in (["--execute","extra"],["--production"]):
            with self.subTest(args=args):
                p=subprocess.run(["bash",str(FILE),*args],capture_output=True,text=True,timeout=5)
                self.assertEqual(p.returncode,3)

    def test_exact_deployed_image_pins(self):
        s=FILE.read_text()
        self.assertIn("sha256:1624c272977968a700ca6f4b37107c46ec5bd35c7122cd6566fa7b7c8674a8e8",s)
        self.assertIn("sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5",s)
        self.assertIn('docker image inspect "$img"',s)

    def test_isolated_local_docker_and_cleanup(self):
        s=FILE.read_text()
        self.assertIn("docker network create --internal --driver bridge",s)
        self.assertIn("--read-only",s)
        self.assertIn("--tmpfs /var/lib/postgresql/data",s)
        self.assertIn("trap cleanup EXIT",s)
        self.assertIn('docker rm -f "$pg"',s)
        self.assertIn('docker network rm "$net"',s)
        for banned in ("--privileged","--network host","--publish","--mount ","ssh ","tailscale"):
            self.assertNotIn(banned,s)

    def test_generated_synthetic_only_credentials(self):
        s=FILE.read_text()
        self.assertIn('[[ "$(hostname)" == "x1-370" ]]',s)
        for key in ("admin_pw","api_pw","worker_pw"):
            self.assertIn(key+"=$(openssl rand -hex 20)",s)

    def test_real_migrations_and_worker_source(self):
        s=FILE.read_text()
        self.assertIn('alembic "$app" upgrade head',s)
        self.assertIn('[[ "$head" == "20260817_0004" ]]',s)
        self.assertIn("from kipnerter_api.outbox import OutboxDispatcher",s)
        self.assertIn("async_sessionmaker(worker,expire_on_commit=False)",s)

    def test_worker_only_select_and_update_not_insert(self):
        s=FILE.read_text()
        self.assertIn("GRANT SELECT,UPDATE ON TABLE public.outbox_events TO synthetic_worker",s)
        self.assertNotIn("GRANT SELECT,INSERT,UPDATE ON TABLE public.outbox_events TO synthetic_worker",s)
        self.assertIn('CREATE ROLE synthetic_worker LOGIN NOINHERIT NOSUPERUSER',s)
        self.assertIn('"worker_insert_denied":True',s)

    def test_real_claim_and_acknowledgement(self):
        s=FILE.read_text()
        self.assertIn("await dispatch.dispatch_once()",s)
        self.assertIn('assert first==2 and second==0 and called==["ok"]',s)
        self.assertIn('observations["synthetic.ok"]==(True,False,0,True)',s)

    def test_dead_letter_and_retry_controls(self):
        s=FILE.read_text()
        self.assertIn('observations["synthetic.unhandled"]==(False,True,1,True)',s)
        self.assertIn('"synthetic transient failure"',s)
        self.assertIn('assert await retry.dispatch_once()==0',s)
        self.assertIn("UPDATE outbox_events SET next_attempt_at=now()-interval '1 second'",s)
        self.assertIn('assert await retry.dispatch_once()==1 and attempt==[2]',s)
        self.assertIn('"transient_retry_published_after_delay":True',s)

    def test_migration_and_cross_workload_denials(self):
        s=FILE.read_text()
        for operation in ("SELECT count(*) FROM public.outbox_events",
             "SELECT count(*) FROM public.devices","ALTER TABLE public.outbox_events",
             "SET ROLE spatial_migrator","UPDATE alembic_version SET"):
            self.assertIn(operation,s)

    def test_permanent_release_hold(self):
        s=FILE.read_text()
        self.assertIn('"production_modified":False',s)
        self.assertIn('"source_writes_fenced":False',s)
        self.assertIn('"safe_to_cutover":False',s)
        self.assertIn('"release_gate":"NO_GO"',s)
