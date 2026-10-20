"""No-live-Docker regression tests for one-shot private filesystem preservation."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch, Mock

from scripts import portal_legacy_rootfs_preserve_once as job

class RootfsPreservationTests(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.base=Path(self.d.name)/"private"
        self.base.mkdir(mode=0o700)
        (self.base/job.SOURCE_RECEIPT).write_text(json.dumps({
            "schema":1,"private_archive_created":True,
            "safe_to_cutover":False,"docker_images_recovered":False}))
        self.src={role:(sha,"2026-08-17T17:14:43Z",200*1024**2,1000)
                  for role,ref,sha in job.ROLES}

    def fake_run(self,args,timeout=12):
        role=args[-1]
        if args[:2]==["docker","inspect"]:
            return "true|%s|%s|kipnerter|0|1000|%d|2026-08-17T17:14:43Z"%(
                next(sha for n,ref,sha in job.ROLES if n==role),
                next(ref for n,ref,sha in job.ROLES if n==role),
                200*1024**2)
        if args[:3]==["docker","image","inspect"]:
            if role.startswith("sha256:"):
                raise subprocess.CalledProcessError(1,args)
            return "sha256:" + "a"*64
        raise AssertionError(args)

    def test_preflight_accepts_exact_private_originals_without_writes(self):
        with patch.object(job,"run",side_effect=self.fake_run),patch.object(
            job.shutil,"disk_usage",return_value=Mock(free=70*1024**3)):
            result=job.preflight(self.base)
        self.assertEqual(len(result),2)
        self.assertFalse((self.base/job.RECEIPT).exists())

    def test_existing_receipt_denies_replay(self):
        (self.base/job.RECEIPT).write_text("old")
        with self.assertRaisesRegex(ValueError,"one-shot"):
            job.preflight(self.base)

    def test_partial_denies_replay(self):
        (self.base/".legacy-rootfs-incomplete-deadbeef").write_text("partial")
        with self.assertRaisesRegex(ValueError,"partial"):
            job.preflight(self.base)

    def test_missing_source_receipt_denies(self):
        (self.base/job.SOURCE_RECEIPT).unlink()
        with self.assertRaisesRegex(ValueError,"source receipt"):
            job.preflight(self.base)

    def test_private_custody_enforced(self):
        self.base.chmod(0o755)
        with self.assertRaisesRegex(ValueError,"private"):
            job.preflight(self.base)

    def test_original_image_must_remain_uncached(self):
        def fake(args,timeout=12):
            if args[:3]==["docker","image","inspect"] and args[-1].startswith("sha256:"):
                return args[-1]
            return self.fake_run(args,timeout)
        with patch.object(job,"run",side_effect=fake),patch.object(
            job.shutil,"disk_usage",return_value=Mock(free=70*1024**3)):
            with self.assertRaisesRegex(ValueError,"original image available"):
                job.preflight(self.base)

    def test_both_roles_required_and_exact(self):
        role,ref,sha=job.ROLES[0]
        with patch.object(job,"run",return_value="false|"+sha+"|"+ref+
                          "|kipnerter|0|1000|100000|2026-08-17T17:14:43Z"):
            with self.assertRaises(ValueError):
                job.inspect(role,ref,sha)

    def test_no_export_claimed_on_failing_one_shot(self):
        with patch.object(job,"preflight",side_effect=ValueError("refused")):
            self.assertEqual(job.main(),2)
        self.assertFalse((self.base/job.RECEIPT).exists())

if __name__=="__main__":
    unittest.main()
