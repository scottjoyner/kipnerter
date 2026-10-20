"""Synthetic OCI archive digest-tree controls, no Docker or production data."""
import hashlib
import gzip
from unittest.mock import patch
import io
import json
import tarfile
import unittest

from scripts.portal_legacy_oci_archive_verify import verify_archive


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def build_archive(*, mutate=None, omit=None, config_override=None,
                  manifest_override=None, docker_override=None, tar_override=None,
                  compression=None, diffid_override=None):
    layer = b"SYNTHETIC_FIXTURE_NOT_IMAGE_LAYER_CONTENT" * 3
    uncompressed_id = hashlib.sha256(layer).hexdigest()
    if compression == "gzip":
        layer = gzip.compress(layer, mtime=0)
    layer_id = hashlib.sha256(layer).hexdigest()
    config = {
        "os": "linux", "architecture": "amd64",
        "rootfs": {"type": "layers", "diff_ids": ["sha256:" + (diffid_override or uncompressed_id)]},
        "config": {"Entrypoint": ["./fixture"], "Env": ["SECRET=synthetic-not-real"]},
    }
    if config_override:
        config.update(config_override)
    conf_bytes = encoded(config)
    conf_id = hashlib.sha256(conf_bytes).hexdigest()
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {"mediaType": "application/vnd.oci.image.config.v1+json",
                   "digest": "sha256:" + conf_id, "size": len(conf_bytes)},
        "layers": [{"mediaType": ("application/vnd.oci.image.layer.v1.tar+gzip"
                                 if compression == "gzip" else
                                 "application/vnd.oci.image.layer.v1.tar"),
                    "digest": "sha256:" + layer_id, "size": len(layer)}],
    }
    if manifest_override:
        manifest_override(manifest)
    man_bytes = encoded(manifest)
    man_id = hashlib.sha256(man_bytes).hexdigest()
    imageindex = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [{
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": "sha256:" + man_id,
            "size": len(man_bytes),
            "platform": {"os": "linux", "architecture": "amd64"},
        }],
    }
    index_bytes = encoded(imageindex)
    image_id = hashlib.sha256(index_bytes).hexdigest()
    top = {"schemaVersion": 2,
           "mediaType": "application/vnd.oci.image.index.v1+json",
           "manifests": [{"mediaType": "application/vnd.oci.image.index.v1+json",
                          "digest": "sha256:" + image_id,
                          "size": len(index_bytes)}]}
    compat = [{"Config": "blobs/sha256/" + conf_id,
               "RepoTags": ["test:synthetic"],
               "Layers": ["blobs/sha256/" + layer_id]}]
    if docker_override:
        docker_override(compat)
    blobs = {
        "blobs/sha256/" + image_id: index_bytes,
        "blobs/sha256/" + man_id: man_bytes,
        "blobs/sha256/" + conf_id: conf_bytes,
        "blobs/sha256/" + layer_id: layer,
        "index.json": encoded(top),
        "manifest.json": encoded(compat),
        "oci-layout": encoded({"imageLayoutVersion": "1.0.0"}),
    }
    if mutate:
        mutate(blobs)
    if omit:
        blobs.pop(omit, None)
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for name, body in blobs.items():
            item = tarfile.TarInfo(name)
            item.size = len(body)
            if tar_override:
                tar_override(item)
            tar.addfile(item, io.BytesIO(body))
    out.seek(0)
    return out, "sha256:" + image_id, blobs


