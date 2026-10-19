import unittest
from scripts.verify_api_recovery_portal_control_plane import assess, REQUIRED


def schema(routes):
    paths={}
    for method,path in routes:
        paths.setdefault(path,{})[method.lower()]={"operationId":method+path}
    return {"openapi":"3.0.3","paths":paths}


class GatewayPortalCompatibilityTests(unittest.TestCase):
    def test_standalone_recovery_must_not_drop_operator_control_plane(self):
        report=assess(schema(REQUIRED),schema({("GET","/health")}))
        self.assertEqual(report["compatibility"],"NO_GO")
        self.assertEqual(report["portal_control_plane_preserved"],0)
        self.assertEqual(len(report["missing_methods_and_paths"]),len(REQUIRED))
        self.assertFalse(report["safe_to_deploy"])

    def test_preserved_routes_necessary_but_not_sufficient(self):
        result=assess(schema(REQUIRED),schema(REQUIRED|{("GET","/health")}))
        self.assertEqual(result["compatibility"],"PASS_CANDIDATE")
        self.assertFalse(result["safe_to_deploy"])
        self.assertFalse(result["authorization_and_freshness_verified"])

    def test_portal_schema_change_requires_new_source_review(self):
        with self.assertRaisesRegex(ValueError,"portal source"):
            assess(schema({("GET","/health")}),schema(REQUIRED))

    def test_wrong_method_is_not_route_compatibility(self):
        change={(("POST" if m=="GET" else m),p) for m,p in REQUIRED}
        result=assess(schema(REQUIRED),schema(change))
        self.assertEqual(result["portal_control_plane_preserved"],0)

    def test_spec_tampering_denied(self):
        with self.assertRaises(ValueError):
            assess({"paths":None},schema(REQUIRED))

if __name__=="__main__":
    unittest.main()
