#!/usr/bin/env python3
"""Read-only, digest-pinned OCI metadata witness for research-only storage candidates.

Never pulls layers, starts containers, touches volumes, or authorizes a release.
The fixed candidates are NOT interchangeable with the deployed MinIO image.
"""
import argparse
import hashlib
import json
import re
import subprocess

CANDIDATES = {
    "silo": ("docker.io/pgsty/silo",
             "635197cb9f36d01bee221d34d1c7d7960f6a95c48b0b6c01d99cd13bdae51a46"),
    "aistor": ("quay.io/minio/aistor/minio",
               "107cf2014a9583c74c11e3cdbd6903d89c2244355886b89ce532f4ecae9c23f3"),
}
INDEX_TYPES = {"application/vnd.oci.image.index.v1+json",
               "application/vnd.docker.distribution.manifest.list.v2+json"}
MANIFEST_TYPES = {"application/vnd.oci.image.manifest.v1+json",
                  "application/vnd.docker.distribution.manifest.v2+json"}
DIGEST = re.compile(r"sha256:[a-f0-9]{64}\Z")
MAX_BYTES = 131072
# This read-only witness supports runnable OCI/Docker images, not arbitrary
# OCI artifacts. These values describe blobs; the blobs are not downloaded.
CONFIG_TYPES = {
    "application/vnd.oci.image.config.v1+json",
    "application/vnd.docker.container.image.v1+json",
}
LAYER_TYPES = {
    "application/vnd.oci.image.layer.v1.tar",
    "application/vnd.oci.image.layer.v1.tar+gzip",
    "application/vnd.oci.image.layer.v1.tar+zstd",
    "application/vnd.docker.image.rootfs.diff.tar.gzip",
}
MAX_DESCRIPTOR_SIZE = 20 * 1024 ** 3
MAX_LAYERS = 128


def _descriptor(value, media_types):
    """Validate an OCI blob descriptor without fetching the referenced blob."""
    return (isinstance(value, dict) and
            type(value.get("size")) is int and
            0 < value["size"] <= MAX_DESCRIPTOR_SIZE and
            type(value.get("digest")) is str and
            bool(DIGEST.fullmatch(value["digest"])) and
            type(value.get("mediaType")) is str and
            value["mediaType"] in media_types)



def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate registry metadata key")
        result[key] = value
    return result


def _decode(value):
    if not isinstance(value, (bytes, str)) or len(value) > MAX_BYTES:
        raise ValueError("missing or oversized registry metadata")
    return json.loads(value, object_pairs_hook=_unique)


def _request(args, runner):
    proc = runner(["docker", "buildx", "imagetools", "inspect", *args],
                  capture_output=True, check=False, timeout=15)
    if proc.returncode != 0:
        raise ValueError("registry observation unavailable")
    return proc.stdout


def witness(candidate, runner=subprocess.run):
    if candidate not in CANDIDATES:
        raise ValueError("not an allowlisted research candidate")
    repo, pinned = CANDIDATES[candidate]
    ref = repo + "@sha256:" + pinned
    record = {
        "candidate": candidate,
        "reference": ref,
        "status": "unavailable",
        "index_digest_verified": False,
        "linux_amd64_descriptor_observed": False,
        "linux_amd64_child_manifest_bytes_verified": False,
        "child_descriptor_size_verified": False,
        "config_descriptor_shape_verified": False,
        "layer_descriptors_shape_verified": False,
        "child_digest": None,
        "architecture_runtime_verified": False,
        "restore_parity_verified": False,
        "independent_custody_verified": False,
        "production_approved": False,
        "layers_downloaded": False,
    }
    try:
        formatted = _decode(_request([ref, "--format", "{{json .Manifest}}"], runner))
        if (not isinstance(formatted, dict) or
                formatted.get("digest") != "sha256:" + pinned or
                formatted.get("mediaType") not in INDEX_TYPES):
            raise ValueError("unexpected registry index identity")
        raw = _request([ref, "--raw"], runner)
        if (not isinstance(raw, bytes) or len(raw) > MAX_BYTES or
                hashlib.sha256(raw).hexdigest() != pinned):
            raise ValueError("index bytes do not match pinned digest")
        index = _decode(raw)
        if (not isinstance(index, dict) or index.get("schemaVersion") != 2 or
                index.get("mediaType") != formatted["mediaType"]):
            raise ValueError("malformed registry index")
        record["index_digest_verified"] = True
        manifests = index.get("manifests")
        if not isinstance(manifests, list) or not 1 <= len(manifests) <= 64:
            raise ValueError("invalid index descriptor count")
        candidates = [
            item for item in manifests
            if isinstance(item, dict) and isinstance(item.get("platform"), dict)
            and item["platform"].get("os") == "linux"
            and item["platform"].get("architecture") == "amd64"
            and item["platform"].get("variant") in (None, "")
            and _descriptor(item, MANIFEST_TYPES)
            and item["size"] <= MAX_BYTES
        ]
        if len(candidates) != 1:
            raise ValueError("ambiguous or absent linux/amd64 child manifest")
        child = candidates[0]
        record["linux_amd64_descriptor_observed"] = True
        record["child_digest"] = child["digest"]
        # Digest-bound child lookup. No image config or layers are fetched.
        child_ref = repo + "@" + child["digest"]
        child_raw = _request([child_ref, "--raw"], runner)
        if (not isinstance(child_raw, bytes) or len(child_raw) > MAX_BYTES or
                "sha256:" + hashlib.sha256(child_raw).hexdigest() != child["digest"]):
            raise ValueError("child bytes do not match descriptor digest")
        if len(child_raw) != child["size"]:
            raise ValueError("child bytes do not match descriptor size")
        record["child_descriptor_size_verified"] = True
        manifest = _decode(child_raw)
        if (not isinstance(manifest, dict) or
                type(manifest.get("schemaVersion")) is not int or
                manifest["schemaVersion"] != 2 or
                manifest.get("mediaType") != child["mediaType"]):
            raise ValueError("invalid child image manifest")
        if not _descriptor(manifest.get("config"), CONFIG_TYPES):
            raise ValueError("invalid runnable-image config descriptor")
        record["config_descriptor_shape_verified"] = True
        layers = manifest.get("layers")
        if (not isinstance(layers, list) or
                not 1 <= len(layers) <= MAX_LAYERS or
                not all(_descriptor(layer, LAYER_TYPES) for layer in layers)):
            raise ValueError("invalid runnable-image layer descriptors")
        record["layer_descriptors_shape_verified"] = True
        # Only the index and child manifest bytes were retrieved. The
        # referenced config/layer blob hashes are metadata declarations.
        record["linux_amd64_child_manifest_bytes_verified"] = True
        record["status"] = "immutable_manifest_tree_verified"
    except (ValueError, TypeError, UnicodeError, OSError, subprocess.SubprocessError):
        pass
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, choices=tuple(CANDIDATES))
    args = parser.parse_args()
    result = witness(args.candidate)
    print(json.dumps({"source": "read_only_research_image_witness",
                      "result": result}, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "immutable_manifest_tree_verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
