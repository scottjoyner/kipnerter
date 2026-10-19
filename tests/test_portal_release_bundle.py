import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from scripts.portal_release_bundle import build, verify, stage_verified
from scripts.portal_atomic_release import prepare, switch, inspect
from tests.test_portal_atomic_release import managed, OLD


def run_git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def repo(path, files):
    path.mkdir(parents=True)
    run_git(path, 'init', '-q')
    run_git(path, 'config', 'user.name', 'Synthetic Tester')
    run_git(path, 'config', 'user.email', 'tester@example.test')
    for name, content in files.items():
        item = path / name
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_text(content)
    run_git(path, 'add', '.')
    run_git(path, 'commit', '-qm', 'synthetic inputs')
    return run_git(path, 'rev-parse', 'HEAD')


class SourcePinnedReleaseTests(unittest.TestCase):
    def make_fixture(self, root):
        platform = root / 'platform'
        spatial = root / 'spatial'
        p = repo(platform, {
            'docker-compose.yml': 'services: {}\n',
            'compose.spatial.yml': 'services: {}\n',
            'compose.staging.yml': 'services: {}\n',
            'apps/web/Dockerfile': 'FROM scratch\n',
            'apps/api/Dockerfile': 'FROM scratch\n',
            'apps/web/app/page.js': 'export default function Page() {}\n',
            'scripts/tool.py': 'print("safe")\n',
        })
        s = repo(spatial, {'Dockerfile': 'FROM scratch\n', 'src/main.py': 'print(42)\n'})
        return platform, spatial, p, s

    def test_exact_git_blobs_only_with_byte_for_byte_reproducibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform, spatial, p, s = self.make_fixture(root)
            (platform / '.env').write_text('REAL_SECRET_EXAMPLE=never_ship\n')
            (platform / 'apps/web/node_modules/private.js').parent.mkdir(parents=True)
            (platform / 'apps/web/node_modules/private.js').write_text('DO_NOT_SHIP\n')
            (platform / 'apps/web/.next/cache').mkdir(parents=True)
            (platform / 'apps/web/.next/cache/build.log').write_text('SECRET_UNTRACKED\n')
            (platform / 'apps/web/app/page.js').write_text('MUTATED_UNCOMMITTED_WORKTREE\n')
            (spatial / 'src/main.py').write_text('MODIFIED_UNCOMMITTED_SPATIAL\n')
            a = root / 'release-a.tgz'
            b = root / 'release-b.tgz'
            doc = build(platform, spatial, p, s, a)
            self.assertEqual(verify(a, p, s), doc)
            build(platform, spatial, p, s, b)
            self.assertEqual(hashlib.sha256(a.read_bytes()).hexdigest(),
                             hashlib.sha256(b.read_bytes()).hexdigest())
            with tarfile.open(a, 'r:gz') as tar:
                names = tar.getnames()
                self.assertIn('spatial-api/src/main.py', names)
                self.assertNotIn('.env', names)
                self.assertNotIn('apps/web/node_modules/private.js', names)
                self.assertNotIn('apps/web/.next/cache/build.log', names)
                self.assertEqual(tar.extractfile('apps/web/app/page.js').read(),
                                 b'export default function Page() {}\n')
            self.assertTrue(all('DO_NOT_SHIP' not in str(row) for row in doc['files']))
            self.assertEqual(os.stat(a).st_mode & 0o777, 0o600)

    def test_ref_drift_invalid_hash_and_archive_overwrite_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform, spatial, p, s = self.make_fixture(root)
            output = root / 'release.tgz'
            with self.assertRaisesRegex(ValueError, 'exact 40-digit'):
                build(platform, spatial, 'main', s, output)
            with self.assertRaisesRegex(ValueError, 'differs'):
                build(platform, spatial, 'a' * 40, s, output)
            build(platform, spatial, p, s, output)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                build(platform, spatial, p, s, output)
            with self.assertRaisesRegex(ValueError, 'wrong release provenance'):
                verify(output, 'f' * 40, s)
            with output.open('ab') as stream:
                stream.write(b'corrupted archive bytes')
            with self.assertRaisesRegex(ValueError, 'trailing gzip'):
                verify(output, p, s)

    def test_receiving_host_checks_exact_archive_before_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform, spatial, p, s = self.make_fixture(root)
            bundle = root / 'approved.tgz'
            build(platform, spatial, p, s, bundle)
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
            revision_store = root / 'private-verified'
            prepared = stage_verified(bundle, p, s, digest, revision_store)
            self.assertEqual(prepared.name, p)
            self.assertEqual((prepared/'apps/web/app/page.js').read_text(),
                             'export default function Page() {}\n')
            self.assertTrue((prepared/'spatial-api/Dockerfile').exists())
            self.assertEqual(revision_store.stat().st_mode & 0o077, 0)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                stage_verified(bundle, p, s, digest, revision_store)
            self.assertEqual(len(list(revision_store.iterdir())), 1)

    def test_receiving_host_rejects_wrong_hash_and_tampering_without_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform, spatial, p, s = self.make_fixture(root)
            bundle = root / 'approved.tgz'
            build(platform, spatial, p, s, bundle)
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
            prepared = root / 'private-verified'
            with self.assertRaisesRegex(ValueError, 'checksum differs'):
                stage_verified(bundle, p, s, 'f'*64, prepared)
            self.assertFalse(prepared.exists())
            with bundle.open('ab') as fd: fd.write(b'unreviewed bytes')
            with self.assertRaisesRegex(ValueError, 'checksum differs'):
                stage_verified(bundle, p, s, digest, prepared)
            self.assertFalse(prepared.exists())

    def test_receiving_host_rejects_world_readable_and_symlinked_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform, spatial, p, s = self.make_fixture(root)
            bundle = root / 'approved.tgz'
            build(platform, spatial, p, s, bundle)
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
            bundle.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'owned privately'):
                stage_verified(bundle, p, s, digest, root/'private')
            bundle.chmod(0o600)
            outsider = root/'untrusted'
            outsider.mkdir()
            (root/'alias').symlink_to(outsider, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'untrusted revision store'):
                stage_verified(bundle, p, s, digest, root/'alias')

    def test_remote_stdin_verifier_stages_only_exact_bytes(self):
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform, spatial, platform_sha, spatial_sha = self.make_fixture(root)
            incoming = root/'incoming.tgz'
            build(platform, spatial, platform_sha, spatial_sha, incoming)
            digest = hashlib.sha256(incoming.read_bytes()).hexdigest()
            source = (Path(__file__).resolve().parents[1] /
                      'scripts/portal_release_bundle.py').read_text()
            arguments = [sys.executable, '-', 'stage', '--platform-sha', platform_sha,
                         '--spatial-sha', spatial_sha, '--archive', str(incoming),
                         '--archive-sha256', digest, '--revisions-root', str(root/'verified')]
            result = subprocess.run(arguments, input=source, capture_output=True,
                                    text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('independently verified', result.stdout)
            self.assertTrue((root/'verified'/platform_sha/'spatial-api/Dockerfile').is_file())
            second = subprocess.run(arguments, input=source, capture_output=True,
                                    text=True, timeout=10)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn('cannot overwrite', second.stderr)

    def test_deploy_workflow_gates_promotion_after_receiver_verification(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    '.github/workflows/deploy.yml').read_text()
        events = [workflow.index(text) for text in (
            'Build immutable source bundle before tailnet access',
            'Resolve deployment target',
            'Receive and verify bundle on the actual destination',
            'Validate explicitly provisioned atomic release layout',
            'Preserve and verify production application rollback snapshot',
            'Upload revision after verified rollback snapshot',
            'Require independent cutover and data-recovery approval',
            'Validate and prebuild candidate before active cutover',
            'Atomically select the prepared revision and deploy',
            'Verify deployment health',
            'Confirm release after public and private health checks',
        )]
        self.assertEqual(events, sorted(events))
        self.assertIn('python3 - stage --platform-sha', workflow)
        self.assertIn('python3 - prepare --root /opt/kipnerter', workflow)
        self.assertIn('python3 - promote --root /opt/kipnerter', workflow)
        self.assertIn('python3 - confirm --root /opt/kipnerter', workflow)
        self.assertIn('python3 - status --root /opt/kipnerter', workflow)
        self.assertIn('if: success()', workflow)
        self.assertIn('cd /opt/kipnerter/releases/$GITHUB_SHA && docker compose', workflow)
        self.assertIn('up -d --no-build --remove-orphans', workflow)
        prebuild = workflow.split('      - name: Validate and prebuild candidate before active cutover')[1].split('      - name: Atomically select the prepared revision and deploy')[0]
        self.assertIn('build --pull', prebuild)
        self.assertNotIn(' up -d', prebuild)
        after_switch = workflow.split('      - name: Atomically select the prepared revision and deploy')[1].split('      - name: Verify deployment health')[0]
        self.assertNotIn('build --pull', after_switch)
        self.assertIn('KIPNERTER_CUTOVER_APPROVED_SHA', workflow)
        self.assertIn('KIPNERTER_DATA_RECOVERY_WITNESS_SHA', workflow)
        self.assertIn('docker compose -p $PROJECT', workflow)
        self.assertIn('/opt/kipnerter/current', workflow)
        self.assertNotIn('cp -a $VERIFIED/. /opt/kipnerter/', workflow)
        self.assertNotIn('cat > /opt/kipnerter/.env', workflow)
        self.assertNotIn("sed -n 's/^KIPNERTER_GATEWAY_TOKEN=", workflow)
        self.assertNotIn('tar -xzf - -C /opt/kipnerter', workflow)
        self.assertNotIn('sudo chown -R', workflow)

    def test_complete_verified_bundle_prepare_switch_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform, spatial, p, s = self.make_fixture(root)
            bundle = root / "received.tgz"
            build(platform, spatial, p, s, bundle)
            source = stage_verified(bundle, p, s,
                                    hashlib.sha256(bundle.read_bytes()).hexdigest(),
                                    root / "isolated-verified")
            self.assertTrue((source / ".portal-staged.json").is_file())
            actual = managed(root / "managed")
            environment = root / "candidate.env"
            environment.write_text("SYNTHETIC_STAGE_PASSWORD=not_a_real_secret\n")
            environment.chmod(0o600)
            deployed = prepare(actual, source, environment, p)
            self.assertEqual(deployed, actual/"releases"/p)
            self.assertEqual(inspect(actual), OLD)
            self.assertEqual((deployed / ".env").stat().st_mode & 0o777, 0o600)
            self.assertEqual(switch(actual, p, OLD)["active"], p)
            self.assertEqual(inspect(actual), p)
            self.assertEqual((actual / "current/apps/web/app/page.js").read_text(),
                             "export default function Page() {}\n")
            self.assertEqual(switch(actual, OLD, p)["active"], OLD)
            self.assertEqual(inspect(actual), OLD)

    def test_managed_candidate_prepare_via_exact_remote_stdin_program(self):
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform, spatial, p, s = self.make_fixture(root)
            bundle = root / "received.tgz"
            build(platform, spatial, p, s, bundle)
            source = stage_verified(bundle, p, s,
                                    hashlib.sha256(bundle.read_bytes()).hexdigest(),
                                    root / "verified")
            live = managed(root / "managed")
            envfile = root / "stage.env"
            envfile.write_text("SYNTHETIC_STAGE_KEY=this_is_only_a_fixture\n")
            envfile.chmod(0o600)
            script = (Path(__file__).resolve().parents[1] /
                      "scripts/portal_atomic_release.py").read_text()
            argv = [sys.executable, "-", "prepare", "--root", str(live),
                    "--verified-source", str(source),
                    "--environment-file", str(envfile), "--revision", p]
            proc = subprocess.run(argv, input=script, text=True,
                                  capture_output=True, timeout=12)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("not activated", proc.stdout)
            self.assertEqual(inspect(live), OLD)
            replay = subprocess.run(argv, input=script, text=True,
                                    capture_output=True, timeout=12)
            self.assertNotEqual(replay.returncode, 0)
            self.assertEqual(inspect(live), OLD)

    def test_prepare_rejects_forged_source_and_bad_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform, spatial, p, s = self.make_fixture(root)
            bundle = root / "received.tgz"
            build(platform, spatial, p, s, bundle)
            source = stage_verified(bundle, p, s,
                                    hashlib.sha256(bundle.read_bytes()).hexdigest(),
                                    root / "isolated-verified")
            actual = managed(root / "managed")
            environment = root / "candidate.env"
            environment.write_text("FAKE=synthetic\n")
            environment.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private"):
                prepare(actual, source, environment, p)
            environment.chmod(0o600)
            (source / "apps/web/app/page.js").write_text("mutation")
            with self.assertRaisesRegex(ValueError, "modified"):
                prepare(actual, source, environment, p)
            self.assertFalse((actual / "releases" / p).exists())
            self.assertEqual(inspect(actual), OLD)

    def test_tracked_symlinks_and_submodules_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform, spatial, p, s = self.make_fixture(root)
            link = platform / 'apps/web/private-link'
            link.symlink_to('/etc/passwd')
            run_git(platform, 'add', 'apps/web/private-link')
            run_git(platform, 'commit', '-qm', 'add symlink')
            with self.assertRaisesRegex(ValueError, 'symbolic link'):
                build(platform, spatial, run_git(platform, 'rev-parse', 'HEAD'), s,
                      root / 'should-not-exist.tgz')

    def test_changed_archive_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform, spatial, p, s = self.make_fixture(root)
            original = root / 'original.tgz'
            changed = root / 'tampered.tgz'
            build(platform, spatial, p, s, original)
            with tarfile.open(original, 'r:gz') as inp, tarfile.open(changed, 'w:gz') as out:
                for member in inp:
                    content = inp.extractfile(member).read()
                    if member.name == 'apps/web/app/page.js':
                        content = b'const secret = true;\n'
                        member.size = len(content)
                    out.addfile(member, io.BytesIO(content))
            with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                verify(changed, p, s)

    def test_unlisted_archive_members_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            platform, spatial, p, s = self.make_fixture(root)
            original = root / 'original.tgz'
            changed = root / 'unlisted.tgz'
            build(platform, spatial, p, s, original)
            with tarfile.open(original, 'r:gz') as inp, tarfile.open(changed, 'w:gz') as out:
                for member in inp:
                    out.addfile(member, io.BytesIO(inp.extractfile(member).read()))
                extra = tarfile.TarInfo('apps/web/untracked.py')
                extra.size = 3
                out.addfile(extra, io.BytesIO(b'bad'))
            with self.assertRaisesRegex(ValueError, 'unlisted release files'):
                verify(changed, p, s)


if __name__ == '__main__':
    unittest.main()
