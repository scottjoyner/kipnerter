import json
import subprocess
import unittest
from scripts.portal_image_custody import SOURCES, inspect


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class ImageCustodyTests(unittest.TestCase):
    def test_exact_image_allowlist_and_no_docker_mutation(self):
        def runner(args, **kwargs):
            self.assertEqual(args[:4], ["docker", "buildx", "imagetools", "inspect"])
            self.assertIn(args[4], SOURCES.values())
            self.assertEqual(args[-2:], ["--format", "{{json .Manifest}}"])
            self.assertEqual(kwargs["timeout"], 15)
            self.assertFalse(kwargs["check"])
            self.assertTrue(kwargs["capture_output"])
            return Result(stdout=json.dumps({
                "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                "digest": "sha256:" + "a" * 64,
                "size": 3254,
            }))
        result = inspect("spatial-postgres", runner)
        self.assertEqual(result["status"], "manifest_digest_observed")
        self.assertEqual(result["digest"], "sha256:" + "a" * 64)
        self.assertFalse(result["architecture_verified"])
        self.assertFalse(result["restore_equivalence_verified"])
        self.assertFalse(result["recovery_approved"])
        self.assertEqual(result["manifest_kind"], "single_manifest")
        with self.assertRaises(ValueError):
            inspect("other-image", runner)

    def test_registry_errors_fail_closed_and_are_redacted(self):
        for fail in (
            lambda *_a, **_kw: Result(returncode=1, stderr="AUTH=PRIVATE_SECRET"),
            lambda *_a, **_kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("docker",15)),
            lambda *_a, **_kw: (_ for _ in ()).throw(OSError("TOKEN_PRIVATE")),
        ):
            result = inspect("spatial-minio", fail)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["digest"], None)
            self.assertNotIn("PRIVATE", str(result))
            self.assertFalse(result["recovery_approved"])

    def test_malformed_or_oversized_manifest_cannot_qualify(self):
        for doc in (
            {},
            {"mediaType":"unexpected", "digest":"sha256:"+"a"*64},
            {"mediaType":"application/vnd.oci.image.manifest.v1+json",
             "digest":"sha256:bad"},
            [],
        ):
            result=inspect("spatial-minio", lambda *_a, **_kw: Result(stdout=json.dumps(doc)))
            self.assertEqual(result["status"],"unavailable")
        large=Result(stdout="X" * 65537)
        self.assertEqual(inspect("spatial-minio",
                                 lambda *_a, **_kw: large)["status"],"unavailable")

    def test_oci_index_observed_but_not_architecture_verified(self):
        manifest = {"mediaType":"application/vnd.oci.image.index.v1+json",
                    "digest":"sha256:"+"1"*64,
                    "manifests":[{"platform":{"os":"linux","architecture":"amd64"}}]}
        result=inspect("spatial-postgres",
                       lambda *_a, **_kw: Result(stdout=json.dumps(manifest)))
        self.assertEqual(result["manifest_kind"],"index")
        self.assertFalse(result["architecture_verified"])


if __name__ == "__main__":
    unittest.main()
