import hashlib
import json
import subprocess
import unittest
from scripts.portal_image_custody import SOURCES, inspect


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def metadata_runner(document, *, tamper=False, fail_format=False, fail_raw=False):
    raw=json.dumps(document, separators=(',', ':'), sort_keys=True).encode()
    digest='sha256:'+hashlib.sha256(raw).hexdigest()
    def runner(args, **kwargs):
        assert args[:4] == ['docker','buildx','imagetools','inspect']
        assert args[4] in SOURCES.values()
        assert kwargs['timeout']==15 and kwargs['capture_output'] is True
        assert kwargs['check'] is False
        if '--raw' in args:
            assert args[-1]=='--raw'
            return Result(returncode=1 if fail_raw else 0,
                          stdout=raw+b'changed' if tamper else raw)
        assert args[-2:]==['--format','{{json .Manifest}}']
        assert kwargs['text'] is True
        return Result(returncode=1 if fail_format else 0,
                      stdout=json.dumps({'mediaType':document.get('mediaType'),
                                         'digest':digest, 'size':len(raw)}))
    return runner


SINGLE={'mediaType':'application/vnd.docker.distribution.manifest.v2+json',
        'schemaVersion':2,'config':{'digest':'sha256:'+'f'*64},'layers':[]}


class ImageCustodyTests(unittest.TestCase):
    def test_exact_allowlist_and_digest_of_raw_manifest(self):
        value=inspect('spatial-postgres',metadata_runner(SINGLE))
        self.assertEqual(value['status'],'manifest_bytes_verified')
        self.assertTrue(value['raw_manifest_digest_verified'])
        self.assertEqual(value['manifest_kind'],'single_manifest')
        self.assertEqual(value['digest'], 'sha256:'+hashlib.sha256(
            json.dumps(SINGLE,separators=(',', ':'),sort_keys=True).encode()).hexdigest())
        self.assertFalse(value['architecture_verified'])
        self.assertFalse(value['linux_amd64_descriptor_observed'])
        self.assertIsNone(value['linux_amd64_manifest_digest'])
        self.assertFalse(value['restore_equivalence_verified'])
        self.assertFalse(value['recovery_approved'])
        with self.assertRaises(ValueError):inspect('unknown-image',metadata_runner(SINGLE))

    def test_tag_changed_between_metadata_reads_is_not_attested(self):
        value=inspect('spatial-postgres',metadata_runner(SINGLE,tamper=True))
        self.assertFalse(value['raw_manifest_digest_verified'])
        self.assertEqual(value['status'],'manifest_digest_observed')
        self.assertFalse(value['architecture_verified'])

    def test_registry_errors_redacted_and_do_not_qualify(self):
        for runner in (
            metadata_runner(SINGLE,fail_format=True),
            metadata_runner(SINGLE,fail_raw=True),
            lambda *_a, **_kw: Result(returncode=1, stderr='PRIVATE_TOKEN_DO_NOT_PRINT'),
            lambda *_a, **_kw: (_ for _ in ()).throw(subprocess.TimeoutExpired('docker',15)),
            lambda *_a, **_kw: (_ for _ in ()).throw(OSError('PRIVATE_TOKEN_DO_NOT_PRINT')),
        ):
            value=inspect('spatial-minio',runner)
            self.assertNotEqual(value['status'],'manifest_bytes_verified')
            self.assertFalse(value['raw_manifest_digest_verified'])
            self.assertFalse(value['recovery_approved'])
            self.assertNotIn('PRIVATE_TOKEN',str(value))

    def test_index_has_unique_amd64_descriptor_but_not_runtime_proof(self):
        index={'mediaType':'application/vnd.oci.image.index.v1+json',
               'schemaVersion':2, 'manifests':[
                   {'digest':'sha256:'+'a'*64,'platform':{'os':'linux','architecture':'amd64'}},
                   {'digest':'sha256:'+'b'*64,'platform':{'os':'linux','architecture':'arm64'}},
               ]}
        value=inspect('spatial-minio',metadata_runner(index))
        self.assertEqual(value['status'],'manifest_bytes_verified')
        self.assertTrue(value['linux_amd64_descriptor_observed'])
        self.assertEqual(value['linux_amd64_manifest_digest'],'sha256:'+'a'*64)
        self.assertFalse(value['architecture_verified'])
        self.assertFalse(value['recovery_approved'])
        index['manifests'].append({'digest':'sha256:'+'c'*64,'platform':{'os':'linux','architecture':'amd64'}})
        ambiguous=inspect('spatial-minio',metadata_runner(index))
        self.assertTrue(ambiguous['raw_manifest_digest_verified'])
        self.assertFalse(ambiguous['linux_amd64_descriptor_observed'])

    def test_malformed_raw_json_and_digest_never_create_approval(self):
        for document in ({},[],{'mediaType':'unexpected','digest':'sha256:'+'f'*64}):
            if isinstance(document,dict):
                value=inspect('spatial-postgres',metadata_runner(document))
                self.assertNotEqual(value['status'],'manifest_bytes_verified')
        def runner(args, **kwargs):
            if '--raw' in args:return Result(stdout=b'not JSON')
            return Result(stdout=json.dumps({'mediaType':SINGLE['mediaType'],
                                             'digest':'sha256:'+hashlib.sha256(b'not JSON').hexdigest()}))
        self.assertFalse(inspect('spatial-postgres',runner)['raw_manifest_digest_verified'])

    def test_overlarge_raw_manifest_rejected_before_parsing(self):
        def runner(args, **kwargs):
            if '--raw' in args:return Result(stdout=b'X'*131073)
            return Result(stdout=json.dumps({'mediaType':SINGLE['mediaType'],
                                              'digest':'sha256:'+'a'*64}))
        value=inspect('spatial-postgres',runner)
        self.assertFalse(value['raw_manifest_digest_verified'])


if __name__=='__main__':unittest.main()
