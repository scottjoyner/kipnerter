#!/usr/bin/env python3
"""Create and validate a private, versioned pre-deploy rollback snapshot.

Snapshot is intentionally *application files only*. Docker named volumes and
database migrations require separate backup/rollback authority. Production
deployment must stop if no previous release can be preserved and verified.
"""
import argparse
import hashlib
import hmac
import os
import re
import shutil
import stat
import tarfile
import tempfile
from pathlib import Path

MAX_TOTAL_BYTES = 8 * 1024**3
MAX_MEMBERS = 50000
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _root(path):
    path = Path(path).absolute()
    if not path.is_dir() or path.is_symlink() or path.resolve() != path:
        raise ValueError("deployment root missing, indirect, or not a directory")
    if path.stat().st_uid != os.getuid():
        raise ValueError("deployment root not owned by current operator")
    if not (path / "docker-compose.yml").is_file() or not (path / ".env").is_file():
        raise ValueError("no known deployed Compose application to preserve")
    if path.joinpath(".env").stat().st_mode & 0o077:
        raise ValueError("existing deployment secrets are not private")
    return path


def _private_dir(path, root):
    folder = Path(path).absolute()
    if folder == root or folder.is_relative_to(root):
        raise ValueError("backup directory may not be inside deployment")
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        raise ValueError("invalid backup directory")
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    if folder.resolve() != folder or folder.stat().st_uid != os.getuid():
        raise ValueError("untrusted backup directory")
    folder.chmod(0o700)
    return folder


def _entries(root):
    total = 0
    for base, dirs, files in os.walk(root, followlinks=False):
        base = Path(base)
        dirs[:] = sorted(x for x in dirs if x != ".git")
        for item in sorted(dirs + files):
            path = base / item
            st = path.lstat()
            if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                raise ValueError("special file or symlink in release snapshot")
            if st.st_uid != os.getuid():
                raise ValueError("unowned path in deployment")
            total += st.st_size if stat.S_ISREG(st.st_mode) else 0
            if total > MAX_TOTAL_BYTES:
                raise ValueError("release tree too large for bounded rollback")
            yield path, path.relative_to(root)


def _digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _validate_archive(archive):
    with tarfile.open(archive, "r:gz") as tar:
        seen = set()
        bytes_seen = 0
        for m in tar:
            p = Path(m.name)
            bytes_seen += m.size
            if (not p.parts or p.is_absolute() or ".." in p.parts or
                    str(p) != m.name or m.name in seen or
                    len(seen) >= MAX_MEMBERS or bytes_seen > MAX_TOTAL_BYTES or
                    not (m.isfile() or m.isdir())):
                raise ValueError("unsafe rollback archive contents")
            seen.add(m.name)
        if "docker-compose.yml" not in seen or ".env" not in seen:
            raise ValueError("rollback bundle is not a deployed application")
    return True


def snapshot(root, backup_dir, revision):
    if not SHA.fullmatch(revision):
        raise ValueError("revision must be an exact commit SHA")
    root = _root(root)
    backup_dir = _private_dir(backup_dir, root)
    # Reject running the backup under insufficiently available storage;
    # prefer an explicit HOLD over a silently incomplete rollback image.
    members = list(_entries(root))
    total = sum(p.stat().st_size for p, _ in members if p.is_file())
    if shutil.disk_usage(backup_dir).free < total + 128*1024*1024:
        raise ValueError("insufficient free capacity for release snapshot")
    dest = backup_dir / f"pre-{revision}.tar.gz"
    digest_file = backup_dir / f"pre-{revision}.sha256"
    if dest.exists() or digest_file.exists() or dest.is_symlink() or digest_file.is_symlink():
        raise ValueError("release snapshot already exists; never overwrite")
    fd, scratch = tempfile.mkstemp(prefix=".pre-release-", dir=backup_dir)
    os.fchmod(fd, 0o600)
    os.close(fd)
    try:
        with tarfile.open(scratch, "w:gz") as tar:
            for path, name in members:
                tar.add(path, arcname=str(name), recursive=False)
        _validate_archive(scratch)
        digest = _digest(Path(scratch))
        os.replace(scratch, dest)
        fd, tmpsha = tempfile.mkstemp(prefix=".checksum-", dir=backup_dir)
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(digest + "  " + dest.name + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmpsha, digest_file)
        return dest
    finally:
        if os.path.exists(scratch):
            os.unlink(scratch)


def validate(archive, digest_file):
    archive, digest_file = Path(archive), Path(digest_file)
    for path in (archive, digest_file):
        if (not path.is_file() or path.is_symlink() or
                path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077):
            raise ValueError("rollback file absent or not private")
    if archive.stat().st_size > MAX_TOTAL_BYTES:
        raise ValueError("rollback snapshot exceeds size cap")
    expected = digest_file.read_text().split()
    if len(expected) != 2 or expected[1] != archive.name or not DIGEST.fullmatch(expected[0]):
        raise ValueError("rollback checksum manifest invalid")
    if not hmac.compare_digest(_digest(archive), expected[0]):
        raise ValueError("rollback snapshot checksum mismatch")
    _validate_archive(archive)
    return True



def rehearse(archive, digest_file, destination):
    """Restore to a NEW private directory for visual/rehearsal inspection.

    This does not modify the current release or launch Docker containers.
    An operator must independently rehearse actual Compose rollback on a
    separate staging node before using the snapshot as a production recovery.
    """
    validate(archive, digest_file)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("rehearsal destination must not already exist")
    parent = destination.parent
    if not parent.is_dir() or parent.is_symlink() or parent.resolve() != parent:
        raise ValueError("untrusted rehearsal parent")
    destination.mkdir(mode=0o700)
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(destination, filter="data")
        if not (destination / "docker-compose.yml").is_file() or not (destination / ".env").is_file():
            raise ValueError("incomplete rehearsal application")
        return destination
    except BaseException:
        shutil.rmtree(destination)
        raise

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["snapshot", "verify", "rehearse"])
    parser.add_argument("--root", default="/opt/kipnerter")
    parser.add_argument("--backup-dir", default="/opt/kipnerter-release-backups")
    parser.add_argument("--revision")
    parser.add_argument("--destination", default="")
    args = parser.parse_args()
    try:
        if args.operation == "snapshot":
            if not args.revision:
                raise ValueError("revision required")
            bundle = snapshot(args.root, args.backup_dir, args.revision)
            validate(bundle, bundle.with_suffix("").with_suffix(".sha256"))
            print("Pre-deployment application snapshot created and SHA256 verified")
        else:
            if not args.revision or not SHA.fullmatch(args.revision):
                raise ValueError("revision required")
            bundle = Path(args.backup_dir) / f"pre-{args.revision}.tar.gz"
            verify_path = Path(args.backup_dir) / f"pre-{args.revision}.sha256"
            if args.operation == "verify":
                validate(bundle, verify_path)
                print("Rollback application bundle integrity verified")
            else:
                if not args.destination:
                    raise ValueError("separate rehearsal destination required")
                rehearse(bundle, verify_path, args.destination)
                print("Application rollback rehearsal extracted to separate directory")
    except (OSError, ValueError, tarfile.TarError) as exc:
        raise SystemExit("RELEASE HOLD: " + str(exc)) from None


if __name__ == "__main__":
    main()
