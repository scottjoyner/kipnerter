"""Fail-closed synthetic controls for same-image disposable SIGKILL recovery."""
import json
import unittest

from scripts.portal_legacy_isolated_candidate_smoke import EXPECTED, RESEARCH
from scripts.portal_legacy_research_failure_recovery import rehearsal

IMAGE = RESEARCH["synthetic-loopback"]
N1, N2 = "kp-legacy-isolated-" + "a"*12, "kp-legacy-isolated-" + "b"*12
C1, C2 = "a"*64, "b"*64
POLICY = {
    "/tmp": "rw,nosuid,nodev,noexec,size=33554432",
    "/run": "rw,nosuid,nodev,noexec,size=8388608",
    "/data": "rw,nosuid,nodev,noexec,size=33554432",
}


class FakeDocker:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure
        self.started = 0
        self.running = {}
        self.killed = False

    def __call__(self, argv, *, timeout=25):
        self.calls.append(argv)
        if argv[1:3] == ["image", "inspect"]:
            return IMAGE if self.failure != "wrong_image" else "sha256:"+"0"*64
        if argv[1] == "run":
            self.started += 1
            name = argv[argv.index("--name")+1]
            ident = C1 if self.started == 1 or self.failure == "reuse_id" else C2
            self.running[name] = ident
            if self.failure == "second_start_failed" and self.started == 2:
                raise ValueError("synthetic second startup failure")
            return ident
        if argv[1] == "inspect":
            target = argv[-1]
            name = target if target.startswith("kp-legacy-isolated-") else next(
                (n for n, c in self.running.items() if c == target), None)
            if self.failure == "stale_binding" and target == C1:
                return "unknown"
            if name not in self.running:
                raise ValueError("synthetic unknown container")
            if "HostConfig" in argv[3]:
                output = "|".join([
                    "none", "true", "0", IMAGE, "true", "0", "3",
                    json.dumps(POLICY), "402653184", "64", "500000000",
                    json.dumps(["ALL"]), json.dumps(["no-new-privileges"]),
                    "true",
                ])
                if self.failure == "unexpected_mount":
                    output = output.replace("|true|0|3|","|true|1|3|")
                return output
            return "|".join([self.running[name], IMAGE,
                              "/"+name, "true"])
        if argv[1] == "exec":
            if self.failure == "recovered_auth_broken" and self.started == 2:
                output = dict(EXPECTED)
                output["/api/v1/control-plane/overview:synthetic-auth"] = 503
                return json.dumps(output)
            return json.dumps(EXPECTED)
        if argv[1] == "kill":
            if self.failure == "kill_denied":
                raise ValueError("injection denied")
            ident = argv[-1]
            if ident != C1:
                raise AssertionError("attempt to kill unqualified fixture")
            self.killed = True
            if self.failure != "stuck_after_sigkill":
                self.running.pop(N1, None)
            return ident if self.failure != "kill_wrong_response" else C2
        if argv[1] == "ps":
            name = argv[argv.index("--filter")+1].removeprefix("name=^/").removesuffix("$")
            return name if name in self.running else ""
        if argv[1] == "rm":
            name = argv[-1]
            if self.failure == "cleanup_denied":
                raise ValueError("synthetic no cleanup")
            self.running.pop(name, None)
            return C1
        raise AssertionError("unexpected Docker command")


