"""Bounded local OCI runtime observation is NOT backup or release evidence."""
import subprocess
import unittest

from scripts.portal_storage_runtime_probe import EXPECTED_ID, IMAGE, probe


class FakeDocker:
    def __init__(self, status="503", identity=EXPECTED_ID, launch_code=0, rm_code=0):
        self.status = status
        self.identity = identity
        self.launch_code = launch_code
        self.rm_code = rm_code
        self.commands = []

    def __call__(self, argv, *, capture_output, timeout, check):
        self.commands.append(argv)
        assert argv[0] == "docker" and capture_output is True and check is False
        assert timeout <= 20
        if argv[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(argv, 0, self.identity.encode() + b"\n", b"")
        if argv[1] == "run":
            assert "--network" in argv and argv[argv.index("--network")+1] == "none"
            assert "--read-only" in argv and "--rm" in argv
            assert "--publish" not in argv and "-p" not in argv
            assert "--mount" not in argv and "--volume" not in argv
            assert argv[-3:] == [EXPECTED_ID, "server", "/data"]
            return subprocess.CompletedProcess(argv, self.launch_code, b"ephemeral", b"")
        if argv[1] == "exec":
            assert "127.0.0.1" in " ".join(argv)
            return subprocess.CompletedProcess(argv, 0, self.status.encode(), b"")
        if argv[1:3] == ["rm", "--force"]:
            return subprocess.CompletedProcess(argv, self.rm_code, b"", b"")
        raise AssertionError("unapproved Docker operation")


class StorageRuntimeTests(unittest.TestCase):
    def test_realistic_license_disabled_http_503_is_release_hold(self):
        fake = FakeDocker("503")
        result = probe(runner=fake, pause=lambda _: None)
        self.assertEqual(result["status"], "HOLD")
        self.assertEqual(result["readiness_http_code"], 503)
        self.assertFalse(result["synthetic_s3_roundtrip_verified"])
        self.assertFalse(result["minio_backup_restoration_verified"])
        self.assertFalse(result["original_production_minio_image_verified"])
        self.assertFalse(result["production_recovery_approved"])
        self.assertTrue(result["disposable_container_cleanup_verified"])
        self.assertEqual(len([x for x in fake.commands if x[1] == "rm"]), 1)

    def test_http_200_still_cannot_authorize_recovery_or_s3_parity(self):
        result = probe(runner=FakeDocker("200"), pause=lambda _: None)
        self.assertEqual(result["status"], "HTTP_READY_ONLY")
        self.assertTrue(result["readiness_http_verified"])
        self.assertFalse(result["synthetic_s3_roundtrip_verified"])
        self.assertFalse(result["original_production_minio_image_verified"])
        self.assertFalse(result["production_recovery_approved"])

    def test_mismatching_cached_image_never_starts_runtime(self):
        fake = FakeDocker(identity="sha256:"+"b"*64)
        result = probe(runner=fake, pause=lambda _: None)
        self.assertEqual(result["status"], "HOLD")
        self.assertFalse(result["image_identity_matches_cached_digest"])
        self.assertFalse(any(a[1] == "run" for a in fake.commands))

    def test_unexpected_status_or_failed_launch_are_hold(self):
        for status in ("401", "404", "000", "invalid"):
            with self.subTest(status=status):
                fake = FakeDocker(status)
                result = probe(runner=fake, pause=lambda _: None, attempts=2)
                self.assertEqual(result["status"], "HOLD")
                self.assertFalse(result["readiness_http_verified"])
        result = probe(runner=FakeDocker(launch_code=125), pause=lambda _: None)
        self.assertEqual(result["status"], "HOLD")

    def test_cleanup_failure_invalidates_positive_observation(self):
        result = probe(runner=FakeDocker("200", rm_code=1), pause=lambda _: None)
        self.assertEqual(result["status"], "HOLD_CLEANUP_UNVERIFIED")
        self.assertFalse(result["readiness_http_verified"])
        self.assertFalse(result["disposable_container_cleanup_verified"])

    def test_attempt_budget_must_be_bounded_integer(self):
        for budget in (0, 21, True, -1, 1.1):
            with self.subTest(budget=budget):
                fake = FakeDocker()
                result = probe(runner=fake, pause=lambda _: None, attempts=budget)
                self.assertEqual(result["status"], "HOLD")
                self.assertFalse(any(a[1] == "run" for a in fake.commands))


if __name__ == "__main__":
    unittest.main()
