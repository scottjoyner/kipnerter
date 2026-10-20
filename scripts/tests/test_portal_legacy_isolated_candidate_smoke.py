"""Synthetic-only regression checks for fail-closed isolated recovery rehearsal."""
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.portal_legacy_isolated_candidate_smoke import (
    EXPECTED, RESEARCH, classify_probe, commands, rehearsal, safety_inspect
)

FIXED_NAME = "kp-legacy-isolated-" + "a" * 12
TMPFS = {
    "/tmp": "rw,nosuid,nodev,noexec,size=33554432",
    "/run": "rw,nosuid,nodev,noexec,size=8388608",
    "/data": "rw,nosuid,nodev,noexec,size=33554432",
}


def receipt(image, *, mounts=0, network="none", ports=0, tmpfs=None, cap=None):
    return "|".join([
        network, "true", str(ports), image, "true", str(mounts), "3",
        json.dumps(TMPFS if tmpfs is None else tmpfs),
        "402653184", "64", "500000000",
        json.dumps(["ALL"] if cap is None else cap),
        json.dumps(["no-new-privileges"]), "true"
    ])


class FakeDocker:
    def __init__(self, *, failure=None, wrong_code=False):
        self.ops = []
        self.failure = failure
        self.wrong_code = wrong_code
        self.image = RESEARCH["synthetic-loopback"]

    def __call__(self, argv, **kwargs):
        self.ops.append(argv)
        if argv[1:3] == ["image", "inspect"]:
            return self.image
        if argv[1] == "run":
            if self.failure == "run":
                raise ValueError("synthetic daemon rejection")
            return "f" * 64
        if argv[1] == "inspect":
            if self.failure == "inspect":
                return receipt(self.image, network="bridge")
            return receipt(self.image)
        if argv[1] == "exec":
            if self.failure == "exec":
                raise ValueError("synthetic container unavailable")
            obj = dict(EXPECTED)
            if self.wrong_code:
                obj["/api/v1/control-plane/overview"] = 200
            return json.dumps(obj)
        if argv[1] == "rm":
            if self.failure == "rm":
                raise ValueError("synthetic cleanup unavailable")
            return "f" * 64
        if argv[1] == "ps":
            if self.failure == "leftovers":
                return FIXED_NAME
            return ""
        raise AssertionError("unexpected subprocess")


