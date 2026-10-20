#!/usr/bin/env python3
"""Offline scratch restore of private 1.7 backup with NO access to live volumes.

The only durable new input is the previously captured private dump/tar. This
test starts uniquely named disposable containers with --network none, no ports,
synthetic credentials and a temporary MinIO data copy; tears them down always.
It is not independent external backup custody or cutover authorization.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import time

SOURCE = "ad4cffe6e1fe6c659d97e48a96d220f2f0543c55"
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_ARCHIVE = 3 * 1024**3


def call(args, *, timeout=30, env=None, stdin=None, capture=False):
    result = subprocess.run(args, timeout=timeout, env=env, stdin=stdin,
                            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=True)
    if capture and len(result.stdout) > 1024:
        raise ValueError("Docker command produced unexpectedly large metadata")
    return result.stdout.decode().strip() if capture else ""


def _open_private_backup_file(path: Path):
    """Open a private snapshot child through one pinned directory descriptor.

    Prevents symlink/FIFO/hardlink readers and path replacement between a
    preliminary pathname check and actual bytes read. No deletion/writes.
    """
    if path.name not in ("snapshot-receipt.json", "postgresql.custom",
                         "minio-raw-live.tar"):
        raise ValueError("unrecognized backup archive filename")
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY |
                           os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        dstat = os.fstat(directory_fd)
        if (not stat.S_ISDIR(dstat.st_mode) or dstat.st_uid != os.getuid()
                or dstat.st_mode & 0o077):
            raise ValueError("private backup directory untrusted")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                     os.O_CLOEXEC, dir_fd=directory_fd)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_nlink != 1):
                raise ValueError("untrusted backup file mode, owner or hardlink")
            return os.fdopen(fd, "rb")
        except BaseException:
            os.close(fd)
            raise
    finally:
        os.close(directory_fd)


def _unique_pairs(pairs):
    mapping = {}
    for key, value in pairs:
        if key in mapping:
            raise ValueError("duplicate backup receipt JSON field")
        mapping[key] = value
    return mapping


def _check_opened_archive(stream, expected: str, *, expected_bytes=None) -> None:
    """Hash a single pinned, private FD; caller may rewind and consume same FD."""
    if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("untrusted backup digest")
    if (expected_bytes is not None and
            (type(expected_bytes) is not int or not 0 < expected_bytes <= MAX_ARCHIVE)):
        raise ValueError("untrusted archive length")
    sha = hashlib.sha256()
    prior = os.fstat(stream.fileno())
    if prior.st_size == 0 or prior.st_size > MAX_ARCHIVE:
        raise ValueError("untrusted archive size")
    if expected_bytes is not None and prior.st_size != expected_bytes:
        raise ValueError("backup archive size mismatch")
    stream.seek(0)
    total = 0
    for chunk in iter(lambda: stream.read(1024*1024), b""):
        total += len(chunk)
        if total > MAX_ARCHIVE:
            raise ValueError("backup archive exceeds bound")
        sha.update(chunk)
    after = os.fstat(stream.fileno())
    if (total != prior.st_size or total != after.st_size or
            prior.st_mtime_ns != after.st_mtime_ns or
            prior.st_ctime_ns != after.st_ctime_ns):
        raise ValueError("backup archive changed during verification")
    if sha.hexdigest() != expected:
        raise ValueError("private archived bytes changed")
    stream.seek(0)


def archive_digest(path: Path, expected: str, *, expected_bytes=None) -> None:
    with _open_private_backup_file(path) as stream:
        _check_opened_archive(stream, expected, expected_bytes=expected_bytes)


def load_receipt(folder: Path) -> dict:
    with _open_private_backup_file(folder / "snapshot-receipt.json") as receipt:
        if os.fstat(receipt.fileno()).st_size > 65536:
            raise ValueError("private backup receipt oversized")
        raw = receipt.read(65537)
    if len(raw) > 65536:
        raise ValueError("private backup receipt exceeded size cap")
    report = json.loads(raw, object_pairs_hook=_unique_pairs)
    if (not isinstance(report, dict) or type(report.get("schema")) is not int or
            report["schema"] != 1 or report.get("source_staging_sha") != SOURCE or
            report.get("postgres_archive_toc_parsed") is not True or
            report.get("safe_to_cutover") is not False):
        raise ValueError("private backup receipt does not match exact rehearsal")
    required_false = (
        "postgres_database_restore_rehearsed",
        "minio_s3_level_restore_rehearsed",
        "minio_point_in_time_consistency_verified",
        "external_independent_custody_verified",
        "production_containers_changed",
        "production_volumes_written",
    )
    if (any(report.get(field) is not False for field in required_false) or
            type(report.get("minio_archive_members_checked")) is not int or
            not 2 <= report["minio_archive_members_checked"] <= 300000 or
            type(report.get("minio_payload_bytes_inspected")) is not int or
            not 0 < report["minio_payload_bytes_inspected"] <= MAX_ARCHIVE):
        raise ValueError("untrusted backup receipt fields or unsupported claims")
    for name, field, length in (
        ("postgresql.custom", "postgres_logical_dump_sha256", "postgres_dump_bytes"),
        ("minio-raw-live.tar", "minio_live_raw_copy_sha256", "minio_copy_bytes"),
    ):
        archive_digest(folder / name, report.get(field),
                       expected_bytes=report.get(length))
    return report


def checked_extract(archive: Path, root: Path, *, expected=None,
                    expected_bytes=None) -> Path:
    count = 0
    # Verify and extract through ONE already-open file descriptor, never
    # Path -> hash -> Path reopen (which permits race-based replacement).
    with _open_private_backup_file(archive) as raw:
        if expected is not None:
            _check_opened_archive(raw, expected, expected_bytes=expected_bytes)
        with tarfile.open(fileobj=raw, mode="r:") as tar:
            for member in tar:
                parts = member.name.split("/")
                if (member.name.startswith("/") or chr(92) in member.name or
                        any(part == ".." for part in parts) or
                        member.issym() or member.islnk() or
                        not (member.isdir() or member.isfile())):
                    raise ValueError("unsafe raw object data archive")
                count += 1
                if count > 300000:
                    raise ValueError("too many raw object archive entries")
            if count < 2:
                raise ValueError("empty raw object data archive")
            tar.extractall(root, filter="data")
    data = root / "data"
    if not data.is_dir() or data.is_symlink():
        raise ValueError("restored scratch MinIO directory is invalid")
    return data


def image_of(container: str) -> str:
    identity=call(["docker","inspect","--format","{{.Image}}",container],
                  capture=True)
    if not IMAGE_RE.fullmatch(identity):
        raise ValueError("untrusted or mutable source image identity")
    return identity


def scratch_postgres(archive: Path, *, expected: str, expected_bytes: int) -> int:
    image=image_of("kipnerter-spatial-postgres-1")
    name="kipnerter-rehearsal-pg-"+secrets.token_hex(5)
    password=secrets.token_urlsafe(32)
    environment=dict(os.environ, POSTGRES_PASSWORD=password)
    started=False
    try:
        call(["docker","run","-d","--rm","--name",name,
              "--network","none","--pids-limit","128","--memory","1536m",
              "--tmpfs","/var/lib/postgresql/data:rw,nosuid,size=1073741824",
              "--tmpfs","/tmp:rw,nosuid,size=67108864",
              "-e","POSTGRES_PASSWORD",image],
             timeout=30,env=environment)
        started=True
        for attempt in range(50):
            try:
                call(["docker","exec","-u","postgres",name,"pg_isready",
                      "-U","postgres","-d","postgres"],timeout=3)
                break
            except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
                time.sleep(.3)
        else:
            raise ValueError("scratch PostgreSQL did not become ready")
        call(["docker","exec","-u","postgres",name,
              "createdb","-U","postgres","kipnerter"],timeout=15)
        with _open_private_backup_file(archive) as raw:
            _check_opened_archive(raw, expected, expected_bytes=expected_bytes)
            call(["docker","exec","-i","-u","postgres",name,"pg_restore",
                  "--no-owner","--no-acl","-U","postgres","-d","kipnerter"],
                 timeout=120,stdin=raw)
        count=call(["docker","exec","-u","postgres",name,"psql",
                    "-U","postgres","-d","kipnerter","-Atqc",
                    "SELECT count(*) FROM pg_catalog.pg_tables WHERE "
                    "schemaname NOT LIKE 'pg_%' AND schemaname <> 'information_schema'"],
                   capture=True,timeout=12)
        if not re.fullmatch(r"[0-9]{1,6}",count):
            raise ValueError("unexpected restored schema count")
        return int(count)
    finally:
        if started:
            subprocess.run(["docker","rm","-f",name],stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,timeout=25)


def scratch_minio(archive: Path, backup_base: Path, *, expected: str, expected_bytes: int) -> bool:
    image=image_of("kipnerter-spatial-minio-1")
    name="kipnerter-rehearsal-minio-"+secrets.token_hex(5)
    user=secrets.token_urlsafe(22)
    pwd=secrets.token_urlsafe(35)
    started=False
    with tempfile.TemporaryDirectory(prefix="minio-rehearsal-",dir=backup_base) as tmp:
        scratch=checked_extract(archive, Path(tmp), expected=expected, expected_bytes=expected_bytes)
        environment=dict(os.environ,MINIO_ROOT_USER=user,MINIO_ROOT_PASSWORD=pwd)
        try:
            call(["docker","run","-d","--rm","--name",name,
                  "--network","none","--pids-limit","128","--memory","1024m",
                  "--user",f"{os.getuid()}:{os.getgid()}",
                  "--read-only","--tmpfs","/tmp:rw,nosuid,size=67108864",
                  "--mount",f"type=bind,src={scratch},dst=/data",
                  "-e","MINIO_ROOT_USER","-e","MINIO_ROOT_PASSWORD",
                  "-e","HOME=/tmp",image,"server","/data"],
                 timeout=35,env=environment)
            started=True
            for attempt in range(60):
                try:
                    call(["docker","exec",name,"curl","--fail","--silent",
                          "--max-time","2",
                          "http://127.0.0.1:9000/minio/health/ready"],
                         timeout=4)
                    return True
                except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
                    time.sleep(.25)
            raise ValueError("scratch MinIO did not become healthy")
        finally:
            if started:
                subprocess.run(["docker","rm","-f",name],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,timeout=25)
    return False


def main() -> int:
    try:
        home=Path.home()/".local/state/kipnerter-release"
        folder=home/"state-backups"/("ios17-precutover-"+SOURCE[:12])
        if (folder.is_symlink() or not folder.is_dir() or
                folder.stat().st_mode & 0o077):
            raise ValueError("untrusted snapshot custody folder")
        report=load_receipt(folder)
        if shutil.disk_usage(folder).free < 8*1024**3:
            raise ValueError("insufficient scratch restore headroom")
        schema_tables=scratch_postgres(
            folder/"postgresql.custom",
            expected=report["postgres_logical_dump_sha256"],
            expected_bytes=report["postgres_dump_bytes"])
        minio_ready=scratch_minio(
            folder/"minio-raw-live.tar", folder,
            expected=report["minio_live_raw_copy_sha256"],
            expected_bytes=report["minio_copy_bytes"])
        outcome={
            "source_sha": SOURCE,
            "postgres_restore_to_disposable_container":"PASS",
            "restored_user_tables_count":schema_tables,
            "minio_raw_copy_to_disposable_server":"PASS" if minio_ready else "HOLD",
            "disposable_containers_network":"none",
            "host_ports_published":False,
            "production_containers_or_volumes_modified":False,
            "independent_external_custody":False,
            "minio_object_inventory_compared_to_live":False,
            "minio_point_in_time_consistency_verified":False,
            "safe_to_cutover":False,
        }
        print(json.dumps(outcome,sort_keys=True))
        return 0 if minio_ready else 2
    except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError,
            tarfile.TarError,json.JSONDecodeError) as err:
        print(json.dumps({"result":"HOLD","reason_class":type(err).__name__,
                          "production_containers_or_volumes_modified":False,
                          "safe_to_cutover":False},sort_keys=True))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
