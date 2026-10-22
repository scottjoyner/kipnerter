#!/usr/bin/env python3
"""Read-only production data-recovery preflight for the legacy Kipnerter stack.

Never accesses DB rows, S3 keys/objects, Docker container environment,
PostgreSQL passwords, backup payloads or Compose secret files. The presence of
tools/mounts is necessary but NEVER sufficient evidence of a restorable backup.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

POSTGRES_TARGET = "/var/lib/postgresql/data"
MINIO_TARGET = "/data"
EXPECTED = {
    "postgres": ("spatial-postgres", POSTGRES_TARGET, "spatial_postgres_data"),
    "minio": ("spatial-minio", MINIO_TARGET, "spatial_minio_data"),
}
CONTAINER_RE = re.compile(r"^kipnerter-spatial-(postgres|minio)-[1-9][0-9]*$")
SHA = re.compile(r"^[a-f0-9]{40}$")


def checked(args: list[str], *, timeout: int = 12) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                            check=True)
    if len(result.stdout) > 50_000:
        raise ValueError("docker metadata output exceeded bound")
    return result.stdout.strip()


def mount_state(mounts: object, target: str, expected_suffix: str) -> dict:
    """Inspect only structured Volume mount metadata; never read volume bytes."""
    if not isinstance(mounts, list):
        raise ValueError("invalid Docker mounts")
    matches = [m for m in mounts if isinstance(m, dict) and
               m.get("Destination") == target]
    if len(matches) != 1:
        raise ValueError("data target must have exactly one Docker mount")
    m = matches[0]
    name = m.get("Name")
    if (m.get("Type") != "volume" or not isinstance(name, str) or
            not name.endswith("_" + expected_suffix) or
            m.get("RW") is not True):
        raise ValueError("data target is not the expected durable named volume")
    return {"named_volume_bound": True,
            "volume_name_matches_declared_compose": True,
            "target_matches_declared_compose": True}


def select_containers(rows: object) -> dict[str, str]:
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("invalid or excessive container inventory")
    selected: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid Docker row")
        name = row.get("name")
        if not isinstance(name, str) or not CONTAINER_RE.fullmatch(name):
            continue
        purpose = "postgres" if "-postgres-" in name else "minio"
        if purpose in selected or row.get("running") is not True:
            raise ValueError("missing or duplicate running stateful service")
        selected[purpose] = name
    if set(selected) != set(EXPECTED):
        raise ValueError("both exact running stateful services required")
    return selected


def classify(containers: object, mounts: dict[str, object],
             binaries: dict[str, bool], free_bytes: int,
             *, staged_source_exists: bool) -> dict:
    selected = select_containers(containers)
    checks = {}
    for purpose, (service, target, suffix) in EXPECTED.items():
        checks[purpose] = mount_state(mounts.get(purpose), target, suffix)
    minimum = free_bytes >= 4 * 1024**3
    return {
        "production_container_identity": "verified",
        "stateful_mount_checks": checks,
        "postgres_dump_binary_present": binaries.get("pg_dump") is True,
        "postgres_restore_binary_present": binaries.get("pg_restore") is True,
        "minio_server_binary_present": binaries.get("minio") is True,
        "minio_backup_client_binary_present": binaries.get("mc") is True,
        "free_disk_at_least_4gib": minimum,
        "free_gib_floor": free_bytes // (1024**3),
        "three_source_private_stage_present": staged_source_exists,
        "postgres_backup_completed": False,
        "minio_backup_completed": False,
        "independent_backup_custody_verified": False,
        "postgres_restore_rehearsal_passed": False,
        "minio_restore_rehearsal_passed": False,
        "managed_release_migration_approved": False,
        "safe_to_cutover": False,
        "production_modified": False,
    }


def main() -> int:
    try:
        cmd = checked(["docker", "ps", "--format", "{{json .}}"], timeout=12)
        parsed = []
        for line in cmd.splitlines():
            item = json.loads(line)
            parsed.append({"name": item.get("Names"),
                           "running": item.get("State", "").lower() == "running" or
                                      str(item.get("Status", "")).lower().startswith("up ")})
        selected = select_containers(parsed)
        mounts: dict[str, object] = {}
        for purpose, container in selected.items():
            mounts[purpose] = json.loads(checked([
                "docker", "inspect", "--format", "{{json .Mounts}}", container
            ], timeout=10))
        binaries: dict[str, bool] = {}
        for program,container in (
            ("pg_dump", selected["postgres"]),
            ("pg_restore", selected["postgres"]),
            ("minio", selected["minio"]),
            ("mc", selected["minio"]),
        ):
            try:
                checked(["docker", "exec", container, program, "--version"], timeout=8)
                binaries[program] = True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                binaries[program] = False
        source_sha = "ad4cffe6e1fe6c659d97e48a96d220f2f0543c55"
        private = Path.home() / ".local/state/kipnerter-release/verified" / source_sha
        staged = ((private / ".portal-staged.json").is_file() and
                  (private / "gateway-api/Dockerfile").is_file() and
                  (private / "spatial-api/Dockerfile").is_file())
        # Presence is not a second independent source digest or recovery proof.
        root = Path("/opt/kipnerter")
        result = classify(parsed, mounts, binaries,
                          shutil.disk_usage(root).free,
                          staged_source_exists=staged)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError,
            json.JSONDecodeError) as exc:
        print(json.dumps({"result": "NO_GO",
                          "reason_class": type(exc).__name__,
                          "safe_to_cutover": False,
                          "production_modified": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
