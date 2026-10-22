import json
from pathlib import Path
import subprocess
import sys
import unittest
from scripts.portal_state_recovery_preflight import analyze


def model(environment="staging"):
    project = "kipnerter-staging" if environment == "staging" else "kipnerter"
    api = "https://staging-api.kipnerter.com" if environment == "staging" else "https://api.kipnerter.com"
    service_env = {"KIPNERTER_ENVIRONMENT": environment,
                   "KIPNERTER_DATABASE_URL": "postgresql+asyncpg://test:SECRET@spatial-postgres:5432/kipnerter",
                   "KIPNERTER_S3_ENDPOINT_URL": "http://spatial-minio:9000",
                   "KIPNERTER_S3_PUBLIC_ENDPOINT_URL": api}
    m = {
        "name": project,
        "volumes": {v: {"name": project + "_" + v} for v in ("spatial_postgres_data", "spatial_minio_data")},
        "networks": {"spatial_backend": {"internal": True}, "frontend": {}},
        "services": {
            "spatial-postgres": {"image": "postgis/postgis:16-3.4",
                                 "volumes": [{"type":"volume","source":"spatial_postgres_data",
                                              "target":"/var/lib/postgresql/data"}],
                                 "networks": {"spatial_backend":None}},
            "spatial-minio": {"image": "minio/minio:latest",
                              "volumes": [{"type":"volume","source":"spatial_minio_data",
                                           "target":"/data"}],
                              "networks": {"spatial_backend":None,"frontend":None}},
            "spatial-api": {"environment": dict(service_env)},
            "spatial-worker": {"environment": dict(service_env)},
            "web": {"environment":{"NEXTAUTH_URL":"https://staging.kipnerter.com"}},
            "caddy": {"volumes":[{"type":"bind","source":"/tmp/fixture/Caddyfile.staging",
                                   "target":"/etc/caddy/Caddyfile","read_only":True}]},
        },
    }
    return m


