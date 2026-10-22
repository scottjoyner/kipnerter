#!/usr/bin/env python3
"""Synthetic-only scratch launch and backup/restore for two exact archived images.

Explicit --execute required, and restricted to the prequalified x1-370 host.
No production Docker/volumes, remote mounts, host ports, or external networks.
Container, tmpfs and temporary synthetic credentials are removed after each
probe. A pass NEVER means production data was backed up, restored or approved.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import secrets
import socket
import subprocess
import time

HOST = "x1-370"
IMAGES = {
    "postgres": ("postgis/postgis:16-3.4", "sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5"),
    "minio": ("minio/minio:latest", "sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e"),
}
REQUIRED_FLAGS = {"--network": "none", "--read-only": None, "--cap-drop": "ALL",
                  "--security-opt": "no-new-privileges", "--pids-limit": "128"}
FORBIDDEN = {"-v", "--volume", "--mount", "-p", "--publish", "--privileged",
             "--network=host", "--network=bridge", "--cap-add", "--device",
             "--pid", "--ipc", "--userns", "--volumes-from"}


def call(argv: list[str], *, input_bytes: bytes | None = None, timeout: int = 25,
         check: bool = True) -> bytes:
    p = subprocess.run(argv, input=input_bytes, capture_output=True, timeout=timeout)
    if check and p.returncode:
        # Do not dump image configurations, container environment or auth data.
        raise ValueError("isolated scratch command failed")
    return p.stdout if p.returncode == 0 else b""


def validate_argv(argv: list[str]) -> None:
    if len(argv) < 20 or argv[:2] != ["docker", "run"]:
        raise ValueError("not an approved Docker scratch launch")
    if any(token in FORBIDDEN or token.startswith(("--publish=", "--volume=", "--mount=")) for token in argv):
        raise ValueError("host exposure or real volume access forbidden")
    for flag, expected in REQUIRED_FLAGS.items():
        if argv.count(flag) != 1:
            raise ValueError("isolation flag absent")
        if expected is not None and (argv.index(flag) + 1 >= len(argv)
                                     or argv[argv.index(flag) + 1] != expected):
            raise ValueError("isolation flag altered")
    if (argv.count("--tmpfs") < 2 or argv.count("--rm") != 1
            or argv.count("-d") != 1 or argv.count("--user") != 1):
        raise ValueError("scratch disposable filesystem missing")
    if "--user" not in argv or not argv[argv.index("--user") + 1].count(":") == 1:
        raise ValueError("non-root runtime user required")


def image_ready(role: str) -> bool:
    tag, identity = IMAGES[role]
    try:
        return call(["docker", "image", "inspect", "--format", "{{.Id}}", tag], timeout=8).decode().strip() == identity
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def args_for(role: str, name: str, username: str, password: str) -> list[str]:
    image = IMAGES[role][1]
    argv = ["docker", "run", "--rm", "-d", "--name", name,
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "128",
            "--memory", "896m", "--cpus", "1"]
    if role == "postgres":
        argv += ["--user", "999:999",
                 "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,size=268435456,uid=999,gid=999,mode=0700",
                 "--tmpfs", "/var/run/postgresql:rw,nosuid,size=16777216,uid=999,gid=999,mode=0775",
                 "--tmpfs", "/tmp:rw,nosuid,size=16777216,uid=999,gid=999",
                 "--env", "PGDATA=/var/lib/postgresql/data/pgdata",
                 "--env", "POSTGRES_PASSWORD=" + password, "--env", "POSTGRES_DB=synthetic",
                 image]
    elif role == "minio":
        argv += ["--user", "10001:10001",
                 "--tmpfs", "/data:rw,nosuid,size=268435456,uid=10001,gid=10001,mode=0700",
                 "--tmpfs", "/tmp:rw,nosuid,size=134217728,uid=10001,gid=10001,mode=0700",
                 "--env", "HOME=/tmp", "--env", "MINIO_ROOT_USER=" + username,
                 "--env", "MINIO_ROOT_PASSWORD=" + password,
                 image, "server", "/data", "--address", "127.0.0.1:9000",
                 "--console-address", "127.0.0.1:9001"]
    else:
        raise ValueError("unknown scratch role")
    validate_argv(argv)
    return argv


def inspect_container(cid: str, role: str) -> None:
    obj = json.loads(call(["docker", "inspect", cid], timeout=8))[0]
    cfg = obj["HostConfig"]
    if (obj["Image"] != IMAGES[role][1] or cfg["NetworkMode"] != "none"
            or cfg["ReadonlyRootfs"] is not True or cfg["Privileged"] is not False
            or cfg.get("PortBindings") or cfg.get("CapDrop") != ["ALL"]
            or any(m.get("Type") in ("bind", "volume") for m in obj.get("Mounts", []))
            or not any(v in (cfg.get("SecurityOpt") or []) for v in ("no-new-privileges", "no-new-privileges:true"))
            or not 0 < cfg.get("PidsLimit", 0) <= 128):
        raise ValueError("real Docker container isolation denied")


def start(role: str, name: str, username: str, password: str) -> str:
    cid = call(args_for(role, name, username, password), timeout=25).decode().strip()
    if len(cid) != 64 or any(c not in "0123456789abcdef" for c in cid):
        raise ValueError("untrusted scratch container ID")
    try:
        inspect_container(cid, role)
    except BaseException:
        remove(cid)
        raise
    return cid


def remove(cid: str) -> None:
    subprocess.run(["docker", "rm", "-f", cid], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=25, check=False)


def postgres_synthetic() -> dict:
    username, password = "syntheticuser", secrets.token_urlsafe(28)
    name = "kipnerter-exact-archive-synthetic-pg-" + secrets.token_hex(6)
    cid = None
    try:
        cid = start("postgres", name, username, password)
        for _ in range(60):
            try:
                call(["docker", "exec", "-u", "postgres", cid, "pg_isready",
                      "-U", "postgres", "-d", "synthetic"], timeout=5)
                break
            except (ValueError, subprocess.SubprocessError):
                time.sleep(.5)
        else:
            raise ValueError("synthetic PostgreSQL did not become ready")
        call(["docker", "exec", "-u", "postgres", cid, "psql", "-X", "-v", "ON_ERROR_STOP=1",
              "-U", "postgres", "-d", "synthetic", "-c",
              "CREATE TABLE archive_probe (id INTEGER PRIMARY KEY, content TEXT NOT NULL);"
              "INSERT INTO archive_probe VALUES (42, 'SYNTHETIC_ONLY');"])
        call(["docker", "exec", "-u", "postgres", cid, "createdb", "-U", "postgres", "synthetic_restore"])
        dump = call(["docker", "exec", "-u", "postgres", cid, "pg_dump", "-U", "postgres",
                     "-Fc", "synthetic"], timeout=25)
        if not 100 <= len(dump) <= 4 * 1024 * 1024:
            raise ValueError("unexpected synthetic dump length")
        call(["docker", "exec", "-i", "-u", "postgres", cid, "pg_restore",
              "--no-owner", "--no-privileges", "-U", "postgres", "-d", "synthetic_restore"],
             input_bytes=dump, timeout=30)
        answer = call(["docker", "exec", "-u", "postgres", cid, "psql", "-X", "-Atq",
                       "-U", "postgres", "-d", "synthetic_restore", "-c",
                       "SELECT id||'|'||content FROM archive_probe ORDER BY id;"]).decode().strip()
        if answer != "42|SYNTHETIC_ONLY":
            raise ValueError("synthetic PostgreSQL restoration mismatch")
        return {"status": "SYNTHETIC_DUMP_RESTORE_PASS", "synthetic_dump_bytes": len(dump),
                "exact_running_image_id": IMAGES["postgres"][1]}
    finally:
        if cid:
            remove(cid)


def minio_synthetic() -> dict:
    username, password = "syntheticuser", secrets.token_urlsafe(30)
    names = ["kipnerter-exact-archive-synthetic-minio-" + secrets.token_hex(6) for _ in range(2)]
    ids: list[str] = []
    try:
        for name in names:
            ids.append(start("minio", name, username, password))
        for cid in ids:
            for _ in range(75):
                try:
                    call(["docker", "exec", cid, "/usr/bin/mc", "alias", "set", "scratch",
                          "http://127.0.0.1:9000", username, password], timeout=5)
                    call(["docker", "exec", cid, "/usr/bin/mc", "ready", "scratch"], timeout=5)
                    break
                except (ValueError, subprocess.SubprocessError):
                    time.sleep(.5)
            else:
                raise ValueError("synthetic MinIO did not become ready")
            call(["docker", "exec", cid, "/usr/bin/mc", "mb", "scratch/fleet-synthetic"])
        payload = (b"ARCHIVED_MINIO_IMAGE_SYNTHETIC_BACKUP_RESTORE_ONLY|" + bytes(range(256))) * 12
        digest = hashlib.sha256(payload).hexdigest()
        call(["docker", "exec", "-i", ids[0], "/usr/bin/mc", "pipe",
              "scratch/fleet-synthetic/test.bin"], input_bytes=payload)
        source = call(["docker", "exec", ids[0], "/usr/bin/mc", "cat", "scratch/fleet-synthetic/test.bin"])
        if source != payload or hashlib.sha256(source).hexdigest() != digest:
            raise ValueError("synthetic MinIO source differs")
        call(["docker", "exec", "-i", ids[1], "/usr/bin/mc", "pipe",
              "scratch/fleet-synthetic/test.bin"], input_bytes=source)
        restored = call(["docker", "exec", ids[1], "/usr/bin/mc", "cat", "scratch/fleet-synthetic/test.bin"])
        if restored != payload or hashlib.sha256(restored).hexdigest() != digest:
            raise ValueError("synthetic MinIO restored object differs")
        return {"status": "SYNTHETIC_OBJECT_RESTORE_PASS", "synthetic_object_bytes": len(payload),
                "synthetic_object_sha256": digest, "exact_running_image_id": IMAGES["minio"][1]}
    finally:
        for cid in ids:
            remove(cid)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="run scratch containers on x1-370 only")
    args = parser.parse_args()
    report = {"purpose": "exact_archive_image_synthetic_rehearsal",
              "executable_proof": False, "production_data_restored": False,
              "independent_custody_verified": False, "real_oidc_verified": False,
              "safe_to_cutover": False, "production_modified": False, "release_gate": "NO_GO"}
    if not args.execute:
        report["state"] = "DRY_RUN_NO_DOCKER_OPERATIONS"
        print(json.dumps(report,sort_keys=True))
        return 3
    if socket.gethostname() != HOST:
        report["state"] = "DENIED_NOT_ALLOWLISTED_TEST_HOST"
        print(json.dumps(report,sort_keys=True))
        return 3
    try:
        if not all(image_ready(role) for role in IMAGES):
            raise ValueError("exact imported images unavailable")
        report["postgres"] = postgres_synthetic()
        report["minio"] = minio_synthetic()
        report["executable_proof"] = True
        report["state"] = "SYNTHETIC_EXACT_IMAGES_PASS_NOT_PRODUCTION_RESTORE"
        print(json.dumps(report,sort_keys=True))
        return 0
    except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError) as exc:
        report["state"] = "HOLD"
        report["error_class"] = type(exc).__name__
        print(json.dumps(report,sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