class CandidateIsolationTests(unittest.TestCase):
    def test_fixed_run_command_has_no_network_ports_bind_or_privileges(self):
        for role, image in RESEARCH.items():
            with self.subTest(role=role):
                start, inspect, probe, remove = commands(
                    FIXED_NAME, image, synthetic=role == "synthetic-loopback")
                self.assertEqual(start[0:3], ["docker", "run", "--detach"])
                for pair in (("--network", "none"), ("--read-only", "--cap-drop"),
                             ("--security-opt", "no-new-privileges"),
                             ("--pull", "never"), ("--restart", "no")):
                    if pair[0] == "--read-only":
                        self.assertIn("--read-only", start)
                    else:
                        pos = start.index(pair[0])
                        self.assertEqual(start[pos+1], pair[1])
                for forbidden in ("--publish", "-p", "--volume", "-v",
                                  "--privileged", "--network=host", "--mount"):
                    self.assertNotIn(forbidden, start)
                self.assertIn("/data:rw,nosuid,nodev,noexec,size=33554432", start)
                self.assertEqual(remove[0:3], ["docker", "rm", "--force"])
                self.assertEqual(probe[:2], ["docker", "exec"])

    def test_isolation_receipt_rejects_unapproved_network_mounts_ports(self):
        image = RESEARCH["synthetic-loopback"]
        safety_inspect(receipt(image), image)
        for changed in (receipt(image, network="bridge"), receipt(image, mounts=1),
                        receipt(image, ports=1), receipt(image, cap=["NET_ADMIN"]),
                        receipt(image, tmpfs={"/tmp":"rw"})):
            with self.subTest(shape=changed[:35]):
                with self.assertRaises(ValueError):
                    safety_inspect(changed, image)

    def test_probe_denial_and_health_required(self):
        classify_probe(json.dumps(EXPECTED))
        for name in EXPECTED:
            changed = dict(EXPECTED)
            changed[name] = 401 if EXPECTED[name] == 200 else 200
            with self.subTest(route=name), self.assertRaises(ValueError):
                classify_probe(json.dumps(changed))

    def test_probe_rejects_duplicate_partial_and_wrong_types(self):
        for raw in ("{}", "[]", '{"a":1,"a":2}',
                    json.dumps({**EXPECTED, "/ready": True}),
                    "X"*3000):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                classify_probe(raw)

    def test_positive_fixture_cannot_be_promoted_to_legacy(self):
        fake = FakeDocker()
        result = rehearsal("synthetic-loopback", call=fake,
                           pauses=lambda _: None, nonce="a"*12)
        self.assertEqual(result["status"], "SYNTHETIC_LOOPBACK_ISOLATION_PASS_NOT_LEGACY")
        self.assertTrue(result["disposable_container_cleanup_verified"])
        self.assertTrue(result["synthetic_http_fixture"])
        self.assertFalse(result["actual_candidate_api_health_verified"])
        for key in ("safe_to_cutover", "original_legacy_api_equivalence_verified",
                    "runnable_original_rollback_verified",
                    "legacy_web_image_rehearsed", "production_modified"):
            self.assertFalse(result[key])
        self.assertEqual([x[1] for x in fake.ops].count("rm"), 1)
        self.assertEqual(fake.ops[-1][1], "ps")

    def test_run_timeout_must_attempt_cleanup(self):
        fake = FakeDocker(failure="run")
        with self.assertRaises(ValueError):
            rehearsal("synthetic-loopback", call=fake,
                      pauses=lambda _: None, nonce="a"*12)
        self.assertEqual([x[1] for x in fake.ops].count("rm"), 1)

    def test_inspect_security_mismatch_attempts_cleanup(self):
        fake = FakeDocker(failure="inspect")
        with self.assertRaisesRegex(ValueError, "receipt mismatch"):
            rehearsal("synthetic-loopback", call=fake,
                      pauses=lambda _: None, nonce="a"*12)
        self.assertIn("rm", [x[1] for x in fake.ops])

    def test_unauthenticated_control_plane_open_causes_hold_and_cleanup(self):
        fake = FakeDocker(wrong_code=True)
        with self.assertRaisesRegex(ValueError, "probe failed"):
            rehearsal("synthetic-loopback", call=fake,
                      pauses=lambda _: None, nonce="a"*12)
        self.assertEqual([x[1] for x in fake.ops].count("exec"), 18)
        self.assertIn("rm", [x[1] for x in fake.ops])

    def test_cleanup_failure_is_hard_hold(self):
        fake = FakeDocker(failure="rm")
        with self.assertRaisesRegex(ValueError, "cleanup"):
            rehearsal("synthetic-loopback", call=fake,
                      pauses=lambda _: None, nonce="a"*12)

    def test_leftover_container_is_hard_hold(self):
        fake = FakeDocker(failure="leftovers")
        with self.assertRaises(ValueError):
            rehearsal("synthetic-loopback", call=fake,
                      pauses=lambda _: None, nonce="a"*12)
        self.assertIn("ps", [x[1] for x in fake.ops])

    def test_unapproved_image_role_and_container_name_denied(self):
        with self.assertRaises(ValueError):
            rehearsal("legacy-api", call=FakeDocker(), nonce="a"*12)
        with self.assertRaises(ValueError):
            commands("production-api", RESEARCH["compat-031"])
        with self.assertRaises(ValueError):
            commands(FIXED_NAME, "sha256:"+"0"*64)

    def test_synthetic_server_not_allowed_for_other_image(self):
        with self.assertRaises(ValueError):
            commands(FIXED_NAME, RESEARCH["compat-031"], synthetic=True)


if __name__ == "__main__":
    unittest.main()
