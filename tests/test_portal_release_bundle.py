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
            'Preserve and verify production application rollback snapshot',
            'Upload revision after verified rollback snapshot',
            'Build and deploy',
        )]
        self.assertEqual(events, sorted(events))
        self.assertIn('python3 - stage --platform-sha', workflow)
        self.assertIn('cp -a $VERIFIED/. /opt/kipnerter/', workflow)
        self.assertNotIn('tar -xzf - -C /opt/kipnerter', workflow)
        self.assertNotIn('sudo chown -R', workflow)

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
