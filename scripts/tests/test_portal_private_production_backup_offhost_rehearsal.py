"""Offline fail-closed safety tests. No real Tailscale, Docker or production bytes."""
import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import portal_private_production_backup_offhost_rehearsal as m
from scripts import portal_state_restore_rehearsal as restore


class OffhostPrivateBackupControls(unittest.TestCase):
    def test_backup_source_fixed_and_digest_inventory_exact(self):
        self.assertEqual(m.SOURCE,restore.SOURCE)
        self.assertEqual(set(m.ARCHIVES),{'snapshot-receipt.json','postgresql.custom','minio-raw-live.tar'})
        self.assertEqual([m.ARCHIVES[x][0] for x in m.ARCHIVES],[774,52881,84992])
        for size,digest in m.ARCHIVES.values():
            self.assertGreater(size,0)
            self.assertEqual(len(digest),64)
            self.assertTrue(all(c in '0123456789abcdef' for c in digest))
        self.assertEqual(set(m.IMAGES),{'kipnerter-spatial-postgres-1','kipnerter-spatial-minio-1'})
        self.assertTrue(all(x.startswith('sha256:') and len(x)==71 for x in m.IMAGES.values()))

    def test_unknown_remote_archive_name_rejected_without_contact(self):
        with patch.object(m.subprocess,'run',side_effect=AssertionError('no SSH allowed')):
            with self.assertRaises(ValueError):m.fetched_bytes('other_backup.tar')

    def test_mismatched_remote_backup_bytes_or_size_rejected(self):
        p=subprocess.CompletedProcess(args=[],returncode=0,stdout=b'invalid-file')
        with patch.object(m.subprocess,'run',return_value=p) as caller:
            with self.assertRaisesRegex(ValueError,'does not match pinned original'):
                m.fetched_bytes('postgresql.custom')
        argv=caller.call_args.args[0]
        self.assertEqual(argv[:4],['timeout','20s','tailscale','ssh'])
        self.assertEqual(argv[4],m.PROD_SSH)
        self.assertIn('head -c 52882',argv[-1])

    def test_tampered_exact_size_denied(self):
        p=subprocess.CompletedProcess(args=[],returncode=0,stdout=b'x'*m.ARCHIVES['snapshot-receipt.json'][0])
        with patch.object(m.subprocess,'run',return_value=p):
            with self.assertRaisesRegex(ValueError,'does not match pinned original'):
                m.fetched_bytes('snapshot-receipt.json')

    def test_failed_ssh_exit_denied(self):
        p=subprocess.CompletedProcess(args=[],returncode=1,stdout=b'')
        with patch.object(m.subprocess,'run',return_value=p):
            with self.assertRaises(ValueError):m.fetched_bytes('minio-raw-live.tar')

    def test_wrong_locally_loaded_image_is_denied(self):
        p=subprocess.CompletedProcess(args=[],returncode=0,stdout=b'sha256:'+b'0'*64)
        with patch.object(m.subprocess,'run',return_value=p):
            with self.assertRaises(ValueError):m.verify_image_id('kipnerter-spatial-postgres-1')

    def test_remote_actual_image_drift_is_denied(self):
        output=b'/kipnerter-spatial-minio-1 sha256:'+b'0'*64+b'\n'
        p=subprocess.CompletedProcess(args=[],returncode=0,stdout=output)
        with patch.object(m.subprocess,'run',return_value=p):
            with self.assertRaises(ValueError):m.read_only_remote_identity()

    def test_default_returns_dry_run_without_tools(self):
        with patch('sys.argv',['script']),patch.object(m,'run_rehearsal',side_effect=AssertionError('must not run')):
            out=io.StringIO()
            with redirect_stdout(out):code=m.main()
        self.assertEqual(code,3)
        report=json.loads(out.getvalue())
        self.assertEqual(report['status'],'DRY_RUN_NO_REMOTE_OR_DOCKER_OPERATIONS')
        self.assertEqual(report['release_gate'],'NO_GO')
        self.assertFalse(report['safe_to_cutover'])

    def test_other_host_rejected_before_image_inspection(self):
        with patch.object(m.socket,'gethostname',return_value='kipnerter-prod-01'),patch.object(m,'verify_image_id',side_effect=AssertionError('image inspect happened')):
            with self.assertRaises(ValueError):m.run_rehearsal()

    def test_non_tmpfs_rejected_before_image_inspection(self):
        with patch.object(m.socket,'gethostname',return_value=m.TEST_HOST),patch.object(m,'private_tmpfs_ready',return_value=False),patch.object(m,'verify_image_id',side_effect=AssertionError('image inspect happened')):
            with self.assertRaises(ValueError):m.run_rehearsal()

    def test_mismatched_image_rejected_without_production_transfer(self):
        with patch.object(m.socket,'gethostname',return_value=m.TEST_HOST),patch.object(m,'private_tmpfs_ready',return_value=True),patch.object(m,'verify_image_id',side_effect=ValueError('wrong image')),patch.object(m,'fetched_bytes',side_effect=AssertionError('read backup')):
            with self.assertRaises(ValueError):m.run_rehearsal()

    def test_failed_remote_read_cleans_tmpfs_and_restores_image_lookup(self):
        import glob
        prior=set(glob.glob('/dev/shm/kipnerter-actual-backup-rehearsal-*'))
        original=restore.image_of
        with patch.object(m.socket,'gethostname',return_value=m.TEST_HOST),patch.object(m,'private_tmpfs_ready',return_value=True),patch.object(m,'verify_image_id',return_value=None),patch.object(m,'read_only_remote_identity',return_value=None),patch.object(m,'fetched_bytes',side_effect=ValueError('tampered')):
            with self.assertRaises(ValueError):m.run_rehearsal()
        self.assertIs(restore.image_of,original)
        self.assertEqual(set(glob.glob('/dev/shm/kipnerter-actual-backup-rehearsal-*')),prior)

    def test_success_receipt_cannot_approve_cutover(self):
        result={'status':'OLD_REAL_BACKUP_SCRATCH_RESTORE_PASS_NOT_RELEASE_AUTHORIZATION',
                'postgres_user_tables_restored':50,'minio_raw_backup_server_started':True}
        with patch('sys.argv',['script','--execute']),patch.object(m,'run_rehearsal',return_value=result):
            out=io.StringIO()
            with redirect_stdout(out):code=m.main()
        self.assertEqual(code,0)
        doc=json.loads(out.getvalue())
        for flag in ('safe_to_cutover','production_data_point_in_time_verified',
                     'minio_live_object_inventory_verified','independent_administrative_custody',
                     'real_oidc_browser_login_verified','production_database_backup_current',
                     'production_containers_or_volumes_modified','temporary_backup_bytes_retained'):
            self.assertFalse(doc[flag])
        self.assertEqual(doc['release_gate'],'NO_GO')

    def test_error_returns_hold_without_sensitive_details(self):
        with patch('sys.argv',['script','--execute']),patch.object(m,'run_rehearsal',side_effect=ValueError('secret should not appear in output')):
            out=io.StringIO()
            with redirect_stdout(out):code=m.main()
        self.assertEqual(code,2)
        self.assertNotIn('secret',out.getvalue())
        self.assertEqual(json.loads(out.getvalue())['status'],'HOLD')


if __name__=='__main__':unittest.main()
