"""Cross-image fail-closed test harness: not production rollback."""
import json
import unittest

from scripts.portal_legacy_cross_image_preflight import rehearsal
from scripts.portal_legacy_isolated_candidate_smoke import RESEARCH, EXPECTED

NAMES = ["kp-legacy-isolated-" + x*12 for x in ("a","b","c")]
IDENTITIES = ["1"*64, "2"*64, "3"*64]
TMPFS = {
    "/tmp": "rw,nosuid,nodev,noexec,size=33554432",
    "/run": "rw,nosuid,nodev,noexec,size=8388608",
    "/data": "rw,nosuid,nodev,noexec,size=33554432",
}


class FakeDocker:
    def __init__(self, *, failure=None):
        self.failure = failure
        self.calls = []
        self.containers = {}
        self.created = 0
        self.kills = []

    def __call__(self, args, *, timeout=25):
        self.calls.append(args)
        op = args[1]
        if op == "image":
            image = args[-1]
            return image if self.failure != "wrong_image" else "sha256:" + "0"*64
        if op == "run":
            name = args[args.index("--name")+1]
            image = next(v for v in RESEARCH.values() if v in args)
            self.created += 1
            ident = IDENTITIES[self.created-1]
            if self.failure == "duplicate_id" and self.created == 3:
                ident = IDENTITIES[0]
            self.containers[name] = (ident, image)
            if self.failure == "last_run_failed" and self.created == 3:
                raise ValueError("synthetic missing candidate")
            return ident
        if op == "inspect":
            target = args[-1]
            name = (target if target.startswith("kp-legacy-isolated-")
                    else next((n for n, (i, _) in self.containers.items() if i == target), None))
            if name is None or name not in self.containers:
                raise ValueError("unknown test container")
            ident, image = self.containers[name]
            if "HostConfig" in args[3]:
                mounts = "1" if self.failure == "bad_mount" and self.created == 1 else "0"
                return "|".join([
                    "none","true","0",image,"true",mounts,"3",
                    json.dumps(TMPFS),"402653184","64","500000000",
                    json.dumps(["ALL"]),json.dumps(["no-new-privileges"]),"true",
                ])
            if self.failure == "stale_pre_kill" and self.created == 2 and target == ident:
                return "MISMATCHED"
            return "|".join([ident,image,"/"+name,"true"])
        if op == "exec":
            name = args[2]
            image = self.containers[name][1]
            results = dict(EXPECTED)
            if image in (
                RESEARCH["ios17-research"],
                RESEARCH["turns-research"],
                RESEARCH["recovery-research"],
            ):
                results["/api/v1/control-plane/overview"] = 404
                results["/api/v1/release"] = 404
            if self.failure == "fallback_auth_broken_after_failure" and self.created == 3:
                results["/api/v1/control-plane/overview:synthetic-auth"] = 503
            if self.failure == "upgrade_auth_broken" and self.created == 2:
                results["/api/v1/control-plane/overview:synthetic-auth"] = 503
            return json.dumps(results)
        if op == "kill":
            identifier = args[-1]
            self.kills.append(identifier)
            if self.failure == "wrong_kill_receipt":
                return IDENTITIES[0]
            name = next((n for n, (i, _) in self.containers.items()
                         if i == identifier), None)
            if name is None:
                raise ValueError("attempt to kill unknown container")
            if self.failure != "not_stopped":
                self.containers.pop(name)
            return identifier
        if op == "ps":
            name = args[args.index("--filter")+1].removeprefix("name=^/").removesuffix("$")
            return name if name in self.containers else ""
        if op == "rm":
            name = args[-1]
            if self.failure == "cleanup_denied":
                raise ValueError("synthetic cleanup denied")
            self.containers.pop(name, None)
            return "OK"
        raise AssertionError("unrecognized Docker verb: " + op)


