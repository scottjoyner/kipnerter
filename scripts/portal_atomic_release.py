#!/usr/bin/env python3
"""Local, fail-closed atomic application-pointer switching, no Docker actions.

The installed root is explicitly *managed*, with private releases/<SHA> and a
'current' symlink referring ONLY to a verified prior release. An existing
legacy /opt/kipnerter checkout is NOT silently migrated. Named Compose volumes
and stateful schema migrations are deliberately outside this mechanism.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

SHA = re.compile(r"[a-f0-9]{40}\Z")
MANIFEST = ".portal-file-manifest.json"
MAX_ROWS = 10000
MAX_TOTAL = 256 * 1024 * 1024


def _sha(s):
    if not isinstance(s, str) or not SHA.fullmatch(s):
        raise ValueError("expected exact 40-character commit revision")
    return s


def _owned_private_dir(path):
    if (not path.is_dir() or path.is_symlink()
            or path.stat().st_uid != os.getuid() or
            path.stat().st_mode & 0o077):
        raise ValueError("managed release directory must be real, operator-owned and private")
    if path.resolve() != path:
        raise ValueError("managed release directory has indirect ancestors")


def _root(path):
    root = Path(os.path.abspath(path))
    _owned_private_dir(root)
    releases = root / "releases"
    _owned_private_dir(releases)
    current = root / "current"
    if not current.is_symlink() or current.lstat().st_uid != os.getuid():
        raise ValueError("legacy deployment or missing managed current link: HOLD")
    active = os.readlink(current)
    match = re.fullmatch(r"releases/([a-f0-9]{40})", active)
    if not match:
        raise ValueError("current link must reference exactly one managed revision")
    revision = match.group(1)
    dest = releases / revision
    _owned_private_dir(dest)
    return root, releases, current, revision


def _digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _validated_tree(folder, revision, enforce_name=True):
    _owned_private_dir(folder)
    if enforce_name and folder.name != revision:
        raise ValueError("mismatched named revision")
    manifest = folder / MANIFEST
    if (not manifest.is_file() or manifest.is_symlink() or
            manifest.stat().st_uid != os.getuid() or
            manifest.stat().st_mode & 0o077):
        raise ValueError("release manifest missing or not private")
    if manifest.stat().st_size > 1024 * 1024:
        raise ValueError("release manifest exceeds cap")
    meta = json.loads(manifest.read_text())
    if (not isinstance(meta, dict) or set(meta) != {"revision", "files"}
            or meta["revision"] != revision or
            not isinstance(meta["files"], list) or
            not 1 <= len(meta["files"]) <= MAX_ROWS):
        raise ValueError("invalid release integrity manifest")
    witnessed = set()
    total = 0
    for row in meta["files"]:
        if (not isinstance(row, dict) or set(row) != {"path", "sha256", "mode"}
                or not isinstance(row["path"], str) or
                not re.fullmatch(r"[a-f0-9]{64}", str(row["sha256"])) or
                type(row["mode"]) is not int or row["mode"] not in (0o600, 0o644, 0o755)):
            raise ValueError("invalid release manifest entry")
        parts = row["path"].split("/")
        if (any(x in ("", ".", "..") for x in parts) or
                any(x.startswith(".portal-") for x in parts) or
                row["path"] in witnessed or len(row["path"]) > 500):
            raise ValueError("unsafe or repeated manifest path")
        witnessed.add(row["path"])
        item = folder.joinpath(*parts)
        if item.is_symlink() or not item.is_file():
            raise ValueError("missing or linked release file")
        if (item.stat().st_uid != os.getuid() or
                stat.S_IMODE(item.stat().st_mode) != row["mode"]):
            raise ValueError("release file ownership or mode changed")
        total += item.stat().st_size
        if total > MAX_TOTAL or _digest(item) != row["sha256"]:
            raise ValueError("release source integrity changed")
    needed = {"docker-compose.yml", "compose.spatial.yml", "apps/web/Dockerfile",
              "apps/api/Dockerfile", "spatial-api/Dockerfile", ".env"}
    if not needed <= witnessed:
        raise ValueError("release missing application or private environment files")
    # Reject unlisted residual files, including stale assets from older
    # revisions, private keys, and symlinked folders.
    actual = set()
    for base, directories, files in os.walk(folder, followlinks=False):
        for directory in directories:
            path = Path(base) / directory
            if path.is_symlink() or path.stat().st_uid != os.getuid():
                raise ValueError("untrusted release directory entry")
        for name in files:
            path = Path(base) / name
            if path.name == MANIFEST and path.parent == folder:
                continue
            actual.add(path.relative_to(folder).as_posix())
            if path.is_symlink():
                raise ValueError("unlisted symlink in release")
    if witnessed != actual:
        raise ValueError("unlisted or missing files in revision")
    return meta



def prepare(root_path, verified_source, environment_file, revision):
    """Copy an independently staged bundle into a fresh managed release.

    This never selects/activates a revision. The operator must have explicitly
    initialized an isolated managed layout with an existing good release first.
    """
    revision = _sha(revision)
    root, releases, _, active = _root(root_path)
    _validated_tree(releases / active, active)
    if (releases / revision).exists() or (releases / revision).is_symlink():
        raise ValueError("revision already present; refusing overwrite")
    source = Path(os.path.abspath(verified_source))
    _owned_private_dir(source)
    if source.name != revision or source.is_relative_to(root):
        raise ValueError("verified source must be separate and match exact revision")
    receipt = source / ".portal-staged.json"
    if (receipt.is_symlink() or not receipt.is_file() or
            receipt.stat().st_uid != os.getuid() or
            receipt.stat().st_mode & 0o077 or receipt.stat().st_size > 1024 * 1024):
        raise ValueError("missing private source-receipt")
    record = json.loads(receipt.read_text())
    if (not isinstance(record, dict) or
            set(record) != {"platform_sha", "spatial_api_sha", "archive_sha256", "files"} or
            record["platform_sha"] != revision or
            not re.fullmatch(r"[a-f0-9]{40}", str(record["spatial_api_sha"])) or
            not re.fullmatch(r"[a-f0-9]{64}", str(record["archive_sha256"])) or
            not isinstance(record["files"], list) or
            not 1 <= len(record["files"]) <= MAX_ROWS):
        raise ValueError("untrusted staged receipt")
    env = Path(os.path.abspath(environment_file))
    if (env.is_symlink() or not env.is_file() or env.stat().st_uid != os.getuid()
            or stat.S_IMODE(env.stat().st_mode) != 0o600 or env.is_relative_to(source)
            or env.is_relative_to(root)):
        raise ValueError("candidate environment must be an external private regular file")
    if env.stat().st_size > 1024 * 1024:
        raise ValueError("candidate environment too large")
    seen = set()
    files = []
    total = 0
    for row in record["files"]:
        if (not isinstance(row, dict) or
                set(row) != {"path", "mode", "bytes", "sha256"}):
            raise ValueError("invalid provenance row")
        name = row["path"]
        if (not isinstance(name, str) or len(name) > 500 or
                name.startswith("/") or chr(92) in name or
                any(x in ("", ".", "..") or x.startswith(".env") for x in name.split("/")) or
                name in seen or
                type(row["bytes"]) is not int or not 0 <= row["bytes"] <= 32 * 1024 * 1024 or
                type(row["mode"]) is not int or row["mode"] not in (0o644, 0o755) or
                not re.fullmatch(r"[a-f0-9]{64}", str(row["sha256"]))):
            raise ValueError("unapproved staged source path or data")
        seen.add(name)
        file = source.joinpath(*name.split("/"))
        if file.is_symlink() or not file.is_file() or file.stat().st_uid != os.getuid():
            raise ValueError("staged source file missing or linked")
        if (stat.S_IMODE(file.stat().st_mode) != row["mode"] or
                file.stat().st_size != row["bytes"] or _digest(file) != row["sha256"]):
            raise ValueError("staged source modified after receipt validation")
        total += row["bytes"]
        if total > MAX_TOTAL:
            raise ValueError("staged source exceeds total bytes cap")
        files.append(file)
    # Staging receipts should contain exactly the manifest files + receipt;
    # no stale source file may slip into a newly prepared release.
    actual = set()
    for base, dirs, names in os.walk(source, followlinks=False):
        for folder in dirs:
            if (Path(base) / folder).is_symlink():
                raise ValueError("staged source has linked directory")
        for name in names:
            path = Path(base) / name
            if path.is_symlink():
                raise ValueError("staged source has linked file")
            if path == receipt:
                continue
            actual.add(path.relative_to(source).as_posix())
    if seen != actual:
        raise ValueError("unlisted file in staged source")
    scratch = Path(tempfile.mkdtemp(prefix=".prepare-", dir=releases))
    try:
        prepared_rows = []
        for row, source_file in zip(record["files"], files):
            dest = scratch.joinpath(*row["path"].split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with source_file.open("rb") as reader, dest.open("xb") as writer:
                digest = hashlib.sha256()
                count = 0
                for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                    count += len(chunk)
                    if count > 32 * 1024 * 1024:
                        raise ValueError("source changed during copy")
                    digest.update(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            if digest.hexdigest() != row["sha256"] or count != row["bytes"]:
                raise ValueError("source changed during preparation")
            dest.chmod(row["mode"])
            prepared_rows.append({"path": row["path"], "mode": row["mode"],
                                  "sha256": row["sha256"]})
        data = env.read_bytes()
        env_target = scratch / ".env"
        with env_target.open("xb") as writer:
            os.fchmod(writer.fileno(), 0o600)
            writer.write(data)
            writer.flush()
            os.fsync(writer.fileno())
        prepared_rows.append({"path": ".env", "mode": 0o600,
                              "sha256": hashlib.sha256(data).hexdigest()})
        receipt_file = scratch / MANIFEST
        with receipt_file.open("x") as writer:
            os.fchmod(writer.fileno(), 0o600)
            json.dump({"revision": revision, "files": prepared_rows}, writer,
                      separators=(",", ":"), sort_keys=True)
            writer.flush()
            os.fsync(writer.fileno())
        # scratch has a temporary name; validator must still verify everything
        # before an exact-SHA release can appear in the managed release store.
        _validated_tree(scratch, revision, enforce_name=False)
        os.rename(scratch, releases / revision)
        return releases / revision
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)

def inspect(root):
    root, releases, current, active = _root(root)
    _validated_tree(releases / active, active)
    return active


def switch(root, target, expected_current):
    target, expected_current = _sha(target), _sha(expected_current)
    root, releases, link, _ = _root(root)
    lock = root / ".portal-release.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if (st.st_uid != os.getuid() or not stat.S_ISREG(st.st_mode)
                or st.st_mode & 0o077):
            raise ValueError("unsafe cutover lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _, releases, link, active = _root(root)
        if active != expected_current or target == active:
            raise ValueError("current revision differs from authorized previous revision")
        _validated_tree(releases / active, active)
        _validated_tree(releases / target, target)
        # Only the small symlink pointer is atomically replaced. Durable
        # contents must have been prepared and verified separately.
        temp = root / (".current." + target)
        if os.path.lexists(temp):
            raise ValueError("cutover temporary pointer already exists")
        try:
            os.symlink("releases/" + target, temp)
            os.replace(temp, link)
            dfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if os.path.lexists(temp):
                os.unlink(temp)
        return {"previous": active, "active": target}
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("inspect", "switch", "prepare"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--revision")
    parser.add_argument("--expected-current")
    parser.add_argument("--verified-source")
    parser.add_argument("--environment-file")
    args = parser.parse_args()
    try:
        if args.action == "inspect":
            print("Active managed release: " + inspect(args.root))
        elif args.action == "prepare":
            candidate = prepare(args.root, args.verified_source,
                                args.environment_file, args.revision)
            print("Verified candidate prepared, not activated: " + candidate.name)
        else:
            result = switch(args.root, args.revision, args.expected_current)
            print("Atomic release pointer changed: " + result["previous"] +
                  " -> " + result["active"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit("RELEASE HOLD: atomic cutover rejected: " + str(exc)) from None


if __name__ == "__main__":
    main()
