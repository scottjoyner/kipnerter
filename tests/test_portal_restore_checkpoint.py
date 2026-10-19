"""Synthetic observer signatures, with no fleet access or restore actions."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.portal_restore_evidence import _canonical
from scripts.portal_restore_checkpoint import verify_checkpoint
from tests.test_portal_restore_evidence import signed_fixture

PRIOR = "c" * 64


def openssl(*args):
    output = subprocess.run(["openssl", *args], capture_output=True, timeout=6)
    if output.returncode:
        raise RuntimeError("fixture OpenSSL call failed")
    return output.stdout


def fixture(root):
    receipt, role_trust = signed_fixture(root)
    key = root / "observer.pem"
    pub = root / "observer.pub"
    message = root / "checkpoint.payload"
    signature = root / "checkpoint.sig"
    openssl("genpkey", "-algorithm", "Ed25519", "-out", str(key))
    openssl("pkey", "-in", str(key), "-pubout", "-out", str(pub))
    key_id = hashlib.sha256(openssl("pkey", "-pubin", "-in", str(pub),
                                    "-outform", "DER")).hexdigest()
    payload = {
        "version": 1, "scope": "staging_synthetic_restore_checkpoint",
        "receipt_sha256": hashlib.sha256(_canonical(
            {k: v for k, v in receipt.items() if k != "signatures"})).hexdigest(),
        "fixture_nonce": receipt["fixture_nonce"],
        "release_sha": receipt["release_sha"],
        "topology_sha256": receipt["topology_sha256"],
        "sequence": 12,
        "previous_checkpoint_sha256": PRIOR,
        "observed_at": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
    }
    message.write_bytes(_canonical(payload))
    openssl("pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in",
            str(message), "-out", str(signature))
    checkpoint = {"payload": payload,
                  "observer_signature": {"key_id": key_id, "signature": signature.read_bytes().hex()}}
    trust = {"version": 1, "scope": "staging_synthetic_restore_observer",
             "observer": {"key_id": key_id, "public_key_pem": pub.read_text()}}
    return receipt, role_trust, checkpoint, trust


class SignedCheckpointTests(unittest.TestCase):
    def test_third_distinct_signature_binds_exact_receipt_and_prior_anchor(self):
        with tempfile.TemporaryDirectory() as temp:
            receipt, roles, checkpoint, witness = fixture(Path(temp))
            result = verify_checkpoint(checkpoint, witness, receipt, roles, 12, PRIOR)
            self.assertTrue(result["observer_signature_valid"])
            self.assertTrue(result["third_distinct_public_key"])
            self.assertTrue(result["external_anchor_matches"])
            for field in ("durable_external_high_water_verified",
                          "restore_operations_independently_observed",
                          "observer_administrative_custody_verified",
                          "production_recovery_approved"):
                self.assertFalse(result[field])
            self.assertNotIn(checkpoint["observer_signature"]["signature"], str(result))

    def test_reject_modified_claim_nonce_topology_sequence_and_prior_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            receipt, roles, checkpoint, witness = fixture(Path(temp))
            for attr, value in (("fixture_nonce", "c"*32),
                                ("topology_sha256", "e"*64),
                                ("release_sha", "f"*40),
                                ("receipt_sha256", "f"*64),
                                ("sequence", 13),
                                ("previous_checkpoint_sha256", "e"*64)):
                bad = copy.deepcopy(checkpoint)
                bad["payload"][attr] = value
                with self.subTest(attr=attr), self.assertRaises(ValueError):
                    verify_checkpoint(bad, witness, receipt, roles, 12, PRIOR)
            for sequence, prior in ((11, PRIOR), (12, "d"*64), (1, PRIOR)):
                with self.subTest(sequence=sequence,prior=prior), self.assertRaises(ValueError):
                    verify_checkpoint(checkpoint, witness, receipt, roles, sequence, prior)

    def test_reject_forged_signature_reused_key_and_stale_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            receipt, roles, checkpoint, witness = fixture(Path(temp))
            fake = copy.deepcopy(checkpoint)
            fake["observer_signature"]["signature"] = "f" * 128
            with self.assertRaisesRegex(ValueError, "signature"):
                verify_checkpoint(fake, witness, receipt, roles, 12, PRIOR)
            fake = copy.deepcopy(checkpoint)
            fake["payload"]["observed_at"] = (
                datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
            with self.assertRaises(ValueError):
                verify_checkpoint(fake, witness, receipt, roles, 12, PRIOR)
            same_key = copy.deepcopy(witness)
            same_key["observer"] = copy.deepcopy(roles["roles"]["executor"])
            fake = copy.deepcopy(checkpoint)
            fake["observer_signature"]["key_id"] = same_key["observer"]["key_id"]
            with self.assertRaisesRegex(ValueError, "distinct"):
                verify_checkpoint(fake, same_key, receipt, roles, 12, PRIOR)

    def test_reject_valid_signature_for_different_signed_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            receipt, roles, checkpoint, witness = fixture(Path(temp))
            other = copy.deepcopy(receipt)
            other["fixture_nonce"] = "f"*32
            with self.assertRaises(ValueError):
                verify_checkpoint(checkpoint, witness, other, roles, 12, PRIOR)

    def test_cli_requires_private_external_role_and_observer_custody_files(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            receipt, roles, checkpoint, witness = fixture(folder)
            names = {"receipt": receipt, "roles": roles,
                     "checkpoint": checkpoint, "observer": witness}
            for key, value in names.items():
                file = folder / (key + ".json")
                file.write_text(json.dumps(value))
                file.chmod(0o600)
            script = Path(__file__).resolve().parents[1] / "scripts/portal_restore_checkpoint.py"
            argv = [sys.executable, str(script),
                    "--receipt", str(folder/"receipt.json"),
                    "--external-role-trust", str(folder/"roles.json"),
                    "--checkpoint", str(folder/"checkpoint.json"),
                    "--external-observer-trust", str(folder/"observer.json"),
                    "--expected-sequence", "12", "--expected-prior-sha256", PRIOR]
            executed = subprocess.run(argv, capture_output=True, text=True, timeout=9)
            self.assertEqual(executed.returncode, 0, executed.stderr)
            self.assertFalse(json.loads(executed.stdout)["production_recovery_approved"])
            (folder/"observer.json").chmod(0o644)
            failed = subprocess.run(argv, capture_output=True, text=True, timeout=9)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse(failed.stdout.strip())
            (folder/"observer.json").chmod(0o600)
            (folder/"checkpoint.json").write_text(
                (folder/"checkpoint.json").read_text().replace('"version": 1',
                                                              '"version": 1, "version": 1'))
            failed = subprocess.run(argv, capture_output=True, text=True, timeout=9)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("duplicate", failed.stderr)


if __name__ == "__main__":
    unittest.main()
