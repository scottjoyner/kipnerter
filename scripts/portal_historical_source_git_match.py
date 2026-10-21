#!/usr/bin/env python3
"""Offline historical Git/source-receipt integrity check. NOT original OCI recovery."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

REV = "05955fef99cb83bfb2b4d4fb75664266e1ba385c"
EXPECTED_SHA = "68475f07e32adcc783bba4ec02faf44709bff90ae8e77024b7206d2871d3a07b"
DOCKER = {
    "apps/api/Dockerfile": "691fa56601ad18c98e96595aee2d738c5b52fe6445e75dee6269843a3bf106f4",
    "apps/web/Dockerfile": "f7df4a0f05209509328e6319c2c4375a22f35b1e64bcbcec950b1ecd41f6c7fa",
}
ROOT = {"docker-compose.yml", "compose.spatial.yml"}
TREES = ("apps/api/", "apps/web/", "infra/caddy/")
SKIP = {".git", ".next", "node_modules", "__pycache__", ".venv", ".pytest_cache", ".cache", "dist", "build", "coverage", ".turbo"}
EXT = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".css", ".html", ".txt", ".toml", ".yml", ".yaml", ".md", ".json", ".sh", ".svg", ".png", ".ico", ".webp", ".gif", ".jpeg", ".jpg", ".wasm"}
DENY = (".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db", ".log", ".zip", ".tar", ".gz", ".env", ".sql", ".jsonl", ".trace", ".gguf", ".safetensors")

def allowed(path):
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        return False
    parts = path.split("/")
    if any(not x or x in (".", "..") or x.startswith(".env") or x in SKIP for x in parts):
        return False
    if path in ROOT:
        return True
    if not path.startswith(TREES):
        return False
    leaf = parts[-1].lower()
    return not leaf.startswith("id_") and not leaf.endswith(DENY) and (
        Path(leaf).suffix in EXT or leaf in ("dockerfile", "requirements.txt", "package.json", "package-lock.json")
    )

def verify(files, *, expected_sha=EXPECTED_SHA, expected_count=15, docker=DOCKER):
    if len(files) != expected_count or not (ROOT | set(docker)).issubset(files):
        raise ValueError("source inventory differs from preserved receipt")
    h = hashlib.sha256()
    size = 0
    for name, content in sorted(files.items()):
        if not allowed(name) or not isinstance(content, bytes) or len(content) > 16 * 1024**2:
            raise ValueError("unsafe historical source entry")
        size += len(content)
        if size > 128 * 1024**2:
            raise ValueError("unbounded historical source")
        h.update(name.encode() + b"\x00" + hashlib.sha256(content).digest())
    if h.hexdigest() != expected_sha:
        raise ValueError("Git source differs from preserved archive receipt")
    for name, expected in docker.items():
        if hashlib.sha256(files[name]).hexdigest() != expected:
            raise ValueError("Dockerfile fingerprint mismatch")
    return {
        "status": "HISTORICAL_GIT_SOURCE_MATCH_NOT_OCI",
        "git_revision": REV, "source_file_count": len(files),
        "source_receipt_manifest_verified": True,
        "dockerfile_fingerprints_verified": True,
        "web_lockfile_present": "apps/web/package-lock.json" in files,
        "independent_custody_verified": False,
        "original_oci_images_recovered": False,
        "runnable_rollback_verified": False,
        "production_modified": False, "safe_to_cutover": False,
    }

def from_git(directory):
    base = ["git", "-C", str(directory)]
    def command(*args):
        return subprocess.run(base + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=12, check=True).stdout
    if command("rev-parse", "--verify", REV + "^{commit}").decode().strip() != REV:
        raise ValueError("pinned historical commit unavailable")
    rows = command("ls-tree", "-r", "-z", REV, "--", "apps/api", "apps/web", "infra/caddy", "docker-compose.yml", "compose.spatial.yml")
    if len(rows) > 1000000:
        raise ValueError("unbounded historical Git tree")
    found = {}
    for row in rows.split(b"\x00"):
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        path = raw_path.decode("utf-8")
        if not allowed(path):
            continue
        mode, kind, oid = metadata.decode("ascii").split()
        if mode not in ("100644", "100755") or kind != "blob" or not re.fullmatch("[a-f0-9]{40,64}", oid) or path in found:
            raise ValueError("unsafe or linked Git entry")
        size = command("cat-file", "-s", oid).decode().strip()
        if not size.isdecimal() or int(size) > 16 * 1024**2:
            raise ValueError("Git source too large")
        content = command("cat-file", "blob", oid)
        if len(content) != int(size):
            raise ValueError("truncated Git source")
        found[path] = content
        if len(found) > 8000:
            raise ValueError("too many source inputs")
    return found

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        outcome = verify(from_git(args.repository))
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        outcome = {"status": "HOLD", "safe_to_cutover": False, "original_oci_images_recovered": False}
        print(json.dumps(outcome, sort_keys=True))
        return 2
    print(json.dumps(outcome, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
