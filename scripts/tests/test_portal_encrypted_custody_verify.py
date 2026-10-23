"""Offline controls for fixed-receipt encrypted recovery verification.

No production, no Tailnet or cloud API; mock every external command.
"""
from __future__ import annotations
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import portal_encrypted_custody_verify as m


class EncryptedCustodyControls(unittest.TestCase):
    def test_pinned_non_atomic_default(self):
        self.assertTrue(m.ID.startswith("20261023T"))
        self.assertEqual(m.REMOTE, ".local/state/kipnerter-private-backups/" + m.ID)
        self.assertEqual(len(m.MANIFEST_SHA), 64)
        self.assertEqual(len(m.SIGNATURE_SHA), 64)

    def test_remote_hashes_rejects_invalid_inventory(self):
        for value in (b'{}', b'[]', b'{"postgresql.cms":"f"}'):
            with self.subTest(value=value), patch.object(m.subprocess, "run") as proc:
                proc.return_value.stdout = value
                with self.assertRaises((ValueError, TypeError)):
                    m.remote_ciphertext_hashes()

    def test_remote_hash_lookup_uses_fixed_host_and_read_only_stdin(self):
        content=json.dumps({"postgresql.cms":m.PG_CIPHER_SHA,
            "minio.cms":m.MINIO_CIPHER_SHA,"manifest.json":m.MANIFEST_SHA}).encode()
        with patch.object(m.subprocess, "run") as proc:
            proc.return_value.stdout=content
            result=m.remote_ciphertext_hashes()
        self.assertEqual(result["postgresql.cms"],m.PG_CIPHER_SHA)
        args=proc.call_args.args[0]
        self.assertEqual(args[-2:],["xwing","python3 -"])
        script=proc.call_args.kwargs["input"].decode()
        self.assertNotIn("docker ",script)
        self.assertNotIn("sudo ",script)
        self.assertNotIn("rm -",script)
        self.assertIn("stat().st_mode",script)

    def test_cipher_digest_drift_denied_before_public_crypto(self):
        bad={"postgresql.cms":"0"*64,"minio.cms":m.MINIO_CIPHER_SHA,
             "manifest.json":m.MANIFEST_SHA}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);root.chmod(0o700)
            with patch.object(m,"ROOT",root), patch.object(m,"remote_ciphertext_hashes",return_value=bad),patch.object(m,"verify_public_certificate",side_effect=AssertionError("unexpected")):
                with self.assertRaises(ValueError) as caught:
                    m.verified()
                self.assertIn("stored ciphertext",str(caught.exception))

    def test_invalid_public_cert_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            p=root/"lenovo-cert.pem"
            p.write_text("untrusted data")
            p.chmod(0o600)
            with patch.object(m,"ROOT",root),patch.object(m,"run",return_value=b"fake-cert-der"):
                with self.assertRaises(ValueError):
                    m.verify_public_certificate()

    def test_unavailable_backup_produces_failed_closed_private_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            root.chmod(0o700)
            output=io.StringIO()
            with patch.object(m,"ROOT",root),patch.object(m,"verified",side_effect=ValueError("untrusted file")),redirect_stdout(output):
                status=m.main()
            self.assertEqual(status,3)
            report=json.loads(output.getvalue())
            self.assertEqual(report["classification"],"CHECK_REQUIRED")
            self.assertEqual(report["release_gate"],"NO_GO")
            self.assertFalse(report["safe_to_cutover"])
            self.assertEqual(report["failure_class"],"ValueError")
            self.assertEqual((root/"status.json").stat().st_mode & 0o077,0)
            self.assertNotIn("untrusted file",(root/"status.json").read_text())

    def test_successful_backup_still_denies_production(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            root.chmod(0o700)
            verified={"classification":"SIGNED_ENCRYPTED_COPY_VERIFIED_NOT_ATOMIC",
                "receipt_id":m.ID,"ciphertext_sha256_verified":True,
                "manifest_signature_verified":True,"remote_keys_present_and_private":True,
                "independent_administrative_custody":False,
                "cross_service_point_in_time_consistent":False,
                "safe_to_cutover":False,"release_gate":"NO_GO"}
            with patch.object(m,"ROOT",root),patch.object(m,"verified",return_value=verified),redirect_stdout(io.StringIO()):
                status=m.main()
            self.assertEqual(status,0)
            actual=json.loads((root/"status.json").read_text())
            self.assertFalse(actual["safe_to_cutover"])
            self.assertFalse(actual["independent_administrative_custody"])
            self.assertEqual(actual["release_gate"],"NO_GO")

    def test_no_secret_values_in_signed_receipt_projection(self):
        keys=("SIGNATURE_SHA","MANIFEST_SHA","PG_CIPHER_SHA","MINIO_CIPHER_SHA")
        for key in keys:
            self.assertEqual(len(getattr(m,key)),64)
        self.assertNotIn("TS_AUTHKEY",m.__doc__)
        self.assertNotIn("DIGITALOCEAN_ACCESS_TOKEN",m.__doc__)


if __name__=="__main__":
    unittest.main()
