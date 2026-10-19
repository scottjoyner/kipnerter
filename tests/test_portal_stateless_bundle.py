import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from scripts.portal_stateless_bundle import (
    REQUIRED, SHA, allowed, inventory, build, verify,
)


class StatelessArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config",
                        "user.email", "test@invalid.example"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config",
                        "user.name", "test"], check=True)
        for name in REQUIRED | {"apps/web/app/chat/page.js", "apps/api/app/main.py"}:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("source-" + name)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)
        self.sha = subprocess.check_output(["git", "-C", str(self.root),
                                            "rev-parse", "HEAD"], text=True).strip()
        self.archive = Path(self.tmp.name) / "bundle.tgz"

    def test_valid_archive_excludes_state(self):
        digest = build(self.root, self.sha, self.archive)
        self.assertEqual(len(digest), 64)
        report = verify(self.archive, self.sha)
        self.assertEqual(report["platform_sha"], self.sha)
        self.assertFalse(report["contains_spatial_data"])
        self.assertFalse(report["deployment_authorized"])
        with tarfile.open(self.archive) as archive:
            names = set(archive.getnames())
        self.assertFalse(any("minio" in p or "spatial-api/" in p
                             or ".env" in p for p in names))

    def test_build_is_reproducible(self):
        build(self.root, self.sha, self.archive)
        other = Path(self.tmp.name) / "second.tgz"
        build(self.root, self.sha, other)
        self.assertEqual(self.archive.read_bytes(), other.read_bytes())

    def test_rejects_wrong_revision_and_existing_output(self):
        with self.assertRaises(ValueError):
            build(self.root, "f" * 40, self.archive)
        build(self.root, self.sha, self.archive)
        with self.assertRaises(ValueError):
            build(self.root, self.sha, self.archive)
        with self.assertRaises(ValueError):
            verify(self.archive, "e" * 40)

    def test_path_and_secret_rejection(self):
        for path in ("../bad", "/etc/passwd", "apps/api/.env",
                     "apps/web/node_modules/index.js", "apps/api/x/../foo",
                     "spatial-api/Dockerfile", "compose.spatial.yml",
                     "apps/api/x\\t"):
            with self.subTest(path=path):
                self.assertFalse(allowed(path))
        self.assertTrue(allowed("apps/web/app/chat/page.js"))

    def test_symlink_in_git_source_denied(self):
        target = self.root / "apps/web/link"
        target.symlink_to("/etc/hosts")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "link"], check=True)
        sha = subprocess.check_output(["git", "-C", str(self.root),
                                       "rev-parse", "HEAD"], text=True).strip()
        with self.assertRaises(ValueError):
            inventory(self.root, sha)

    def test_corrupt_bytes_rejected(self):
        build(self.root, self.sha, self.archive)
        data = bytearray(self.archive.read_bytes())
        data[len(data) // 2] ^= 0xFF
        self.archive.write_bytes(data)
        with self.assertRaises((ValueError, tarfile.TarError, OSError, EOFError)):
            verify(self.archive, self.sha)

    def test_truncated_archive_rejected(self):
        build(self.root, self.sha, self.archive)
        self.archive.write_bytes(self.archive.read_bytes()[:20])
        with self.assertRaises((ValueError, tarfile.TarError, OSError, EOFError)):
            verify(self.archive, self.sha)


if __name__ == "__main__":
    unittest.main()
