#!/usr/bin/env python3
"""Read-only OCI registry evidence for two approved persistent-service images.

Runs only docker buildx imagetools inspect; never docker pull/build/run.
Digest resolution does NOT prove architecture, binary safety or restore parity.
"""
import argparse
import hashlib
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
RAW_MAX_BYTES = 131072
PLATFORM = {"os": "linux", "architecture": "amd64"}


def inspect(service, runner=subprocess.run):
    if service not in SOURCES:
        raise ValueError("unapproved stateful service")
    image = SOURCES[service]
    result = {"service": service, "configured_image": image, "status": "unavailable",
              "digest": None, "architecture_verified": False,
              "restore_equivalence_verified": False, "recovery_approved": False,
              "raw_manifest_digest_verified": False,
              "linux_amd64_descriptor_observed": False,
              "linux_amd64_manifest_digest": None}
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
    # Independently fetch the canonical registry manifest bytes. No layers
    # or image config blobs are downloaded. Verify that registry metadata
    # names the exact bytes, not merely a mutable tag or a formatted digest.
    try:
        raw = runner(["docker", "buildx", "imagetools", "inspect", image,
                      "--raw"], capture_output=True, check=False,
                     timeout=15)
    except (OSError, subprocess.SubprocessError):
        return result
    body = raw.stdout
    if (raw.returncode != 0 or not isinstance(body, (bytes, str)) or
            len(body) > RAW_MAX_BYTES):
        return result
    if isinstance(body, str):
        body = body.encode("utf-8", "strict")
    if "sha256:" + hashlib.sha256(body).hexdigest() != result["digest"]:
        return result
    try:
        manifest = json.loads(body)
    except (TypeError, ValueError, UnicodeError):
        return result
    if (not isinstance(manifest, dict) or
            manifest.get("mediaType") != data["mediaType"]):
        return result
    if result["manifest_kind"] == "index":
        descriptors = manifest.get("manifests")
        if isinstance(descriptors, list) and len(descriptors) <= 64:
            choices = []
            for descriptor in descriptors:
                if not isinstance(descriptor, dict):
                    continue
                platform = descriptor.get("platform")
                if (isinstance(platform, dict) and
                        platform.get("os") == PLATFORM["os"] and
                        platform.get("architecture") == PLATFORM["architecture"] and
                        platform.get("variant") in (None, "")):
                    candidate = descriptor.get("digest")
                    if isinstance(candidate, str) and DIGEST.fullmatch(candidate):
                        choices.append(candidate)
            if len(choices) == 1:
                result["linux_amd64_descriptor_observed"] = True
                result["linux_amd64_manifest_digest"] = choices[0]
    result["raw_manifest_digest_verified"] = True
    result["status"] = "manifest_bytes_verified"
    # A registry manifest alone cannot establish runtime architecture or
    # binary compatibility, even when the index has an amd64 descriptor.
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", choices=tuple(SOURCES))
    args = parser.parse_args()
    services = [args.service] if args.service else list(SOURCES)
    values = [inspect(s) for s in services]
    print(json.dumps({"source": "read_only_registry_observation", "images": values},
                     separators=(",", ":"), sort_keys=True))
    if any(v["status"] != "manifest_bytes_verified" for v in values):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
