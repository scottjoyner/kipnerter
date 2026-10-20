"""Only private allowlisted old web/API source may enter rollback review."""
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.portal_legacy_source_preserve_once import (
    gather,private_dir,preflight,snapshot,FILENAME,RECEIPT
)


def fixture(root:Path):
    for part in ("apps/api/app","apps/web/app","infra/caddy"):
        (root/part).mkdir(parents=True,exist_ok=True)
    data={
        "docker-compose.yml":"services: {}\n",
        "compose.spatial.yml":"services: {}\n",
        "apps/api/Dockerfile":"FROM python:3.12-slim\n",
        "apps/api/requirements.txt":"fastapi\n",
        "apps/api/app/main.py":"print('safe')\n",
        "apps/web/Dockerfile":"FROM node:22-alpine\n",
        "apps/web/package.json":'{"name":"legacy-web"}\n',
        "apps/web/package-lock.json":'{"lockfileVersion":3}\n',
        "apps/web/app/page.jsx":"export default function Page(){}\n",
        "infra/caddy/Caddyfile":"localhost\n",
    }
    for key,value in data.items():
        (root/key).write_text(value)
    return data


class SourcePreserveTests(unittest.TestCase):
    def test_snapshot_contains_exact_allowlisted_source_not_env(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"release";root.mkdir()
            fixture(root)
            (root/".env").write_text("PRIVATE=secret")
            (root/"apps/web/.env.local").write_text("PRIVATE=secret")
            (root/"apps/web/node_modules").mkdir()
            (root/"apps/web/node_modules/private.js").write_text("secret")
            destination=Path(d)/"backup";destination.mkdir(mode=0o700)
            result=snapshot(root,destination)
            self.assertTrue(result["private_archive_created"])
            self.assertFalse(result["docker_images_recovered"])
            self.assertFalse(result["safe_to_cutover"])
            with tarfile.open(destination/FILENAME) as archive:
                names=archive.getnames()
                self.assertIn("apps/api/Dockerfile",names)
                self.assertIn("apps/web/app/page.jsx",names)
                self.assertNotIn(".env",names)
                self.assertNotIn("apps/web/.env.local",names)
                self.assertNotIn("apps/web/node_modules/private.js",names)
            self.assertEqual((destination/FILENAME).stat().st_mode&0o777,0o600)
            self.assertEqual((destination/RECEIPT).stat().st_mode&0o777,0o600)

    def test_retry_cannot_overwrite_source_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"release";root.mkdir();fixture(root)
            destination=Path(d)/"backup";destination.mkdir(mode=0o700)
            snapshot(root,destination)
            with self.assertRaisesRegex(ValueError,"already present"):
                snapshot(root,destination)

    def test_symlinked_app_source_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"release";root.mkdir();fixture(root)
            target=root/"apps/api/app/main.py"
            target.unlink()
            target.symlink_to("/etc/passwd")
            with self.assertRaisesRegex(ValueError,"linked"):
                gather(root)

    def test_missing_package_lock_is_preserved_as_explicit_nonreproducible_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"release";root.mkdir();fixture(root)
            (root/"apps/web/package-lock.json").unlink()
            destination=Path(d)/"backup";destination.mkdir(mode=0o700)
            check=preflight(root,destination)
            self.assertEqual(check["source_preflight"],"PASS")
            self.assertFalse(check["web_dependency_lock_present"])
            self.assertFalse(check["web_legacy_build_reproducibility_verified"])
            report=snapshot(root,destination)
            self.assertTrue(report["private_archive_created"])
            self.assertFalse(report["web_dependency_lock_present"])
            self.assertFalse(report["web_legacy_build_reproducibility_verified"])
            self.assertFalse(report["docker_images_recovered"])
            self.assertFalse(report["safe_to_cutover"])
            with tarfile.open(destination/FILENAME) as archive:
                self.assertNotIn("apps/web/package-lock.json",archive.getnames())

    def test_missing_package_manifest_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"release";root.mkdir();fixture(root)
            (root/"apps/web/package.json").unlink()
            with self.assertRaisesRegex(ValueError,"essential"):
                gather(root)

    def test_large_code_file_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"release";root.mkdir();fixture(root)
            with (root/"apps/api/app/large.py").open("wb") as file:
                file.truncate(17*1024**2)
            with self.assertRaisesRegex(ValueError,"invalid source"):
                gather(root)

    def test_backup_custody_must_be_private(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/"backup";folder.mkdir(mode=0o755)
            with self.assertRaisesRegex(ValueError,"custody"):
                private_dir(folder)

if __name__=="__main__":
    unittest.main()
