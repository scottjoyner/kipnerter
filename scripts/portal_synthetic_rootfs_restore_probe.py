#!/usr/bin/env python3
"""Bounded synthetic Docker rootfs import/boot on a NONPRODUCTION host only.

Never reads actual legacy archives. Never proves original OCI image recovery.
Requires explicit --run-synthetic flag; creates only short-lived tagged
synthetic images and no-network, read-only, auto-removed containers.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import tarfile

ROLES = ("api", "web")
EXPECTED = {"api": b"synthetic-api-restore-proof\n",
            "web": b"synthetic-web-restore-proof\n"}
MAX_TAR = 8 * 1024 * 1024
DOCKER_TIMEOUT = 35
BINARY = Path("/bin/busybox")


def synthetic_tar(role: str, busybox: bytes) -> bytes:
    if role not in ROLES or not isinstance(busybox, bytes) or not 0 < len(busybox) < 4 * 1024 * 1024:
        raise ValueError("invalid synthetic source")
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for directory in ("bin", "app"):
            x = tarfile.TarInfo(directory)
            x.type = tarfile.DIRTYPE
            x.mode = 0o755
            tar.addfile(x)
        for name, data, mode in (
            ("bin/busybox", busybox, 0o755),
            ("app/proof.txt", EXPECTED[role], 0o644),
        ):
            x = tarfile.TarInfo(name)
            x.mode = mode
            x.size = len(data)
            x.uid = x.gid = x.mtime = 0
            tar.addfile(x, io.BytesIO(data))
    data = out.getvalue()
    if len(data) > MAX_TAR:
        raise ValueError("unbounded synthetic archive")
    verify_tar(data, role)
    return data


def verify_tar(data: bytes, role: str) -> None:
    if role not in ROLES or not isinstance(data, bytes) or not 0 < len(data) <= MAX_TAR:
        raise ValueError("invalid input tar")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
        members = tar.getmembers()
        if [m.name for m in members] != ["bin", "app", "bin/busybox", "app/proof.txt"]:
            raise ValueError("unexpected synthetic archive member")
        if any(not (m.isdir() or m.isfile()) or m.uid or m.gid or m.mtime for m in members):
            raise ValueError("unsafe synthetic archive member")
        x = tar.extractfile("app/proof.txt")
        if x is None or x.read() != EXPECTED[role]:
            raise ValueError("synthetic proof missing")


def docker(*args, input_data=None) -> str:
    proc = subprocess.run(
        ["docker", *args], input=input_data, capture_output=True,
        timeout=DOCKER_TIMEOUT, check=True,
    )
    if len(proc.stdout) > 4096:
        raise ValueError("unexpected verbose Docker response")
    return proc.stdout.decode("utf-8", "strict").strip()


def run_synthetic(nonproduction_ack: bool, busybox_path: Path = BINARY):
    if not nonproduction_ack:
        raise ValueError("explicit isolated nonproduction acknowledgement required")
    if busybox_path.is_symlink() or not busybox_path.is_file():
        raise ValueError("static synthetic binary absent")
    binary = busybox_path.read_bytes()
    # Ubuntu fleet fixture is a statically linked BusyBox ELF; no network/pull.
    if not binary.startswith(b"\x7fELF"):
        raise ValueError("synthetic ELF fixture missing")
    report = []
    for role in ROLES:
        tag = "local/kipnerter-synthetic-rootfs:" + secrets.token_hex(12)
        name = "kipnerter-synthetic-recovery-" + secrets.token_hex(12)
        created_image = False
        try:
            # Refuse to reuse/delete any existing image tag.
            try:
                docker("image", "inspect", "--format", "{{.Id}}", tag)
            except subprocess.CalledProcessError:
                pass
            else:
                raise ValueError("synthetic image name already occupied")
            contents = synthetic_tar(role, binary)
            fingerprint = hashlib.sha256(contents).hexdigest()
            image = docker("import", "-", tag, input_data=contents)
            created_image = True
            if not image.startswith("sha256:") or len(image) != 71:
                raise ValueError("Docker image import receipt malformed")
            output = docker(
                "run", "--rm", "--name", name,
                "--pull=never", "--network=none", "--read-only",
                "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--pids-limit=32", "--memory=128m", "--cpus=0.25",
                "--user=65534:65534",
                "--entrypoint=/bin/busybox", tag,
                "sh", "-c", "test -r /app/proof.txt && /bin/busybox cat /app/proof.txt",
            )
            if output.encode() + b"\n" != EXPECTED[role]:
                raise ValueError("synthetic isolated restore output mismatch")
            report.append({
                "role": role, "isolated_container_works": True,
                "synthetic_archive_sha256": fingerprint,
                "original_oci_image_recovered": False,
            })
        finally:
            # Never delete an existing tag or a tag whose import was unverified.
            # Fail closed if the freshly created synthetic image cannot be removed.
            if created_image:
                docker("image", "rm", tag)
    return {"status": "SYNTHETIC_ISOLATED_RESTORE_ONLY",
            "roles": report,
            "actual_legacy_rootfs_accessed": False,
            "original_images_recovered": False,
            "legacy_functional_rollback_proven": False,
            "production_modified": False,
            "public_deployment_authorized": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-synthetic", action="store_true")
    ap.add_argument("--nonproduction-host-ack", action="store_true")
    args = ap.parse_args()
    if not args.run_synthetic or not args.nonproduction_host_ack:
        raise SystemExit("NO_GO: requires --run-synthetic --nonproduction-host-ack")
    try:
        print(json.dumps(run_synthetic(True), sort_keys=True))
    except (OSError, ValueError, subprocess.SubprocessError):
        print(json.dumps({"status": "HOLD", "legacy_rollback_proven": False,
                          "production_modified": False}, sort_keys=True))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
