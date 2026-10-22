"""Offline synthetic OCI/Docker multiarch storage archive verification controls."""
import gzip
import hashlib
import io
import json
import tarfile
import unittest
from unittest.mock import patch

from scripts import portal_legacy_oci_archive_verify as legacy
from scripts.portal_stateful_oci_archive_verify import ROLES, check
from scripts.tests.test_portal_legacy_oci_archive_verify import build_archive, encoded


def docker_archive(*, config_change=None, manifest_change=None,
                   nested_change=None, compat_change=None, blob_change=None,
                   duplicate_amd64=False, wrong_media=False):
    payload = b"SYNTHETIC_ONLY_NOT_REAL_STORAGE_IMAGE" * 5
    layer = gzip.compress(payload, mtime=0)
    layer_digest = hashlib.sha256(layer).hexdigest()
    config = {"os": "linux", "architecture": "amd64",
              "rootfs": {"type": "layers", "diff_ids": ["sha256:" + hashlib.sha256(payload).hexdigest()]},
              "config": {"Entrypoint": ["/mock"]}}
    if config_change: config_change(config)
    config_bytes = encoded(config)
    config_digest = hashlib.sha256(config_bytes).hexdigest()
    manifest = {"schemaVersion": 2,
                "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                "config": {"mediaType": "application/vnd.docker.container.image.v1+json",
                           "digest": "sha256:" + config_digest, "size": len(config_bytes)},
                "layers": [{"mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip",
                            "digest": "sha256:" + layer_digest, "size": len(layer)}]}
    if manifest_change: manifest_change(manifest)
    manifest_bytes = encoded(manifest)
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    descriptor = {"mediaType": manifest["mediaType"],
                  "digest": "sha256:" + manifest_digest,
                  "size": len(manifest_bytes),
                  "platform": {"os": "linux", "architecture": "amd64"}}
    index = {"schemaVersion": 2,
             "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
             "manifests": [descriptor,
                           {"mediaType": manifest["mediaType"],
                            "digest": "sha256:" + "e"*64, "size": 101,
                            "platform": {"os": "linux", "architecture": "arm64"}}]}
    if duplicate_amd64: index["manifests"].append(descriptor)
    if nested_change: nested_change(index)
    index_bytes = encoded(index)
    index_digest = hashlib.sha256(index_bytes).hexdigest()
    root = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [{"mediaType": "application/vnd.docker.distribution.manifest.list.v2+json" if not wrong_media else "application/vnd.attacker.manifest.v1",
                           "digest": "sha256:" + index_digest,
                           "size": len(index_bytes)}]}
    compat = [{"Config": "blobs/sha256/" + config_digest,
               "RepoTags": ["fixture:synthetic"],
               "Layers": ["blobs/sha256/" + layer_digest]}]
    if compat_change: compat_change(compat)
    blobs = {
        "index.json": encoded(root),
        "manifest.json": encoded(compat),
        "oci-layout": encoded({"imageLayoutVersion": "1.0.0"}),
        "blobs/sha256/" + index_digest: index_bytes,
        "blobs/sha256/" + manifest_digest: manifest_bytes,
        "blobs/sha256/" + config_digest: config_bytes,
        "blobs/sha256/" + layer_digest: layer,
    }
    if blob_change: blob_change(blobs)
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for name, content in blobs.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    out.seek(0)
    return out, "sha256:" + index_digest


class StatefulArchiveSafety(unittest.TestCase):
    def test_two_pinned_roles_are_explicit_and_not_release_authorizations(self):
        self.assertEqual(set(ROLES), {"spatial-minio", "spatial-postgres"})
        self.assertTrue(all(len(s)==71 and s.startswith('sha256:') for s in ROLES.values()))

    def test_direct_oci_archive_verified_and_legacy_constants_not_changed(self):
        raw, identity, _ = build_archive(compression="gzip")
        original = legacy.MANIFEST, legacy.CONFIG
        report = check(raw, identity)
        self.assertEqual(report["status"], "OCI_CONTENT_TREE_VERIFIED_NOT_RESTORED")
        self.assertEqual((legacy.MANIFEST, legacy.CONFIG), original)
        for claim in ("registry_provenance_independent", "production_data_included",
                      "live_restore_verified", "independent_admin_custody",
                      "production_modified", "safe_to_cutover"):
            self.assertFalse(report[claim])

    def test_nested_docker_multiplatform_amd64_archive_verifies(self):
        raw, identity = docker_archive()
        original = legacy.MANIFEST, legacy.CONFIG
        report = check(raw,identity)
        self.assertTrue(report["all_included_blob_hashes_verified"])
        self.assertTrue(report["uncompressed_layer_diffids_verified"])
        self.assertEqual(report["saved_layer_count"],1)
        self.assertEqual((legacy.MANIFEST, legacy.CONFIG), original)

    def test_wrong_expected_image_rejected(self):
        raw, identity = docker_archive()
        with self.assertRaisesRegex(ValueError, "image ID"):
            check(raw, "sha256:" + "f"*64)

    def test_duplicate_amd64_platform_rejected(self):
        raw, identity = docker_archive(duplicate_amd64=True)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            check(raw, identity)

    def test_non_amd64_platform_rejected(self):
        raw, identity = docker_archive(nested_change=lambda x: x["manifests"][0]["platform"].update(architecture="arm64"))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            check(raw, identity)

    def test_unexpected_root_descriptor_media_denied(self):
        raw, identity = docker_archive(wrong_media=True)
        with self.assertRaisesRegex(ValueError, "media"):
            check(raw, identity)

    def test_config_wrong_architecture_rejected(self):
        raw, identity = docker_archive(config_change=lambda x: x.update(architecture="arm64"))
        with self.assertRaisesRegex(ValueError, "platform"):
            check(raw, identity)

    def test_diffid_rejected_without_mutating_legacy_verifier_globals(self):
        raw, identity = docker_archive(config_change=lambda x: x["rootfs"]["diff_ids"].__setitem__(0,"sha256:"+"0"*64))
        old = (legacy.MANIFEST,legacy.CONFIG)
        with self.assertRaisesRegex(ValueError, "diffID"):
            check(raw,identity)
        self.assertEqual(old,(legacy.MANIFEST,legacy.CONFIG))

    def test_docker_compat_manifest_wrong_layers_rejected(self):
        raw, identity = docker_archive(compat_change=lambda x: x[0]["Layers"].__setitem__(0,"blobs/sha256/"+"0"*64))
        with self.assertRaisesRegex(ValueError, "disagrees"):
            check(raw,identity)

    def test_modified_or_missing_layer_blob_denied(self):
        def modify(blobs):
            key=next(k for k,v in blobs.items() if v.startswith(b"\x1f\x8b"))
            blobs[key] += b"TAMPER"
        raw, identity = docker_archive(blob_change=modify)
        with self.assertRaisesRegex(ValueError, "digest|trailing"):
            check(raw,identity)

    def test_traversal_member_denied(self):
        raw, identity = docker_archive(blob_change=lambda b: b.update({"../danger":b"NO"}))
        with self.assertRaisesRegex(ValueError, "unsafe"):
            check(raw,identity)

    def test_gzip_expansion_budget_denies_bomb(self):
        raw, identity = docker_archive()
        with patch.object(legacy,'MAX_INFLATED_LAYER',64):
            with self.assertRaisesRegex(ValueError,"expanded"):
                check(raw,identity)


if __name__=='__main__':unittest.main()
