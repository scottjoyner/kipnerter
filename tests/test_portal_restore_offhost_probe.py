"""Memory-only remote probe: positive, negative, transport and no-write checks."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.portal_restore_custodian_ledger import ZERO, append_verified_tip
from scripts.portal_restore_offhost_probe import (
    REMOTE_PROGRAM, read_locked_synthetic_ledger, probe,
)
from tests.test_portal_restore_high_water import highwater_fixture


def local_remote(argv, **kwargs):
    assert argv[0] == "ssh"
    assert "StrictHostKeyChecking=yes" in argv
    assert argv[-2] == "lenovo"
    assert argv[-1].startswith("python3 -c ")
    return subprocess.run([sys.executable, "-c", REMOTE_PROGRAM], **kwargs)


def make_store(root):
    fixtures = highwater_fixture(root)
    directory = root / "ledger"
    directory.mkdir(mode=0o700)
    result = append_verified_tip(directory, chain=fixtures[0], anchor=fixtures[1],
        roles=fixtures[2], observer=fixtures[3], signed_tip=fixtures[4],
        custodian_trust=fixtures[5], expected_cursor=ZERO,
        bootstrap_expected=(13, fixtures[1]["end_sha256"]))
    return directory, result["cursor_sha256"]


class OffhostProbeTests(unittest.TestCase):
    def test_memory_only_probe_reports_only_qualified_synthetic_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            store, cursor = make_store(Path(folder))
            output = probe(store, cursor, runner=local_remote)
            self.assertTrue(output["expected_cursor_matched"])
            self.assertEqual(output["end_sequence"], 13)
            self.assertTrue(output["remote_memory_only_compute"])
            for field in ("remote_persistence_verified",
                          "independent_administrative_custody_verified",
                          "rollback_resistant_high_water_verified",
                          "production_recovery_approved"):
                self.assertFalse(output[field])
            self.assertNotIn("ledger", json.dumps(output))

    def test_bad_cursor_rejected_before_ssh_and_unapproved_host_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            store, cursor = make_store(Path(folder))
            def no_ssh(*a, **kwargs):
                raise AssertionError("unexpected remote execution")
            with self.assertRaisesRegex(ValueError, "cursor"):
                probe(store, "a"*64, runner=no_ssh)
            with self.assertRaisesRegex(ValueError, "alias"):
                probe(store, cursor, host="production", runner=no_ssh)
            with self.assertRaises(ValueError):
                probe(store, "invalid", runner=no_ssh)

    def test_changed_inflight_bytes_and_truncation_fail_remote_check(self):
        with tempfile.TemporaryDirectory() as folder:
            store, cursor = make_store(Path(folder))
            raw, original, seq, count = read_locked_synthetic_ledger(store)
            self.assertEqual(original, cursor)
            for payload in (raw[:-1], raw.replace(b'"end_sequence":13', b'"end_sequence":12'),
                            raw + raw, b'x'*100):
                def changed(_):
                    return payload, cursor, seq, count
                with self.subTest(first=payload[:15]), self.assertRaisesRegex(ValueError, "remote"):
                    probe(store, cursor, runner=local_remote, snapshot_reader=changed)

    def test_refuse_wrong_remote_challenge_or_fake_success(self):
        with tempfile.TemporaryDirectory() as folder:
            store, cursor = make_store(Path(folder))
            def forged(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({
                    "challenge": "f"*64, "cursor_sha256": cursor, "end_sequence": 13,
                    "record_count": 1, "host": "lenovo",
                    "recomputed_from_synthetic_bytes": True}).encode())
            with self.assertRaisesRegex(ValueError, "challenge"):
                probe(store, cursor, runner=forged)
            def bad_shell(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 255, stdout=b"")
            with self.assertRaisesRegex(ValueError, "unavailable"):
                probe(store, cursor, runner=bad_shell)
            def huge_reply(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, stdout=b"x"*2000)
            with self.assertRaisesRegex(ValueError, "unavailable"):
                probe(store, cursor, runner=huge_reply)

    def test_no_trust_of_symlink_or_permissive_or_hardlinked_local_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store, cursor = make_store(root)
            path = store / "synthetic-high-water.jsonl"
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private"):
                probe(store, cursor, runner=local_remote)
            path.chmod(0o600)
            duplicate = store / "hardlink"
            duplicate.hardlink_to(path)
            with self.assertRaisesRegex(ValueError, "single-link"):
                probe(store, cursor, runner=local_remote)
            duplicate.unlink()
            named = root / "link"
            named.symlink_to(path)
            with self.assertRaises(OSError):
                read_locked_synthetic_ledger(root, "link")


if __name__ == "__main__":
    unittest.main()
