"""Offline safety contracts for real spatial S3 adapter and two synthetic S3 roles."""
import json
import subprocess
import unittest
from pathlib import Path
FILE=Path(__file__).resolve().parents[1]/"portal_real_spatial_s3_scoped_roles.sh"

class ScopedS3Contract(unittest.TestCase):
    def test_default_without_docker(self):
        p=subprocess.run(["bash",str(FILE)],capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,3)
        self.assertEqual(json.loads(p.stdout)["status"],"DRY_RUN_NO_DOCKER_ACCESS")

    def test_unknown_or_extra_args_fail_closed(self):
        for argv in (["--production"],["--execute","more"]):
            with self.subTest(argv=argv):
                r=subprocess.run(["bash",str(FILE),*argv],capture_output=True,text=True,timeout=5)
                self.assertEqual(r.returncode,3)

    def test_deployed_image_pins(self):
        s=FILE.read_text()
        self.assertIn("sha256:1624c272977968a700ca6f4b37107c46ec5bd35c7122cd6566fa7b7c8674a8e8",s)
        self.assertIn("sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e",s)
        self.assertIn("docker image inspect",s)

    def test_local_only_disposable_internal(self):
        s=FILE.read_text()
        self.assertIn('[[ "$(hostname)" == "x1-370" ]]',s)
        self.assertIn('[[ ! -v DOCKER_HOST && ! -v DOCKER_CONTEXT ]]',s)
        self.assertIn("docker network create --internal --driver bridge",s)
        self.assertIn("--read-only",s)
        self.assertIn("--tmpfs /data:rw,nosuid,size=196m",s)
        self.assertIn("trap cleanup EXIT",s)
        self.assertIn('docker rm -f "$minio"',s)
        self.assertIn('docker network rm "$net"',s)
        for banned in ("--network host","--privileged","--publish","--mount ","ssh ","tailscale"):
            self.assertNotIn(banned,s)

    def test_credentials_random_not_root_shared(self):
        s=FILE.read_text()
        for name in ("root_pw","api_pw","worker_pw"):
            self.assertIn(name+"=$(openssl rand -hex 20)",s)
        self.assertIn("mc admin user add local synthetic_api",s)
        self.assertIn("mc admin user add local synthetic_worker",s)
        self.assertNotIn("GRANT SELECT",s)

    def test_api_policy_just_get_put_and_bucket_list(self):
        s=FILE.read_text()
        self.assertIn('"Action":["s3:ListBucket"]',s)
        self.assertIn('"Action":["s3:GetObject","s3:PutObject"]',s)
        self.assertIn('"Resource":["arn:aws:s3:::kp-s3-scoped-test/*"]',s)

    def test_worker_policy_only_get_and_list(self):
        s=FILE.read_text()
        self.assertIn('{"Effect":"Allow","Action":["s3:GetObject"]',s)
        self.assertIn('mc admin policy attach local syntheticworker --user synthetic_worker',s)
        self.assertNotIn('"Action":["s3:DeleteObject"]',s)
        self.assertNotIn('"Action":["s3:CreateBucket"]',s)

    def test_real_app_storage_adapter(self):
        s=FILE.read_text()
        self.assertEqual(s.count("from kipnerter_api.storage import S3ObjectStorage"),2)
        self.assertEqual(s.count("await storage.ensure_bucket()"),2)
        self.assertIn('await storage.presign_put',s)
        self.assertIn('async for part in storage.open',s)

    def test_positive_and_negative_object_access(self):
        s=FILE.read_text()
        self.assertIn('storage.client.put_object',s)
        self.assertIn('storage.client.delete_object',s)
        self.assertIn('storage.client.create_bucket',s)
        self.assertIn('put_delete_create_denied',s)
        self.assertIn('bucket_create_denied',s)

    def test_no_cutover_promotion(self):
        s=FILE.read_text()
        self.assertIn('"production_modified":False',s)
        self.assertIn('"source_writes_fenced":False',s)
        self.assertIn('"safe_to_cutover":False',s)
        self.assertIn('"release_gate":"NO_GO"',s)