class CrossImageGateTests(unittest.TestCase):
    def test_fixture_cross_image_mechanics_positive_but_no_release(self):
        fake=FakeDocker()
        result=rehearsal("compat-031","synthetic-loopback",call=fake,
                         pauses=lambda _:None,nonces=("a"*12,"b"*12,"c"*12))
        self.assertEqual(result["status"],"SYNTHETIC_CROSS_IMAGE_MECHANICS_PASS_NOT_ROLLBACK")
        self.assertTrue(result["rollback_candidate_prequalified_before_any_injection"])
        self.assertEqual(fake.kills,[IDENTITIES[1]])
        self.assertEqual(fake.created,3)
        self.assertFalse(fake.containers)
        for label in ("original_historical_production_image_recovered",
                      "original_production_web_tested","operational_equivalence_verified",
                      "production_data_rollback_verified","independent_custody_verified",
                      "real_chat_execution_verified","production_modified",
                      "safe_to_cutover"):
            self.assertFalse(result[label])

    def test_all_incompatible_fallback_variants_deny_before_any_kill(self):
        for role in ("ios17-research","turns-research","recovery-research"):
            with self.subTest(role=role):
                fake=FakeDocker()
                with self.assertRaises(ValueError):
                    rehearsal("compat-031",role,call=fake,
                              pauses=lambda _:None,nonces=("a"*12,"b"*12,"c"*12))
                self.assertEqual(fake.created,1)
                self.assertEqual(fake.kills,[])
                self.assertFalse(fake.containers)

    def test_unapproved_upgrade_roles_and_injection_names_rejected(self):
        for pair in (("synthetic-loopback","compat-031"),
                     ("legacy-api","synthetic-loopback"),
                     ("compat-031","compat-031")):
            fake=FakeDocker()
            with self.subTest(pair=pair),self.assertRaises(ValueError):
                rehearsal(*pair,call=fake,nonces=("a"*12,"b"*12,"c"*12))
            self.assertEqual(fake.calls,[])
        for tokens in (("a"*12,"b"*12,"b"*12),("a"*12,"Z"*12,"c"*12),
                       ("a"*12,"b"*12,";shutdown"),("a"*12,),None):
            if tokens is None:
                continue
            fake=FakeDocker()
            with self.subTest(tokens=tokens),self.assertRaises(ValueError):
                rehearsal("compat-031","synthetic-loopback",
                          call=fake,nonces=tokens)
            self.assertEqual(fake.calls,[])

    def test_wrong_image_ref_denies_any_launch(self):
        fake=FakeDocker(failure="wrong_image")
        with self.assertRaisesRegex(ValueError,"pinned local image"):
            rehearsal("compat-031","synthetic-loopback",call=fake,
                      nonces=("a"*12,"b"*12,"c"*12))
        self.assertEqual(fake.created,0)
        self.assertEqual(fake.kills,[])

    def test_unexpected_mount_on_fallback_denies_before_kill(self):
        fake=FakeDocker(failure="bad_mount")
        with self.assertRaises(ValueError):
            rehearsal("compat-031","synthetic-loopback",call=fake,
                      pauses=lambda _:None,nonces=("a"*12,"b"*12,"c"*12))
        self.assertEqual(fake.created,1)
        self.assertFalse(fake.kills)
        self.assertFalse(fake.containers)

    def test_upgrade_auth_failure_denies_kill(self):
        fake=FakeDocker(failure="upgrade_auth_broken")
        with self.assertRaises(ValueError):
            rehearsal("compat-031","synthetic-loopback",call=fake,
                      pauses=lambda _:None,nonces=("a"*12,"b"*12,"c"*12))
        self.assertEqual(fake.created,2)
        self.assertEqual(fake.kills,[])
        self.assertFalse(fake.containers)

    def test_stale_upgrade_container_binding_denies_kill(self):
        fake=FakeDocker(failure="stale_pre_kill")
        with self.assertRaises(ValueError):
            rehearsal("compat-031","synthetic-loopback",call=fake,
                      pauses=lambda _:None,nonces=("a"*12,"b"*12,"c"*12))
        self.assertEqual(fake.kills,[])
        self.assertFalse(fake.containers)

    def test_wrong_kill_receipt_denies_recovery(self):
        fake=FakeDocker(failure="wrong_kill_receipt")
        with self.assertRaisesRegex(ValueError,"SIGKILL"):
            rehearsal("compat-031","synthetic-loopback",call=fake,
                      pauses=lambda _:None,nonces=("a"*12,"b"*12,"c"*12))
        self.assertEqual(fake.created,2)
        self.assertFalse(fake.containers)

    def test_not_stopped_never_counts_as_recovery(self):
        fake=FakeDocker(failure="not_stopped")
        with self.assertRaises(ValueError):
            rehearsal("compat-031","synthetic-loopback",call=fake,
                      pauses=lambda _:None,nonces=("a"*12,"b"*12,"c"*12))
        self.assertEqual(fake.created,2)
        self.assertFalse(fake.containers)

    def test_failed_fresh_fallback_denies_promotion(self):
        fake=FakeDocker(failure="last_run_failed")
        with self.assertRaises(ValueError):
            rehearsal("compat-031","synthetic-loopback",call=fake,
                      pauses=lambda _:None,nonces=("a"*12,"b"*12,"c"*12))
        self.assertEqual(fake.created,3)
        self.assertFalse(fake.containers)

    def test_bad_recovered_auth_denies_promotion(self):
        fake=FakeDocker(failure="fallback_auth_broken_after_failure")
        with self.assertRaises(ValueError):
            rehearsal("compat-031","synthetic-loopback",call=fake,
                      pauses=lambda _:None,nonces=("a"*12,"b"*12,"c"*12))
        self.assertEqual(fake.created,3)
        self.assertFalse(fake.containers)

    def test_reused_old_fallback_identity_denies_promotion(self):
        fake=FakeDocker(failure="duplicate_id")
        with self.assertRaisesRegex(ValueError,"fresh fallback"):
            rehearsal("compat-031","synthetic-loopback",call=fake,
                      pauses=lambda _:None,nonces=("a"*12,"b"*12,"c"*12))
        self.assertEqual(fake.created,3)
        self.assertFalse(fake.containers)

    def test_uncertain_cleanup_is_always_hard_hold(self):
        fake=FakeDocker(failure="cleanup_denied")
        with self.assertRaisesRegex(ValueError,"cleanup"):
            rehearsal("compat-031","synthetic-loopback",call=fake,
                      pauses=lambda _:None,nonces=("a"*12,"b"*12,"c"*12))


if __name__=="__main__":
    unittest.main()