class RecoveryContractTests(unittest.TestCase):
    def test_positive_synthetic_restart_after_exact_sigkill(self):
        fake = FakeDocker()
        report = rehearsal("synthetic-loopback", call=fake,
                           pauses=lambda _:None, identifiers=("a"*12, "b"*12))
        self.assertEqual(report["status"], "RESEARCH_RESTART_AFTER_SIGKILL_PASS_NOT_LEGACY")
        self.assertTrue(report["all_disposable_cleanup_verified"])
        self.assertTrue(report["fresh_container_id_observed"])
        self.assertEqual(fake.started, 2)
        self.assertTrue(fake.killed)
        self.assertFalse(fake.running)
        self.assertEqual(len([cmd for cmd in fake.calls if cmd[1] == "kill"]), 1)
        for name in ("original_historical_web_or_api_images_recovered",
                     "prior_production_image_rollback_verified",
                     "database_or_object_store_restored",
                     "original_release_auth_parity_verified",
                     "production_modified", "safe_to_cutover"):
            self.assertFalse(report[name])

    def test_nonapproved_image_and_role_rejected_before_run(self):
        fake=FakeDocker(failure="wrong_image")
        with self.assertRaises(ValueError):
            rehearsal("synthetic-loopback", call=fake,
                      identifiers=("a"*12,"b"*12))
        self.assertFalse(any(c[1]=="run" for c in fake.calls))
        with self.assertRaises(ValueError):
            rehearsal("legacy-api", call=fake, identifiers=("a"*12,"b"*12))

    def test_reject_identical_invalid_or_unsafe_names(self):
        for ids in (("a"*12,"a"*12), ("a"*12,"Z"*12),
                    ("a"*12,";rm -rf /"), ("a"*12,), "a"*24, ()):
            fake=FakeDocker()
            with self.subTest(ids=ids),self.assertRaises(ValueError):
                rehearsal("synthetic-loopback", call=fake, identifiers=ids)
            self.assertFalse(fake.calls)

    def test_wrong_policy_denies_injection_and_cleans(self):
        fake=FakeDocker(failure="unexpected_mount")
        with self.assertRaises(ValueError):
            rehearsal("synthetic-loopback", call=fake,
                      pauses=lambda _:None, identifiers=("a"*12,"b"*12))
        self.assertFalse(fake.killed)
        self.assertEqual(fake.running, {})

    def test_identity_mismatch_denies_destructive_kill(self):
        fake=FakeDocker(failure="stale_binding")
        with self.assertRaises(ValueError):
            rehearsal("synthetic-loopback", call=fake,
                      pauses=lambda _:None, identifiers=("a"*12,"b"*12))
        self.assertFalse(fake.killed)
        self.assertEqual(fake.running, {})

    def test_injected_kill_denied_does_not_report_recovery(self):
        fake=FakeDocker(failure="kill_denied")
        with self.assertRaises(ValueError):
            rehearsal("synthetic-loopback", call=fake,
                      pauses=lambda _:None, identifiers=("a"*12,"b"*12))
        self.assertEqual(fake.running, {})

    def test_injected_kill_wrong_id_denies_recovery(self):
        fake=FakeDocker(failure="kill_wrong_response")
        with self.assertRaisesRegex(ValueError,"pinned container"):
            rehearsal("synthetic-loopback", call=fake,
                      pauses=lambda _:None, identifiers=("a"*12,"b"*12))
        self.assertEqual(fake.running, {})

    def test_failed_second_start_is_not_recovery(self):
        fake=FakeDocker(failure="second_start_failed")
        with self.assertRaises(ValueError):
            rehearsal("synthetic-loopback", call=fake,
                      pauses=lambda _:None, identifiers=("a"*12,"b"*12))
        self.assertTrue(fake.killed)
        self.assertEqual(fake.running, {})

    def test_recovered_health_without_auth_does_not_count(self):
        fake=FakeDocker(failure="recovered_auth_broken")
        with self.assertRaises(ValueError):
            rehearsal("synthetic-loopback", call=fake,
                      pauses=lambda _:None, identifiers=("a"*12,"b"*12))
        self.assertEqual(fake.running, {})
        self.assertEqual(fake.started, 2)

    def test_same_container_id_cannot_claim_fresh_restart(self):
        fake=FakeDocker(failure="reuse_id")
        with self.assertRaisesRegex(ValueError,"same container ID"):
            rehearsal("synthetic-loopback",call=fake,
                      pauses=lambda _:None,identifiers=("a"*12,"b"*12))
        self.assertFalse(fake.running)

    def test_cleanup_denial_never_returns_success(self):
        fake=FakeDocker(failure="cleanup_denied")
        with self.assertRaisesRegex(ValueError,"remain unqualified"):
            rehearsal("synthetic-loopback",call=fake,
                      pauses=lambda _:None, identifiers=("a"*12,"b"*12))

    def test_sigkill_not_observed_as_stopped_fails_closed(self):
        fake=FakeDocker(failure="stuck_after_sigkill")
        with self.assertRaisesRegex(ValueError,"did not disappear"):
            rehearsal("synthetic-loopback", call=fake,
                      pauses=lambda _:None, identifiers=("a"*12,"b"*12))
        self.assertEqual(fake.running, {})


if __name__ == "__main__":
    unittest.main()
