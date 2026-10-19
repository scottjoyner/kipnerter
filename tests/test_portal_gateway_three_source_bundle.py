"""Three-source portal release bundles enforce immutable independent API checkout.

No Docker deployment, network, production container or named-volume mutation.
"""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.portal_release_bundle import build, verify, stage_verified
from tests.test_portal_release_bundle import repo
from tests import test_portal_release_bundle as fixtures


class ThreeSourceBundleTests(unittest.TestCase):
    def fixture(self, root):
        platform, spatial, p, s = fixtures.SourcePinnedReleaseTests().make_fixture(root)
        (platform / "compose.gateway-031.yml").write_text("services:\n  api:\n    build: ./gateway-api\n")
        import subprocess
        subprocess.run(["git", "-C", str(platform), "add", "compose.gateway-031.yml"], check=True)
        subprocess.run(["git", "-C", str(platform), "commit", "-qm", "reviewed opt-in overlay"], check=True)
        p = subprocess.check_output(["git","-C",str(platform),"rev-parse","HEAD"],text=True).strip()
        gateway = root / "gateway"
        g = repo(gateway, {
            "Dockerfile": "FROM scratch\n",
            "app/main.py": "print('source pinned gateway')\n",
            "pyproject.toml": "[project]\nname = 'fixture'\nversion = '0.3.1'\n",
        })
        return platform, spatial, gateway, p, s, g

    def test_v2_reproducible_three_source_custody_with_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            platform, spatial, gateway,p,s,g=self.fixture(root)
            (gateway/"app/main.py").write_text("MUTATED UNCOMMITTED")
            (gateway/".env").write_text("never_ship=private")
            (gateway/"__pycache__").mkdir()
            (gateway/"__pycache__/secret.pyc").write_text("never_ship")
            one=root/"one.tar.gz";two=root/"two.tar.gz"
            value=build(platform,spatial,p,s,one,gateway,g)
            self.assertEqual(value["version"],2)
            self.assertEqual(value["gateway_api_sha"],g)
            self.assertEqual(verify(one,p,s,gateway_sha=g),value)
            build(platform,spatial,p,s,two,gateway,g)
            self.assertEqual(hashlib.sha256(one.read_bytes()).digest(),
                             hashlib.sha256(two.read_bytes()).digest())
            with tarfile.open(one,"r:gz") as src:
                names=src.getnames()
                self.assertIn("gateway-api/Dockerfile",names)
                self.assertIn("gateway-api/app/main.py",names)
                self.assertIn("compose.gateway-031.yml",names)
                self.assertNotIn("gateway-api/.env",names)
                self.assertNotIn("gateway-api/__pycache__/secret.pyc",names)
                self.assertEqual(src.extractfile("gateway-api/app/main.py").read(),
                                 b"print('source pinned gateway')\n")

    def test_no_v2_acceptance_without_explicit_gateway_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            a,b,g,p,s,h=self.fixture(root)
            output=root/"three.tar.gz"
            build(a,b,p,s,output,g,h)
            with self.assertRaisesRegex(ValueError,"unsafe bundle entry|wrong release provenance"):
                verify(output,p,s)
            with self.assertRaisesRegex(ValueError,"wrong release provenance"):
                verify(output,p,s,gateway_sha="f"*40)
            with self.assertRaisesRegex(ValueError,"gateway source and exact SHA"):
                build(a,b,p,s,root/"missing.tar.gz",g,None)

    def test_missing_or_untracked_gateway_overlay_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            a,b,g,p,s,h=self.fixture(root)
            # Verify original earlier platform commit before opt-in overlay was tracked.
            import subprocess
            older=subprocess.check_output(["git","-C",str(a),"rev-parse","HEAD^"],text=True).strip()
            subprocess.run(["git","-C",str(a),"checkout","--detach",older],check=True,
                           capture_output=True)
            with self.assertRaisesRegex(ValueError,"missing required tracked release input"):
                build(a,b,older,s,root/"missing.tar.gz",g,h)

    def test_gateway_revision_drift_refused_before_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            a,b,g,p,s,h=self.fixture(root)
            with self.assertRaisesRegex(ValueError,"differs"):
                build(a,b,p,s,root/"invalid.tar.gz",g,"a"*40)
            self.assertFalse((root/"invalid.tar.gz").exists())

    def test_receiver_stages_both_source_revisions_with_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            a,b,g,p,s,h=self.fixture(root)
            bundle=root/"candidate.tar.gz"
            build(a,b,p,s,bundle,g,h)
            digest=hashlib.sha256(bundle.read_bytes()).hexdigest()
            target=root/"private-stage"
            ready=stage_verified(bundle,p,s,digest,target,gateway_sha=h)
            self.assertTrue((ready/"gateway-api/Dockerfile").exists())
            self.assertTrue((ready/"compose.gateway-031.yml").exists())
            receipt=json.loads((ready/".portal-staged.json").read_text())
            self.assertEqual(receipt["gateway_api_sha"],h)
            self.assertEqual(receipt["archive_sha256"],digest)
            self.assertFalse((ready/".env").exists())
            with self.assertRaisesRegex(ValueError,"cannot overwrite"):
                stage_verified(bundle,p,s,digest,target,gateway_sha=h)


if __name__=="__main__":
    unittest.main()
