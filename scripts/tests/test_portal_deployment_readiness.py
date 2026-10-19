import unittest
from scripts.portal_deployment_readiness import classify, REQUIRED, STAGING

PIN = "a" * 40

def filled(environment):
    x = {key:"x"*40 for key in REQUIRED + (STAGING if environment=="staging" else ())}
    x.update({
        "TSIDP_ISSUER":"https://id.example.invalid",
        "FLEET_MONITOR_BASE_URL":"https://observer.example.invalid",
        "KIPNERTER_SPATIAL_DB_PASSWORD":("a" * 24),
        "KIPNERTER_CUTOVER_APPROVED_SHA": PIN,
        "KIPNERTER_DATA_RECOVERY_WITNESS_SHA": PIN,
        "KIPNERTER_DEPLOY_USER":"kipnerter",
    })
    return x

class ReadinessTests(unittest.TestCase):
    def test_empty_staging_does_not_implicitly_target_production(self):
        result = classify("staging", PIN, {})
        self.assertEqual(result["configuration_gate"],"NO_GO")
        self.assertIn("KIPNERTER_DEPLOY_HOST",result["missing_secret_names"])
        self.assertIn("TSIDP_ISSUER",result["missing_secret_names"])
        self.assertFalse(result["authorized_for_cutover"])

    def test_empty_production_is_hold(self):
        result=classify("production",PIN,{})
        self.assertEqual(result["configuration_gate"],"NO_GO")
        self.assertNotIn("KIPNERTER_DEPLOY_HOST",result["missing_secret_names"])
        self.assertIn("KIPNERTER_DATA_RECOVERY_WITNESS_SHA",result["missing_secret_names"])

    def test_all_config_only_candidate_never_authorizes_deployment(self):
        result=classify("staging",PIN,filled("staging"))
        self.assertEqual(result["configuration_gate"],"PASS_CANDIDATE")
        self.assertFalse(result["authorized_for_cutover"])
        self.assertFalse(result["oidc_live_login_verified"])
        self.assertFalse(result["data_restore_rehearsal_verified"])

    def test_stale_witness_sha_denied(self):
        x=filled("production");x["KIPNERTER_CUTOVER_APPROVED_SHA"]="b"*40
        self.assertIn("KIPNERTER_CUTOVER_APPROVED_SHA_REVISION_MISMATCH",
                      classify("production",PIN,x)["invalid_secret_checks"])

    def test_insecure_secret_denied_without_printing_value(self):
        x=filled("production");x["NEXTAUTH_SECRET"]="TOP_SECRET"
        result=classify("production",PIN,x)
        self.assertIn("NEXTAUTH_SECRET_TOO_SHORT",result["invalid_secret_checks"])
        self.assertNotIn("TOP_SECRET",str(result))

    def test_staging_root_denied(self):
        x=filled("staging");x["KIPNERTER_DEPLOY_USER"]="root"
        self.assertIn("KIPNERTER_DEPLOY_USER_ROOT_DENIED",
            classify("staging",PIN,x)["invalid_secret_checks"])

    def test_invalid_sha_and_environment_denied(self):
        for sha in ("", "HEAD", "A"*40, "../main"):
            with self.subTest(sha=sha),self.assertRaises(ValueError):
                classify("staging",sha,{})
        with self.assertRaises(ValueError): classify("dev",PIN,{})

    def test_insecure_oidc_denied(self):
        x=filled("production");x["TSIDP_ISSUER"]="http://localhost"
        self.assertIn("TSIDP_ISSUER_MUST_BE_HTTPS",
            classify("production",PIN,x)["invalid_secret_checks"])

if __name__ == "__main__":
    unittest.main()
