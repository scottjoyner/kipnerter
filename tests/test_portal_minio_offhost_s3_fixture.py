"""Fail-closed tests for host-key-verified synthetic-only MinIO replay."""
import ast
import copy
import json
import subprocess
import unittest

from scripts.portal_minio_offhost_s3_fixture import probe, verify_response, REMOTE_CODE

GOOD = {
    "source": "isolated_destroyer_synthetic_minio_roundtrip",
    "status": "SYNTHETIC_ONLY_PASS",
    "runtime_isolation_inspected": True,
    "server_cached_id_verified": True,
    "mc_cached_id_verified": True,
    "network_external": "none",
    "host_ports_published": False,
    "host_mounts_attached": False,
    "production_data_accessed": False,
    "synthetic_object_source_verified": True,
    "synthetic_object_copy_verified": True,
    "negative_integrity_control_rejected": True,
    "minio_prod_image_identity_verified": False,
    "real_backup_restored": False,
    "independent_custody_verified": False,
    "production_recovery_approved": False,
    "cleanup_verified": True,
    "object_byte_count": 1070,
    "sha256_matched_on_both_isolated_servers": True,
}


def fake_runner(modifier=None, code=0):
    def called(argv, **kwargs):
        assert argv[0] == "ssh"
        assert argv[-2] == "destroyer"
        assert argv[-1].startswith("python3 -c ")
        assert "StrictHostKeyChecking=yes" in argv
        assert "BatchMode=yes" in argv
        assert "ClearAllForwardings=yes" in argv
        assert kwargs["check"] is False
        assert kwargs["timeout"] <= 130
        payload = json.loads(kwargs["input"])
        content = copy.deepcopy(GOOD)
        content["challenge"] = payload["challenge"]
        if modifier:
            content = modifier(content)
        return subprocess.CompletedProcess(argv, code, stdout=json.dumps(content).encode(), stderr=b"")
    return called


