#!/usr/bin/env python3
"""Read-only OCI registry evidence for two approved persistent-service images.

Runs only docker buildx imagetools inspect; never docker pull/build/run.
Digest resolution does NOT prove architecture, binary safety or restore parity.
"""
import argparse
import json
import re
import subprocess

SOURCES = {
    "spatial-postgres": "postgis/postgis:16-3.4",
    "spatial-minio": "minio/minio:latest",
}
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
MEDIA = {
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
}
MAX_BYTES = 65536


def inspect(service, runner=subprocess.run):
    if service not in SOURCES:
        raise ValueError("unapproved stateful service")
    image = SOURCES[service]
    result = {"service": service, "configured_image": image, "status": "unavailable",
              "digest": None, "architecture_verified": False,
              "restore_equivalence_verified": False, "recovery_approved": False}
    try:
        proc = runner(
            ["docker", "buildx", "imagetools", "inspect", image,
             "--format", "{{json .Manifest}}"],
            capture_output=True, text=True, check=False, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return result
    # Never leak raw registry errors or credentials through this witness.
    if (proc.returncode != 0 or not isinstance(proc.stdout, str)
            or len(proc.stdout.encode()) > MAX_BYTES):
        return result
    try:
        data = json.loads(proc.stdout)
    except (TypeError, ValueError):
        return result
    if (not isinstance(data, dict) or data.get("mediaType") not in MEDIA
            or not isinstance(data.get("digest"), str)
            or not DIGEST.fullmatch(data["digest"])):
        return result
    result["status"] = "manifest_digest_observed"
    result["digest"] = data["digest"]
    result["manifest_kind"] = ("index" if "index" in data["mediaType"]
                               or "manifest.list" in data["mediaType"]
                               else "single_manifest")
    # A manifest digest need not attest platform compatibility. The Docker
    # daemon's architecture and an independently witnessed container startup
    # are required before this may become an approved restore image.
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", choices=tuple(SOURCES))
    args = parser.parse_args()
    services = [args.service] if args.service else list(SOURCES)
    values = [inspect(s) for s in services]
    print(json.dumps({"source": "read_only_registry_observation", "images": values},
                     separators=(",", ":"), sort_keys=True))
    if any(v["status"] != "manifest_digest_observed" for v in values):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
