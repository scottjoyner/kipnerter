"""Synthetic fixture signatures are test-only; no production recovery claim."""
from datetime import datetime, timedelta, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.portal_restore_evidence import _canonical, verify

D = "d" * 64
E = "e" * 64
SHA = "a" * 40


def synthetic():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "version": 1,
        "scope": "synthetic_isolated_restore",
        "environment": "staging",
        "project": "kipnerter-staging",
        "release_sha": SHA,
        "topology_sha256": D,
        "fixture_nonce": "b" * 32,
        "observed_at": now,
        "images": [
            {"service": "spatial-postgres",
             "reference": "postgis/postgis:16-3.4@sha256:" + D,
             "volume": "kipnerter-staging_spatial_postgres_data"},
            {"service": "spatial-minio",
             "reference": "minio/minio@sha256:" + E,
             "volume": "kipnerter-staging_spatial_minio_data"},
        ],
        "database": {
            "backup_sha256": D, "backup_bytes": 1000,
            "source_rows": 5, "restored_rows": 5,
            "source_schema_sha256": D, "restored_schema_sha256": D,
            "source_logical_sha256": E, "restored_logical_sha256": E,
        },
        "objects": {
            "backup_sha256": E, "backup_bytes": 780,
            "source_count": 3, "restored_count": 3,
            "source_inventory_sha256": D, "restored_inventory_sha256": D,
        },
        "negative_tests": {
            "truncated_db_backup_rejected": True,
            "tampered_object_rejected": True,
            "restore_destination_is_new": True,
            "writers_quiesced": True,
        },
        "signatures": {},
    }


def subprocess_checked(command, **kwargs):
    res = subprocess.run(command, capture_output=True, check=False,
                         timeout=6, **kwargs)
    if res.returncode:
        raise RuntimeError("test OpenSSL failed")
    return res.stdout


def signed_fixture(root):
    evidence = synthetic()
    trust = {"version": 1, "scope": "staging_synthetic_restore", "roles": {}}
    payload = {k: v for k, v in evidence.items() if k != "signatures"}
    (root / "message").write_bytes(_canonical(payload))
    for role in ("executor", "independent_reviewer"):
        key = root / (role + ".pem")
        pub = root / (role + ".pub")
        sig = root / (role + ".sig")
        subprocess_checked(["openssl", "genpkey", "-algorithm", "Ed25519",
                            "-out", str(key)])
        subprocess_checked(["openssl", "pkey", "-in", str(key), "-pubout",
                            "-out", str(pub)])
        der = subprocess_checked(["openssl", "pkey", "-pubin", "-in", str(pub),
                                  "-outform", "DER"])
        key_id = hashlib.sha256(der).hexdigest()
        subprocess_checked(["openssl", "pkeyutl", "-sign", "-inkey", str(key),
                            "-rawin", "-in", str(root / "message"),
                            "-out", str(sig)])
        trust["roles"][role] = {"key_id": key_id, "public_key_pem": pub.read_text()}
        evidence["signatures"][role] = {"key_id": key_id, "signature": sig.read_bytes().hex()}
    return evidence, trust