class PhysicalS3ContractTests(unittest.TestCase):
    def test_accept_only_genuine_synthetic_no_production_flags(self):
        result = probe(runner=fake_runner())
        self.assertEqual(result["status"], "SYNTHETIC_ONLY_PASS")
        self.assertTrue(result["synthetic_object_copy_verified"])
        self.assertFalse(result["real_backup_restored"])
        self.assertFalse(result["production_recovery_approved"])

    def test_wrong_nonce_never_accepted(self):
        with self.assertRaisesRegex(ValueError, "challenge"):
            probe(runner=fake_runner(lambda x: x | {"challenge": "a"*64}))

    def test_cannot_claim_production_restoration_or_custody(self):
        for name in ("production_recovery_approved", "real_backup_restored",
                     "minio_prod_image_identity_verified", "production_data_accessed",
                     "independent_custody_verified", "host_mounts_attached",
                     "host_ports_published"):
            with self.subTest(flag=name), self.assertRaisesRegex(ValueError, "unsafe"):
                probe(runner=fake_runner(lambda x: x | {name: True}))

    def test_external_network_or_cleanup_failure_block(self):
        for field, val in (("network_external", "bridge"), ("cleanup_verified", False)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                probe(runner=fake_runner(lambda x: x | {field: val}))

    def test_success_requires_complete_parity(self):
        for field in ("runtime_isolation_inspected", "server_cached_id_verified", "mc_cached_id_verified",
                      "synthetic_object_source_verified", "synthetic_object_copy_verified",
                      "negative_integrity_control_rejected",
                      "sha256_matched_on_both_isolated_servers"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "incomplete"):
                probe(runner=fake_runner(lambda x: x | {field: False}))
        with self.assertRaisesRegex(ValueError, "size"):
            probe(runner=fake_runner(lambda x: x | {"object_byte_count": True}))

    def test_hold_is_not_promoted_and_transport_errors_fail(self):
        result = probe(runner=fake_runner(lambda x: x | {
            "status": "HOLD",
            "synthetic_object_source_verified": False,
            "synthetic_object_copy_verified": False,
        }))
        self.assertEqual(result["status"], "HOLD")
        with self.assertRaises(ValueError):
            probe(runner=fake_runner(code=255))
        with self.assertRaises(ValueError):
            probe(runner=fake_runner(lambda x: x | {"status": "production-ready"}))

    def test_only_fixed_prequalified_host_and_in_memory_code(self):
        with self.assertRaisesRegex(ValueError, "prequalified"):
            probe(host="production", runner=lambda *a, **kw: self.fail("SSH invoked"))
        self.assertIn('"--network","none"', REMOTE_CODE)
        self.assertIn('"--network","container:"+src', REMOTE_CODE)
        self.assertIn('"--tmpfs","/data:', REMOTE_CODE)
        self.assertIn("verify_runtime(src,\"none\")", REMOTE_CODE)
        self.assertIn("verify_runtime(dst,\"container:\"+src)", REMOTE_CODE)
        self.assertIn("{{json .HostConfig}}", REMOTE_CODE)
        self.assertIn("{{json .Mounts}}", REMOTE_CODE)
        self.assertNotIn("docker volume", REMOTE_CODE)
        self.assertNotIn("docker compose", REMOTE_CODE)

    def test_malformed_json_remote_cannot_pass(self):
        def bad(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=b"not-json")
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            probe(runner=bad)
        def huge(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=b"x"*8000)
        with self.assertRaisesRegex(ValueError, "bounded"):
            probe(runner=huge)


class ActualDockerIsolationInspectionTests(unittest.TestCase):
    """Execute only the remote isolation function, with synthetic Docker metadata."""

    def _run(self, changes=None, *, mounts=None, image=None, target=False):
        function=next(item for item in ast.parse(REMOTE_CODE).body
                      if isinstance(item,ast.FunctionDef) and item.name=="verify_runtime")
        compiled=compile(ast.Module(body=[function],type_ignores=[]),"<safe-fixture>","exec")
        image_id="sha256:a98a9d647e700e45c1d3d2e44709f23952a39c199731d84e623eb558fd5501f4"
        source_id="c"*64
        config={"NetworkMode":"container:"+source_id if target else "none",
                "ReadonlyRootfs":True,"Privileged":False,"PublishAllPorts":False,
                "PortBindings":{},"Binds":None,"Mounts":None,
                "Tmpfs":{"/data":"rw,nosuid,size=67108864",
                         "/tmp":"rw,nosuid,size=33554432"},
                "PidsLimit":128,"Memory":536870912,"NanoCpus":500000000}
        config.update(changes or {})
        def inspected(argv,*,deadline=8):
            marker=argv[3]
            assert argv[:3]==["docker","inspect","--format"]
            assert deadline<=8
            if marker=="{{json .HostConfig}}":return json.dumps(config).encode()
            if marker=="{{json .Mounts}}":return json.dumps([] if mounts is None else mounts).encode()
            if marker=="{{.Image}}":return (image or image_id).encode()
            if marker=="{{.Id}}":return source_id.encode()
            raise AssertionError("unexpected Docker inspection")
        scope={"must":inspected,"json":json,"SERVER":image_id,"src":"src"}
        exec(compiled,scope)
        return scope["verify_runtime"]("dst" if target else "src",
                                       "container:src" if target else "none")

    def test_actual_isolation_fields_and_docker_network_id_normalization(self):
        self._run()
        self._run(target=True)

    def test_each_docker_isolation_escape_fails_closed(self):
        violations={"NetworkMode":"bridge","ReadonlyRootfs":False,
                    "Privileged":True,"PublishAllPorts":True,
                    "PortBindings":{"9000/tcp":[{"HostPort":"9000"}]},
                    "Binds":["/production:/data"],"Mounts":[{"Type":"bind"}],
                    "Tmpfs":{"/tmp":"rw"},"PidsLimit":0,
                    "Memory":0,"NanoCpus":0}
        for field,value in violations.items():
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,"runtime_isolation_mismatch"):
                self._run({field:value})
        with self.assertRaisesRegex(ValueError,"runtime_image_or_mounts_mismatch"):
            self._run(mounts=[{"Type":"volume"}])
        with self.assertRaisesRegex(ValueError,"runtime_image_or_mounts_mismatch"):
            self._run(image="sha256:"+"0"*64)
        with self.assertRaisesRegex(ValueError,"runtime_isolation_mismatch"):
            self._run({"NetworkMode":"container:unexpected"},target=True)


if __name__ == "__main__":
    unittest.main()
