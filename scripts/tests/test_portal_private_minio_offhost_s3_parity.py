"""Offline controls for private S3 parity runner. No SSH, Docker or DB reads."""
import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from scripts import portal_private_minio_offhost_s3_parity as m


class PrivateS3ParitySafety(unittest.TestCase):
    def setUp(self):
        self.verified={'status':'READ_ONLY_S3_CONTENT_ATTESTED',
                       'bucket_present':True,'object_count':2,
                       'metadata_digest':'a'*64,'content_digest':'b'*64,
                       'writes_fenced':False,'safe_to_cutover':False}

    def mock_result(self, value, exit=0):
        return subprocess.CompletedProcess(args=[],returncode=exit,stdout=json.dumps(value).encode())

    def test_source_invocation_never_runs_main(self):
        src=m.live_source()
        self.assertNotIn('if __name__=="__main__":',src)
        self.assertIn('content_inventory("kipnerter-spatial-minio-1")',src)
        self.assertIn('before != after',src)
        self.assertNotIn('portal_minio_s3_parity.main()',src)

    def test_rejects_fake_remote_approval_and_wrong_object_count(self):
        changes=[{'writes_fenced':True},{'safe_to_cutover':True},
                 {'bucket_present':False},{'object_count':0},{'object_count':m.s3.MAX_OBJECTS+1},
                 {'status':'PASS'}, {'content_digest':'invalid'},
                 {'metadata_digest':'zz'*32},{'extra':'not allowed'}]
        for change in changes:
            with self.subTest(change=change):
                body={**self.verified,**change}
                with self.assertRaises(ValueError):
                    m.checked_live_read(command_runner=lambda *a,**k:self.mock_result(body))

    def test_source_checks_remote_identity_and_output_size(self):
        calls=[]
        def mock(argv,**kwargs):
            calls.append((argv,kwargs))
            return self.mock_result(self.verified)
        x=m.checked_live_read(command_runner=mock)
        self.assertEqual(x,self.verified)
        self.assertEqual(calls[0][0][2:5],['tailscale','ssh',m.backup.PROD_SSH])
        self.assertIn(b'content_inventory',calls[0][1]['input'])
        self.assertLess(len(calls[0][1]['input']),30000)

    def test_remote_truncated_oversized_and_duplicate_json_rejected(self):
        failures=[subprocess.CompletedProcess([],1,b''),
                  subprocess.CompletedProcess([],0,b''),
                  subprocess.CompletedProcess([],0,b'x'*5000),
                  subprocess.CompletedProcess([],0,b'{"status":"READ_ONLY_S3_CONTENT_ATTESTED","status":"READ_ONLY_S3_CONTENT_ATTESTED"}')]
        for response in failures:
            with self.subTest(response=response.returncode):
                with self.assertRaises((ValueError,json.JSONDecodeError)):
                    m.checked_live_read(command_runner=lambda *a,**k:response)

    def test_default_does_not_trigger_remote_tooling(self):
        out=io.StringIO()
        with patch('sys.argv',['script']),patch.object(m,'execute',side_effect=AssertionError('should not execute')),redirect_stdout(out):
            self.assertEqual(m.main(),3)
        result=json.loads(out.getvalue())
        self.assertEqual(result['release_gate'],'NO_GO')
        self.assertFalse(result['safe_to_cutover'])

    def test_rejects_other_host_before_tools(self):
        with patch.object(m.socket,'gethostname',return_value='kipnerter-prod-01'),patch.object(m.backup,'verify_image_id',side_effect=AssertionError('image inspected')):
            with self.assertRaises(ValueError):m.execute()

    def test_rejects_unknown_image_before_live_read(self):
        with patch.object(m.socket,'gethostname',return_value=m.backup.TEST_HOST),patch.object(m.backup,'private_tmpfs_ready',return_value=True),patch.object(m.backup,'verify_image_id',side_effect=ValueError('mismatch')),patch.object(m,'checked_live_read',side_effect=AssertionError('remote invoked')):
            with self.assertRaises(ValueError):m.execute()

    def test_metadata_and_body_mismatch_denied(self):
        v=dict(self.verified)
        for restored in (
            ((True,2,'a'*64),(2,'c'*64)),
            ((True,2,'f'*64),(2,'b'*64)),
            ((True,1,'a'*64),(2,'b'*64)),
            ((False,2,'a'*64),(2,'b'*64)),
        ):
            with self.subTest(restored=restored):
                with patch.object(m.socket,'gethostname',return_value=m.backup.TEST_HOST),\
                     patch.object(m.backup,'private_tmpfs_ready',return_value=True),\
                     patch.object(m.backup,'verify_image_id',return_value=None),\
                     patch.object(m.backup,'read_only_remote_identity',return_value=None),\
                     patch.object(m,'checked_live_read',side_effect=[v,v]),\
                     patch.object(m,'restored_raw_s3',return_value=restored):
                    with self.assertRaises(ValueError):m.execute()

    def test_live_source_change_denied_after_restored_check(self):
        original=dict(self.verified)
        changed={**self.verified,'content_digest':'c'*64}
        with patch.object(m.socket,'gethostname',return_value=m.backup.TEST_HOST),\
             patch.object(m.backup,'private_tmpfs_ready',return_value=True),\
             patch.object(m.backup,'verify_image_id',return_value=None),\
             patch.object(m.backup,'read_only_remote_identity',return_value=None),\
             patch.object(m,'checked_live_read',side_effect=[original,changed]),\
             patch.object(m,'restored_raw_s3',return_value=((True,2,'a'*64),(2,'b'*64))):
            with self.assertRaisesRegex(ValueError,'changed'):m.execute()

    def test_passing_metadata_and_bodies_never_approve_release(self):
        v=dict(self.verified)
        with patch.object(m.socket,'gethostname',return_value=m.backup.TEST_HOST),\
             patch.object(m.backup,'private_tmpfs_ready',return_value=True),\
             patch.object(m.backup,'verify_image_id',return_value=None),\
             patch.object(m.backup,'read_only_remote_identity',return_value=None),\
             patch.object(m,'checked_live_read',side_effect=[v,v]),\
             patch.object(m,'restored_raw_s3',return_value=((True,2,'a'*64),(2,'b'*64))):
            r=m.execute()
        self.assertEqual(r['status'],'PREVIOUS_PRODUCTION_BACKUP_S3_CONTENT_PARITY_PASS_NOT_PIT')
        for key in ('point_in_time_verified','source_writes_fenced','safe_to_cutover',
                    'current_backup_freshness_verified','independent_custody_verified',
                    'production_modified','production_data_uploaded_to_github'):
            self.assertFalse(r[key])
        self.assertEqual(r['release_gate'],'NO_GO')

    def test_remote_error_has_no_sensitive_details_in_stdout(self):
        out=io.StringIO()
        with patch('sys.argv',['script','--execute']), \
             patch.object(m,'execute',side_effect=ValueError('private S3 bucket name and keys')), \
             redirect_stdout(out):
            code=m.main()
        self.assertEqual(code,2)
        self.assertNotIn('bucket name',out.getvalue())
        self.assertNotIn('keys',out.getvalue())
        self.assertEqual(json.loads(out.getvalue())['status'],'HOLD')


if __name__=='__main__':unittest.main()
