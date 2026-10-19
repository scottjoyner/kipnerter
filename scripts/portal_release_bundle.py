#!/usr/bin/env python3
"""Reproducible, tracked-source-only web/API release bundle and verifier.

Builds from two pinned *Git object databases*, never from dirty worktrees,
node_modules, .next, untracked local secrets, or nested .git folders. Verify
before remote extraction. Integrity proves consistency with pinned Git blobs,
not a code-signing identity, database rollback, or release approval.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import zlib

MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_ENTRIES = 10000
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
MANIFEST = "release-provenance.json"
ALLOWED_PREFIXES = ("apps/", "infra/", "scripts/")
ALLOWED_FILES = {"docker-compose.yml", "compose.spatial.yml", "compose.staging.yml"}
DENIED_PARTS = {".git", "node_modules", ".next", "__pycache__", ".venv", "venv", "dist", "coverage"}


def safe_path(path):
    if (not isinstance(path, str) or len(path) > 500 or not path
            or '\\' in path or '\n' in path or '\r' in path
            or path.startswith('/') or path.startswith('-') or '\x00' in path):
        raise ValueError("invalid bundle path")
    parts = path.split('/')
    if any(x in ('', '.', '..') or x in DENIED_PARTS or x.startswith('.env') for x in parts):
        raise ValueError("unsafe bundle path component")
    if str(PurePosixPath(path)) != path:
        raise ValueError("noncanonical bundle path")
    return path


def git(repo, *args, input=None):
    result = subprocess.run(['git', '-C', str(repo), *args], input=input,
                            capture_output=True, timeout=30, check=True)
    return result.stdout


def exact_sha(repo, ref):
    if not SHA40.fullmatch(ref):
        raise ValueError("release revisions must be exact 40-digit commit SHAs")
    actual = git(repo, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    if actual != ref:
        raise ValueError("checked-out release HEAD differs from requested exact commit")
    return ref


def git_entries(repo, prefix, allowed):
    raw = git(repo, 'ls-tree', '-r', '-z', 'HEAD')
    count = 0
    for row in raw.split(b'\x00'):
        if not row:
            continue
        header, raw_name = row.split(b'\t', 1)
        mode, typ, blob = header.decode('ascii').split(' ')
        name = raw_name.decode('utf-8', 'strict')
        if not allowed(name):
            continue
        dest = safe_path(prefix + name)
        if mode not in ('100644', '100755') or typ != 'blob' or not SHA40.fullmatch(blob):
            raise ValueError("release source contains symbolic link/submodule/special path")
        data = git(repo, 'cat-file', 'blob', blob)
        if len(data) > MAX_FILE:
            raise ValueError("tracked source exceeds per-file cap")
        count += 1
        if count > MAX_ENTRIES:
            raise ValueError("excessive release source entries")
        yield dest, int(mode[-3:], 8), data


def platform_file(name):
    return name in ALLOWED_FILES or name.startswith(ALLOWED_PREFIXES)


def spatial_file(name):
    return bool(name)  # safe_path enforces component restrictions


def build(platform_repo, spatial_repo, platform_sha, spatial_sha, output):
    exact_sha(platform_repo, platform_sha)
    exact_sha(spatial_repo, spatial_sha)
    output = Path(output)
    if output.is_symlink():
        raise ValueError("cannot replace linked release artifact")
    if output.exists():
        raise ValueError("release bundle already exists; refusing overwrite")
    all_files = list(git_entries(platform_repo, '', platform_file))
    all_files.extend(git_entries(spatial_repo, 'spatial-api/', spatial_file))
    all_files.sort(key=lambda x: x[0])
    if not all_files or len(all_files) > MAX_ENTRIES:
        raise ValueError("empty or oversized release")
    paths = [x[0] for x in all_files]
    if len(set(paths)) != len(paths):
        raise ValueError("overlapping release paths")
    for essential in ('docker-compose.yml', 'compose.spatial.yml',
                      'apps/web/Dockerfile', 'apps/api/Dockerfile',
                      'spatial-api/Dockerfile'):
        if essential not in paths:
            raise ValueError("missing required tracked release input")
    total = sum(len(data) for _, _, data in all_files)
    if total > MAX_TOTAL:
        raise ValueError("release payload exceeds bounded size")
    digest_items = [{'path': name, 'mode': mode, 'bytes': len(data),
                     'sha256': hashlib.sha256(data).hexdigest()}
                    for name, mode, data in all_files]
    manifest = {'version': 1, 'platform_sha': platform_sha,
                'spatial_api_sha': spatial_sha, 'files': digest_items}
    manifest_bytes = (json.dumps(manifest, separators=(',', ':'), sort_keys=True) + '\n').encode()
    if len(manifest_bytes) > MAX_FILE:
        raise ValueError("release manifest is too large")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.release-bundle-', dir=output.parent)
    os.fchmod(fd, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            with gzip.GzipFile(fileobj=stream, mode='wb', mtime=0, filename='') as compressed:
                with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
                    for name, mode, data in all_files + [(MANIFEST, 0o600, manifest_bytes)]:
                        member = tarfile.TarInfo(name)
                        member.uid = member.gid = 0
                        member.uname = member.gname = ''
                        member.mtime = 0
                        member.mode = mode
                        member.size = len(data)
                        archive.addfile(member, io.BytesIO(data))
            stream.flush()
            os.fsync(stream.fileno())
        verify(tmp, platform_sha, spatial_sha)
        os.replace(tmp, output)
        return manifest
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def verify(archive, platform_sha, spatial_sha):
    if not SHA40.fullmatch(platform_sha) or not SHA40.fullmatch(spatial_sha):
        raise ValueError("invalid pinned commit revision")
    archive = Path(archive)
    if archive.is_symlink() or not archive.is_file():
        raise ValueError("release archive missing or linked")
    if archive.stat().st_size > MAX_TOTAL + 8 * 1024 * 1024:
        raise ValueError("release archive exceeds size limit")
    # tarfile accepts otherwise-ignored trailing bytes in some gzip archives.
    # Reject concatenated streams, uncompressed appendices and decompression
    # bombs, so hidden extra data cannot ride along with reviewed source.
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    inflated = 0
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            remaining = MAX_TOTAL + MAX_FILE + 1 - inflated
            if remaining <= 0 or decoder.eof:
                raise ValueError("unexpected trailing or oversized gzip data")
            data = decoder.decompress(chunk, remaining)
            inflated += len(data)
            if decoder.unconsumed_tail or decoder.unused_data:
                raise ValueError("oversized or trailing gzip content")
    if not decoder.eof or inflated > MAX_TOTAL + MAX_FILE:
        raise ValueError("incomplete or oversized gzip stream")
    members = {}
    payload_size = 0
    with tarfile.open(archive, 'r:gz') as bundle:
        for item in bundle:
            name = safe_path(item.name)
            if (not item.isfile() or name in members or
                    (name != MANIFEST and not (platform_file(name) or name.startswith('spatial-api/'))) or
                    item.mode not in (0o600, 0o644, 0o755) or
                    item.size > MAX_FILE or len(members) >= MAX_ENTRIES + 1):
                raise ValueError("unsafe bundle entry")
            payload_size += item.size
            if payload_size > MAX_TOTAL + MAX_FILE:
                raise ValueError("decompressed bundle exceeds limit")
            content = bundle.extractfile(item).read(MAX_FILE + 1)
            if len(content) != item.size:
                raise ValueError("truncated release entry")
            members[name] = (item.mode, content)
    if MANIFEST not in members:
        raise ValueError("missing provenance manifest")
    provenance = json.loads(members.pop(MANIFEST)[1])
    if (not isinstance(provenance, dict) or set(provenance) !=
            {'version', 'platform_sha', 'spatial_api_sha', 'files'} or
            provenance['version'] != 1 or provenance['platform_sha'] != platform_sha or
            provenance['spatial_api_sha'] != spatial_sha or not isinstance(provenance['files'], list)):
        raise ValueError("wrong release provenance")
    listed = set()
    for row in provenance['files']:
        if not isinstance(row, dict) or set(row) != {'path','mode','bytes','sha256'}:
            raise ValueError("unexpected release manifest fields")
        name = safe_path(row['path'])
        if name in listed or name not in members or not SHA64.fullmatch(row['sha256']):
            raise ValueError("manifest references missing or duplicated file")
        listed.add(name)
        mode, data = members[name]
        if mode != row['mode'] or len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError("release file integrity mismatch")
    if listed != set(members):
        raise ValueError("unlisted release files")
    return provenance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['build', 'verify'])
    parser.add_argument('--platform-root', default='.')
    parser.add_argument('--spatial-root', default='spatial-api')
    parser.add_argument('--platform-sha', required=True)
    parser.add_argument('--spatial-sha', required=True)
    parser.add_argument('--archive', required=True)
    args = parser.parse_args()
    try:
        if args.operation == 'build':
            value = build(args.platform_root, args.spatial_root, args.platform_sha, args.spatial_sha, args.archive)
        else:
            value = verify(args.archive, args.platform_sha, args.spatial_sha)
        print('Release bundle verified: file_count=' + str(len(value['files'])))
    except (OSError, ValueError, subprocess.SubprocessError, UnicodeError, tarfile.TarError, KeyError, TypeError) as exc:
        raise SystemExit('RELEASE HOLD: source-pinned bundle rejected: ' + str(exc)) from None


if __name__ == '__main__':
    main()
