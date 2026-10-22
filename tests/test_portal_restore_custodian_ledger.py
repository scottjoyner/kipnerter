"""Research-only local high-water compare/append and corruption controls."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.portal_restore_custodian_ledger import (
    ZERO, append_verified_tip, inspect_local_log,
)
from scripts.portal_restore_evidence import _canonical
from tests.test_portal_restore_chain import resign
from tests.test_portal_restore_high_water import highwater_fixture


def next_tip(root, fixtures):
    chain, anchor, roles, observer, signed_tip, custody = fixtures
    old_entry = chain["entries"][-1]
    prior_hash = hashlib.sha256(_canonical(old_entry["checkpoint"])).hexdigest()
    receipt = copy.deepcopy(old_entry["receipt"])
    observed = datetime.fromisoformat(receipt["observed_at"]) + timedelta(seconds=2)
    receipt["observed_at"] = observed.isoformat()
    receipt["fixture_nonce"] = "e" * 32
    claim = {k: v for k, v in receipt.items() if k != "signatures"}
    for role in ("executor", "independent_reviewer"):
        receipt["signatures"][role]["signature"] = resign(
            root, role + ".pem", claim, "ledger-" + role + ".sig")
    checkpoint = copy.deepcopy(old_entry["checkpoint"])
    payload = checkpoint["payload"]
    payload["receipt_sha256"] = hashlib.sha256(_canonical(claim)).hexdigest()
    payload["fixture_nonce"] = receipt["fixture_nonce"]
    payload["sequence"] = anchor["end_sequence"] + 1
    payload["previous_checkpoint_sha256"] = prior_hash
    payload["observed_at"] = (observed + timedelta(seconds=1)).isoformat()
    checkpoint["observer_signature"]["signature"] = resign(
        root, "observer.pem", payload, "ledger-observer.sig")
    new_hash = hashlib.sha256(_canonical(checkpoint)).hexdigest()
    new_chain = {"version": 1, "scope": chain["scope"],
                 "entries": [old_entry, {"receipt": receipt, "checkpoint": checkpoint}]}
    new_anchor = anchor | {
        "start_sequence": anchor["end_sequence"] - 1,
        "start_sha256": hashlib.sha256(_canonical(chain["entries"][-2]["checkpoint"])).hexdigest(),
        "end_sequence": anchor["end_sequence"] + 1,
        "end_sha256": new_hash,
    }
    tip = copy.deepcopy(signed_tip)
    tip["payload"]["end_sequence"] += 1
    tip["payload"]["end_sha256"] = new_hash
    tip["payload"]["recorded_at"] = (
        observed + timedelta(seconds=2)).isoformat()
    tip["custodian_signature"]["signature"] = resign(
        root, "custodian.pem", tip["payload"], "ledger-custodian.sig")
    return new_chain, new_anchor, roles, observer, tip, custody


def append(folder, fixture, cursor, bootstrap=None):
    return append_verified_tip(folder, chain=fixture[0], anchor=fixture[1],
                               roles=fixture[2], observer=fixture[3],
                               signed_tip=fixture[4], custodian_trust=fixture[5],
                               expected_cursor=cursor, bootstrap_expected=bootstrap)


class LocalCustodianResearchTests(unittest.TestCase):
    def test_two_authentic_signed_tips_append_contiguously(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            fixtures = highwater_fixture(root)
            successor = next_tip(root, fixtures)
            store = root / "private-ledger"
            store.mkdir(mode=0o700)
            seed = (fixtures[1]["end_sequence"], fixtures[1]["end_sha256"])
            first = append(store, fixtures, ZERO, seed)
            self.assertTrue(first["four_key_tip_verified"])
            self.assertFalse(first["independent_custody_verified"])
            second = append(store, successor, first["cursor_sha256"])
            observed = inspect_local_log(store, expected_cursor=second["cursor_sha256"])
            self.assertEqual(second["record_count"], 2)
            self.assertEqual(observed["latest_sequence"], 14)
            self.assertEqual(observed["cursor_sha256"], second["cursor_sha256"])
            self.assertFalse(observed["production_recovery_approved"])

    def test_no_auto_bootstrap_and_no_replay_or_unanchored_advance(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            a = highwater_fixture(root)
            b = next_tip(root, a)
            store = root / "private-ledger"
            store.mkdir(mode=0o700)
            with self.assertRaisesRegex(ValueError, "bootstrap"):
                append(store, a, ZERO)
            with self.assertRaisesRegex(ValueError, "bootstrap"):
                append(store, a, ZERO, (13, "f"*64))
            first = append(store, a, ZERO, (13, a[1]["end_sha256"]))
            with self.assertRaisesRegex(ValueError, "stale|changed"):
                append(store, b, ZERO)
            with self.assertRaisesRegex(ValueError, "replayed|skipped"):
                append(store, a, first["cursor_sha256"])
            second = append(store, b, first["cursor_sha256"])
            with self.assertRaisesRegex(ValueError, "stale|changed"):
                append(store, b, first["cursor_sha256"])
            self.assertEqual(inspect_local_log(store, expected_cursor=second["cursor_sha256"])["cursor_sha256"], second["cursor_sha256"])

    def test_tampering_truncation_and_invalid_records_fail_closed(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            a = highwater_fixture(root)
            store = root / "private-ledger"
            store.mkdir(mode=0o700)
            first = append(store, a, ZERO, (13, a[1]["end_sha256"]))
            record = store / "synthetic-high-water.jsonl"
            clean = record.read_bytes()
            samples = [
                clean[:-1], clean.replace(b'"end_sequence":13', b'"end_sequence":12'),
                clean.replace(b'"scope":', b'"scope":"duplicate","scope":', 1),
                clean + clean, b"x"*2049 + b"\n",
            ]
            for malformed in samples:
                record.write_bytes(malformed)
                with self.subTest(malformed=malformed[:30]), self.assertRaises(ValueError):
                    inspect_local_log(store, expected_cursor=first["cursor_sha256"])
            record.write_bytes(clean)
            self.assertEqual(inspect_local_log(store, expected_cursor=first["cursor_sha256"])["cursor_sha256"], first["cursor_sha256"])
            record.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private"):
                inspect_local_log(store, expected_cursor=first["cursor_sha256"])
            record.chmod(0o600)
            link = root / "link"
            link.symlink_to(record)
            with self.assertRaises(OSError):
                inspect_local_log(root, "link", expected_cursor=first["cursor_sha256"])
            duplicate = store / "hardlink.jsonl"
            duplicate.hardlink_to(record)
            with self.assertRaisesRegex(ValueError, "single-link"):
                inspect_local_log(store, expected_cursor=first["cursor_sha256"])
            duplicate.unlink()

    def test_reject_unsigned_altered_tip_and_directory_permissions(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            a = highwater_fixture(root)
            store = root / "private-ledger"
            store.mkdir(mode=0o700)
            bad = copy.deepcopy(a)
            bad = (*bad[:4], copy.deepcopy(bad[4]), bad[5])
            bad[4]["payload"]["end_sequence"] = 14
            with self.assertRaises(ValueError):
                append(store, bad, ZERO, (13, a[1]["end_sha256"]))
            store.chmod(0o755)
            with self.assertRaisesRegex(ValueError, "owner-private"):
                append(store, a, ZERO, (13, a[1]["end_sha256"]))
            store.chmod(0o700)

    def test_concurrent_compare_append_only_one_succeeds(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            fixture = highwater_fixture(root)
            store = root / "private-ledger"
            store.mkdir(mode=0o700)
            seed = (13, fixture[1]["end_sha256"])
            def attempt(_):
                try:
                    return append(store, fixture, ZERO, seed)["cursor_sha256"]
                except (ValueError, OSError):
                    return "HOLD"
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(attempt, range(2)))
            self.assertEqual(results.count("HOLD"), 1)
            self.assertEqual(inspect_local_log(store, expected_cursor=results[0] if results[0] != "HOLD" else results[1])["count"], 1)


if __name__ == "__main__":
    unittest.main()
