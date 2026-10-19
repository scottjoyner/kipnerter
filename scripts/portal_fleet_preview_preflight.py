#!/usr/bin/env python3
"""Deny-only validator for isolated, stateless fleet-portal preview Compose.

Accepts only rendered Compose JSON on stdin; no Docker/SSH actions or secrets output.
Preflight is not an OIDC, ingress, operator-approval or deployment authorization.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 2 * 1024 * 1024
PROJECT = "kipnerter-fleet-preview"


def validate(model):
    if not isinstance(model, dict) or model.get("name") != PROJECT:
        raise ValueError("wrong Compose project")
    services = model.get("services")
    if not isinstance(services, dict) or set(services) != {"web", "api"}:
        raise ValueError("unexpected service: stateful backend or public ingress denied")
    if model.get("volumes"):
        raise ValueError("named volumes not allowed")
    networks = model.get("networks")
    if not isinstance(networks, dict) or set(networks) != {"frontend", "backend"}:
        raise ValueError("unexpected networks")
    if networks["backend"].get("internal") is not True:
        raise ValueError("backend must be an internal bridge")
    for name in ("web", "api"):
        item = services[name]
        if not isinstance(item, dict) or item.get("privileged") is True:
            raise ValueError("privileged or invalid service")
        if item.get("volumes") or item.get("devices") or item.get("network_mode"):
            raise ValueError("host/device/volume mounts denied")
        if item.get("cap_add") or item.get("pid") or item.get("ipc"):
            raise ValueError("additional privileges denied")
        if item.get("deploy", {}).get("mode") == "global":
            raise ValueError("global workloads denied")
        build = item.get("build")
        if (not isinstance(build, dict)
                or build.get("context") != str(ROOT / "apps" / name)
                or build.get("dockerfile", "Dockerfile") != "Dockerfile"
                or build.get("network") in ("host", "none")):
            raise ValueError("only the exact checked-in service build is allowed")
    web = services["web"]
    api = services["api"]
    if api.get("ports"):
        raise ValueError("API must not bind a host port")
    ports = web.get("ports")
    if not isinstance(ports, list) or len(ports) != 1:
        raise ValueError("exactly one loopback preview port required")
    port = ports[0]
    if not isinstance(port, dict) or any([
        port.get("host_ip") != "127.0.0.1", str(port.get("published")) != "13300",
        port.get("target") != 3000, port.get("protocol") != "tcp",
    ]):
        raise ValueError("preview web port must be loopback-only")
    if set(web.get("networks", {})) != {"frontend"}:
        raise ValueError("web must connect only to frontend")
    if set(api.get("networks", {})) != {"frontend", "backend"}:
        raise ValueError("API network shape changed")
    web_env = web.get("environment")
    api_env = api.get("environment")
    if not isinstance(web_env, dict) or not isinstance(api_env, dict):
        raise ValueError("invalid environment")
    if (web_env.get("KIPNERTER_ENV") != "staging"
            or api_env.get("KIPNERTER_ENV") != "staging"
            or web_env.get("NEXTAUTH_URL") != "https://staging.kipnerter.com"
            or web_env.get("KIPNERTER_INTERNAL_API_URL") != "http://api:8000"):
        raise ValueError("preview has crossed origin or environment boundary")
    if api_env.get("FLEET_MONITOR_BASE_URL") and not str(api_env["FLEET_MONITOR_BASE_URL"]).startswith("https://"):
        raise ValueError("private observer must use HTTPS")
    return {"project": PROJECT, "services": ["api", "web"],
            "web_host_ip": "127.0.0.1", "web_host_port": 13300,
            "contains_persistent_storage": False, "publicly_routable": False,
            "oidc_real_login_verified": False, "deployment_authorized": False,
            "production_modified": False}


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Compose payload too large")
        model = json.loads(raw)
        report = validate(model)
    except (ValueError, TypeError, KeyError, AttributeError):
        print("NO_GO: invalid or unsafe fleet-preview Compose; no changes made", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
