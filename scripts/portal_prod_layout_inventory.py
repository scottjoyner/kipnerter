#!/usr/bin/env python3
"""Read-only, credential-free deployment layout inventory on a tagged host."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path("/opt/kipnerter")
KNOWN_FILES = ("docker-compose.yml", "compose.spatial.yml", "compose.staging.yml", ".env")
KNOWN_DIRS = ("releases", ".portal-release.lock", ".portal-release-pending")


def analyze(root: Path, *, disk=None, containers=None, volumes=None) -> dict:
    disk = disk or (shutil.disk_usage(root) if root.exists() else None)
    active = root / "current"
    current_kind = (
        "symlink" if active.is_symlink() else
        "directory" if active.is_dir() else
        "file" if active.is_file() else "missing"
    )
    # Do not reveal or follow the symlink target. The previous deployment
    # must be identified by a separate authenticated immutable witness.
    result = {
        "root_exists": root.is_dir(),
        "current_entry_kind": current_kind,
        "managed_pointer_present": current_kind == "symlink",
        "compose_files_present": {name:(root / name).is_file() for name in KNOWN_FILES},
        "expected_release_dir_present": (root / "releases").is_dir(),
        "sufficient_disk_for_snapshot": disk is not None and disk.free >= 4 * 1024**3,
        "disk_free_gib_rounded_down": (disk.free // (1024**3)) if disk else None,
        "running_kipnerter_containers": containers if containers is not None else [],
        "kipnerter_named_volumes": volumes if volumes is not None else [],
        "prod_files_modified": False,
        "safe_to_cutover": False,
        "data_restore_verified": False,
    }
    return result


def docker_names(args: list[str], *, field: str) -> list[dict | str]:
    completed = subprocess.run(args, capture_output=True, text=True, check=True, timeout=8)
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if field == "containers":
        rows = []
        for line in lines:
            name, image, status = (line.split("|", 2)+["",""])[:3]
            if "kipnerter" in name.lower():
                rows.append({"name":name[:120],"image":image[:180],
                             "running":status.lower().startswith("up ")})
        return rows[:24]
    return sorted({line.strip()[:120] for line in lines
                   if "kipnerter" in line.lower()})[:36]


def main():
    try:
        rows = docker_names(["docker","ps","--format","{{.Names}}|{{.Image}}|{{.Status}}"],field="containers")
        vols = docker_names(["docker","volume","ls","--format","{{.Name}}"],field="volumes")
        report = analyze(ROOT,containers=rows,volumes=vols)
        print(json.dumps(report,sort_keys=True))
    except (OSError,subprocess.SubprocessError,ValueError):
        print(json.dumps({"state":"NO_GO","reason":"read-only inventory unavailable",
                          "prod_files_modified":False}))
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
