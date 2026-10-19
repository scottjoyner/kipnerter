import copy
import io
import json
import unittest
from unittest.mock import patch

from scripts.portal_fleet_preview_preflight import ROOT, validate, main


def fixture():
    return {
        "name": "kipnerter-fleet-preview",
        "services": {
            "web": {
                "build": {"context": str(ROOT / "apps/web")},
                "ports": [{"host_ip": "127.0.0.1", "published": "13300",
                           "target": 3000, "protocol": "tcp"}],
                "environment": {"KIPNERTER_ENV": "staging",
                                "NEXTAUTH_URL": "https://staging.kipnerter.com",
                                "KIPNERTER_INTERNAL_API_URL": "http://api:8000"},
                "networks": {"frontend": None},
            },
            "api": {
                "build": {"context": str(ROOT / "apps/api")},
                "environment": {"KIPNERTER_ENV": "staging"},
                "networks": {"frontend": None, "backend": None},
            },
        },
        "networks": {"frontend": {}, "backend": {"internal": True}},
    }


class StatelessPreviewTests(unittest.TestCase):
    def test_valid_preview_is_not_release_approval(self):
        report = validate(fixture())
        self.assertFalse(report["deployment_authorized"])
        self.assertFalse(report["publicly_routable"])
        self.assertFalse(report["contains_persistent_storage"])
        self.assertEqual(report["services"], ["api", "web"])

    def test_rejects_unexpected_stateful_services_or_volumes(self):
        for key in ("spatial-minio", "spatial-postgres", "caddy", "malicious"):
            x = fixture()
            x["services"][key] = {"image": "example:latest"}
            with self.assertRaises(ValueError):
                validate(x)
        x = fixture()
        x["volumes"] = {"spatial_minio_data": {}}
        with self.assertRaises(ValueError):
            validate(x)

    def test_denies_nonloopback_and_multiple_ports(self):
        for host in ("0.0.0.0", "::", "100.101.102.103", None):
            x = fixture()
            x["services"]["web"]["ports"][0]["host_ip"] = host
            with self.assertRaises(ValueError):
                validate(x)
        x = fixture()
        x["services"]["api"]["ports"] = [{"host_ip": "127.0.0.1", "published": "18000"}]
        with self.assertRaises(ValueError):
            validate(x)

    def test_rejects_other_project_privileges_and_host_mounts(self):
        mutations = [
            lambda x: x.update(name="kipnerter"),
            lambda x: x["services"]["api"].update(privileged=True),
            lambda x: x["services"]["web"].update(volumes=[{"type": "bind", "source": "/"}]),
            lambda x: x["services"]["api"].update(devices=["/dev/sda"]),
            lambda x: x["services"]["api"].update(network_mode="host"),
            lambda x: x["services"]["api"].update(cap_add=["SYS_ADMIN"]),
            lambda x: x["networks"]["backend"].update(internal=False),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                x = fixture()
                mutate(x)
                with self.assertRaises(ValueError):
                    validate(x)

    def test_rejects_origin_and_observer_insecure_crossings(self):
        mutations = [
            lambda x: x["services"]["web"]["environment"].update(KIPNERTER_ENV="production"),
            lambda x: x["services"]["web"]["environment"].update(NEXTAUTH_URL="https://kipnerter.com"),
            lambda x: x["services"]["api"]["environment"].update(FLEET_MONITOR_BASE_URL="http://private"),
        ]
        for mutate in mutations:
            x = fixture()
            mutate(x)
            with self.assertRaises(ValueError):
                validate(x)


if __name__ == "__main__":
    unittest.main()
