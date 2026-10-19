import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.portal_state_restore_rehearsal import (
    archive_digest, load_receipt, checked_extract, SOURCE,
)


class ScratchRestoreSafetyTests(unittest.TestCase):
    def tar(self, root, name="data/a.txt"):
        path=root/"minio-raw-live.tar"
        with tarfile.open(path,"w") as archive:
            for member in (name, "data/b.txt"):
                item=tarfile.TarInfo(member)
                item.size=1
                archive.addfile(item,io.BytesIO(b"a"))
        return path

    def test_digest_accepts_exact_bytes_only(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"dump"
            path.write_bytes(b"fixture")
            expected=hashlib.sha256(b"fixture").hexdigest()
            archive_digest(path,expected)
            path.write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError,"changed"):
                archive_digest(path,expected)

    def test_digest_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/"safe").write_bytes(b"fixture")
            (p/"link").symlink_to(p/"safe")
            with self.assertRaisesRegex(ValueError,"untrusted"):
                archive_digest(p/"link","a"*64)

    def test_receipt_rejects_wrong_source(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            (p/"snapshot-receipt.json").write_text(json.dumps({
                "schema":1,"source_staging_sha":"a"*40,
                "postgres_archive_toc_parsed":True,"safe_to_cutover":False}))
            with self.assertRaisesRegex(ValueError,"does not match"):
                load_receipt(p)

    def test_safe_raw_archive_extracts_only_inside_scratch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            tar=self.tar(root)
            target=root/"restored";target.mkdir()
            path=checked_extract(tar,target)
            self.assertEqual(path,(target/"data"))
            self.assertEqual((path/"a.txt").read_bytes(),b"a")

    def test_traversal_archive_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            tar=self.tar(root,name="../../etc/passwd")
            target=root/"restore";target.mkdir()
            with self.assertRaisesRegex(ValueError,"unsafe"):
                checked_extract(tar,target)

    def test_missing_restored_directory_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            tar=self.tar(root,name="other/a.txt")
            with tarfile.open(tar,"w") as handle:
                for p in ("other/a.txt","other/b.txt"):
                    i=tarfile.TarInfo(p);i.size=1
                    handle.addfile(i,io.BytesIO(b"x"))
            target=root/"restore";target.mkdir()
            with self.assertRaisesRegex(ValueError,"MinIO directory"):
                checked_extract(tar,target)


if __name__=="__main__":
    unittest.main()
