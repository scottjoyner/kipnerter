#!/usr/bin/env python3
"""Source-only stateless preview archive. Never authorizes deployment or recovery."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_FILES = 512
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MANIFEST = "stateless-fleet-manifest.json"
SOURCES = {"docker-compose.yml", "compose.fleet-preview.yml"}
REQUIRED = SOURCES | {"apps/web/Dockerfile", "apps/web/package.json",
    "apps/web/package-lock.json", "apps/api/Dockerfile",
    "apps/api/requirements.txt"}
BANNED = {".git", ".next", "node_modules", "__pycache__", ".venv", "dist"}

def allowed(name):
    if not isinstance(name, str) or not name or len(name) > 400:
        return False
    if "\\" in name or any(ord(c) < 32 for c in name):
        return False
    parts = name.split("/")
    if any(not part or part in (".", "..") or part in BANNED or
           (part.startswith(".") and part != ".dockerignore") for part in parts):
        return False
    return name in SOURCES or name.startswith(("apps/web/", "apps/api/"))

def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], timeout=20)

def inventory(root, sha):
    if not SHA.fullmatch(sha):
        raise ValueError("invalid exact Git SHA")
    if git(root, "rev-parse", "HEAD").decode().strip() != sha:
        raise ValueError("checkout HEAD differs from requested commit")
    files = []
    total = 0
    for row in git(root, "ls-tree", "-r", "-z", "HEAD").split(b"\x00"):
        if not row:
            continue
        header, name = row.split(b"\t", 1)
        path = name.decode("utf-8", "strict")
        if not allowed(path):
            continue
        mode, kind, blob = header.decode("ascii").split(" ")
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ValueError("symlink/submodule forbidden")
        data = git(root, "cat-file", "blob", blob)
        total += len(data)
        if len(data) > MAX_FILE or total > MAX_TOTAL or len(files) >= MAX_FILES:
            raise ValueError("stateless source exceeds bounded limits")
        files.append((path, int(mode[-3:], 8), data))
    files.sort()
    if not REQUIRED.issubset({r[0] for r in files}):
        raise ValueError("missing stateless source")
    return files

def manifest_for(sha, files):
    return {"version": 1, "purpose": "stateless_fleet_preview_source_only",
        "platform_sha": sha, "contains_spatial_data": False,
        "deployment_authorized": False,
        "files": [{"path": n, "mode": m, "bytes": len(d),
                    "sha256": hashlib.sha256(d).hexdigest()} for n, m, d in files]}

def build(root, sha, output):
    files = inventory(root, sha)
    output = Path(output)
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError("output must not exist")
    meta = manifest_for(sha, files)
    raw_meta = (json.dumps(meta, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd, name = tempfile.mkstemp(prefix=".stateless-bundle-", dir=output.parent)
    os.fchmod(fd, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as gz:
                with tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as tar:
                    for path, mode, data in files + [(MANIFEST, 0o600, raw_meta)]:
                        info = tarfile.TarInfo(path)
                        info.mode = mode
                        info.uid = info.gid = info.mtime = 0
                        info.size = len(data)
                        tar.addfile(info, io.BytesIO(data))
            stream.flush()
            os.fsync(stream.fileno())
        verify(name, sha)
        os.replace(name, output)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return hashlib.sha256(output.read_bytes()).hexdigest()

def verify(archive, sha):
    if not SHA.fullmatch(sha):
        raise ValueError("invalid expected SHA")
    seen = {}
    total = 0
    with tarfile.open(archive, mode="r:gz") as tar:
        for member in tar:
            path = member.name
            if (path in seen or
                (not allowed(path) and path != MANIFEST) or
                not member.isfile() or member.mode not in (0o600, 0o644, 0o755) or
                member.uid != 0 or member.gid != 0 or member.mtime != 0 or
                member.size > MAX_FILE or len(seen) >= MAX_FILES + 1):
                raise ValueError("unsafe or duplicate archive entry")
            total += member.size
            if total > MAX_TOTAL:
                raise ValueError("expansion exceeds bound")
            entry = tar.extractfile(member)
            if entry is None:
                raise ValueError("unreadable archive entry")
            data = entry.read(member.size + 1)
            if len(data) != member.size:
                raise ValueError("archive entry size mismatch")
            seen[path] = (member.mode, data)
    if MANIFEST not in seen or not REQUIRED.issubset(seen):
        raise ValueError("missing manifest or essential source")
    meta = json.loads(seen.pop(MANIFEST)[1])
    if (not isinstance(meta, dict) or set(meta) != {
            "version", "purpose", "platform_sha", "contains_spatial_data",
            "deployment_authorized", "files"
        } or meta["version"] != 1 or
        meta["purpose"] != "stateless_fleet_preview_source_only" or
        meta["platform_sha"] != sha or meta["contains_spatial_data"] is not False or
        meta["deployment_authorized"] is not False or
        not isinstance(meta["files"], list)):
        raise ValueError("manifest intent and revision mismatch")
    expected = manifest_for(sha, [(n, m, d) for n, (m, d) in sorted(seen.items())])
    if meta != expected:
        raise ValueError("archive manifest differs from actual source")
    return {"platform_sha": sha, "verified_files": len(seen),
            "contains_spatial_data": False, "deployment_authorized": False}

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    b = sub.add_parser("build")
    b.add_argument("--root", required=True)
    b.add_argument("--sha", required=True)
    b.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--archive", required=True)
    v.add_argument("--sha", required=True)
    args = parser.parse_args()
    try:
        if args.action == "build":
            result = {"archive_sha256": build(args.root, args.sha, args.out),
                      "deployment_authorized": False}
        else:
            result = verify(args.archive, args.sha)
    except (OSError, ValueError, UnicodeError, subprocess.CalledProcessError,
            tarfile.TarError, json.JSONDecodeError):
        raise SystemExit("NO_GO: stateless archive provenance invalid") from None
    print(json.dumps(result, sort_keys=True))

if __name__ == "__main__":
    main()
