#!/usr/bin/env python3
"""Read-only Compose persistent-state topology gate. No backup or restore."""
import argparse
import hashlib
import json
import re
import sys
from urllib.parse import urlparse

MAX_INPUT = 2 * 1024 * 1024
PROJECT = {"production": "kipnerter", "staging": "kipnerter-staging"}
PUBLIC = {"production": "https://api.kipnerter.com",
          "staging": "https://staging-api.kipnerter.com"}
STORAGE = {"spatial-postgres": ("spatial_postgres_data", "/var/lib/postgresql/data"),
           "spatial-minio": ("spatial_minio_data", "/data")}


def required(model, key):
    if not isinstance(model, dict) or key not in model:
        raise ValueError("missing Compose field")
    return model[key]


def analyze(model, environment):
    if environment not in PROJECT:
        raise ValueError("unknown deployment environment")
    project = PROJECT[environment]
    if not isinstance(model, dict) or model.get("name") != project:
        raise ValueError("incorrect Compose project identity")
    services = required(model, "services")
    volumes = required(model, "volumes")
    networks = required(model, "networks")
    if not all(isinstance(x, dict) for x in (services, volumes, networks)):
        raise ValueError("invalid Compose sections")
    records, holds = [], []
    for service, (name, mountpoint) in STORAGE.items():
        details = required(services, service)
        if details.get("ports") or details.get("network_mode") or details.get("privileged") is True:
            raise ValueError("persistent service exposes host access")
        mounts = required(details, "volumes")
        if not isinstance(mounts, list) or len(mounts) != 1:
            raise ValueError("persistent service requires one dedicated mount")
        mount = mounts[0]
        if (not isinstance(mount, dict) or mount.get("type") != "volume"
                or mount.get("source") != name or mount.get("target") != mountpoint
                or mount.get("read_only") is True):
            raise ValueError("persistent storage target is unexpected")
        volume = required(volumes, name)
        if (not isinstance(volume, dict) or volume.get("external") or
                volume.get("driver_opts") or volume.get("driver") not in (None, "local")
                or volume.get("name") != project + "_" + name):
            raise ValueError("persistent volume is shared, redirected, or external")
        if "spatial_backend" not in required(details, "networks"):
            raise ValueError("persistent service missing restricted network")
        ref = details.get("image")
        if not isinstance(ref, str):
            raise ValueError("persistent image reference missing")
        family = "postgis/postgis" if service == "spatial-postgres" else "minio/minio"
        if not ref.startswith(family + ":") and not ref.startswith(family + "@"):
            raise ValueError("unexpected persistent service image repository")
        digest = ref.rpartition("@sha256:")[2]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            holds.append(service + ": image is not digest-pinned; restore equivalence HOLD")
        records.append({"service": service, "volume": project + "_" + name,
                        "mount": mountpoint})
    # A sidecar or compromised app role must not quietly mount either
    # stateful volume; the two volumes have exclusive owning services.
    expected_owner = {name: service for service, (name, _) in STORAGE.items()}
    for name, service in services.items():
        if not isinstance(service, dict):
            raise ValueError("malformed service declaration")
        mounts = service.get("volumes", [])
        if not isinstance(mounts, list):
            raise ValueError("invalid service volume definition")
        for mount in mounts:
            if not isinstance(mount, dict):
                raise ValueError("invalid volume mount shape")
            volume = mount.get("source")
            if volume in expected_owner and expected_owner[volume] != name:
                raise ValueError("persistent volume is mounted by an unauthorized service")
    if required(networks, "spatial_backend").get("internal") is not True:
        raise ValueError("spatial database network must be internal")
    for service in ("spatial-api", "spatial-worker"):
        settings = required(required(services, service), "environment")
        if settings.get("KIPNERTER_ENVIRONMENT") != environment:
            raise ValueError("service environment differs from intended target")
        if settings.get("KIPNERTER_S3_PUBLIC_ENDPOINT_URL") != PUBLIC[environment]:
            raise ValueError("S3 public origin crosses deployment environments")
        db = settings.get("KIPNERTER_DATABASE_URL")
        if not isinstance(db, str):
            raise ValueError("missing database URI")
        endpoint = urlparse(db)
        if (endpoint.scheme != "postgresql+asyncpg" or
                endpoint.hostname != "spatial-postgres" or endpoint.port != 5432
                or endpoint.path != "/kipnerter"):
            raise ValueError("database URI escapes approved Compose endpoint")
        if settings.get("KIPNERTER_S3_ENDPOINT_URL") != "http://spatial-minio:9000":
            raise ValueError("object store URI escapes Compose network")
    if environment == "staging":
        web = required(required(services, "web"), "environment")
        if web.get("NEXTAUTH_URL") != "https://staging.kipnerter.com":
            raise ValueError("staging login origin does not match stage")
        mounts = required(required(services, "caddy"), "volumes")
        if not any(isinstance(x, dict) and x.get("target") == "/etc/caddy/Caddyfile"
                   and isinstance(x.get("source"), str)
                   and x["source"].endswith("/Caddyfile.staging")
                   and x.get("read_only") is True for x in mounts):
            raise ValueError("staging reverse-proxy config not isolated")
    records.sort(key=lambda x: x["service"])
    fingerprint = hashlib.sha256(json.dumps({"project": project, "storage": records},
                                             sort_keys=True).encode()).hexdigest()
    return {"source": "kipnerter_recovery_topology_preflight",
            "environment": environment, "project": project,
            "topology_sha256": fingerprint, "storage": records,
            "topology_valid": True, "blocking_findings": holds,
            "postgres_restore_executed": False, "minio_restore_executed": False,
            "production_recovery_approved": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True, choices=tuple(PROJECT))
    args = parser.parse_args()
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise SystemExit("RELEASE HOLD: Compose configuration exceeds size cap")
    try:
        result = analyze(json.loads(raw), args.environment)
    except (ValueError, TypeError, KeyError) as exc:
        raise SystemExit("RELEASE HOLD: invalid storage topology: " + str(exc)) from None
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    if result["blocking_findings"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
