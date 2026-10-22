#!/usr/bin/env python3
"""Read-only witness for the pinned, private tsidp identity-provider bootstrap.

This checker never logs credentials, registers devices, changes policies, creates
OIDC clients, or authorizes a public release. The only network request is to a
fixed private Tailnet HTTPS discovery URL, and only after enrollment is proven.
"""
import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infra/tailscale/tsidp-preview.compose.yml"
PROJECT = "kipnerter-oidc-bootstrap"
CONTAINER = "kipnerter-oidc-bootstrap-idp"
IMAGE_DIGEST = "7a30d56cb1a33fd72ea44b12ab3659b5c7a8a3afe3cf4ada76a700f19b96185b"
IMAGE = "ghcr.io/tailscale/tsidp@sha256:" + IMAGE_DIGEST
DNS_NAME = "kipnerter-idp-staging.tailcb8954.ts.net"
ORIGIN = "https://" + DNS_NAME
TAG = "tag:tsidp"
MAX_JSON = 65536


def check_compose(model):
    """Accept exactly the reviewed image, project, isolated service and state volume."""
    if not isinstance(model, dict) or model.get("name") != PROJECT:
        raise ValueError("wrong compose project")
    if set(model.get("services", {})) != {"idp"}:
        raise ValueError("unexpected services")
    service = model["services"]["idp"]
    if service.get("image") != IMAGE or service.get("container_name") != CONTAINER:
        raise ValueError("wrong pinned image/container")
    if any(service.get(x) for x in (
        "ports", "expose", "build", "devices", "cap_add", "network_mode",
        "privileged", "entrypoint", "command", "env_file", "secrets",
        "configs", "extra_hosts", "pid", "ipc", "userns_mode",
        "volumes_from", "group_add", "sysctls", "user", "network_mode")):
        raise ValueError("unexpected exposure or privilege")
    if service.get("restart") != "no" or service.get("read_only") is not True:
        raise ValueError("unsafe restart or filesystem")
    if service.get("cap_drop") != ["ALL"] or "no-new-privileges:true" not in service.get("security_opt", []):
        raise ValueError("container privileges not restricted")
    if not (0 < float(service.get("cpus", 0)) <= .5 and
            0 < int(service.get("mem_limit", 0)) <= 268435456 and
            0 < int(service.get("pids_limit", 0)) <= 128):
        raise ValueError("unbounded resources")
    expected_env = {
        "TAILSCALE_USE_WIP_CODE": "1", "TS_STATE_DIR": "/data",
        "TS_HOSTNAME": "kipnerter-idp-staging", "TS_ADVERTISE_TAGS": TAG,
        "TSIDP_ENABLE_STS": "0",
    }
    if service.get("environment") != expected_env:
        raise ValueError("wrong environment or unexpected secret")
    if service.get("networks") != {"idp_network": None} and service.get("networks") != ["idp_network"]:
        raise ValueError("wrong network")
    networks = model.get("networks", {})
    if set(networks) != {"idp_network"} or networks["idp_network"].get("external") is True:
        raise ValueError("wrong network inventory")
    if set(model.get("volumes", {})) != {"idp_data"}:
        raise ValueError("wrong volume inventory")
    volumes = service.get("volumes")
    if not isinstance(volumes, list) or len(volumes) != 1:
        raise ValueError("single state volume required")
    vol = volumes[0]
    if (vol.get("type") != "volume" or vol.get("source") != "idp_data" or
            vol.get("target") != "/data" or vol.get("read_only") is True):
        raise ValueError("unsafe state volume")
    return True


