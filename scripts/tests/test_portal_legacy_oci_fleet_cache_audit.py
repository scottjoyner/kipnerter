"""Fail-closed, no-secret exact OCI digest cache inventory controls."""
import subprocess
import unittest

from scripts.portal_legacy_oci_fleet_cache_audit import (
    ROLES, HOSTS, audit, classify_ssh_result, remote_command,
)


class FakeSSH:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        self_match = argv[-2]
        assert argv[0] == "ssh" and argv[-1] == remote_command()
        assert self_match in HOSTS
        assert "-T" in argv
        assert "BatchMode=yes" in argv
        assert "StrictHostKeyChecking=yes" in argv
        assert "ClearAllForwardings=yes" in argv
        assert "RequestTTY=no" in argv
        assert kwargs["stderr"] is subprocess.DEVNULL
        assert kwargs["timeout"] <= 11
        assert kwargs["check"] is False
        code, response = self.answers.get(self_match, (255, b""))
        return subprocess.CompletedProcess(argv, code, stdout=response)


class ImageCacheAuditTests(unittest.TestCase):
    def test_exact_both_present_is_discovery_not_release_approval(self):
        fake = FakeSSH({"xwing": (0, b"EXACT_PRESENT\nEXACT_PRESENT\n")})
        report = audit(runner=fake, hosts=("xwing",))
        self.assertEqual(
            report["exact_image_cache_hits"],
            ["xwing:legacy-api", "xwing:legacy-web"],
        )
        for field in ("runnable_rollback_verified", "production_recovery_approved",
                      "safe_to_cutover", "original_image_bytes_retrieved",
                      "registries_contacted", "docker_daemons_modified",
                      "independent_admin_custody_verified"):
            self.assertFalse(report[field])

    def test_explicit_absent_vs_no_docker_vs_unavailable(self):
        fake = FakeSSH({
            "destroyer": (0, b"EXACT_ABSENT\nEXACT_ABSENT\n"),
            "lenovo": (0, b"DOCKER_INACCESSIBLE\n"),
            "deathstar-xps-8920": (255, b""),
        })
        out = audit(runner=fake,
                    hosts=("destroyer", "lenovo", "deathstar-xps-8920"))
        self.assertEqual(out["host_classification"]["destroyer"]["legacy-api"],
                         "EXACT_ABSENT")
        self.assertEqual(out["host_classification"]["lenovo"]["legacy-api"],
                         "DOCKER_INACCESSIBLE")
        self.assertEqual(out["host_classification"]["deathstar-xps-8920"]["legacy-api"],
                         "SSH_UNAVAILABLE")
        self.assertEqual(out["exact_image_cache_hits"], [])

    def test_fixed_host_allowlist_no_production_or_injection(self):
        for hosts in (("kipnerter-prod-01-1",), ("destroyer", "destroyer"),
                      (), ("destroyer", "fake;docker rm -f important")):
            with self.subTest(hosts=hosts),self.assertRaisesRegex(ValueError, "host"):
                audit(runner=lambda *a, **k: self.fail("unexpected SSH"), hosts=hosts)

    def test_wrong_stdout_is_untrusted_not_confirmed_absent(self):
        for output in (b"", b"EXACT_PRESENT\n", b"true\nfalse\n",
                       b"EXACT_PRESENT\nDOCKER_INACCESSIBLE\n",
                       b"EXACT_ABSENT\n"*2 + b"EXACT_ABSENT\n",
                       b"x"*200, b"\xff\xfe"):
            with self.subTest(sample=output[:30]):
                result = audit(
                    runner=FakeSSH({"destroyer": (0, output)}),
                    hosts=("destroyer",))
                self.assertEqual(result["host_classification"]["destroyer"]["docker"],
                                 "UNTRUSTED_RESPONSE")
                self.assertFalse(result["exact_image_cache_hits"])

    def test_fail_closed_on_timeout_and_local_subprocess_error(self):
        def timeout(*args, **kw):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=kw["timeout"])
        out = audit(runner=timeout, hosts=("xwing",))
        self.assertEqual(out["host_classification"]["xwing"]["docker"],
                         "SSH_UNAVAILABLE")
        def denied(*args, **kw):
            raise OSError("synthetic")
        out = audit(runner=denied, hosts=("xwing",))
        self.assertEqual(out["host_classification"]["xwing"]["legacy-web"],
                         "SSH_UNAVAILABLE")

    def test_remote_script_no_mutations_and_no_user_supplied_command(self):
        cmd = remote_command()
        for role, image in ROLES.items():
            self.assertIn(image, cmd)
        self.assertIn("docker image inspect", cmd)
        self.assertIn("docker info", cmd)
        for forbidden in ("docker run", "docker pull", "docker build", "docker save",
                          "docker export", "docker commit", "docker rm", "sudo",
                          "curl ", "wget ", "docker exec"):
            self.assertNotIn(forbidden, cmd)

    def test_direct_classifier_disallows_true_or_partial_results(self):
        with self.assertRaisesRegex(ValueError, "untrusted"):
            classify_ssh_result(0, b"EXACT_PRESENT\nfalse\n")
        self.assertEqual(classify_ssh_result(9, b"EXACT_PRESENT\nEXACT_PRESENT\n")[
            "legacy-api"], "SSH_UNAVAILABLE")
        self.assertEqual(classify_ssh_result(0, b"DOCKER_INACCESSIBLE\n")[
            "legacy-web"], "DOCKER_INACCESSIBLE")
        self.assertEqual(classify_ssh_result(0, b"EXACT_ABSENT\nEXACT_PRESENT\n")[
            "legacy-web"], "EXACT_PRESENT")


if __name__ == "__main__":
    unittest.main()
