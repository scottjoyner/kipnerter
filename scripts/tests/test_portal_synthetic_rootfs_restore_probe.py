"""Synthetic fixtures only: never use Docker or private production evidence."""
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts import portal_synthetic_rootfs_restore_probe as p

ELF = b"\x7fELF" + b"test-binary" * 10

class SyntheticRestoreTests(unittest.TestCase):
    def test_deterministic_archive_has_no_sensitive_files(self):
        for role in p.ROLES:
            a=p.synthetic_tar(role,ELF)
            self.assertEqual(a,p.synthetic_tar(role,ELF))
            self.assertLess(len(a),p.MAX_TAR)
            self.assertNotIn(b"PASSWORD=",a)
            p.verify_tar(a,role)
            with tarfile.open(fileobj=io.BytesIO(a)) as tar:
                self.assertEqual(tar.getnames(),["bin","app","bin/busybox","app/proof.txt"])

    def test_unsafe_archive_rejected(self):
        a=p.synthetic_tar("api",ELF)
        with self.assertRaises(ValueError):
            p.verify_tar(a,"web")
        with self.assertRaises(ValueError):
            p.synthetic_tar("prod-api",ELF)
        with self.assertRaises(ValueError):
            p.verify_tar(a+b"extra", "unknown")

    def test_no_ack_must_never_touch_docker(self):
        with patch.object(p,"docker",side_effect=AssertionError("should not run")):
            with self.assertRaises(ValueError):
                p.run_synthetic(False)

    def test_existing_image_tag_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"busybox"
            path.write_bytes(ELF)
            observed=[]
            def fake(*args,input_data=None):
                observed.append(args)
                if args[:2]==("image","inspect"):
                    return "sha256:"+"a"*64
                raise AssertionError("must not import/run/delete existing image")
            with patch.object(p,"docker",side_effect=fake):
                with self.assertRaisesRegex(ValueError,"occupied"):
                    p.run_synthetic(True,path)
            self.assertEqual(len(observed),1)

    def test_imported_test_images_cleaned_and_runs_restricted(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"busybox"; path.write_bytes(ELF)
            calls=[]
            def fake(*args,input_data=None):
                calls.append((args,input_data is not None))
                if args[:2]==("image","inspect"):
                    raise subprocess.CalledProcessError(1,args)
                if args[0]=="import":
                    self.assertTrue(input_data)
                    return "sha256:"+"a"*64
                if args[0]=="run":
                    for constraint in ("--rm","--network=none","--read-only",
                                       "--cap-drop=ALL","--security-opt=no-new-privileges",
                                       "--pull=never","--memory=128m",
                                       "--user=65534:65534"):
                        self.assertIn(constraint,args)
                    role = "api" if len([x for x in calls if x[0][0]=="run"])==1 else "web"
                    return p.EXPECTED[role].decode().strip()
                if args[:2]==("image","rm"):
                    return ""
                raise AssertionError(args)
            with patch.object(p,"docker",side_effect=fake):
                result=p.run_synthetic(True,path)
            self.assertEqual(len(result["roles"]),2)
            self.assertFalse(result["legacy_functional_rollback_proven"])
            self.assertEqual(len([x for x in calls if x[0][:2]==("image","rm")]),2)

if __name__=="__main__":
    unittest.main()