class OCIArchiveControls(unittest.TestCase):
    def test_research_manifest_config_and_blob_tree_verifies_without_launch(self):
        raw, identity, _ = build_archive()
        report = verify_archive(raw, identity)
        self.assertEqual(report["status"], "OCI_DIGEST_TREE_VERIFIED_NOT_RUNNABLE")
        self.assertEqual(report["saved_layer_count"], 1)
        self.assertTrue(report["uncompressed_layer_diffids_verified"])
        for expected in ("safe_to_cutover", "launch_behavior_verified",
                         "rollback_after_failure_verified",
                         "original_image_registry_provenance_verified",
                         "sensitive_config_or_layer_bytes_disclosed",
                         "archive_imported_or_extracted", "production_modified"):
            self.assertFalse(report[expected], expected)

    def test_gzip_compressed_layer_matches_uncompressed_diffid(self):
        raw, identity, _ = build_archive(compression="gzip")
        report = verify_archive(raw, identity)
        self.assertTrue(report["uncompressed_layer_diffids_verified"])
        self.assertEqual(report["saved_layer_count"], 1)

    def test_wrong_uncompressed_diffid_rejected_even_when_saved_layer_checksum_ok(self):
        raw, identity, _ = build_archive(
            compression="gzip", diffid_override="f"*64)
        with self.assertRaisesRegex(ValueError, "diffID"):
            verify_archive(raw, identity)

    def test_fake_gzip_magic_rejected_as_corrupt_stream(self):
        def sabotage(blobs):
            key = next(k for k, v in blobs.items() if v.startswith(b"SYNTHETIC_FIXTURE"))
            old = blobs.pop(key)
            spoiled = b"\x1f\x8b" + old
            blobs["blobs/sha256/" + hashlib.sha256(spoiled).hexdigest()] = spoiled
            # Other metadata still points to old digest, but invalid gzip
            # must fail before descriptor comparison.
        raw, identity, _ = build_archive(mutate=sabotage)
        with self.assertRaisesRegex(ValueError, "compressed"):
            verify_archive(raw, identity)

    def test_gzip_trailing_bytes_rejected_before_layer_promotion(self):
        def sabotage(blobs):
            target = next(k for k in blobs if
                          blobs[k].startswith(b"\x1f\x8b"))
            old = blobs.pop(target)
            spoiled = old + b"TRAILING!"
            blobs["blobs/sha256/" + hashlib.sha256(spoiled).hexdigest()] = spoiled
        raw, identity, _ = build_archive(compression="gzip", mutate=sabotage)
        with self.assertRaisesRegex(ValueError, "trailing"):
            verify_archive(raw, identity)

    def test_gzip_expansion_limit_denies_ratio_bomb(self):
        raw, identity, _ = build_archive(compression="gzip")
        with patch("scripts.portal_legacy_oci_archive_verify.MAX_INFLATED_LAYER", 32):
            with self.assertRaisesRegex(ValueError, "expanded"):
                verify_archive(raw, identity)

    def test_media_mismatch_between_gzip_bytes_and_raw_descriptor_rejected(self):
        def change(manifest):
            manifest["layers"][0]["mediaType"] = "application/vnd.oci.image.layer.v1.tar"
        raw, identity, _ = build_archive(
            compression="gzip", manifest_override=change)
        with self.assertRaisesRegex(ValueError, "diffID"):
            verify_archive(raw, identity)

    def test_zstd_media_rejected_until_bounded_zstd_decoder_is_available(self):
        def change(manifest):
            manifest["layers"][0]["mediaType"] = "application/vnd.oci.image.layer.v1.tar+zstd"
        raw, identity, _ = build_archive(manifest_override=change)
        with self.assertRaisesRegex(ValueError, "compression"):
            verify_archive(raw, identity)

    def test_mismatched_image_id_rejected(self):
        raw, identity, _ = build_archive()
        with self.assertRaisesRegex(ValueError, "identity"):
            verify_archive(raw, "sha256:" + "c"*64)

    def test_layer_blob_tamper_fails_digest(self):
        def flip(b):
            key = next(k for k,v in b.items() if v.startswith(b"SYNTHETIC_FIXTURE"))
            b[key] += b"tamper"
        raw, identity, _ = build_archive(mutate=flip)
        with self.assertRaisesRegex(ValueError, "digest path"):
            verify_archive(raw, identity)

    def test_missing_blob_rejected(self):
        raw, identity, blobs = build_archive()
        missing = next(k for k, v in blobs.items() if v.startswith(b"SYNTHETIC_FIXTURE"))
        raw, identity, blobs = build_archive(omit=missing)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            verify_archive(raw, identity)

    def test_config_platform_mismatch_rejected(self):
        raw, identity, _ = build_archive(config_override={"architecture": "arm64"})
        with self.assertRaisesRegex(ValueError, "platform"):
            verify_archive(raw, identity)

    def test_unearned_docker_compat_layer_claim_rejected(self):
        raw, identity, _ = build_archive(
            docker_override=lambda d: d[0].update({"Layers": ["blobs/sha256/" + "0"*64]}))
        with self.assertRaisesRegex(ValueError, "disagrees"):
            verify_archive(raw, identity)

    def test_descriptor_claims_wrong_layer_length_rejected(self):
        def change(m):
            m["layers"][0]["size"] += 1
        raw, identity, _ = build_archive(manifest_override=change)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            verify_archive(raw, identity)

    def test_manifest_unsupported_media_rejected(self):
        def change(m):
            m["layers"][0]["mediaType"] = "application/vnd.attacker.exe"
        raw, identity, _ = build_archive(manifest_override=change)
        with self.assertRaisesRegex(ValueError, "media"):
            verify_archive(raw, identity)

    def test_no_digest_named_blob_rewrites(self):
        def corrupt(b):
            name = next(k for k in b if k.startswith("blobs/sha256/"))
            b[name] = b"malformed"+b[name]
        raw, identity, _ = build_archive(mutate=corrupt)
        with self.assertRaisesRegex(ValueError, "digest path"):
            verify_archive(raw, identity)

    def test_absolute_and_traversal_members_denied(self):
        for name in ("../etc/passwords", "/etc/private", "blobs/sha256/../../secrets"):
            with self.subTest(name=name):
                raw, identity, _ = build_archive(
                    mutate=lambda d: d.update({name: b"notsafe"}))
                with self.assertRaisesRegex(ValueError, "unsafe|unexpected"):
                    verify_archive(raw, identity)

    def test_nontarfile_entry_denied(self):
        raw, identity, _ = build_archive(
            tar_override=lambda item: setattr(item, "type", tarfile.SYMTYPE))
        with self.assertRaisesRegex(ValueError, "unsafe"):
            verify_archive(raw, identity)

    def test_duplicate_metadata_key_denied(self):
        raw, identity, blobs = build_archive(
            mutate=lambda b: b.update({"index.json": b'{"schemaVersion":2,"schemaVersion":2}'}))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            verify_archive(raw, identity)

    def test_invalid_digest_argument_denied(self):
        raw, identity, _ = build_archive()
        with self.assertRaisesRegex(ValueError, "digest"):
            verify_archive(raw, "latest")
        with self.assertRaisesRegex(ValueError, "digest"):
            verify_archive(raw, True)


if __name__=="__main__":
    unittest.main()
