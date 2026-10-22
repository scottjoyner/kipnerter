import copy
import hashlib
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts import portal_storage_candidate_witness as mod


def encoded(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def digest(blob):
    return "sha256:" + hashlib.sha256(blob).hexdigest()


CHILD = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
         "config": {"mediaType": "application/vnd.oci.image.config.v1+json",
                    "digest": "sha256:" + "a" * 64, "size": 256},
         "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                     "digest": "sha256:" + "b" * 64, "size": 512}]}
CHILD_BYTES = encoded(CHILD)


def fixture(*, duplicate=False, bad_index=False, bad_child=False,
            missing_arch=False, fail=False, large=False, duplicates=False,
            bad_child_size=False, config_malformed=False, bad_config_size=False,
            bad_layer=False, empty_layers=False, boolean_descriptor_size=False):
    child = copy.deepcopy(CHILD)
    if config_malformed:
        child["config"].pop("mediaType")
    if bad_config_size:
        child["config"]["size"] = -5
    if bad_layer:
        child["layers"][0]["digest"] = "sha256:not-a-digest"
    if empty_layers:
        child["layers"] = []
    child_bytes = encoded(child)
    descriptor = {"mediaType": child["mediaType"], "digest": digest(child_bytes),
                  "size": len(child_bytes),
                  "platform": {"os": "linux", "architecture": "amd64"}}
    if bad_child_size:
        descriptor["size"] += 1
    if boolean_descriptor_size:
        descriptor["size"] = True
    index = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json",
             "manifests": ([descriptor, descriptor] if duplicate else
                           [{**descriptor, "platform": {"os": "linux", "architecture": "arm64"}}]
                           if missing_arch else [descriptor])}
    raw_index = encoded(index)
    pin = hashlib.sha256(raw_index).hexdigest()
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        assert args[:4] == ["docker", "buildx", "imagetools", "inspect"]
        assert kwargs == {"capture_output": True, "check": False, "timeout": 15}
        class Response:
            returncode = 1 if fail else 0
            stdout = b""
        result = Response()
        if args[-2:] == ["--format", "{{json .Manifest}}"]:
            metadata = {"mediaType": index["mediaType"], "digest":
                        "sha256:" + ("f" * 64 if bad_index else pin)}
            result.stdout = encoded(metadata)
        elif args[-1:] == ["--raw"] and len(calls) == 2:
            result.stdout = (b"X" * 131073 if large else
                             raw_index + b"X" if bad_index else
                             raw_index.replace(b'"schemaVersion"', b'"schemaVersion":0,"schemaVersion"')
                             if duplicates else raw_index)
        else:
            result.stdout = child_bytes + b"X" if bad_child else child_bytes
        return result

    return pin, runner, calls


class StorageResearchWitnessTests(unittest.TestCase):
    def inspect_fixture(self, **flags):
        pin, runner, calls = fixture(**flags)
        with patch.dict(mod.CANDIDATES, {"silo": ("docker.io/pgsty/silo", pin)}):
            receipt = mod.witness("silo", runner)
        return receipt, calls, pin

    def test_verified_index_and_amd64_child_still_not_release_approval(self):
        record, calls, pinned = self.inspect_fixture()
        self.assertEqual(record["status"], "immutable_manifest_tree_verified")
        self.assertTrue(record["index_digest_verified"])
        self.assertTrue(record["linux_amd64_descriptor_observed"])
        self.assertTrue(record["linux_amd64_child_manifest_bytes_verified"])
        self.assertTrue(record["child_descriptor_size_verified"])
        self.assertTrue(record["config_descriptor_shape_verified"])
        self.assertTrue(record["layer_descriptors_shape_verified"])
        self.assertEqual(record["child_digest"], digest(CHILD_BYTES))
        for flag in ("production_approved", "restore_parity_verified",
                     "architecture_runtime_verified", "independent_custody_verified",
                     "layers_downloaded"):
            self.assertFalse(record[flag])
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][4], "docker.io/pgsty/silo@sha256:" + pinned)
        self.assertEqual(calls[2][4], "docker.io/pgsty/silo@" + digest(CHILD_BYTES))
        self.assertTrue(all("--raw" in call or "--format" in call for call in calls))

    def test_refuses_unknown_candidate_and_user_supplied_image(self):
        with self.assertRaises(ValueError):
            mod.witness("https://untrusted.example/image")
        with self.assertRaises(ValueError):
            mod.witness("minio/minio:latest")

    def test_wrong_or_modified_index_is_never_valid(self):
        for flag in ("bad_index", "large", "duplicates"):
            receipt, _, _ = self.inspect_fixture(**{flag: True})
            self.assertNotEqual(receipt["status"], "immutable_manifest_tree_verified")
            self.assertFalse(receipt["production_approved"])

    def test_wrong_child_digest_rejected(self):
        receipt, _, _ = self.inspect_fixture(bad_child=True)
        self.assertTrue(receipt["index_digest_verified"])
        self.assertFalse(receipt["linux_amd64_child_manifest_bytes_verified"])
        self.assertFalse(receipt["production_approved"])

    def test_child_size_mismatch_or_noninteger_size_rejected(self):
        for flag in ("bad_child_size", "boolean_descriptor_size"):
            record, _, _ = self.inspect_fixture(**{flag: True})
            self.assertNotEqual(record["status"], "immutable_manifest_tree_verified")
            self.assertFalse(record["production_approved"])
            self.assertFalse(record["child_descriptor_size_verified"])

    def test_invalid_config_and_layer_descriptors_rejected_even_with_valid_hashes(self):
        for flag in ("config_malformed", "bad_config_size", "bad_layer", "empty_layers"):
            record, _, _ = self.inspect_fixture(**{flag: True})
            self.assertNotEqual(record["status"], "immutable_manifest_tree_verified")
            self.assertTrue(record["index_digest_verified"])
            self.assertTrue(record["child_descriptor_size_verified"])
            self.assertFalse(record["linux_amd64_child_manifest_bytes_verified"])
            self.assertFalse(record["production_approved"])
            self.assertFalse(record["layers_downloaded"])

    def test_duplicate_or_missing_amd64_descriptor_rejected(self):
        for flag in ("duplicate", "missing_arch"):
            receipt, _, _ = self.inspect_fixture(**{flag: True})
            self.assertTrue(receipt["index_digest_verified"])
            self.assertFalse(receipt["linux_amd64_descriptor_observed"])
            self.assertFalse(receipt["production_approved"])

    def test_error_receipt_never_leaks_registry_output(self):
        receipt, _, _ = self.inspect_fixture(fail=True)
        self.assertEqual(receipt["status"], "unavailable")
        self.assertNotIn("PRIVATE_TOKEN", json.dumps(receipt))
        self.assertFalse(receipt["production_approved"])

    def test_subprocess_failure_never_claims_success(self):
        def throws(*args, **kwargs):
            raise subprocess.TimeoutExpired("docker", 15)
        self.assertEqual(mod.witness("silo", throws)["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
