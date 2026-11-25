"""Secret-free tests of live storage authority credential correlations."""
import contextlib
import io
import json
import sys
import unittest
from unittest.mock import patch
from scripts import portal_production_storage_authority_readonly as m

OK={"status":"WRITER_SURFACE_READ_ONLY_OBSERVED_NOT_FENCED","release_gate":"NO_GO","running_containers":7}

def bindings(user="admin",s3_root=True):
    root="fictionalroot"
    shared={"KIPNERTER_DATABASE_URL":f"postgresql+asyncpg://{user}:fake@pg:5432/db",
      "KIPNERTER_S3_ACCESS_KEY_ID":root if s3_root else "synthetic-scoped",
      "KIPNERTER_S3_SECRET_ACCESS_KEY":"fabricated_shared" if s3_root else "fabricated_scoped"}
    return {m.PG:{"POSTGRES_DB":"db"},m.S3:{"MINIO_ROOT_USER":root,"MINIO_ROOT_PASSWORD":"fabricated_shared"},
       m.CLIENTS[0]:dict(shared),m.CLIENTS[1]:dict(shared)}

class BindingCensus(unittest.TestCase):
    def test_default_never_inspects(self):
        with patch.object(sys,"argv",["probe"]),patch.object(m,"live_report",side_effect=AssertionError("must not inspect")):
            with patch("builtins.print") as p:self.assertEqual(m.main(),3)
        self.assertEqual(json.loads(p.call_args.args[0])["status"],"DRY_RUN_NO_DOCKER_OR_SQL")

    def test_wrong_host_denied(self):
        with patch.object(sys,"argv",["probe","--inspect-live"]),patch.object(m.socket,"gethostname",return_value="wrong"):
            with patch.object(m,"live_report",side_effect=AssertionError("must not inspect")):
                with patch("builtins.print") as p:self.assertEqual(m.main(),3)
        self.assertEqual(json.loads(p.call_args.args[0])["status"],"HOLD_UNAPPROVED_HOST")

    def test_docker_override_denied(self):
        with patch.object(sys,"argv",["probe","--inspect-live"]),patch.object(m.socket,"gethostname",return_value=m.surface.HOST):
            with patch.dict(m.os.environ,{"DOCKER_HOST":"tcp://other:2375"}):
                with patch.object(m,"live_report",side_effect=AssertionError("must not inspect")):
                    with patch("builtins.print") as p:self.assertEqual(m.main(),3)
        self.assertEqual(json.loads(p.call_args.args[0])["status"],"HOLD_DOCKER_TARGET_OVERRIDE")

    def test_observed_root_and_superuser_convergence(self):
        roles=m.parse_catalog(b"admin|t|t|t|t\n")
        result=m.classify(bindings(),roles,OK)
        self.assertEqual(result["postgres_configured_clients_using_privileged_roles"],2)
        self.assertEqual(result["s3_app_clients_using_root_access_identifier"],2)
        self.assertEqual(result["s3_app_clients_using_root_credential_pair"],2)
        self.assertTrue(result["postgres_app_clients_same_login"])
        self.assertEqual(result["release_gate"],"NO_GO")
        redacted=json.dumps(result)
        for secret in ("fabricated_shared",'"admin"',"fictionalroot"):self.assertNotIn(secret,redacted)

    def test_nonroot_still_hold(self):
        result=m.classify(bindings(user="scoped",s3_root=False),
          m.parse_catalog(b"scoped|f|t|f|f\nadmin|t|t|t|t\n"),OK)
        self.assertEqual(result["postgres_configured_clients_using_privileged_roles"],0)
        self.assertEqual(result["s3_app_clients_using_root_credential_pair"],0)
        self.assertEqual(result["status"],"HOLD_EXTERNAL_STORAGE_AUTHORITY_UNPROVEN")
        self.assertFalse(result["safe_to_cutover"])

    def test_untrusted_environment_fails_closed(self):
        with self.assertRaises(ValueError):
            m.environment({"Config":{"Env":["KIPNERTER_DATABASE_URL=one","KIPNERTER_DATABASE_URL=two"]}})

    def test_bad_role_catalog_rejected(self):
        for b in (b"",b"admin|x|t|f|f",b"admin|t|t|t|t\nadmin|t|t|t|t"):
            with self.subTest(b=b),self.assertRaises(ValueError):m.parse_catalog(b)

    def test_dsn_scheme_supports_app(self):
        self.assertEqual(m.pg_principal("postgresql+asyncpg://admin:fake@pg/db"),"admin")
        with self.assertRaises(ValueError):m.pg_principal("https://admin:secret@pg/db")

    def test_no_release_or_writer_fence_from_matching_accounts(self):
        r=m.classify(bindings(),m.parse_catalog(b"admin|t|t|t|t\n"),OK)
        self.assertFalse(r["minio_writes_fenced"])
        self.assertFalse(r["postgres_writes_fenced"])
        self.assertFalse(r["all_actual_connected_sessions_attributed"])
        self.assertFalse(r["s3_other_admin_or_external_access_excluded"])
