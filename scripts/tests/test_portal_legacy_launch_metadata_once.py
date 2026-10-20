"""Synthetic-only negative controls for private legacy launch-metadata custody."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from scripts import portal_legacy_launch_metadata_once as m

class LaunchMetadataOnceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)/"backup"
        self.base.mkdir(mode=0o700)
        rows=[]
        for role,(ref,image) in m.ROLES.items():
            p=self.base/("legacy-rootfs-before-17-20261019-"+role+".tar")
            p.write_bytes(b"synthetic-empty-test-rootfs")
            p.chmod(0o600)
            rows.append({"role":role,"source_image":image,"rootfs_tar_bytes":p.stat().st_size,
                         "rootfs_tar_sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
        receipt={"schema":1,"rootfs_files_created":True,"safe_to_cutover":False,
                 "legacy_container_images_recovered":False,
                 "runnable_rollback_verified":False,"roles":rows}
        q=self.base/m.ROOTFS_RECEIPT
        q.write_text(json.dumps(receipt))
        q.chmod(0o600)

    def fixture(self,role):
        ref,image=m.ROLES[role]
        return {"Name":"/"+role,"Image":image,
            "Config":{"Image":ref,"Labels":{"com.docker.compose.project":"kipnerter"},
                      "Entrypoint":["/usr/bin/node"],"Cmd":["app.js"],
                      "Env":["APP_SECRET=synthetic-value-not-for-logs"],
                      "WorkingDir":"/app","User":"node"},
            "HostConfig":{"NetworkMode":"kipnerter_default","PortBindings":{}},
            "State":{"Running":True,"StartedAt":"2026-08-17T17:14:43Z"},
            "Mounts":[]}

    def test_original_identity_and_private_config_capture(self):
        role=next(iter(m.ROLES))
        selected=m.extract_launch_metadata(self.fixture(role),role)
        self.assertEqual(selected["source_ref"],m.ROLES[role][0])
        self.assertEqual(selected["environment_names_only"],["APP_SECRET"])
        self.assertNotIn("synthetic-value",json.dumps(selected))
        self.assertNotIn("app.js",json.dumps(selected))
        self.assertNotIn("APP_SECRET=",str({k:selected[k] for k in ("role","image_id")}))
        changed=self.fixture(role);changed["Mounts"]=[{"Source":"/unknown"}]
        with self.assertRaises(ValueError):m.extract_launch_metadata(changed,role)
        changed=self.fixture(role);changed["Image"]="sha256:"+"a"*64
        with self.assertRaises(ValueError):m.extract_launch_metadata(changed,role)
        changed=self.fixture(role);changed["State"]["Running"]=False
        with self.assertRaises(ValueError):m.extract_launch_metadata(changed,role)

    def test_private_snapshot_and_digest_no_public_content(self):
        snapshots=[m.extract_launch_metadata(self.fixture(role),role) for role in m.ROLES]
        with patch.object(m,"inspect_one",side_effect=snapshots+snapshots):
            result=m.evidence(self.base)
        self.assertTrue(result["metadata_receipt_saved"])
        self.assertFalse(result["safe_to_cutover"])
        self.assertNotIn("synthetic-value",str(result))
        data=(self.base/m.TARGET).read_bytes()
        self.assertNotIn(b"synthetic-value",data)
        self.assertNotIn(b"app.js",data)
        receipt=json.loads((self.base/m.RECEIPT).read_text())
        self.assertEqual(receipt["metadata_file_sha256"],hashlib.sha256(data).hexdigest())
        self.assertFalse(receipt["runnable_rollback_verified"])
        self.assertEqual(stat.S_IMODE((self.base/m.TARGET).stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE((self.base/m.RECEIPT).stat().st_mode),0o600)
        with patch.object(m,"inspect_one",side_effect=AssertionError("must not inspect")):
            with self.assertRaisesRegex(ValueError,"one-shot"):
                m.evidence(self.base)

    def test_duplicate_json_fields_rejected(self):
        with self.assertRaisesRegex(ValueError,"ambiguous"):
            json.loads('{"schema":1,"schema":2}',object_pairs_hook=m.no_duplicate_json_pairs)

    def test_changed_live_container_between_reads_denied(self):
        before=[m.extract_launch_metadata(self.fixture(role),role) for role in m.ROLES]
        after=json.loads(json.dumps(before))
        after[0]["started_at"]="2026-10-20T00:00:00Z"
        with patch.object(m,"inspect_one",side_effect=before+after):
            with self.assertRaisesRegex(ValueError,"changed during"):
                m.evidence(self.base)
        self.assertFalse((self.base/m.TARGET).exists())

    def test_world_readable_directory_denied(self):
        self.base.chmod(0o755)
        with self.assertRaisesRegex(ValueError,"0700"):m.evidence(self.base)

    def test_existing_incomplete_file_rejected(self):
        (self.base/".launch-metadata-incomplete-deadbeef").write_text("partial")
        with self.assertRaisesRegex(ValueError,"one-shot"):m.evidence(self.base)

    def test_corrupt_rootfs_archive_denied_even_when_size_unchanged(self):
        role=next(iter(m.ROLES))
        tar=self.base/("legacy-rootfs-before-17-20261019-"+role+".tar")
        buf=bytearray(tar.read_bytes());buf[-1] ^= 1;tar.write_bytes(buf)
        with self.assertRaisesRegex(ValueError,"checksum mismatch"):
            m.evidence(self.base)

    def test_rootfs_receipt_must_not_claim_rollback(self):
        p=self.base/m.ROOTFS_RECEIPT
        data=json.loads(p.read_text());data["safe_to_cutover"]=True
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,"invalid original"):
            m.evidence(self.base)

    def test_metadata_probe_refuses_non_list_inspect(self):
        role=next(iter(m.ROLES))
        class Result:stdout=b'{"Name":"/broken"}'
        with patch.object(m.subprocess,"run",return_value=Result()):
            with self.assertRaisesRegex(ValueError,"ambiguous Docker"):
                m.inspect_one(role)

if __name__ == "__main__":unittest.main()
