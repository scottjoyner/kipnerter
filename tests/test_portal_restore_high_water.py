"""Offline fourth-key checkpoint high-water controls, no service changes."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.portal_restore_evidence import _canonical
from scripts.portal_restore_high_water import verify_high_water
from tests.test_portal_restore_chain import chain_fixture, resign
from tests.test_portal_restore_checkpoint import openssl


def highwater_fixture(root):
    chain, anchor, roles, observer = chain_fixture(root)
    key = root / "custodian.pem"
    pub = root / "custodian.pub"
    openssl("genpkey", "-algorithm", "Ed25519", "-out", str(key))
    openssl("pkey", "-in", str(key), "-pubout", "-out", str(pub))
    keyid = hashlib.sha256(openssl("pkey", "-pubin", "-in", str(pub),
                                  "-outform", "DER")).hexdigest()
    checkpoint_time = datetime.fromisoformat(
        chain["entries"][-1]["checkpoint"]["payload"]["observed_at"])
    payload = {
        "version": 1, "scope": "synthetic_restore_custodian_high_water",
        "end_sequence": anchor["end_sequence"],
        "end_sha256": anchor["end_sha256"],
        "release_sha": anchor["release_sha"],
        "topology_sha256": anchor["topology_sha256"],
        "recorded_at": (checkpoint_time + timedelta(seconds=1)).isoformat(),
    }
    tip = {"payload": payload, "custodian_signature": {
        "key_id": keyid, "signature": resign(root, "custodian.pem", payload, "highwater.sig")
    }}
    trust = {"version": 1, "scope": "synthetic_restore_custodian_trust",
             "custodian": {"key_id": keyid, "public_key_pem": pub.read_text()}}
    return chain, anchor, roles, observer, tip, trust


class HighWaterTests(unittest.TestCase):
    def test_fourth_key_success_does_not_assert_durability(self):
        with tempfile.TemporaryDirectory() as folder:
            inputs = highwater_fixture(Path(folder))
            result = verify_high_water(*inputs)
            self.assertEqual(result["end_sequence"], 13)
            self.assertTrue(result["chain_tip_matches_custodian_record"])
            self.assertTrue(result["custodian_signature_valid"])
            for key in ("independent_custodian_control_verified",
                        "rollback_resistant_persistence_verified",
                        "durable_external_high_water_verified",
                        "real_restore_verified", "production_recovery_approved"):
                self.assertFalse(result[key])
            self.assertNotIn(inputs[4]["custodian_signature"]["signature"],
                             json.dumps(result))

    def test_reject_rollbacks_forks_and_unanchored_forward_claims(self):
        with tempfile.TemporaryDirectory() as folder:
            inputs = highwater_fixture(Path(folder))
            for changes in (
                {"end_sequence": 12}, {"end_sequence": 14},
                {"end_sha256": "f"*64}, {"release_sha": "b"*40},
                {"topology_sha256": "e"*64}
            ):
                anchor = copy.deepcopy(inputs[1])
                anchor.update(changes)
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    verify_high_water(inputs[0], anchor, *inputs[2:])
            for field, value in (("end_sequence", 12), ("end_sequence", 14),
                                 ("end_sha256", "e"*64)):
                tip = copy.deepcopy(inputs[4])
                tip["payload"][field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    verify_high_water(*inputs[:4], tip, inputs[5])

    def test_reject_forgery_wrong_custodian_and_key_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            inputs = highwater_fixture(Path(folder))
            altered = copy.deepcopy(inputs[4])
            altered["custodian_signature"]["signature"] = "a" * 128
            with self.assertRaisesRegex(ValueError, "signature"):
                verify_high_water(*inputs[:4], altered, inputs[5])
            wrong = copy.deepcopy(inputs[5])
            wrong["custodian"]["key_id"] = "a" * 64
            with self.assertRaises(ValueError):
                verify_high_water(*inputs[:5], wrong)
            reused = copy.deepcopy(inputs[5])
            reused["custodian"] = copy.deepcopy(inputs[3]["observer"])
            altered = copy.deepcopy(inputs[4])
            altered["custodian_signature"]["key_id"] = reused["custodian"]["key_id"]
            with self.assertRaisesRegex(ValueError, "distinct"):
                verify_high_water(*inputs[:4], altered, reused)
            altered = copy.deepcopy(inputs[4])
            altered["payload"]["recorded_at"] = (
                datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
            with self.assertRaises(ValueError):
                verify_high_water(*inputs[:4], altered, inputs[5])

    def test_cli_fail_closed_on_permissions_inodes_symlink_fifo_and_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixtures = highwater_fixture(root)
            names = ("chain", "external-anchor", "external-role-trust",
                     "external-observer-trust", "signed-high-water", "external-custodian-trust")
            files = []
            for name, item in zip(names, fixtures):
                p = root / (name + ".json")
                p.write_text(json.dumps(item))
                p.chmod(0o600)
                files.append(p)
            args = [sys.executable, str(Path(__file__).resolve().parents[1] /
                                         "scripts/portal_restore_high_water.py")]
            for name, file in zip(names, files):
                args.extend(("--" + name, str(file)))
            def invoke(override=None):
                result = subprocess.run(override or args, capture_output=True,
                                        text=True, timeout=15)
                return result
            valid = invoke()
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertFalse(json.loads(valid.stdout)["production_recovery_approved"])
            files[4].chmod(0o644)
            denied = invoke()
            self.assertNotEqual(denied.returncode, 0)
            self.assertFalse(denied.stdout.strip())
            files[4].chmod(0o600)
            link = root / "tip-symlink"
            link.symlink_to(files[4])
            redirected = list(args)
            redirected[redirected.index("--signed-high-water")+1] = str(link)
            self.assertNotEqual(invoke(redirected).returncode, 0)
            link.unlink()
            linked = root / "tip-hardlink"
            linked.hardlink_to(files[4])
            duplicate = list(args)
            duplicate[duplicate.index("--external-custodian-trust")+1] = str(linked)
            self.assertIn("distinct opened inodes", invoke(duplicate).stderr)
            linked.unlink()
            named_pipe = root / "untrusted-pipe"
            os.mkfifo(named_pipe)
            piped = list(args)
            piped[piped.index("--signed-high-water")+1] = str(named_pipe)
            # An adversary-controlled FIFO must fail promptly, not hang on open().
            self.assertNotEqual(invoke(piped).returncode, 0)
            files[4].write_text(files[4].read_text().replace(
                '"payload":', '"payload": null, "payload":', 1))
            self.assertIn("duplicate", invoke().stderr)


if __name__ == "__main__":
    unittest.main()
