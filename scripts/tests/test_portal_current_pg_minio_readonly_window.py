"""Offline safety controls for fresh read-only PostgreSQL+MinIO observation."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

from scripts import portal_current_pg_minio_readonly_window as m


class FakeProc:
    def __init__(self, payload, status=0):
        self.stdout=io.BytesIO(payload)
        self.status=status
    def wait(self,timeout=12):return self.status
    def poll(self):return self.status


def synthetic_tar():
    output=io.BytesIO()
    with tarfile.open(mode='w',fileobj=output) as tf:
        root=tarfile.TarInfo('data');root.type=tarfile.DIRTYPE;tf.addfile(root)
        child=tarfile.TarInfo('data/synthetic-only');content=b'NOT_REAL_MINIO_DATA'*12
        child.size=len(content);tf.addfile(child,io.BytesIO(content))
    return output.getvalue()


class PairedReadOnlyControls(unittest.TestCase):
    def setUp(self):
        self.live={'status':'READ_ONLY_S3_CONTENT_ATTESTED',
                   'bucket_present':True,'object_count':2,
                   'metadata_digest':'a'*64,'content_digest':'b'*64,
                   'writes_fenced':False,'safe_to_cutover':False}
        self.objects=((True,2,'a'*64),(2,'b'*64))

    def test_default_does_not_run_any_command(self):
        out=io.StringIO()
        with patch('sys.argv',['cmd']),patch.object(m,'execute',side_effect=AssertionError('ran')),redirect_stdout(out):
            self.assertEqual(m.main(),3)
        result=json.loads(out.getvalue())
        self.assertFalse(result['safe_to_cutover'])
        self.assertEqual(result['release_gate'],'NO_GO')

    def test_exact_minio_read_only_source_command(self):
        self.assertEqual(m.MINIO_SSH_ARGS[:5],['timeout','90s','tailscale','ssh',m.backup.PROD_SSH])
        self.assertEqual(m.MINIO_SSH_ARGS[-1], 'docker cp kipnerter-spatial-minio-1:/data -')
        self.assertNotIn('docker run', m.MINIO_SSH_ARGS[-1])
        self.assertNotIn(' rm ',m.MINIO_SSH_ARGS[-1])

    def test_unapproved_host_denied_without_image_or_remote_access(self):
        with patch.object(m.socket,'gethostname',return_value='kipnerter-prod-01'), \
             patch.object(m.backup,'verify_image_id',side_effect=AssertionError('image inspected')):
            with self.assertRaises(ValueError):m.prereqs()

    def test_non_tmpfs_denied_before_image_inspection(self):
        with patch.object(m.socket,'gethostname',return_value=m.backup.TEST_HOST), \
             patch.object(m.backup,'private_tmpfs_ready',return_value=False), \
             patch.object(m.backup,'verify_image_id',side_effect=AssertionError('image inspected')):
            with self.assertRaises(ValueError):m.prereqs()

    def test_exact_image_id_required_for_both_roles(self):
        with patch.object(m.socket,'gethostname',return_value=m.backup.TEST_HOST), \
             patch.object(m.backup,'private_tmpfs_ready',return_value=True), \
             patch.object(m.backup,'verify_image_id',side_effect=ValueError('drift')), \
             patch.object(m.s3w,'checked_live_read',side_effect=AssertionError('live S3 invoked')):
            with self.assertRaises(ValueError):m.prereqs()

    def test_read_only_tar_stream_validates_archive_before_extract(self):
        contents=synthetic_tar()
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            archive,count,sha,members=m.fresh_minio_archive(Path(tmp),popen=lambda *a,**k:FakeProc(contents))
            self.assertTrue(archive.exists())
            self.assertEqual(count,len(contents))
            self.assertEqual(len(sha),64)
            self.assertEqual(members,2)
            self.assertEqual(archive.stat().st_mode & 0o077,0)

    def test_empty_truncated_oversized_or_failed_minio_copy_denied(self):
        variations=[(b'',0),(b'garbage',0),(b'x'*(m.MAX_RAW_MINIO_BYTES+1),0),
                    (synthetic_tar(),1)]
        for payload,exitcode in variations:
            with self.subTest(size=len(payload),exitcode=exitcode),tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
                with self.assertRaises((ValueError,tarfile.TarError)):
                    m.fresh_minio_archive(Path(tmp),popen=lambda *a,**k:FakeProc(payload,exitcode))

    def test_minio_copy_refuses_existing_path_overwrite(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            target=Path(tmp)/'minio-live-copy.tar';target.write_bytes(b'EXISTING')
            with self.assertRaises(FileExistsError):
                m.fresh_minio_archive(Path(tmp),popen=lambda *a,**k:FakeProc(synthetic_tar()))
            self.assertEqual(target.read_bytes(),b'EXISTING')

    def test_restored_s3_requires_object_count_metadata_and_content(self):
        cases=[((True,2,'x'*64),(2,'b'*64)),
               ((True,2,'a'*64),(2,'x'*64)),
               ((True,1,'a'*64),(1,'b'*64))]
        for ret in cases:
            with self.subTest(ret=ret),patch.object(m,'prereqs',return_value=None), \
                 patch.object(m.s3w,'checked_live_read',side_effect=[self.live,self.live]), \
                 patch.object(m.pg,'fetch_current_dump',return_value=(Path('/dev/null'),52881,'a'*64)), \
                 patch.object(m.recovery,'scratch_postgres',return_value=50), \
                 patch.object(m,'fresh_minio_archive',return_value=(Path('/dev/null'),85000,'b'*64,53)), \
                 patch.object(m,'restored_minio_content',return_value=ret), \
                 patch.object(m.backup,'read_only_remote_identity',return_value=None):
                with self.assertRaises(ValueError):m.execute()

    def test_live_s3_change_detected_after_restore(self):
        changed={**self.live,'content_digest':'c'*64}
        with patch.object(m,'prereqs',return_value=None), \
             patch.object(m.s3w,'checked_live_read',side_effect=[self.live,changed]), \
             patch.object(m.pg,'fetch_current_dump',return_value=(Path('/dev/null'),52881,'a'*64)), \
             patch.object(m.recovery,'scratch_postgres',return_value=50), \
             patch.object(m,'fresh_minio_archive',return_value=(Path('/dev/null'),85000,'b'*64,53)), \
             patch.object(m,'restored_minio_content',return_value=self.objects), \
             patch.object(m.backup,'read_only_remote_identity',return_value=None):
            with self.assertRaisesRegex(ValueError,'changed'):m.execute()

    def test_passing_both_services_never_sets_consistency_or_cutover(self):
        with patch.object(m,'prereqs',return_value=None), \
             patch.object(m.s3w,'checked_live_read',side_effect=[self.live,self.live]), \
             patch.object(m.pg,'fetch_current_dump',return_value=(Path('/dev/null'),52881,'a'*64)), \
             patch.object(m.recovery,'scratch_postgres',return_value=50), \
             patch.object(m,'fresh_minio_archive',return_value=(Path('/dev/null'),85000,'b'*64,53)), \
             patch.object(m,'restored_minio_content',return_value=self.objects), \
             patch.object(m.backup,'read_only_remote_identity',return_value=None):
            r=m.execute()
        self.assertEqual(r['release_gate'],'NO_GO')
        self.assertEqual(r['status'],'FRESH_PG_AND_MINIO_READONLY_OBSERVATION_WINDOW_PASS_NOT_ATOMIC')
        for key in ('postgres_source_writes_fenced','minio_source_writes_fenced',
                    'cross_service_point_in_time_consistent','independent_administrative_custody',
                    'real_oidc_browser_login_verified','safe_to_cutover','fresh_data_retained_offhost'):
            self.assertFalse(r[key],key)

    def test_failed_recovery_cleans_backup_tmpfs_and_reverts_image_resolution(self):
        old=m.recovery.image_of
        previous=set(Path('/dev/shm').glob('kipnerter-current-pg-minio-window-*'))
        with patch.object(m,'prereqs',return_value=None), \
             patch.object(m.s3w,'checked_live_read',return_value=self.live), \
             patch.object(m.pg,'fetch_current_dump',side_effect=ValueError('failed copy')):
            with self.assertRaises(ValueError):m.execute()
        self.assertIs(m.recovery.image_of,old)
        self.assertEqual(set(Path('/dev/shm').glob('kipnerter-current-pg-minio-window-*')),previous)

    def test_error_response_does_not_disclose_private_object_key(self):
        out=io.StringIO()
        with patch('sys.argv',['cmd','--execute']), \
             patch.object(m,'execute',side_effect=ValueError('bucket secret-key should stay private')), \
             redirect_stdout(out):
            self.assertEqual(m.main(),2)
        self.assertNotIn('secret-key',out.getvalue())
        self.assertEqual(json.loads(out.getvalue())['status'],'HOLD')


if __name__=='__main__':unittest.main()
