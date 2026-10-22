"""Offline negative controls: never SSH, read production, or run Docker."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout

from scripts import portal_current_postgres_tmpfs_restore as m

VALID=b'PGDMP'+b'NO_REAL_DB_DATA'*100

class FreshPostgresRestoreSafety(unittest.TestCase):
    def test_exact_remote_identity_and_read_only_dump(self):
        self.assertEqual(m.REMOTE,m.backup.PROD_SSH)
        self.assertEqual(m.PG,'kipnerter-spatial-postgres-1')
        self.assertEqual(m.IMAGE,m.backup.IMAGES[m.PG])
        self.assertEqual(m.REMOTE_ARGS[:5],['timeout','100s','tailscale','ssh',m.REMOTE])
        command=m.REMOTE_ARGS[-1]
        self.assertIn('pg_dump -Fc',command)
        self.assertIn('docker exec -u postgres',command)
        self.assertNotIn('docker run',command)
        self.assertNotIn('docker cp',command)
        self.assertNotIn('pg_restore',command)

    def test_valid_custom_format_bytes_only(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            size,digest=m.bounded_archive(io.BytesIO(VALID),Path(tmp)/'custom.dump')
            self.assertEqual(size,len(VALID))
            self.assertEqual(len(digest),64)
            self.assertEqual((Path(tmp)/'custom.dump').read_bytes(),VALID)

    def test_refuse_non_pg_dump_magic(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            with self.assertRaisesRegex(ValueError,'custom-format'):
                m.bounded_archive(io.BytesIO(b'WRONG'+VALID[5:]),Path(tmp)/'bad.dump')

    def test_refuse_empty_and_truncated_dumps(self):
        for payload in (b'',b'PGDMP',b'PGDMP'+b'x'*300):
            with self.subTest(length=len(payload)),tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
                with self.assertRaisesRegex(ValueError,'missing or truncated'):
                    m.bounded_archive(io.BytesIO(payload),Path(tmp)/'bad.dump')

    def test_refuse_dump_larger_than_cap(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            with self.assertRaisesRegex(ValueError,'8 MiB'):
                m.bounded_archive(io.BytesIO(b'PGDMP'+b'x'*m.MAX_DUMP),Path(tmp)/'oversize')

    def test_refuse_nonbinary_stream(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            with self.assertRaisesRegex(ValueError,'nonbinary'):
                m.bounded_archive(io.StringIO('PGDMP'+'a'*1200),Path(tmp)/'bad')

    def test_time_budget_denies_input(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            with self.assertRaisesRegex(ValueError,'timed out'):
                clock=iter((0,200))
                m.bounded_archive(io.BytesIO(VALID),Path(tmp)/'slow',monotonic=lambda:next(clock))

    def test_no_overwrite_existing_backup_file(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            p=Path(tmp)/'backup';p.write_bytes(b'KEEP_OLD')
            with self.assertRaises(FileExistsError):m.bounded_archive(io.BytesIO(VALID),p)
            self.assertEqual(p.read_bytes(),b'KEEP_OLD')

    def test_no_real_ssh_without_execute(self):
        with patch('sys.argv',['test']),patch.object(m,'execute',side_effect=AssertionError('executed')),redirect_stdout(io.StringIO()) as out:
            self.assertEqual(m.main(),3)
        result=json.loads(out.getvalue())
        self.assertFalse(result['safe_to_cutover'])
        self.assertEqual(result['release_gate'],'NO_GO')

    def test_unapproved_host_denied_before_docker_and_ssh(self):
        with patch.object(m.socket,'gethostname',return_value='kipnerter-prod-01'),patch.object(m.backup,'verify_image_id',side_effect=AssertionError('docker called')):
            with self.assertRaisesRegex(ValueError,'unauthorized'):m.validate_scratch()

    def test_no_tmpfs_denied_before_docker(self):
        with patch.object(m.socket,'gethostname',return_value=m.HOST),patch.object(m.backup,'private_tmpfs_ready',return_value=False),patch.object(m.backup,'verify_image_id',side_effect=AssertionError('docker called')):
            with self.assertRaisesRegex(ValueError,'RAM-backed'):m.validate_scratch()

    def test_image_drift_denied_before_remote_dump(self):
        with patch.object(m.socket,'gethostname',return_value=m.HOST),patch.object(m.backup,'private_tmpfs_ready',return_value=True),patch.object(m.backup,'verify_image_id',side_effect=ValueError('wrong image')),patch.object(m.backup,'read_only_remote_identity',side_effect=AssertionError('ssh ran')):
            with self.assertRaises(ValueError):m.validate_scratch()

    def test_source_command_failure_is_denied(self):
        class FailedProcess:
            def __init__(self):
                self.stdout=io.BytesIO(VALID)
            def wait(self,timeout=10):return 1
            def poll(self):return 1
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            with self.assertRaisesRegex(ValueError,'source PostgreSQL dump failed'):
                m.fetch_current_dump(Path(tmp),popen=lambda *a,**k:FailedProcess())

    def test_fresh_backup_result_cannot_approve_cross_service_release(self):
        temp_paths=[]
        def synthetic_fetch(root):
            p=root/'postgresql.custom';p.write_bytes(VALID)
            temp_paths.append(p)
            return p,len(VALID),'a'*64
        with patch.object(m,'validate_scratch',return_value=None), \
             patch.object(m,'fetch_current_dump',side_effect=synthetic_fetch), \
             patch.object(m.backup,'read_only_remote_identity',return_value=None), \
             patch.object(m.restore,'scratch_postgres',return_value=50):
            report=m.execute()
        self.assertFalse(temp_paths[0].exists())
        self.assertEqual(report['restored_user_tables'],50)
        self.assertTrue(report['database_transaction_snapshot_consistent'])
        for field in ('minio_included_in_snapshot','production_writes_fenced',
                      'cross_service_point_in_time_consistent','independent_custody_verified',
                      'real_oidc_browser_login_verified','safe_to_cutover',
                      'production_data_retained_offhost','production_services_or_volumes_changed'):
            self.assertFalse(report[field],field)
        self.assertEqual(report['release_gate'],'NO_GO')

    def test_tmpfs_cleanup_and_restore_identity_on_failure(self):
        old=m.restore.image_of
        before=set(Path('/dev/shm').glob('kipnerter-current-pg-restore-*'))
        with patch.object(m,'validate_scratch',return_value=None), \
             patch.object(m,'fetch_current_dump',side_effect=ValueError('fail')):
            with self.assertRaises(ValueError):m.execute()
        self.assertIs(m.restore.image_of,old)
        self.assertEqual(set(Path('/dev/shm').glob('kipnerter-current-pg-restore-*')),before)

    def test_operator_failure_hides_sensitive_error(self):
        out=io.StringIO()
        with patch('sys.argv',['test','--execute']),patch.object(m,'execute',side_effect=ValueError('production customer email in exception')),redirect_stdout(out):
            self.assertEqual(m.main(),2)
        self.assertNotIn('customer email',out.getvalue())
        self.assertEqual(json.loads(out.getvalue())['status'],'HOLD')

if __name__=='__main__':unittest.main()
