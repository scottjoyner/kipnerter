"""Isolated local pointer cutover tests; never read real production directories."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.portal_atomic_release import MANIFEST, PENDING, inspect, switch, confirm, status

OLD = "a" * 40
NEW = "b" * 40


def prepared(folder, revision):
    folder.mkdir(mode=0o700)
    files = {
        "docker-compose.yml": "services: {}\n",
        "compose.spatial.yml": "services: {}\n",
        "apps/web/Dockerfile": "FROM scratch\n",
        "apps/api/Dockerfile": "FROM scratch\n",
        "spatial-api/Dockerfile": "FROM scratch\n",
        "apps/web/current-revision.txt": revision,
        ".env": "SIMULATED_TEST_TOKEN=dummy_test_string\n",
    }
    rows = []
    for rel, content in sorted(files.items()):
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(content)
        mode = 0o600 if rel == ".env" else 0o644
        path.chmod(mode)
        rows.append({"path": rel, "sha256": hashlib.sha256(content.encode()).hexdigest(),
                     "mode": mode})
    manifest = folder / MANIFEST
    manifest.write_text(json.dumps({"revision": revision, "files": rows}))
    manifest.chmod(0o600)


def managed(root):
    root.mkdir(mode=0o700)
    releases = root / "releases"
    releases.mkdir(mode=0o700)
    for rev in (OLD, NEW):
        prepared(releases / rev, rev)
    (root / "current").symlink_to("releases/" + OLD)
    return root


class AtomicPointerTests(unittest.TestCase):
    def test_switch_is_atomic_and_rollback_is_exact_expected_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = managed(Path(tmp) / "managed")
            self.assertEqual(inspect(root), OLD)
            result = switch(root, NEW, OLD)
            self.assertEqual(result, {"previous": OLD, "active": NEW})
            self.assertEqual(inspect(root), NEW)
            self.assertEqual((root / "current/apps/web/current-revision.txt").read_text(), NEW)
            self.assertEqual(switch(root, OLD, NEW)["active"], OLD)
            self.assertEqual(inspect(root), OLD)
            self.assertFalse(any(x.name.startswith(".current.") for x in root.iterdir()))

    def test_legacy_directory_refused_without_mutating_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "legacy"
            root.mkdir(mode=0o700)
            (root / "docker-compose.yml").write_text("services: {}\n")
            with self.assertRaisesRegex(ValueError, "managed"):
                switch(root, NEW, OLD)
            self.assertFalse((root / "current").exists())
            self.assertEqual((root / "docker-compose.yml").read_text(), "services: {}\n")

    def test_wrong_expected_sha_duplicate_and_missing_revisions_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = managed(Path(tmp) / "managed")
            for target, expected in ((NEW, NEW), (OLD, OLD), ("c"*40, OLD),
                                     ("bad", OLD)):
                with self.subTest(target=target, expected=expected):
                    with self.assertRaises(ValueError):
                        switch(root, target, expected)
            self.assertEqual(inspect(root), OLD)

    def test_tamper_unlisted_files_and_symlinks_refused(self):
        for attack in ("change", "unlisted", "link"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as tmp:
                root = managed(Path(tmp) / "managed")
                target = root / "releases" / NEW
                if attack == "change":
                    (target / "apps/web/current-revision.txt").write_text("replaced")
                if attack == "unlisted":
                    (target / "secret-unlisted").write_text("surprise")
                if attack == "link":
                    (target / "apps/web/current-revision.txt").unlink()
                    (target / "apps/web/current-revision.txt").symlink_to("/etc/hosts")
                with self.assertRaises(ValueError):
                    switch(root, NEW, OLD)
                self.assertEqual(inspect(root), OLD)

    def test_refuses_unmanaged_current_symlink_and_private_env_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = managed(Path(tmp) / "managed")
            (root / "current").unlink()
            (root / "current").symlink_to("/tmp")
            with self.assertRaisesRegex(ValueError, "current link"):
                switch(root, NEW, OLD)
            (root / "current").unlink()
            (root / "current").symlink_to("releases/" + OLD)
            (root / "releases" / NEW / ".env").chmod(0o644)
            with self.assertRaises(ValueError):
                switch(root, NEW, OLD)
            self.assertEqual(inspect(root), OLD)

    def test_nonblocking_lock_prevents_concurrent_cutover(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = managed(Path(tmp) / "managed")
            lock = root / ".portal-release.lock"
            with lock.open("w+") as stream:
                os.chmod(lock, 0o600)
                stream.flush()
                stream.fileno()
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    switch(root, NEW, OLD)
            self.assertEqual(inspect(root), OLD)

    def test_promote_leaves_durable_hold_until_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = managed(Path(tmp) / "managed")
            result = switch(root, NEW, OLD, track=True)
            self.assertEqual(result["active"], NEW)
            self.assertTrue((root / PENDING).is_file())
            self.assertEqual(status(root)["promotion"], "PENDING_HOLD")
            self.assertEqual(status(root)["pending_from"], OLD)
            self.assertEqual(status(root)["pending_to"], NEW)
            self.assertEqual((root / PENDING).stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, "unresolved prior release"):
                inspect(root)
            with self.assertRaisesRegex(ValueError, "pending release"):
                switch(root, OLD, NEW)
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                confirm(root, NEW, NEW)
            self.assertEqual(confirm(root, NEW, OLD), NEW)
            self.assertEqual(inspect(root), NEW)
            self.assertEqual(status(root)["promotion"], "not_pending")
            self.assertFalse((root / PENDING).exists())
            receipt = root / ".portal-confirmations" / (NEW + ".json")
            self.assertTrue(receipt.is_file())
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
            self.assertEqual(switch(root, OLD, NEW, track=True)["active"], OLD)
            self.assertEqual(confirm(root, OLD, NEW), OLD)
            self.assertEqual(inspect(root), OLD)

    def test_unfinished_promote_blocks_new_release_and_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = managed(Path(tmp) / "managed")
            # File-level pointer switch succeeded, but simulated Docker up
            # or public health check did not; do not acknowledge it.
            switch(root, NEW, OLD, track=True)
            with self.assertRaisesRegex(ValueError, "pending release"):
                switch(root, OLD, NEW, track=True)
            (root / "releases" / NEW / "apps/web/current-revision.txt").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "source integrity changed"):
                confirm(root, NEW, OLD)
            self.assertTrue((root / PENDING).is_file())

    def test_remote_promotion_confirmation_stdin_and_stale_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = managed(Path(tmp) / "managed")
            script = (Path(__file__).resolve().parents[1] /
                      "scripts/portal_atomic_release.py").read_text()
            def remote(action, previous, selected):
                return subprocess.run(
                    [sys.executable, "-", action, "--root", str(root),
                     "--revision", selected, "--expected-current", previous],
                    input=script, text=True, capture_output=True, timeout=8)
            first = remote("promote", OLD, NEW)
            self.assertEqual(first.returncode, 0, first.stderr)
            wrong = remote("confirm", NEW, OLD)
            self.assertNotEqual(wrong.returncode, 0)
            second = remote("confirm", OLD, NEW)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(inspect(root), NEW)
            replay = remote("confirm", OLD, NEW)
            self.assertNotEqual(replay.returncode, 0)
            self.assertIn("RELEASE HOLD", replay.stderr)

    def test_readonly_pending_status_via_remote_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = managed(Path(tmp) / "managed")
            switch(root, NEW, OLD, track=True)
            source = (Path(__file__).resolve().parents[1] /
                      "scripts/portal_atomic_release.py").read_text()
            run = subprocess.run(
                [sys.executable, "-", "status", "--root", str(root)],
                input=source, text=True, capture_output=True, timeout=8)
            self.assertEqual(run.returncode, 0, run.stderr)
            data = json.loads(run.stdout)
            self.assertEqual(data["promotion"], "PENDING_HOLD")
            self.assertEqual(data["active_revision"], NEW)
            self.assertNotIn(".env", run.stdout)

    def test_exact_remote_python_stdin_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = managed(Path(tmp) / "managed")
            source = (Path(__file__).resolve().parents[1] /
                      "scripts/portal_atomic_release.py").read_text()
            cmd = [sys.executable, "-", "switch", "--root", str(root),
                   "--revision", NEW, "--expected-current", OLD]
            done = subprocess.run(cmd, input=source, text=True,
                                  capture_output=True, timeout=8)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("Atomic release pointer changed", done.stdout)
            self.assertEqual(inspect(root), NEW)
            replay = subprocess.run(cmd, input=source, text=True,
                                    capture_output=True, timeout=8)
            self.assertNotEqual(replay.returncode, 0)
            self.assertIn("RELEASE HOLD", replay.stderr)


if __name__ == "__main__":
    unittest.main()