def check_runtime(container):
    """Compare actual Docker HostConfig, never just requested CLI parameters."""
    if not isinstance(container, dict) or container.get("Image") != "sha256:" + IMAGE_DIGEST:
        raise ValueError("runtime image mismatch")
    conf, host = container.get("Config", {}), container.get("HostConfig", {})
    if conf.get("User") != "app:app" or conf.get("Image") != IMAGE:
        raise ValueError("unexpected runtime identity/image")
    if (not container.get("State", {}).get("Running") or host.get("Privileged") or
            host.get("PublishAllPorts") or host.get("PortBindings") or
            host.get("ReadonlyRootfs") is not True or host.get("CapDrop") != ["ALL"] or
            "no-new-privileges:true" not in host.get("SecurityOpt", [])):
        raise ValueError("runtime isolation failed")
    if (host.get("NetworkMode") != PROJECT + "_idp_network" or
            host.get("RestartPolicy", {}).get("Name") != "no" or
            not 0 < int(host.get("Memory", 0)) <= 268435456 or
            not 0 < int(host.get("NanoCpus", 0)) <= 500000000 or
            not 0 < int(host.get("PidsLimit", 0)) <= 128):
        raise ValueError("runtime network/resource restrictions absent")
    mounts = container.get("Mounts", [])
    if (len(mounts) != 1 or mounts[0].get("Type") != "volume" or
            mounts[0].get("Name") != PROJECT + "_idp_data" or
            mounts[0].get("Destination") != "/data" or mounts[0].get("RW") is not True):
        raise ValueError("runtime state mount mismatch")
    env = conf.get("Env", [])
    if any(item.startswith(("TS_AUTHKEY=", "TS_CLIENT_SECRET=", "NEXTAUTH_SECRET=")) for item in env):
        raise ValueError("credentials unexpectedly embedded in container")
    return True


def enrolled(status):
    if not isinstance(status, dict):
        return False
    peers = status.get("Peer", {})
    if not isinstance(peers, dict):
        return False
    matching = [p for p in peers.values() if isinstance(p, dict)
                and p.get("HostName") == "kipnerter-idp-staging"
                and p.get("Online") is True and TAG in p.get("Tags", [])]
    return len(matching) == 1


def discovery_valid(metadata, response_url):
    """Reject redirected discovery, credentialed/foreign endpoints or HTTP links."""
    if response_url != ORIGIN + "/.well-known/openid-configuration":
        return False
    if not isinstance(metadata, dict) or metadata.get("issuer") != ORIGIN:
        return False
    for field in ("jwks_uri", "authorization_endpoint", "token_endpoint"):
        url = metadata.get(field)
        if not isinstance(url, str) or len(url) > 1024:
            return False
        try:
            parsed = urllib.parse.urlsplit(url)
            if (parsed.scheme != "https" or parsed.hostname != DNS_NAME or
                    parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
                return False
        except ValueError:
            return False
    return True


def safe_json_command(*args):
    raw = subprocess.check_output(args, timeout=10, stderr=subprocess.DEVNULL)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("oversize tool response")
    return json.loads(raw)


def inspect(offline=False):
    result = {"purpose": "private_tsidp_bootstrap_preflight",
              "compose_safe": False, "runtime_isolated": False,
              "tailnet_enrolled": False, "oidc_discovery_valid": False,
              "oidc_client_registered": False, "browser_login_verified": False,
              "staging_deploy_authorized": False, "production_deploy_authorized": False,
              "release_gate": "NO_GO"}
    try:
        model = safe_json_command("docker", "compose", "-f", str(COMPOSE), "config", "--format", "json")
        result["compose_safe"] = check_compose(model)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return result
    if offline:
        return result
    try:
        found = safe_json_command("docker", "inspect", CONTAINER)
        result["runtime_isolated"] = check_runtime(found[0])
    except (OSError, ValueError, TypeError, KeyError, IndexError, subprocess.SubprocessError):
        return result
    try:
        result["tailnet_enrolled"] = enrolled(safe_json_command("tailscale", "status", "--json"))
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return result
    if result["tailnet_enrolled"]:
        try:
            url = ORIGIN + "/.well-known/openid-configuration"
            with urllib.request.urlopen(url, timeout=8) as response:
                content = response.read(MAX_JSON + 1)
                if len(content) <= MAX_JSON and response.status == 200:
                    result["oidc_discovery_valid"] = discovery_valid(json.loads(content), response.geturl())
        except (OSError, ValueError, TypeError, KeyError, urllib.error.URLError):
            pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="only validate Compose; no Docker inspect or HTTP")
    args = parser.parse_args()
    result = inspect(offline=args.offline)
    print(json.dumps(result, sort_keys=True))
    return 0 if all(result[k] for k in ("compose_safe", "runtime_isolated", "tailnet_enrolled", "oidc_discovery_valid")) else 3


if __name__ == "__main__":
    sys.exit(main())
