"""Synthetic-only tests for private legacy build source archive provenance."""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.portal_legacy_source_archive_verify import BASE_NAME, REQUIRED, inspect


def fixture(root, *, names=None, lock=True):
    root = Path(root)
    members = {name: (b"synthetic source content " + name.encode())
               for name in sorted(REQUIRED)}
    if lock:
        members["apps/web/package-lock.json"] = b"{\"lockfileVersion\":3}"
    if names is not None:
        members = {name: b"synthetic fixture" for name in names}
    archive = root / BASE_NAME
    with tarfile.open(archive, "w:gz") as tar:
        for name, raw in sorted(members.items()):
            entry = tarfile.TarInfo(name)
            entry.size = len(raw)
            entry.mode = 0o644
            tar.addfile(entry, io.BytesIO(raw))
    archive.chmod(0o600)
    digest = hashlib.sha256()
    for name, raw in sorted(members.items()):
        digest.update(name.encode()+b"\x00"+hashlib.sha256(raw).digest())
    upper = (sum(map(len, members.values()))+1024**2-1)//1024**2
    receipt = {
        "schema": 1,
        "source_manifest_sha256": digest.hexdigest(),
        "source_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "source_file_count":len(members),
        "source_total_mib_upper_bound":upper,
        "private_archive_created":True,
        "web_dependency_lock_present": "apps/web/package-lock.json" in members,
        "web_legacy_build_reproducibility_verified":False,
        "docker_images_recovered":False,
        "runnable_equivalence_tested":False,
        "prior_git_revision_authoritative":False,
        "secrets_included_by_design":False,
        "production_app_containers_or_volumes_modified":False,
        "safe_to_cutover":False,
    }
    receipt_path = root / (BASE_NAME+".receipt.json")
    receipt_path.write_text(json.dumps(receipt,sort_keys=True))
    receipt_path.chmod(0o600)
    return receipt, archive, receipt_path


class SourceArchiveSafetyTests(unittest.TestCase):
    def test_exact_source_archive_manifest_is_not_oci_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt, archive, fp = fixture(tmp)
            report = inspect(Path(tmp))
            self.assertEqual(report["status"], "SOURCE_CUSTODY_VERIFIED_NOT_RUNNABLE")
            self.assertEqual(report["archived_source_files_checked"], len(REQUIRED)+1)
            self.assertTrue(report["web_dependency_lock_present"])
            for field in ("original_oci_images_recovered", "actual_build_reproduced",
                          "runnable_rollback_verified","legacy_git_revision_authoritative",
                          "independent_admin_custody_verified",
                          "source_bytes_or_paths_disclosed", "safe_to_cutover"):
                self.assertFalse(report[field])

    def test_changed_archive_body_denied_even_when_valid_gzip(self):
        with tempfile.TemporaryDirectory() as tmp:
            info, archive, receipt = fixture(tmp)
            archive.write_bytes(archive.read_bytes()+b"alteration")
            with self.assertRaisesRegex(ValueError, "digest"):
                inspect(Path(tmp))

    def test_manifest_hash_mismatch_and_wrong_count_denied(self):
        for change, val in (("source_manifest_sha256", "a"*64),
                            ("source_file_count", 100),
                            ("source_total_mib_upper_bound", 0)):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                info, archive, receipt = fixture(tmp)
                info[change] = val
                receipt.write_text(json.dumps(info))
                with self.assertRaises(ValueError):
                    inspect(Path(tmp))

    def test_unearned_authority_claims_denied(self):
        for key in ("web_legacy_build_reproducibility_verified",
                    "docker_images_recovered", "runnable_equivalence_tested",
                    "prior_git_revision_authoritative",
                    "secrets_included_by_design",
                    "production_app_containers_or_volumes_modified",
                    "safe_to_cutover"):
            with self.subTest(flag=key),tempfile.TemporaryDirectory() as tmp:
                info, archive, receipt = fixture(tmp)
                info[key] = True
                receipt.write_text(json.dumps(info))
                with self.assertRaisesRegex(ValueError, "claims"):
                    inspect(Path(tmp))

    def test_duplicate_receipt_members_and_wrong_schema_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            info, archive, receipt = fixture(tmp)
            raw = receipt.read_text().replace('"schema": 1,',
                    '"schema": 1, "schema": 1,', 1)
            receipt.write_text(raw)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                inspect(Path(tmp))
            info["schema"] = True
            receipt.write_text(json.dumps(info))
            with self.assertRaisesRegex(ValueError, "claims"):
                inspect(Path(tmp))

    def test_missing_required_source_and_untrusted_path_denied(self):
        missing = sorted(REQUIRED-{"apps/web/Dockerfile"})
        for names in (missing,
                      sorted(REQUIRED)+["apps/api/../../.env"],
                      sorted(REQUIRED)+["apps/api/.ssh/private.pem"],
                      sorted(REQUIRED)+["arbitrary/extra.js"]):
            with self.subTest(names=names[-1]),tempfile.TemporaryDirectory() as tmp:
                fixture(tmp,names=names)
                with self.assertRaises(ValueError):
                    inspect(Path(tmp))

    def test_web_lock_presence_must_match_attestation(self):
        with tempfile.TemporaryDirectory() as tmp:
            info, archive, receipt = fixture(tmp,lock=False)
            self.assertFalse(inspect(Path(tmp))["web_dependency_lock_present"])
            info["web_dependency_lock_present"] = True
            receipt.write_text(json.dumps(info))
            with self.assertRaisesRegex(ValueError, "lock"):
                inspect(Path(tmp))

    def test_symlink_and_hardlink_archive_denied(self):
        for variant in ("symlink", "hardlink"):
            with self.subTest(variant=variant),tempfile.TemporaryDirectory() as tmp:
                info, archive, receipt = fixture(tmp)
                if variant == "symlink":
                    other = Path(tmp)/"source"
                    archive.rename(other)
                    archive.symlink_to(other)
                    with self.assertRaises(OSError):
                        inspect(Path(tmp))
                else:
                    os.link(archive, Path(tmp)/"other")
                    with self.assertRaises(ValueError):
                        inspect(Path(tmp))

    def test_permissions_folder_and_receipt_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            info, archive, receipt = fixture(tmp)
            receipt.chmod(0o644)
            with self.assertRaises(ValueError):
                inspect(Path(tmp))
            receipt.chmod(0o600)
            Path(tmp).chmod(0o755)
            with self.assertRaises(ValueError):
                inspect(Path(tmp))
            Path(tmp).chmod(0o700)

    def test_no_extraction_and_no_production_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            info, archive, receipt = fixture(tmp)
            before = set(Path(tmp).iterdir())
            inspect(Path(tmp))
            self.assertEqual(before, set(Path(tmp).iterdir()))


if __name__ == "__main__":
    unittest.main()
