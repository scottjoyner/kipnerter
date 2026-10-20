"""Synthetic-only negative tests for private redacted launch evidence verifier."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from scripts import portal_legacy_launch_receipt_verify as v
from scripts import portal_legacy_launch_metadata_once as writer

class PrivateLaunchReceiptTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name) / "private"
        self.base.mkdir(mode=0o700)
        items = []
        for role, image in v.ROLES.items():
            content = ("synthetic-rootfs-" + role).encode()
            self.private(v.ROOTFS + "-" + role + ".tar", content)
            items.append({"role": role, "source_image": image,
                          "rootfs_tar_bytes": len(content),
                          "rootfs_tar_sha256": hashlib.sha256(content).hexdigest()})
        root = {"schema": 1, "rootfs_files_created": True,
                "runnable_rollback_verified": False, "safe_to_cutover": False,
                "roles": items}
        rootraw = self.jsonbytes(root)
        self.private(v.ROOTFS + ".receipt.json", rootraw)
        rows = []
        for role, image in v.ROLES.items():
            ref = "kipnerter-api" if "api" in role else "kipnerter-web"
            doc = {
                "Name": "/" + role, "Image": image,
                "Config": {"Image": ref, "Labels": {"com.docker.compose.project": "kipnerter"},
                           "Env": ["PASSWORD=synthetic-top-secret"],
                           "Entrypoint": ["/usr/local/bin/app"], "Cmd": ["--serve"]},
                "HostConfig": {"NetworkMode": "production_private"},
                "State": {"Running": True, "StartedAt": "2026-08-17T17:14:43Z"},
                "Mounts": []
            }
            rows.append(writer.extract_launch_metadata(doc, role))
        self.metadata = {
            "schema": 1, "purpose": "legacy_launch_configuration_private_recovery_evidence",
            "rootfs_receipt_sha256": hashlib.sha256(rootraw).hexdigest(),
            "roles": rows, "contains_potential_secret_values": False,
            "original_oci_images_recovered": False,
            "runnable_rollback_verified": False, "independent_admin_custody_verified": False,
            "production_containers_modified": False, "safe_to_cutover": False,
        }
        self.write_metadata()

    def jsonbytes(self, obj):
        return (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode()

    def private(self, name, data):
        path = self.base / name
        path.write_bytes(data)
        path.chmod(0o600)
        return path

    def write_metadata(self):
        raw = self.jsonbytes(self.metadata)
        self.private(v.PREFIX, raw)
        receipt = {"schema": 1, "metadata_file_sha256": hashlib.sha256(raw).hexdigest(),
                   "metadata_bytes": len(raw), "role_count": 2,
                   "rootfs_receipt_sha256": self.metadata["rootfs_receipt_sha256"],
                   "contains_potential_secret_values": False,
                   "old_oci_images_recovered": False,
                   "runnable_rollback_verified": False,
                   "independent_admin_custody_verified": False, "safe_to_cutover": False}
        self.private(v.PREFIX + ".receipt.json", self.jsonbytes(receipt))

    def test_valid_sealed_bundle_is_read_only_and_redacted(self):
        result = v.verify(self.base, live_check=False)
        self.assertEqual(result["redacted_launch_roles"], 2)
        self.assertFalse(result["runnable_rollback"])
        self.assertFalse(result["safe_to_cutover"])
        self.assertNotIn(b"synthetic-top-secret", (self.base / v.PREFIX).read_bytes())
        self.assertNotIn(b"production_private", (self.base / v.PREFIX).read_bytes())

    def test_bad_rootfs_digest_denied(self):
        role = next(iter(v.ROLES))
        path = self.base / (v.ROOTFS + "-" + role + ".tar")
        original = path.read_bytes()
        path.write_bytes(original[:-1] + b"!")
        with self.assertRaisesRegex(ValueError, "rootfs archive changed"):
            v.verify(self.base, live_check=False)

    def test_metadata_hash_mismatch_denied(self):
        with (self.base / v.PREFIX).open("ab") as stream:
            stream.write(b"\n")
        with self.assertRaisesRegex(ValueError, "metadata receipt digest mismatch"):
            v.verify(self.base, live_check=False)

    def test_plaintext_launch_configuration_denied(self):
        self.metadata["roles"][0]["Config"] = {"Env": ["PASSWORD=unsafe"]}
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, "unsafe launch role"):
            v.verify(self.base, live_check=False)

    def test_wrong_image_or_rollback_claim_denied(self):
        self.metadata["roles"][0]["image_id"] = "sha256:" + "f" * 64
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, "unsafe launch role"):
            v.verify(self.base, live_check=False)
        self.metadata["roles"][0]["image_id"] = v.ROLES[self.metadata["roles"][0]["role"]]
        self.metadata["safe_to_cutover"] = True
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, "unsafe launch evidence"):
            v.verify(self.base, live_check=False)

    def test_unapproved_file_mode_and_symlink_denied(self):
        target = self.base / v.PREFIX
        target.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "unsafe private evidence"):
            v.verify(self.base, live_check=False)
        target.chmod(0o600)
        target.unlink()
        alternate = self.private("other-data", self.jsonbytes(self.metadata))
        target.symlink_to(alternate)
        with self.assertRaises(OSError):
            v.verify(self.base, live_check=False)

    def test_environment_value_and_duplicate_field_denied(self):
        self.metadata["roles"][0]["environment_names_only"] = ["PASSWORD=bad"]
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, "environment variable values"):
            v.verify(self.base, live_check=False)
        self.metadata["roles"][0]["environment_names_only"] = ["PASSWORD"]
        self.write_metadata()
        file = self.base / v.PREFIX
        file.write_bytes(b'{"schema":1,"schema":2}')
        with self.assertRaisesRegex(ValueError, "duplicate private JSON"):
            v.verify(self.base, live_check=False)

if __name__ == "__main__":
    unittest.main()
