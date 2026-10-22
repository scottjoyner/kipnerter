"""Offline security invariants for separately retained historical-derived web recipe."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "recovery" / "legacy-derived-web"

class RecipeSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = json.loads((RECIPE / "package.json").read_text())
        cls.lock = json.loads((RECIPE / "package-lock.json").read_text())
        cls.dockerfile = (RECIPE / "Dockerfile").read_text()

    def test_known_app_and_nonmajor_security_update_only(self):
        self.assertEqual(self.package["name"], "@kipnerter/web")
        self.assertEqual(self.package["dependencies"], {
            "next": "15.5.28", "react": "19.1.9", "react-dom": "19.1.9",
        })
        self.assertEqual(self.package["overrides"], {"postcss": "8.5.31"})

    def test_lockfile_v3_matches_direct_dependencies_and_packages(self):
        self.assertEqual(self.lock.get("lockfileVersion"), 3)
        self.assertEqual(self.lock["packages"][""]["dependencies"],
                         self.package["dependencies"])
        for name, version in (("next", "15.5.28"), ("postcss", "8.5.31"),
                              ("react", "19.1.9"), ("react-dom", "19.1.9"),
                              ("sharp", "0.35.5")):
            with self.subTest(name=name):
                self.assertEqual(self.lock["packages"]["node_modules/"+name]["version"],
                                 version)

    def test_transitive_dependency_integrity_is_locked(self):
        packages=self.lock["packages"]
        self.assertGreaterEqual(len(packages), 40)
        for path, metadata in packages.items():
            if not path:continue
            with self.subTest(path=path):
                self.assertTrue(path.startswith("node_modules/"))
                self.assertIsInstance(metadata.get("integrity"), str)
                self.assertTrue(metadata["integrity"].startswith("sha512-"))
                self.assertFalse(metadata.get("link", False))

    def test_recipe_digests_identify_physically_tested_artifacts(self):
        expected={
            "Dockerfile":"2cd3c24c72d7fed2bf93306879cdf2506db0ce1bfeb6934cc9380ec4f05bf589",
            "package.json":"5ba63c7ac1564ab8014061bba9f34156cd47984c4d8a8c03ce9df02a9b5a574b",
            "package-lock.json":"b430338b28fe62a8ed9209b45891838e7d236cd93f4d6a8297f7c8335493b81a",
        }
        for filename,sha in expected.items():
            with self.subTest(filename=filename):
                self.assertEqual(hashlib.sha256((RECIPE/filename).read_bytes()).hexdigest(),sha)

    def test_dockerfile_pins_full_base_digest_and_fails_closed_on_audit(self):
        pinned="node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402"
        self.assertEqual(self.dockerfile.count("FROM "+pinned),3)
        self.assertIn("COPY package.json package-lock.json ./",self.dockerfile)
        self.assertIn("npm ci --ignore-scripts --no-fund",self.dockerfile)
        self.assertIn("&& npm audit --omit=dev --audit-level=high",self.dockerfile)
        self.assertIn("RUN npm run build",self.dockerfile)
        self.assertNotIn("RUN npm install",self.dockerfile)
        self.assertNotIn("|| true",self.dockerfile)

    def test_recipe_cannot_set_public_ports_host_mounts_or_prod_credentials(self):
        self.assertIn("EXPOSE 3000",self.dockerfile)
        forbidden=("ports:", "network_mode:", "docker compose up", "docker push",
                   "KIPNERTER_GATEWAY_TOKEN", "MINIO_ROOT_PASSWORD",
                   "POSTGRES_PASSWORD", "TS_OAUTH_SECRET",
                   "ARG DIGITALOCEAN", "--privileged")
        for term in forbidden:
            with self.subTest(term=term):
                self.assertNotIn(term,self.dockerfile)
        self.assertFalse((RECIPE / ".env").exists())
        self.assertFalse((RECIPE / "node_modules").exists())
        self.assertFalse((RECIPE / ".next").exists())

if __name__ == "__main__":
    unittest.main()
