import hashlib
import io
import json
import os
from unittest import mock
import tarfile
from pathlib import Path
import tempfile
import unittest

from scripts.portal_minio_s3_parity import (
    summarize, json_lines, extract, backup_checked, BUCKET, SOURCE,
)


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

    @staticmethod
    def _archive(path, entries):
        with tarfile.open(path, "w") as store:
            for name, body in entries:
                member = tarfile.TarInfo(name)
                member.size = len(body)
                store.addfile(member, io.BytesIO(body))

    def test_rejects_outside_data_namespace_and_duplicate_member(self):
        for items in (
            [("other/not-minio", b"x"), ("data/valid", b"x")],
            [("data/one", b"x"), ("data/one", b"y")],
            [("data/one", b"x"), ("data/../escape", b"y")],
            [("data/one", b"x"), ("data/./other", b"y")],
        ):
            with self.subTest(names=[x[0] for x in items]), tempfile.TemporaryDirectory() as d:
                base = Path(d)
                archive = base / "copy.tar"
                self._archive(archive, items)
                dest = base / "scratch"
                dest.mkdir()
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    extract(archive, dest)
                self.assertEqual(list(dest.iterdir()), [])

    def test_rejects_oversized_declared_expansion_before_write(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            archive = base / "copy.tar"
            self._archive(archive, [("data/one", b"ab"), ("data/two", b"cd")])
            dest = base / "scratch"
            dest.mkdir()
            with mock.patch("scripts.portal_minio_s3_parity.MAX_EXTRACT_BYTES", 3):
                with self.assertRaisesRegex(ValueError, "expansion exceeds bound"):
                    extract(archive, dest)
            self.assertEqual(list(dest.iterdir()), [])

    def test_refuses_nonempty_scratch_root_and_capacity_shortfall(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            archive = base / "copy.tar"
            self._archive(archive, [("data/one", b"abc"), ("data/two", b"def")])
            dest = base / "scratch"
            dest.mkdir()
            (dest / "untrusted.txt").write_text("old")
            with self.assertRaisesRegex(ValueError, "nonempty"):
                extract(archive, dest)
            (dest / "untrusted.txt").unlink()
            with mock.patch("scripts.portal_minio_s3_parity.MIN_SPARE_BYTES", 10**18):
                with self.assertRaisesRegex(ValueError, "capacity"):
                    extract(archive, dest)
            self.assertEqual(list(dest.iterdir()), [])

    def test_valid_private_tar_extracts_into_only_data_tree(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            archive = base / "copy.tar"
            self._archive(archive, [("data/first", b"abc"), ("data/second", b"xyz")])
            dest = base / "empty"
            dest.mkdir()
            output = extract(archive, dest)
            self.assertEqual(output, dest / "data")
            self.assertEqual((output / "first").read_bytes(), b"abc")
            self.assertEqual((output / "second").read_bytes(), b"xyz")
            self.assertEqual(sorted(x.name for x in dest.iterdir()), ["data"])

    def test_exact_private_receipt_and_archive_required(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            archive = base / "minio-raw-live.tar"
            self._archive(archive, [("data/one", b"abc"), ("data/two", b"def")])
            archive.chmod(0o600)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            record = {
                "schema": 1, "source_staging_sha": SOURCE,
                "safe_to_cutover": False,
                "minio_s3_level_restore_rehearsed": False,
                "minio_live_raw_copy_sha256": digest,
                "minio_copy_bytes": archive.stat().st_size,
            }
            receipt = base / "snapshot-receipt.json"
            receipt.write_text(json.dumps(record))
            receipt.chmod(0o600)
            self.assertEqual(backup_checked(base), archive)
            receipt.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "untrusted private"):
                backup_checked(base)
            receipt.chmod(0o600)
            record["minio_copy_bytes"] -= 1
            receipt.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "length drift"):
                backup_checked(base)

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
