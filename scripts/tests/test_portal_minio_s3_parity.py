import io
import json
import tarfile
from pathlib import Path
import tempfile
import unittest

from scripts.portal_minio_s3_parity import summarize,json_lines,extract,BUCKET


def record(**kw):
    return json.dumps(kw) + "\n"


class MinioS3ParityTests(unittest.TestCase):
    def test_same_bucket_object_metadata_is_deterministic(self):
        buckets=record(type="folder",key=BUCKET+"/")
        objects=record(type="file",key="one",size=12,etag="abc")+record(type="file",key="two",size=8,etag="def")
        a=summarize(buckets,objects)
        b=summarize(buckets,record(type="file",key="two",size=8,etag="def")+record(type="file",key="one",size=12,etag="abc"))
        self.assertEqual(a,b)
        self.assertEqual(a[1],2)
        self.assertNotIn("one",str(a))

    def test_changed_etag_or_object_missing_is_detected(self):
        bucket=record(type="folder",key=BUCKET+"/")
        original=summarize(bucket,record(type="file",key="sensitive",size=5,etag="one"))
        changed=summarize(bucket,record(type="file",key="sensitive",size=5,etag="two"))
        missing=summarize(bucket,"")
        self.assertNotEqual(original,changed)
        self.assertNotEqual(original,missing)

    def test_absent_bucket_does_not_invent_data(self):
        result=summarize("", "")
        self.assertEqual(result[0:2],(False,0))

    def test_unbound_object_listing_rejected(self):
        with self.assertRaisesRegex(ValueError,"without bucket"):
            summarize("",record(type="file",key="private",size=1,etag="x"))

    def test_error_record_never_counted_as_object(self):
        with self.assertRaisesRegex(ValueError,"untrusted"):
            json_lines(record(status="error",error={"code":"AccessDenied"}))

    def test_reject_tar_traversal_before_extract(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            archive=root/"payload.tar"
            with tarfile.open(archive,"w") as t:
                entry=tarfile.TarInfo("../../etc/passwd")
                entry.size=1
                t.addfile(entry,io.BytesIO(b"x"))
                other=tarfile.TarInfo("data/healthy")
                other.size=1
                t.addfile(other,io.BytesIO(b"x"))
            dest=root/"scratch";dest.mkdir()
            with self.assertRaisesRegex(ValueError,"unsafe"):
                extract(archive,dest)


if __name__=="__main__":
    unittest.main()
