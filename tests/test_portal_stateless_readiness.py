import unittest
from scripts.portal_stateless_readiness import REQUIRED, classify

REV = "a" * 40


def complete():
    out = {x: "opaque-value" for x in REQUIRED}
    out.update({
        "TSIDP_ISSUER": "https://id.tail1234.ts.net",
        "FLEET_MONITOR_BASE_URL": "https://observer.tail1234.ts.net",
        "KIPNERTER_ALLOWED_EMAILS": "tester@example.org",
        "KIPNERTER_ALLOWED_TSIDP_SUBJECTS": "signed-tsidp-subject-123",
        "KIPNERTER_DEPLOY_HOST": "kipnerter-staging-01",
        "KIPNERTER_DEPLOY_USER": "kipnerter",
        "NEXTAUTH_SECRET": "N" * 40,
        "TSIDP_CLIENT_SECRET": "T" * 36,
        "FLEET_MONITOR_TOKEN": "F" * 40,
        "KIPNERTER_GATEWAY_TOKEN": "K" * 40,
    })
    return out


class StatelessReadinessTests(unittest.TestCase):
    def test_empty_reports_only_missing_names_and_no_effects(self):
        report = classify(REV, {})
        self.assertEqual(report["configuration_gate"], "NO_GO")
        self.assertEqual(report["configured_count"], 0)
        self.assertEqual(set(report["missing_setting_names"]), set(REQUIRED))
        self.assertFalse(report["production_deploy_authorized"])
        self.assertFalse(report["public_ingress_authorized"])

    def test_full_config_is_candidate_not_live_browser_or_deploy_proof(self):
        values = complete()
        values.update(KIPNERTER_DATA_RECOVERY_WITNESS_SHA=REV,
                      KIPNERTER_CUTOVER_APPROVED_SHA=REV)
        report = classify(REV, values)
        self.assertEqual(report["configuration_gate"], "PASS_CANDIDATE")
        self.assertEqual(report["missing_setting_names"], [])
        self.assertEqual(report["invalid_checks"], [])
        for x in ("staging_host_identity_verified", "real_browser_oidc_verified",
                  "signed_restore_verified", "production_deploy_authorized",
                  "public_ingress_authorized", "production_modified"):
            self.assertIs(report[x], False)
        self.assertIs(report["requires_spatial_or_minio_credentials"], False)
        self.assertNotIn("tester@", str(report))
        self.assertNotIn("signed-tsidp", str(report))

    def test_partial_values_do_not_pass(self):
        values = complete()
        for key in REQUIRED:
            x = values.copy()
            x[key] = ""
            with self.subTest(setting=key):
                self.assertEqual(classify(REV, x)["configuration_gate"], "NO_GO")

    def test_unsafe_identity_and_public_origins_deny(self):
        for origin in ("http://id.tail1234.ts.net",
                       "https://id.tail1234.ts.net.evil.example",
                       "https://id.tail1234.ts.net/path",
                       "https://user:pass@id.tail1234.ts.net",
                       "https://localhost:8443",
                       "https://id.tail1234.ts.net?next=evil"):
            with self.subTest(origin=origin):
                x = complete()
                x["TSIDP_ISSUER"] = origin
                self.assertEqual(classify(REV, x)["configuration_gate"], "NO_GO")
        x = complete()
        x["FLEET_MONITOR_BASE_URL"] = "http://observer.tail1234.ts.net"
        self.assertEqual(classify(REV, x)["configuration_gate"], "NO_GO")
        x["FLEET_MONITOR_BASE_URL"] = "https://observer.tail1234.ts.net:8448"
        self.assertEqual(classify(REV, x)["configuration_gate"], "PASS_CANDIDATE")
        x["FLEET_MONITOR_BASE_URL"] = "https://observer.tail1234.ts.net:8090"
        self.assertEqual(classify(REV, x)["configuration_gate"], "NO_GO")

    def test_production_or_root_staging_host_denies(self):
        for host in ("kipnerter-prod-01", "prod.node", "Kipnerter-staging", "-bad"):
            x = complete()
            x["KIPNERTER_DEPLOY_HOST"] = host
            with self.subTest(host=host):
                self.assertEqual(classify(REV, x)["configuration_gate"], "NO_GO")
        x = complete()
        x["KIPNERTER_DEPLOY_USER"] = "root"
        self.assertEqual(classify(REV, x)["configuration_gate"], "NO_GO")

    def test_email_and_subject_allowlist_controls(self):
        for field, bad in [
            ("KIPNERTER_ALLOWED_EMAILS", "tester@example.org, attacker@example.org"),
            ("KIPNERTER_ALLOWED_EMAILS", "tester@example.org,tester@example.org"),
            ("KIPNERTER_ALLOWED_EMAILS", "WRONG@EXAMPLE.ORG"),
            ("KIPNERTER_ALLOWED_TSIDP_SUBJECTS", "trusted,untrusted\n"),
            ("KIPNERTER_ALLOWED_TSIDP_SUBJECTS", "subject-1,subject-1"),
        ]:
            with self.subTest(field=field, bad=bad):
                x = complete()
                x[field] = bad
                if bad == "tester@example.org, attacker@example.org":
                    self.assertIn("KIPNERTER_ALLOWED_EMAILS_INVALID",
                                  classify(REV, x)["invalid_checks"])
                else:
                    self.assertEqual(classify(REV, x)["configuration_gate"], "NO_GO")

    def test_invalid_sha_and_short_tokens_fail(self):
        for revision in ("", "A" * 40, "a" * 39, "x" * 40):
            with self.assertRaises(ValueError):
                classify(revision, complete())
        for key in ("NEXTAUTH_SECRET", "FLEET_MONITOR_TOKEN",
                    "KIPNERTER_GATEWAY_TOKEN", "TSIDP_CLIENT_SECRET"):
            x = complete()
            x[key] = "short"
            self.assertIn(key + "_INVALID", classify(REV, x)["invalid_checks"])


if __name__ == "__main__":
    unittest.main()
