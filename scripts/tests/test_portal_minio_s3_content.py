"""Bounded, local-only S3 byte-parity negative tests (no production calls)."""
import hashlib
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts.portal_minio_s3_parity import (
    BUCKET, MAX_OBJECTS, content_inventory, listed_objects,
    streamed_object_sha,
)

def line(**item):
    return json.dumps(item)+"\n"

class MinioObjectBodySafetyTests(unittest.TestCase):
    def test_two_object_listing_is_bounded_and_private(self):
        roots=line(type="folder",key=BUCKET+"/")
        objects=line(type="file",key="user/alpha",size=3,etag="x")+line(
            type="file",key="user/beta",size=2,etag="y")
        with patch("scripts.portal_minio_s3_parity.run",side_effect=[roots,objects]):
            rows=listed_objects("synthetic-container")
        self.assertEqual(rows,[("user/alpha",3),("user/beta",2)])

    def test_duplicate_object_key_denied(self):
        roots=line(type="folder",key=BUCKET+"/")
        objects=line(type="file",key="one",size=1)+line(type="file",key="one",size=1)
        with patch("scripts.portal_minio_s3_parity.run",side_effect=[roots,objects]):
            with self.assertRaisesRegex(ValueError,"untrusted"):
                listed_objects("synthetic-container")

    def test_size_limit_rejects_before_any_content_call(self):
        roots=line(type="folder",key=BUCKET+"/")
        objects=line(type="file",key="giant",size=1024*1024*1024)
        with patch("scripts.portal_minio_s3_parity.run",side_effect=[roots,objects]):
            with self.assertRaisesRegex(ValueError,"oversized"):
                listed_objects("synthetic-container")

    def test_too_many_objects_rejected(self):
        roots=line(type="folder",key=BUCKET+"/")
        objects="".join(line(type="file",key=f"n{i}",size=1)
                        for i in range(MAX_OBJECTS+1))
        with patch("scripts.portal_minio_s3_parity.run",side_effect=[roots,objects]):
            with self.assertRaisesRegex(ValueError,"limit exceeded"):
                listed_objects("synthetic-container")

    def test_object_key_is_shell_argument_not_command_text(self):
        saved=subprocess.Popen
        key="private/user data; echo NEVER_EXECUTE"
        called=[]
        def spawn(argv,**kwargs):
            called.append(argv)
            return saved([sys.executable,"-c",
                         "import sys;sys.stdout.buffer.write(b'abc')"],**kwargs)
        with patch("scripts.portal_minio_s3_parity.subprocess.Popen",side_effect=spawn):
            digest=streamed_object_sha("fake",key,3)
        self.assertEqual(digest,hashlib.sha256(b"abc").hexdigest())
        self.assertEqual(called[0][-1],"release/"+BUCKET+"/"+key)
        self.assertNotIn(key,called[0][-3])

    def test_more_content_than_advertised_fails_closed(self):
        saved=subprocess.Popen
        def spawn(argv,**kwargs):
            return saved([sys.executable,"-c",
                         "import sys;sys.stdout.buffer.write(b'abcd')"],**kwargs)
        with patch("scripts.portal_minio_s3_parity.subprocess.Popen",side_effect=spawn):
            with self.assertRaisesRegex(ValueError,"changed size"):
                streamed_object_sha("fake","private",3)

    def test_content_parity_detects_byte_change_without_emitting_keys(self):
        with patch("scripts.portal_minio_s3_parity.listed_objects",
                   return_value=[("private-name",3)]):
            with patch("scripts.portal_minio_s3_parity.streamed_object_sha",
                       return_value=hashlib.sha256(b"ABC").hexdigest()):
                original=content_inventory("fake")
            with patch("scripts.portal_minio_s3_parity.streamed_object_sha",
                       return_value=hashlib.sha256(b"ABD").hexdigest()):
                changed=content_inventory("fake")
        self.assertNotEqual(original,changed)
        self.assertNotIn("private-name",str(original))
        self.assertNotIn("ABC",str(original))

if __name__=="__main__":
    unittest.main()
