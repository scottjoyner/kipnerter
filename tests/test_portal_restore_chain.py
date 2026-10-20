"""Offline synthetic chain and malicious fork/replay regression checks."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.portal_restore_chain import verify_chain
from scripts.portal_restore_evidence import _canonical
from tests.test_portal_restore_checkpoint import fixture, PRIOR, openssl


def resign(root, key_file, payload, signature_file):
    (root / 'message-to-sign').write_bytes(_canonical(payload))
    openssl('pkeyutl', '-sign', '-inkey', str(root / key_file), '-rawin',
            '-in', str(root / 'message-to-sign'), '-out', str(root / signature_file))
    return (root / signature_file).read_bytes().hex()


def chain_fixture(root):
    first_receipt, trust, first_checkpoint, observer = fixture(root)
    second_receipt = copy.deepcopy(first_receipt)
    second_receipt['fixture_nonce'] = 'd' * 32
    first_time = datetime.fromisoformat(first_receipt['observed_at'])
    second_receipt['observed_at'] = (first_time + timedelta(seconds=2)).isoformat()
    claim = {k: v for k, v in second_receipt.items() if k != 'signatures'}
    for role in ('executor', 'independent_reviewer'):
        second_receipt['signatures'][role]['signature'] = resign(
            root, role + '.pem', claim, role + '.receipt2.sig')
    second_checkpoint = copy.deepcopy(first_checkpoint)
    payload = second_checkpoint['payload']
    payload['receipt_sha256'] = hashlib.sha256(_canonical(claim)).hexdigest()
    payload['fixture_nonce'] = second_receipt['fixture_nonce']
    payload['sequence'] = 13
    payload['previous_checkpoint_sha256'] = hashlib.sha256(_canonical(first_checkpoint)).hexdigest()
    payload['observed_at'] = (first_time + timedelta(seconds=3)).isoformat()
    second_checkpoint['observer_signature']['signature'] = resign(
        root, 'observer.pem', payload, 'observer2.sig')
    chain = {'version': 1, 'scope': 'synthetic_restore_checkpoint_chain',
             'entries': [{'receipt': first_receipt, 'checkpoint': first_checkpoint},
                         {'receipt': second_receipt, 'checkpoint': second_checkpoint}]}
    anchor = {'version': 1, 'scope': 'operator_pinned_synthetic_restore_chain',
              'start_sequence': 11, 'start_sha256': PRIOR, 'end_sequence': 13,
              'end_sha256': hashlib.sha256(_canonical(second_checkpoint)).hexdigest(),
              'release_sha': 'a' * 40, 'topology_sha256': 'd' * 64}
    return chain, anchor, trust, observer


class ChainVerifierTests(unittest.TestCase):
    def test_anchored_two_receipt_chain_has_only_cryptographic_status(self):
        with tempfile.TemporaryDirectory() as temp:
            chain, anchor, roles, observer = chain_fixture(Path(temp))
            result = verify_chain(chain, anchor, roles, observer)
            self.assertEqual(result['verified_checkpoint_count'], 2)
            self.assertTrue(result['checkpoint_links_and_signatures_valid'])
            self.assertEqual(result['chain_sha256'], anchor['end_sha256'])
            for name in ('independent_external_anchor_custody_verified',
                         'durable_external_high_water_verified',
                         'restore_operations_independently_observed',
                         'production_recovery_approved'):
                self.assertFalse(result[name])
            self.assertNotIn(chain['entries'][0]['receipt']['signatures']['executor']['signature'],
                             json.dumps(result))

    def test_deletion_reordering_duplicate_and_forged_anchor_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            chain, anchor, roles, observer = chain_fixture(Path(temp))
            attacks = [
                (chain | {'entries': chain['entries'][:1]}, anchor),
                (chain | {'entries': list(reversed(chain['entries']))}, anchor),
                (chain | {'entries': [chain['entries'][0], chain['entries'][0]]}, anchor),
                (chain, anchor | {'end_sha256': 'e' * 64}),
                (chain, anchor | {'start_sha256': 'f' * 64}),
                (chain, anchor | {'end_sequence': 14}),
                (chain, anchor | {'release_sha': 'f' * 40}),
                (chain, anchor | {'topology_sha256': 'e' * 64}),
            ]
            for sample, pinned in attacks:
                with self.subTest(sample=str(pinned)[:40]), self.assertRaises(ValueError):
                    verify_chain(sample, pinned, roles, observer)

    def test_cannot_replay_fixture_nonce_or_shuffle_signed_times(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            chain, anchor, roles, observer = chain_fixture(root)
            altered = copy.deepcopy(chain)
            receipt = altered['entries'][1]['receipt']
            receipt['fixture_nonce'] = altered['entries'][0]['receipt']['fixture_nonce']
            claim = {k: v for k, v in receipt.items() if k != 'signatures'}
            for role in ('executor', 'independent_reviewer'):
                receipt['signatures'][role]['signature'] = resign(
                    root, role + '.pem', claim, role + '.replay.sig')
            cp = altered['entries'][1]['checkpoint']
            cp['payload']['fixture_nonce'] = receipt['fixture_nonce']
            cp['payload']['receipt_sha256'] = hashlib.sha256(_canonical(claim)).hexdigest()
            cp['observer_signature']['signature'] = resign(
                root, 'observer.pem', cp['payload'], 'observer-replay.sig')
            changed_anchor = anchor | {'end_sha256': hashlib.sha256(_canonical(cp)).hexdigest()}
            with self.assertRaisesRegex(ValueError, 'nonce replayed'):
                verify_chain(altered, changed_anchor, roles, observer)
            time_fork = copy.deepcopy(chain)
            # A separately valid receipt may still be observed earlier than
            # the prior signed receipt; chain continuity must reject it.
            second_receipt = time_fork['entries'][1]['receipt']
            first_receipt_time = datetime.fromisoformat(
                chain['entries'][0]['receipt']['observed_at'])
            second_receipt['observed_at'] = (
                first_receipt_time - timedelta(seconds=1)).isoformat()
            claim = {k: v for k, v in second_receipt.items() if k != 'signatures'}
            for role in ('executor', 'independent_reviewer'):
                second_receipt['signatures'][role]['signature'] = resign(
                    root, role + '.pem', claim, role + '.time.sig')
            cp2 = time_fork['entries'][1]['checkpoint']
            cp2['payload']['receipt_sha256'] = hashlib.sha256(_canonical(claim)).hexdigest()
            cp2['observer_signature']['signature'] = resign(
                root, 'observer.pem', cp2['payload'], 'observer-time.sig')
            time_anchor = anchor | {'end_sha256': hashlib.sha256(_canonical(cp2)).hexdigest()}
            with self.assertRaisesRegex(ValueError, 'nonmonotonic'):
                verify_chain(time_fork, time_anchor, roles, observer)

    def test_signature_cannot_be_changed_even_when_end_hash_is_updated(self):
        with tempfile.TemporaryDirectory() as temp:
            chain, anchor, roles, observer = chain_fixture(Path(temp))
            forged = copy.deepcopy(chain)
            forged['entries'][1]['checkpoint']['observer_signature']['signature'] = 'f' * 128
            endpoint = anchor | {'end_sha256': hashlib.sha256(
                _canonical(forged['entries'][1]['checkpoint'])).hexdigest()}
            with self.assertRaisesRegex(ValueError, 'signature'):
                verify_chain(forged, endpoint, roles, observer)

    def test_cli_private_independent_anchor_no_duplicate_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            chain, anchor, roles, observer = chain_fixture(root)
            files = {}
            for name, value in [('chain', chain), ('anchor', anchor),
                                ('roles', roles), ('observer', observer)]:
                file = root / (name + '.json')
                file.write_text(json.dumps(value))
                file.chmod(0o600)
                files[name] = file
            script = Path(__file__).resolve().parents[1] / 'scripts/portal_restore_chain.py'
            argv = [sys.executable, str(script), '--chain', str(files['chain']),
                    '--external-anchor', str(files['anchor']),
                    '--external-role-trust', str(files['roles']),
                    '--external-observer-trust', str(files['observer'])]
            result = subprocess.run(argv, capture_output=True, text=True, timeout=12)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['verified_checkpoint_count'], 2)
            files['anchor'].chmod(0o644)
            bad = subprocess.run(argv, capture_output=True, text=True, timeout=12)
            self.assertNotEqual(bad.returncode, 0)
            self.assertFalse(bad.stdout.strip())
            files['anchor'].chmod(0o600)
            same_path = argv.copy()
            same_path[same_path.index('--external-anchor')+1] = str(files['chain'])
            bad = subprocess.run(same_path, capture_output=True, text=True, timeout=12)
            self.assertIn('distinct private files', bad.stderr)
            # A hardlink with a different filename is not a genuinely
            # independent trust input. Compare opened inode identities.
            hardlink = root / "hardlink-anchor.json"
            hardlink.hardlink_to(files['chain'])
            same_inode = argv.copy()
            same_inode[same_inode.index('--external-anchor')+1] = str(hardlink)
            denied = subprocess.run(same_inode, capture_output=True, text=True, timeout=12)
            self.assertIn('distinct private files', denied.stderr)
            hardlink.unlink()
            files['anchor'].write_text(files['anchor'].read_text().replace(
                '"version": 1', '"version": 1, "version": 1'))
            bad = subprocess.run(argv, capture_output=True, text=True, timeout=12)
            self.assertIn('duplicate', bad.stderr)


if __name__ == '__main__':
    unittest.main()
