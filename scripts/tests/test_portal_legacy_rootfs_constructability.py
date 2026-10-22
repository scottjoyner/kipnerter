"""Metadata-only, read-only audit for two synthetic Docker-export fixtures."""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.portal_legacy_rootfs_constructability import (
    PREFIX, ROLES, audit,
)


def build(path, *, members=None):
    root = Path(path)
    records = []
    if members is None:
        members = [("etc/sample.conf", b"nonsecret synthetic test"),
                   ("app/hello.txt", b"demo")]
    for role, image in ROLES.items():
        t = root / (PREFIX+"-"+role+".tar")
        with tarfile.open(t,"w") as tf:
            for name, data in members:
                member = tarfile.TarInfo(name)
                member.size=len(data)
                tf.addfile(member, io.BytesIO(data))
        t.chmod(0o600)
        records.append({
            "role":role,"source_image":image,
            "rootfs_tar_sha256":hashlib.sha256(t.read_bytes()).hexdigest(),
            "rootfs_tar_bytes":t.stat().st_size,
            "tar_member_count":len(members),
        })
    evidence = {
        "schema":1, "rootfs_files_created":True,
        "roles":records,
        "legacy_container_images_recovered":False,
        "rootfs_equivalent_to_original_oci_image":False,
        "runnable_rollback_verified":False,
        "independent_admin_custody_verified":False,
        "consistent_live_snapshot_proven":False,
        "private_sensitive_data_may_be_present":True,
        "production_containers_or_volumes_modified":False,
        "safe_to_cutover":False,
    }
    path = root/(PREFIX+".receipt.json")
    path.write_text(json.dumps(evidence))
    path.chmod(0o600)
    return evidence,path


class LegacyRootfsConstructionTests(unittest.TestCase):
    def test_both_unchanged_archives_only_metadata_hold(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence, receipt = build(directory)
            r = audit(Path(directory))
            self.assertEqual(r["audited_archives"], 2)
            self.assertEqual(r["member_count"], 4)
            self.assertEqual(r["status"], "METADATA_ONLY_HOLD")
            for field in ("safe_to_cutover", "runnable_rollback_verified",
                          "oci_config_and_layer_chain_restored",
                          "privileged_container_or_volume_access",
                          "raw_file_names_or_contents_disclosed"):
                self.assertFalse(r[field])

    def test_mismatched_digest_and_length_rejected(self):
        for key, value in (("rootfs_tar_sha256", "f"*64),
                           ("rootfs_tar_bytes", 99),
                           ("tar_member_count", 99)):
            with self.subTest(key=key),tempfile.TemporaryDirectory() as directory:
                e, receipt = build(directory)
                e["roles"][0][key] = value
                receipt.write_text(json.dumps(e))
                with self.assertRaises(ValueError):
                    audit(Path(directory))

    def test_immutable_image_identity_and_roles_fail_closed(self):
        for mutation in ("role", "image"):
            with self.subTest(kind=mutation),tempfile.TemporaryDirectory() as directory:
                e, receipt = build(directory)
                if mutation == "role":
                    e["roles"][1]["role"]="production-db"
                else:
                    e["roles"][0]["source_image"]="sha256:"+"a"*64
                receipt.write_text(json.dumps(e))
                with self.assertRaises(ValueError):
                    audit(Path(directory))

    def test_duplicate_json_members_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            e, receipt = build(directory)
            receipt.write_text(receipt.read_text().replace(
                '"schema": 1,','"schema": 1, "schema": 1,',1))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                audit(Path(directory))

    def test_symlink_hardlink_and_permissive_archive_denied(self):
        for problem in ("symlink","hardlink","permissions"):
            with self.subTest(kind=problem),tempfile.TemporaryDirectory() as directory:
                e,receipt=build(directory)
                path=Path(directory)/(PREFIX+"-kipnerter-api-1.tar")
                if problem == "symlink":
                    other=Path(directory)/"source.tar"
                    path.rename(other)
                    path.symlink_to(other)
                    with self.assertRaises(OSError):
                        audit(Path(directory))
                elif problem == "hardlink":
                    other=Path(directory)/"hardlink"
                    os.link(path,other)
                    with self.assertRaises(ValueError):
                        audit(Path(directory))
                else:
                    path.chmod(0o644)
                    with self.assertRaises(ValueError):
                        audit(Path(directory))

    def test_duplicate_normalized_tar_path_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            e,receipt=build(directory,members=[
                ("etc/service.txt",b"a"),("./etc/service.txt",b"b")])
            with self.assertRaisesRegex(ValueError,"duplicate legacy rootfs"):
                audit(Path(directory))

    def test_traversal_and_absolute_archive_paths_denied(self):
        for bad in ("../../etc/passwd","/etc/key.pem","a/../b"):
            with self.subTest(name=bad),tempfile.TemporaryDirectory() as directory:
                e,receipt=build(directory,members=[(bad,b"fake")])
                with self.assertRaisesRegex(ValueError,"unsafe"):
                    audit(Path(directory))

    def test_sensitive_paths_not_exposed_in_output(self):
        with tempfile.TemporaryDirectory() as directory:
            secret="var/run/secrets/my-fake-sensitive-key"
            e,receipt=build(directory,members=[
                (secret,b"not-a-secret"),("opt/app/service",b"demo")])
            output=audit(Path(directory))
            self.assertGreater(output["sensitive_name_categories_needing_review"], 0)
            self.assertNotIn(secret,json.dumps(output))
            self.assertFalse(output["safe_to_cutover"])

    def test_unearned_true_claims_cannot_pass(self):
        for key in ("legacy_container_images_recovered",
                    "rootfs_equivalent_to_original_oci_image",
                    "runnable_rollback_verified",
                    "independent_admin_custody_verified",
                    "consistent_live_snapshot_proven",
                    "safe_to_cutover"):
            with self.subTest(flag=key),tempfile.TemporaryDirectory() as directory:
                e,receipt=build(directory)
                e[key]=True
                receipt.write_text(json.dumps(e))
                with self.assertRaises(ValueError):
                    audit(Path(directory))

    def test_receipt_mode_and_directory_mode_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            e,receipt=build(directory)
            receipt.chmod(0o644)
            with self.assertRaises(ValueError):
                audit(Path(directory))
            receipt.chmod(0o600)
            Path(directory).chmod(0o755)
            with self.assertRaises(ValueError):
                audit(Path(directory))
            Path(directory).chmod(0o700)


if __name__=="__main__":
    unittest.main()