class RecoveryPreflightTests(unittest.TestCase):
    def test_stage_and_production_isolated_storage_names(self):
        stage, prod = analyze(model(), "staging"), analyze(model("production"), "production")
        self.assertEqual(stage["project"], "kipnerter-staging")
        self.assertNotEqual(stage["topology_sha256"], prod["topology_sha256"])
        self.assertTrue(all(x["volume"].startswith("kipnerter-staging_") for x in stage["storage"]))
        self.assertTrue(all(x["volume"].startswith("kipnerter_") for x in prod["storage"]))
        self.assertFalse(stage["postgres_restore_executed"])
        self.assertFalse(stage["minio_restore_executed"])
        self.assertFalse(stage["production_recovery_approved"])
        self.assertEqual(len(stage["blocking_findings"]), 2)
        self.assertNotIn("SECRET", str(stage))

    def test_external_and_shared_volume_refused(self):
        for patch in ({"external":True},{"name":"kipnerter_spatial_postgres_data"},
                      {"driver_opts":{"device":"/production/storage"}}):
            stage=model()
            stage["volumes"]["spatial_postgres_data"].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                analyze(stage,"staging")

    def test_storage_bind_or_extra_mount_refused(self):
        for patch in ({"type":"bind"},{"source":"spatial_minio_data"},{"target":"/var/lib/pgdata"}):
            stage=model()
            stage["services"]["spatial-postgres"]["volumes"][0].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                analyze(stage,"staging")
        stage=model()
        stage["services"]["spatial-postgres"]["volumes"].append(
            {"type":"volume","source":"caddy_data","target":"/extra"})
        with self.assertRaises(ValueError):
            analyze(stage,"staging")

    def test_public_exposure_or_unsafe_network_refused(self):
        for patch in ({"ports":[{"published":5432,"target":5432}]},
                      {"network_mode":"host"},{"privileged":True}):
            stage=model()
            stage["services"]["spatial-postgres"].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                analyze(stage,"staging")
        stage=model()
        stage["networks"]["spatial_backend"]["internal"]=False
        with self.assertRaises(ValueError):
            analyze(stage,"staging")

    def test_staging_public_origin_and_backend_cannot_point_to_prod(self):
        mutations=[
            ("spatial-api","KIPNERTER_S3_PUBLIC_ENDPOINT_URL","https://api.kipnerter.com"),
            ("spatial-worker","KIPNERTER_ENVIRONMENT","production"),
            ("spatial-api","KIPNERTER_DATABASE_URL","postgresql://test:SECRET@prod.example/db"),
            ("spatial-worker","KIPNERTER_DATABASE_URL","http://test:SECRET@spatial-postgres:5432/kipnerter"),
            ("spatial-api","KIPNERTER_DATABASE_URL","postgresql+asyncpg://test:SECRET@spatial-postgres:9999/kipnerter"),
            ("spatial-api","KIPNERTER_S3_ENDPOINT_URL","https://prod-minio"),
            ("web","NEXTAUTH_URL","https://kipnerter.com"),
        ]
        for name,key,value in mutations:
            stage=model()
            stage["services"][name]["environment"][key]=value
            with self.subTest(service=name,key=key),self.assertRaises(ValueError):
                analyze(stage,"staging")
        stage=model()
        stage["services"]["caddy"]["volumes"][0]["source"]="/tmp/Caddyfile"
        with self.assertRaises(ValueError):
            analyze(stage,"staging")

    def test_pinned_images_remove_only_image_mutability_holds(self):
        stage=model()
        for name in ("spatial-postgres","spatial-minio"):
            stage["services"][name]["image"]=("postgis/postgis" if name=="spatial-postgres" else "minio/minio")+"@sha256:"+"a"*64
        evidence=analyze(stage,"staging")
        self.assertEqual(evidence["blocking_findings"], [])
        self.assertFalse(evidence["postgres_restore_executed"])

    def test_other_service_cannot_mount_stateful_volumes(self):
        stage=model()
        stage["services"]["spatial-worker"]["volumes"] = [
            {"type": "volume", "source": "spatial_postgres_data", "target": "/secret"}
        ]
        with self.assertRaisesRegex(ValueError, "unauthorized service"):
            analyze(stage, "staging")

    def test_image_reference_must_be_expected_family_and_exact_digest(self):
        for image in ("registry.invalid/foo@sha256:" + "a"*64,
                      "postgis/postgis@sha256:invalid", "postgis/postgis:latest"):
            stage=model()
            stage["services"]["spatial-postgres"]["image"] = image
            if image.startswith("registry"):
                with self.assertRaises(ValueError):
                    analyze(stage,"staging")
            else:
                result=analyze(stage,"staging")
                self.assertTrue(any("spatial-postgres" in x for x in result["blocking_findings"]))

    def test_cli_is_readonly_redacted_and_distinguishes_hold(self):
        source = Path(__file__).resolve().parents[1] / "scripts/portal_state_recovery_preflight.py"
        first = subprocess.run([sys.executable, str(source), "--environment", "staging"],
                               input=json.dumps(model()), text=True, capture_output=True,
                               timeout=6)
        self.assertEqual(first.returncode, 2, first.stderr)
        output = json.loads(first.stdout)
        self.assertTrue(output["topology_valid"])
        self.assertFalse(output["postgres_restore_executed"])
        self.assertFalse(output["minio_restore_executed"])
        self.assertNotIn("SECRET", first.stdout)
        self.assertEqual(len(output["blocking_findings"]), 2)
        bad = model()
        bad["volumes"]["spatial_postgres_data"]["external"] = True
        second = subprocess.run([sys.executable, str(source), "--environment", "staging"],
                                input=json.dumps(bad), text=True, capture_output=True,
                                timeout=6)
        self.assertNotEqual(second.returncode, 0)
        self.assertFalse(second.stdout.strip())
        self.assertNotIn("SECRET", second.stderr)

    def test_wrong_project_refused(self):
        with self.assertRaises(ValueError):
            analyze(model("production"),"staging")


if __name__ == "__main__":
    unittest.main()
