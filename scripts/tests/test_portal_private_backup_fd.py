"""Extra negative controls for private REAL-backup receipt and archive inputs.

Synthetic bytes only: no Docker, SSH, production backup bytes or keys.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import tarfile
import unittest

from scripts.portal_state_restore_rehearsal import (
    SOURCE, archive_digest, checked_extract, load_receipt, _open_private_backup_file,
)


def fixture(folder):
    root=Path(folder)
    dump=root/"postgresql.custom"
    dump.write_bytes(b"PGDMP synthetic no production records")
    dump.chmod(0o600)
    tarpath=root/"minio-raw-live.tar"
    with tarfile.open(tarpath,"w") as tar:
        for key,body in (("data/one.txt",b"synthetic1"),("data/two.txt",b"synthetic2")):
            entry=tarfile.TarInfo(key)
            entry.size=len(body)
            tar.addfile(entry,io.BytesIO(body))
    tarpath.chmod(0o600)
    record={
        "schema":1,"source_staging_sha":SOURCE,
        "postgres_logical_dump_sha256":hashlib.sha256(dump.read_bytes()).hexdigest(),
        "postgres_dump_bytes":dump.stat().st_size,
        "postgres_archive_toc_parsed":True,
        "minio_live_raw_copy_sha256":hashlib.sha256(tarpath.read_bytes()).hexdigest(),
        "minio_copy_bytes":tarpath.stat().st_size,
        "minio_archive_members_checked":2,
        "minio_payload_bytes_inspected":20,
        "postgres_database_restore_rehearsed":False,
        "minio_s3_level_restore_rehearsed":False,
        "minio_point_in_time_consistency_verified":False,
        "external_independent_custody_verified":False,
        "production_containers_changed":False,
        "production_volumes_written":False,
        "safe_to_cutover":False,
    }
    receipt=root/"snapshot-receipt.json"
    receipt.write_text(json.dumps(record,sort_keys=True)+"\n")
    receipt.chmod(0o600)
    return record,receipt,dump,tarpath


class PrivateBackupReceiptSafetyTests(unittest.TestCase):
    def test_valid_private_receipt_rehashes_both_real_input_classes(self):
        with tempfile.TemporaryDirectory() as path:
            expected,receipt,dump,tarpath=fixture(path)
            self.assertEqual(load_receipt(Path(path)),expected)
            with tempfile.TemporaryDirectory() as restored:
                destination=checked_extract(tarpath,Path(restored),
                    expected=expected["minio_live_raw_copy_sha256"],
                    expected_bytes=expected["minio_copy_bytes"])
                self.assertEqual((destination/"one.txt").read_bytes(),b"synthetic1")

    def test_duplicate_receipt_fields_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            record,receipt,*_=fixture(folder)
            raw=receipt.read_text()
            receipt.write_text(raw.replace('"schema": 1,', '"schema": 1, "schema": 1,',1))
            with self.assertRaisesRegex(ValueError,"duplicate"):
                load_receipt(Path(folder))

    def test_mismatched_archive_size_fails_even_when_digest_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            record,receipt,dump,tarpath=fixture(folder)
            record["minio_copy_bytes"]+=1
            receipt.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,"size mismatch"):
                load_receipt(Path(folder))

    def test_attested_backup_bytes_must_be_int_not_bool(self):
        with tempfile.TemporaryDirectory() as folder:
            record,receipt,dump,tarpath=fixture(folder)
            record["postgres_dump_bytes"]=True
            receipt.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,"length"):
                load_receipt(Path(folder))
            record["postgres_dump_bytes"]=dump.stat().st_size
            record["minio_archive_members_checked"]=True
            receipt.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,"untrusted backup receipt"):
                load_receipt(Path(folder))

    def test_claimed_restore_or_production_writes_rejected(self):
        for attr in ("postgres_database_restore_rehearsed",
                     "minio_s3_level_restore_rehearsed",
                     "minio_point_in_time_consistency_verified",
                     "external_independent_custody_verified",
                     "production_containers_changed",
                     "production_volumes_written", "safe_to_cutover"):
            with self.subTest(flag=attr),tempfile.TemporaryDirectory() as folder:
                record,receipt,*_=fixture(folder)
                record[attr]=True
                receipt.write_text(json.dumps(record))
                with self.assertRaises(ValueError):
                    load_receipt(Path(folder))

    def test_symlink_and_hardlink_special_file_fail_without_reading(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            record,receipt,dump,tarpath=fixture(folder)
            backup=root/"saved-dump"
            dump.rename(backup)
            dump.symlink_to(backup)
            with self.assertRaises(OSError):
                archive_digest(dump,record["postgres_logical_dump_sha256"])
            dump.unlink()
            os.mkfifo(dump,0o600)
            with self.assertRaisesRegex(ValueError,"untrusted backup file"):
                archive_digest(dump,record["postgres_logical_dump_sha256"])
            dump.unlink()
            os.link(backup,dump)
            with self.assertRaisesRegex(ValueError,"hardlink"):
                archive_digest(dump,record["postgres_logical_dump_sha256"])

    def test_world_readable_receipt_archive_and_directory_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            record,receipt,dump,tarpath=fixture(folder)
            receipt.chmod(0o644)
            with self.assertRaisesRegex(ValueError,"mode"):
                load_receipt(root)
            receipt.chmod(0o600)
            dump.chmod(0o644)
            with self.assertRaisesRegex(ValueError,"mode"):
                load_receipt(root)
            dump.chmod(0o600)
            root.chmod(0o755)
            with self.assertRaisesRegex(ValueError,"directory"):
                load_receipt(root)
            root.chmod(0o700)

    def test_synthetic_tar_tamper_rejected_on_same_fd_before_extract(self):
        with tempfile.TemporaryDirectory() as folder:
            record,receipt,dump,tarpath=fixture(folder)
            tarpath.write_bytes(tarpath.read_bytes()+b"changed")
            with tempfile.TemporaryDirectory() as restore:
                with self.assertRaisesRegex(ValueError,"size mismatch"):
                    checked_extract(tarpath,Path(restore),
                      expected=record["minio_live_raw_copy_sha256"],
                      expected_bytes=record["minio_copy_bytes"])

    def test_oversized_receipt_not_parsed(self):
        with tempfile.TemporaryDirectory() as folder:
            record,receipt,*_=fixture(folder)
            receipt.write_bytes(b" "*65537)
            with self.assertRaisesRegex(ValueError,"oversized"):
                load_receipt(Path(folder))

    def test_hash_after_opened_file_rejects_wrong_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            record,receipt,dump,tarpath=fixture(folder)
            with self.assertRaisesRegex(ValueError,"changed"):
                archive_digest(dump,"0"*64,
                               expected_bytes=record["postgres_dump_bytes"])
            archive_digest(dump,record["postgres_logical_dump_sha256"],
                           expected_bytes=record["postgres_dump_bytes"])


if __name__=="__main__":
    unittest.main()
