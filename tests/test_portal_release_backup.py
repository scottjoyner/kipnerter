import os
import subprocess
import sys
import stat
import tempfile
import unittest
from pathlib import Path

from scripts.portal_release_backup import snapshot, validate, rehearse

REVISION = "a" * 40


class PortalReleaseBackupTests(unittest.TestCase):
    def test_private_versioned_snapshot_and_offline_rehearsal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "kipnerter"
            source.mkdir()
            (source / "docker-compose.yml").write_text("services: {}\n")
            (source / ".env").write_text("TEST_SECRET=synthetic_do_not_share\n")
            os.chmod(source / ".env", 0o600)
            (source / "src").mkdir()
            (source / "src" / "important.txt").write_text("old good revision")
            backups = base / "release-backups"
            bundle = snapshot(source, backups, REVISION)
            manifest = backups / f"pre-{REVISION}.sha256"
            self.assertTrue(validate(bundle, manifest))
            self.assertEqual(stat.S_IMODE(bundle.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(backups.stat().st_mode), 0o700)
            # Subsequent changes must not mutate the preserved copy.
            (source / "src" / "important.txt").write_text("new broken revision")
            restored = rehearse(bundle, manifest, base / "rollback-proof")
            self.assertEqual((restored / "src" / "important.txt").read_text(), "old good revision")
            self.assertEqual((restored / ".env").read_text(), "TEST_SECRET=synthetic_do_not_share\n")
            with self.assertRaisesRegex(ValueError, "already exists"):
                snapshot(source, backups, REVISION)

    def test_modified_archive_or_checksum_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "app"
            source.mkdir()
            (source / "docker-compose.yml").write_text("services: {}\n")
            (source / ".env").write_text("PRIVATE=synthetic\n")
            os.chmod(source / ".env", 0o600)
            bundle = snapshot(source, base / "private-backup", REVISION)
            manifest = base / "private-backup" / f"pre-{REVISION}.sha256"
            with bundle.open("ab") as f:
                f.write(b"tamper")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                validate(bundle, manifest)

    def test_ssh_stdin_style_cli_snapshot_and_verify(self):
        # The workflow streams this exact Python program to an already
        # authorized Tailscale SSH session rather than fetching unpinned code.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "existing-prod-app"
            root.mkdir()
            (root / "docker-compose.yml").write_text("services: {}\n")
            (root / ".env").write_text("FAKE_TEST_KEY=no_real_credentials\n")
            os.chmod(root / ".env", 0o600)
            script = (Path(__file__).resolve().parents[1] /
                      "scripts/portal_release_backup.py").read_text()
            backup = base / "private"
            args = [sys.executable, "-", "snapshot", "--root", str(root),
                    "--backup-dir", str(backup), "--revision", REVISION]
            proc = subprocess.run(args, input=script, text=True,
                                  capture_output=True, timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("FAKE_TEST_KEY", proc.stdout)
            check = subprocess.run([
                sys.executable, "-", "verify", "--root", str(root),
                "--backup-dir", str(backup), "--revision", REVISION,
            ], input=script, text=True, capture_output=True, timeout=10)
            self.assertEqual(check.returncode, 0, check.stderr)

    def test_legacy_git_rollback_refuses_tar_only_deployment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docker-compose.yml").write_text("services: {}\n")
            script = Path(__file__).resolve().parents[1] / "scripts/rollback.sh"
            env = os.environ.copy()
            env["KIPNERTER_ROOT"] = str(root)
            env["ROLLBACK_SHA"] = REVISION
            result = subprocess.run(["bash", str(script)], env=env,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 3)
            self.assertIn("no Git checkout", result.stderr)

    def test_missing_legacy_app_or_symlink_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "app"
            source.mkdir()
            (source / "docker-compose.yml").write_text("services: {}\n")
            with self.assertRaisesRegex(ValueError, "known deployed"):
                snapshot(source, base / "backup", REVISION)
            (source / ".env").write_text("SYNTHETIC=yes")
            os.chmod(source / ".env", 0o600)
            (source / "link").symlink_to("/etc/passwd")
            with self.assertRaisesRegex(ValueError, "symlink"):
                snapshot(source, base / "backup", REVISION)


if __name__ == "__main__":
    unittest.main()
