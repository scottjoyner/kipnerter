import json
import subprocess
import unittest
from pathlib import Path

FILE=Path(__file__).resolve().parents[1]/"portal_synthetic_storage_writer_fence.sh"

class SyntheticFenceControls(unittest.TestCase):
    def test_default_does_not_touch_docker(self):
        p=subprocess.run(["bash",str(FILE)],capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,3)
        d=json.loads(p.stdout)
        self.assertEqual(d["status"],"DRY_RUN_NO_DOCKER_ACCESS")
        self.assertFalse(d["safe_to_cutover"])
        self.assertEqual(d["release_gate"],"NO_GO")

    def test_unknown_argument_cannot_execute(self):
        p=subprocess.run(["bash",str(FILE),"--restore"],capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,3)

    def test_exact_pinned_storage_images_and_local_host(self):
        s=FILE.read_text()
        self.assertIn("sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5",s)
        self.assertIn("sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e",s)
        self.assertIn('docker image inspect "$image"',s)
        self.assertIn('[[ "$(hostname)" == "x1-370" ]]',s)
        self.assertIn('"$(docker context show)" == "default"',s)

    def test_only_networkless_tmpfs_disposable_containers(self):
        s=FILE.read_text()
        self.assertEqual(s.count("docker run -d --rm --network none"),2)
        self.assertIn("--tmpfs /var/lib/postgresql/data",s)
        self.assertIn("--tmpfs /data",s)
        for forbidden in ("--privileged","--network host","--mount","-v /","tailscale","ssh "):
            self.assertNotIn(forbidden,s)

    def test_never_asserts_complete_fence(self):
        s=FILE.read_text()
        self.assertIn("trap cleanup EXIT",s)
        self.assertIn('docker rm -f "$pg_name"',s)
        self.assertIn('docker rm -f "$s3_name"',s)
        self.assertIn("mc admin policy detach local readwrite",s)
        self.assertIn("mc admin policy attach local readonly",s)
        self.assertIn("REVOKE INSERT,UPDATE,DELETE",s)
        self.assertIn("PRIVILEGED_DATABASE_OWNER_BYPASS_STILL_EXISTS=true",s)
        self.assertIn('"source_writes_fenced":false',s)
        self.assertIn('"release_gate":"NO_GO"',s)
