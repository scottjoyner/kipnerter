import unittest
from scripts.portal_legacy_app_image_sources import classify_ref,classify

class OldApplicationImageSources(unittest.TestCase):
    def test_immutable_registry_digest(self):
        ref="registry.example.invalid/app@sha256:"+"a"*64
        self.assertEqual(classify_ref(ref),"registry_immutable_digest")

    def test_unpinned_tag_is_not_trusted(self):
        self.assertEqual(classify_ref("kipnerter-web:latest"),
                         "mutable_registry_or_local_tag")
        self.assertEqual(classify_ref("kipnerter-api"),"default_tag_or_local_build")

    def test_runtime_local_digest_without_cache_remains_hold(self):
        row=classify("web","kipnerter-web:latest","sha256:"+"a"*64,
                     "compose-config-hash",False,"b"*64)
        self.assertFalse(row["running_image_available_for_docker_save"])
        self.assertFalse(row["source_matches_running_image_layers_proven"])
        self.assertFalse(row["safe_to_cutover"])
        self.assertNotIn("kipnerter-web:latest",str(row))
        self.assertFalse(row["production_modified"])

    def test_registry_digest_does_not_imply_artifact_retrievable(self):
        ref="registry.example.invalid/backend@sha256:"+"f"*64
        row=classify("gateway",ref,"sha256:"+"b"*64,
                     "hash",False,"a"*64)
        self.assertFalse(row["registry_artifact_recovered_and_verified"])

    def test_container_env_or_uri_cannot_be_reference(self):
        for ref in ("https://private/token","user:pass@registry/app:tag",
                    "env=private secret","app name","app|echo sideeffect"):
            with self.subTest(ref=ref),self.assertRaises(ValueError):
                classify_ref(ref)

    def test_invalid_runtime_digest_denied(self):
        with self.assertRaises(ValueError):
            classify("gateway","image:tag","latest","",False,"a"*64)

    def test_missing_dockerfile_hash_denied(self):
        with self.assertRaises(ValueError):
            classify("web","image:tag","sha256:"+"a"*64,"",False,"bad")

if __name__=="__main__":
    unittest.main()
