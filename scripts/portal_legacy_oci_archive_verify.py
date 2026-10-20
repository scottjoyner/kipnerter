#!/usr/bin/env python3
"""Stream-only, no-extraction OCI/Docker image archive digest-tree qualification.

Input archive may contain secrets; no member bytes, config/env values, names
or image IDs are logged. Docker/registry is NOT contacted by this verifier.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
import tarfile
import zlib

MAX_TOTAL = 5 * 1024**3
MAX_MEMBER = 3 * 1024**3
MAX_META = 1024 * 1024
MAX_FILES = 250
MAX_INFLATED_LAYER = 4 * 1024**3
MAX_INFLATED_TOTAL = 8 * 1024**3
BLOCK = 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}\Z")
ROLES = {
    "legacy-api": "sha256:7efc68e54ff1289ee2033440ea0ee176962e3a57e0d24e091a2365ca769d5860",
    "legacy-web": "sha256:5dfd3de1d45260b826d52eb107df8398e872121c9d98ade02540f3917fc78726",
}
INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"
CONFIG = "application/vnd.oci.image.config.v1+json"
LAYER_TYPES = {
    "application/vnd.oci.image.layer.v1.tar",
    "application/vnd.oci.image.layer.v1.tar+gzip",
    "application/vnd.oci.image.layer.v1.tar+zstd",
    "application/vnd.docker.image.rootfs.diff.tar",
    "application/vnd.docker.image.rootfs.diff.tar.gzip",
}


def _json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate OCI metadata field")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def _digest(value):
    if type(value) is not str or not value.startswith("sha256:") or not SHA.fullmatch(value[7:]):
        raise ValueError("invalid OCI descriptor digest")
    return value[7:]


def _descriptor(desc, blobs, *, allowed):
    if not isinstance(desc, dict) or desc.get("mediaType") not in allowed:
        raise ValueError("unsupported OCI descriptor media type")
    digest = _digest(desc.get("digest"))
    item = blobs.get(digest)
    if item is None or type(desc.get("size")) is not int or desc["size"] != item[0]:
        raise ValueError("referenced OCI layer or metadata blob unavailable")
    return digest


def _member_name(name):
    if (not isinstance(name, str) or len(name) > 150 or
            not name or name.startswith("/") or "\\" in name or "\x00" in name or
            any(segment in (".", "..") for segment in name.split("/"))):
        raise ValueError("unsafe OCI archive member path")
    if name in ("manifest.json", "index.json", "oci-layout", "repositories"):
        return name
    if name.startswith("blobs/sha256/"):
        value = name.removeprefix("blobs/sha256/")
        if SHA.fullmatch(value):
            return value
    raise ValueError("unexpected OCI archive member")


def _inflate_piece(decoder, part, digest, total):
    """Consume one gzip chunk with bounded output and no unbounded buffers."""
    pending = part
    while pending:
        out = decoder.decompress(pending, BLOCK)
        pending = decoder.unconsumed_tail
        total += len(out)
        if total > MAX_INFLATED_LAYER:
            raise ValueError("expanded OCI layer exceeds independent size bound")
        digest.update(out)
        if decoder.unused_data:
            raise ValueError("trailing data after compressed OCI layer")
    return total


def _stream_blob(reader, member_size, *, candidate):
    """Return saved-blob hash and optional bounded gzip diffID from one FD."""
    raw_digest = hashlib.sha256()
    inflated = hashlib.sha256()
    decoder = None
    expanded = 0
    data = bytearray()
    consumed = 0
    while part := reader.read(BLOCK):
        consumed += len(part)
        if consumed > member_size:
            raise ValueError("OCI archive member exceeds declared length")
        raw_digest.update(part)
        if member_size <= MAX_META:
            data.extend(part)
        if candidate:
            if decoder is None:
                # OCI raw tar bytes also have a valid diffID: hash of raw bytes.
                if part.startswith(b"\x1f\x8b"):
                    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                else:
                    decoder = False
            if decoder is not False:
                try:
                    expanded = _inflate_piece(decoder, part, inflated, expanded)
                except zlib.error as exc:
                    raise ValueError("invalid compressed OCI layer stream") from exc
    if consumed != member_size:
        raise ValueError("truncated OCI blob")
    if decoder not in (None, False):
        try:
            for _ in range(100):
                tail = decoder.flush(BLOCK)
                expanded += len(tail)
                if expanded > MAX_INFLATED_LAYER:
                    raise ValueError("expanded OCI layer exceeds independent size bound")
                inflated.update(tail)
                if not tail:
                    break
            else:
                raise ValueError("unbounded compressed OCI flush")
        except zlib.error as exc:
            raise ValueError("invalid compressed OCI layer footer") from exc
        if not decoder.eof or decoder.unused_data:
            raise ValueError("incomplete or trailing compressed OCI layer")
        return raw_digest.hexdigest(), bytes(data), inflated.hexdigest(), expanded, "gzip"
    return raw_digest.hexdigest(), bytes(data), raw_digest.hexdigest(), consumed, "raw"


def _archive(stream):
    files = {}
    metadata = {}
    total = 0
    count = 0
    layers = {}
    inflated_total = 0
    with tarfile.open(fileobj=stream, mode="r|") as archive:
        for member in archive:
            if member.isdir() and member.name.rstrip("/") in ("blobs", "blobs/sha256"):
                continue
            if not member.isfile() or member.size < 0 or member.size > MAX_MEMBER:
                raise ValueError("unsafe OCI tar member")
            name = _member_name(member.name)
            count += 1
            total += member.size
            if count > MAX_FILES or total > MAX_TOTAL or name in files:
                raise ValueError("OCI archive exceeds bounds or duplicates member")
            reader = archive.extractfile(member)
            if reader is None:
                raise ValueError("unreadable OCI archive member")
            file_hash, short, diff_id, expanded, mode = _stream_blob(
                reader, member.size, candidate=len(name) == 64)
            if len(name) == 64:
                inflated_total += expanded
                if inflated_total > MAX_INFLATED_TOTAL:
                    raise ValueError("total expanded OCI layer bytes exceed limit")
                layers[name] = (diff_id, mode)
            if len(name) == 64 and file_hash != name:
                raise ValueError("OCI blob bytes differ from digest path")
            files[name] = (member.size, file_hash)
            if member.size <= MAX_META and (len(name) == 64 or name in
                                            ("manifest.json", "index.json", "oci-layout")):
                try:
                    metadata[name] = _json(short)
                except (UnicodeError, ValueError):
                    if name in ("index.json", "manifest.json", "oci-layout"):
                        raise
                    # Non-JSON small OCI blobs can be other metadata/attestations.
    if not count or total == 0:
        raise ValueError("empty OCI archive")
    return files, metadata, count, layers


def _validate_manifest(manifest, blobs, docs, unpacked):
    if (not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2 or
            manifest.get("mediaType") != MANIFEST or
            not isinstance(manifest.get("layers"), list) or
            not 1 <= len(manifest["layers"]) <= 128):
        raise ValueError("invalid linux image OCI manifest")
    config_id = _descriptor(manifest.get("config"), blobs, allowed={CONFIG})
    config = docs.get(config_id)
    if (not isinstance(config, dict) or config.get("os") != "linux" or
            config.get("architecture") != "amd64" or
            not isinstance(config.get("rootfs"), dict) or
            config["rootfs"].get("type") != "layers"):
        raise ValueError("image platform/config cannot be verified")
    diffs = config["rootfs"].get("diff_ids")
    if (not isinstance(diffs, list) or len(diffs) != len(manifest["layers"]) or
            any(not isinstance(d, str) or not d.startswith("sha256:") or
                not SHA.fullmatch(d[7:]) for d in diffs)):
        raise ValueError("image rootfs diffID inventory incomplete")
    layers = []
    for position, layer in enumerate(manifest["layers"]):
        blob = _descriptor(layer, blobs, allowed=LAYER_TYPES)
        diff_id, mode = unpacked[blob]
        if layer["mediaType"] not in (
            "application/vnd.oci.image.layer.v1.tar",
            "application/vnd.docker.image.rootfs.diff.tar",
            "application/vnd.oci.image.layer.v1.tar+gzip",
            "application/vnd.docker.image.rootfs.diff.tar.gzip",
        ):
            # zstd is not currently available in the bounded stdlib reader.
            raise ValueError("unverifiable OCI layer compression type")
        expected_mode = "gzip" if layer["mediaType"].endswith(("+gzip", ".gzip")) else "raw"
        if mode != expected_mode or diffs[position] != "sha256:" + diff_id:
            raise ValueError("uncompressed OCI layer diffID mismatch")
        layers.append(blob)
    return config_id, layers


def verify_archive(stream, expected_image_id):
    expected = _digest(expected_image_id)
    blobs, docs, file_count, unpacked = _archive(stream)
    root = docs.get("index.json")
    if (not isinstance(root, dict) or root.get("schemaVersion") != 2 or
            root.get("mediaType") != INDEX or
            not isinstance(root.get("manifests"), list) or
            len(root["manifests"]) != 1):
        raise ValueError("OCI archive missing single-image root index")
    original = _descriptor(root["manifests"][0], blobs, allowed={INDEX, MANIFEST})
    if root["manifests"][0]["mediaType"] == INDEX:
        index = docs.get(original)
        if (not isinstance(index, dict) or index.get("mediaType") != INDEX or
                not isinstance(index.get("manifests"), list)):
            raise ValueError("referenced OCI image index unavailable")
        matches = [d for d in index["manifests"] if isinstance(d, dict) and
                   isinstance(d.get("platform"), dict) and
                   d["platform"].get("os") == "linux" and
                   d["platform"].get("architecture") == "amd64" and
                   d["platform"].get("variant") in (None, "")]
        if len(matches) != 1:
            raise ValueError("ambiguous linux amd64 image platform")
        manifest_digest = _descriptor(matches[0], blobs, allowed={MANIFEST})
    else:
        manifest_digest = original
    cfg, layers = _validate_manifest(docs.get(manifest_digest), blobs, docs, unpacked)
    if expected not in (original, cfg):
        raise ValueError("OCI image identity does not match pinned original")
    legacy_manifest = docs.get("manifest.json")
    if legacy_manifest is not None:
        if (not isinstance(legacy_manifest, list) or len(legacy_manifest) != 1 or
                not isinstance(legacy_manifest[0], dict)):
            raise ValueError("Docker save compatibility manifest invalid")
        item = legacy_manifest[0]
        if (item.get("Config") != "blobs/sha256/" + cfg or
                item.get("Layers") !=
                ["blobs/sha256/" + d for d in layers]):
            raise ValueError("Docker save manifest disagrees with OCI manifest")
    oci_layout = docs.get("oci-layout")
    if not isinstance(oci_layout, dict) or oci_layout.get("imageLayoutVersion") != "1.0.0":
        raise ValueError("OCI layout format not verified")
    return {
        "status": "OCI_DIGEST_TREE_VERIFIED_NOT_RUNNABLE",
        "pinned_image_id_matched": True,
        "linux_amd64_manifest_present": True,
        "image_config_content_hash_verified": True,
        "layer_blob_compressed_digests_verified": True,
        "saved_layer_count": len(layers),
        "archive_member_count": file_count,
        "original_image_registry_provenance_verified": False,
        "uncompressed_layer_diffids_verified": True,
        "full_multiplatform_archive_verified": False,
        "launch_behavior_verified": False,
        "rollback_after_failure_verified": False,
        "independent_admin_custody_verified": False,
        "sensitive_config_or_layer_bytes_disclosed": False,
        "archive_imported_or_extracted": False,
        "docker_daemon_or_registry_contacted_by_verifier": False,
        "production_modified": False,
        "safe_to_cutover": False,
    }


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--role", choices=tuple(ROLES))
    group.add_argument("--research-fixture-id")
    args = parser.parse_args()
    expected = ROLES[args.role] if args.role else args.research_fixture_id
    try:
        report = verify_archive(sys.stdin.buffer, expected)
        if args.research_fixture_id is not None:
            report["status"] = "RESEARCH_IMAGE_NOT_LEGACY"
    except (ValueError, OSError, tarfile.TarError, UnicodeError, EOFError):
        print(json.dumps({"status": "HOLD",
                          "production_modified": False,
                          "safe_to_cutover": False}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