class RestoreEvidenceTests(unittest.TestCase):
    def test_two_distinct_signatures_authenticate_fixture_claim_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence, trust = signed_fixture(Path(tmp))
            value = verify(evidence, trust)
            self.assertTrue(value["cryptographic_role_signatures_valid"])
            self.assertTrue(value["distinct_public_keys"])
            for field in ("restore_operations_independently_observed",
                          "administrative_key_custody_verified",
                          "rollback_replay_protection_verified",
                          "production_recovery_approved"):
                self.assertFalse(value[field], field)
            self.assertEqual(value["release_sha"], SHA)
            with self.assertRaisesRegex(ValueError, "requested exact release"):
                verify(evidence, trust, expected_release="f"*40)
            with self.assertRaisesRegex(ValueError, "preflight topology"):
                verify(evidence, trust, expected_release=SHA, expected_topology=E)
            self.assertTrue(verify(evidence, trust, expected_release=SHA,
                                   expected_topology=D)["cryptographic_role_signatures_valid"])
            self.assertNotIn(evidence["signatures"]["executor"]["signature"], str(value))
            self.assertNotIn(evidence["signatures"]["independent_reviewer"]["signature"], str(value))

    def test_signatures_reject_changed_claim_and_forged_approvals(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence, trust = signed_fixture(Path(tmp))
            attacks = [
                ("release_sha", "f" * 40),
                ("fixture_nonce", "c" * 32),
                ("topology_sha256", E),
            ]
            for field, value in attacks:
                tamper = copy.deepcopy(evidence)
                tamper[field] = value
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, "signature invalid"):
                    verify(tamper, trust)
            changed = copy.deepcopy(evidence)
            changed["database"]["restored_rows"] = 7
            with self.assertRaisesRegex(ValueError, "mismatch"):
                verify(changed, trust)
            forged = copy.deepcopy(evidence)
            forged["signatures"]["executor"]["signature"] = "a" * 128
            with self.assertRaisesRegex(ValueError, "signature invalid"):
                verify(forged, trust)

    def test_roles_must_have_separate_trusted_public_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence, trust = signed_fixture(Path(tmp))
            copy_key = copy.deepcopy(trust)
            copy_key["roles"]["independent_reviewer"] = copy_key["roles"]["executor"]
            with self.assertRaisesRegex(ValueError, "untrusted signing role"):
                verify(evidence, copy_key)
            no_role = copy.deepcopy(evidence)
            no_role["signatures"].pop("independent_reviewer")
            with self.assertRaisesRegex(ValueError, "both independent"):
                verify(no_role, trust)
            bad_key = copy.deepcopy(trust)
            bad_key["roles"]["executor"]["key_id"] = "f" * 64
            with self.assertRaisesRegex(ValueError, "untrusted signing role"):
                verify(evidence, bad_key)
            wrong_root = copy.deepcopy(trust)
            wrong_root["roles"]["executor"]["public_key_pem"] = trust["roles"]["independent_reviewer"]["public_key_pem"]
            with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                verify(evidence, wrong_root)

    def test_cannot_claim_prod_unisolated_or_unpinned_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence, trust = signed_fixture(Path(tmp))
            for field, value in (("environment", "production"),
                                 ("project", "kipnerter"),
                                 ("scope", "production_restore"),
                                 ("release_sha", "main")):
                bad = copy.deepcopy(evidence)
                bad[field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    verify(bad, trust)
            for mutation in ("volume", "image"):
                bad = copy.deepcopy(evidence)
                if mutation == "volume":
                    bad["images"][0]["volume"] = "kipnerter_spatial_postgres_data"
                else:
                    bad["images"][0]["reference"] = "postgis/postgis:16-3.4"
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    verify(bad, trust)

    def test_recovery_claims_require_exact_equivalence_and_negative_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence, trust = signed_fixture(Path(tmp))
            modifications = [
                ("database", "restored_logical_sha256", D),
                ("database", "restored_schema_sha256", E),
                ("database", "restored_rows", 6),
                ("objects", "restored_count", 4),
                ("objects", "restored_inventory_sha256", E),
                ("negative_tests", "tampered_object_rejected", False),
            ]
            for section, field, value in modifications:
                bad = copy.deepcopy(evidence)
                bad[section][field] = value
                with self.subTest(section=section, field=field), self.assertRaises(ValueError):
                    verify(bad, trust)

    def test_expired_and_naive_claims_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence, trust = signed_fixture(Path(tmp))
            for timestamp in ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                              "2026-10-19T12:00:00",
                              (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()):
                bad = copy.deepcopy(evidence)
                bad["observed_at"] = timestamp
                with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                    verify(bad, trust)

    def test_cli_requires_private_external_trust_file_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence, trust = signed_fixture(root)
            report, trustfile = root / "receipt.json", root / "trust.json"
            report.write_text(json.dumps(evidence))
            trustfile.write_text(json.dumps(trust))
            script = Path(__file__).resolve().parents[1] / "scripts/portal_restore_evidence.py"
            argv = [sys.executable, str(script), "--evidence", str(report),
                    "--external-trust-root", str(trustfile),
                    "--expected-release-sha", SHA,
                    "--expected-topology-sha256", D]
            trustfile.chmod(0o644)
            first = subprocess.run(argv, capture_output=True, text=True, timeout=8)
            self.assertNotEqual(first.returncode, 0)
            self.assertFalse(first.stdout.strip())
            trustfile.chmod(0o600)
            duplicate = report.read_text().replace('"version": 1', '"version": 1, "version": 1')
            report.write_text(duplicate)
            repeated = subprocess.run(argv, capture_output=True, text=True, timeout=8)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("duplicate", repeated.stderr)
            report.write_text(json.dumps(evidence))
            second = subprocess.run(argv, capture_output=True, text=True, timeout=8)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertFalse(json.loads(second.stdout)["production_recovery_approved"])
            linked = root / "trust-link"
            linked.symlink_to(trustfile)
            argv[argv.index("--external-trust-root") + 1] = str(linked)
            third = subprocess.run(argv, capture_output=True, text=True, timeout=8)
            self.assertNotEqual(third.returncode, 0)
            self.assertFalse(third.stdout.strip())


if __name__ == "__main__":
    unittest.main()
