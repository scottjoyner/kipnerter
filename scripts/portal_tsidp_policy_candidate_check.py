#!/usr/bin/env python3
"""Offline deny-only check of the Kipnerter tsidp HuJSON policy *candidate*.

No contact with the Tailnet, admin API, Docker or production. This is NOT a
Tailscale policy validator and can never attest to the live policy. It checks
the repository's limited commented-JSON dialect, not arbitrary HuJSON files.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "infra/tailscale/policy.hujson"
COMPOSE = ROOT / "infra/tailscale/tsidp-preview.compose.yml"
EXPECTED = {"src": ["autogroup:admin"], "dst": ["tag:tsidp"],
            "app": {"tailscale.com/cap/tsidp": [{"allow_admin_ui": True}]}}
# HTTPS transport and the application-level UI capability are independent.
# Do not silently depend on a permissive '*' network grant for reachability.
HTTPS_ADMIN = {"src": ["autogroup:admin"], "dst": ["tag:tsidp"],
               "ip": ["tcp:443"]}
MAX_BYTES = 131072


def strip_line_comments(raw: str) -> str:
    # This checked-in file uses only JSON strings plus // comments. Preserve
    # the string grammar so an embedded `https://` is never truncated.
    result = []
    in_string = False
    escape = False
    index = 0
    while index < len(raw):
        char = raw[index]
        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            result.append(char)
        elif char == "/" and index + 1 < len(raw) and raw[index + 1] == "/":
            while index < len(raw) and raw[index] not in "\r\n":
                index += 1
            continue
        else:
            result.append(char)
        index += 1
    if in_string:
        raise ValueError("unclosed policy string")
    return "".join(result)


def duplicate_safe_dict(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate policy field")
        out[key] = value
    return out


def inspect_policy(raw: str, requested_tag: str) -> dict:
    if type(raw) is not str or len(raw.encode()) > MAX_BYTES:
        raise ValueError("invalid or oversized candidate")
    model = json.loads(strip_line_comments(raw), object_pairs_hook=duplicate_safe_dict)
    if not isinstance(model, dict):
        raise ValueError("expected policy object")
    tag_owners = model.get("tagOwners", {})
    if not isinstance(tag_owners, dict) or tag_owners.get(requested_tag) != ["autogroup:admin"]:
        raise ValueError("requested device tag has no exact admin owner")
    grants = model.get("grants", [])
    if (not isinstance(grants, list) or
            sum(1 for g in grants if g == EXPECTED) != 1 or
            sum(1 for g in grants if g == HTTPS_ADMIN) != 1):
        raise ValueError("required narrow tsidp HTTPS transport / UI capability missing or duplicated")
    if any(isinstance(g, dict) and (requested_tag in g.get("dst", []) or
                                  "tailscale.com/cap/tsidp" in g.get("app", {}))
           and g not in (EXPECTED, HTTPS_ADMIN) for g in grants):
        raise ValueError("unexpected extra tsidp capability or network access")
    if any(isinstance(g, dict) and (g.get("src") == ["*"] or g.get("dst") == ["*"])
           and g.get("ip") == ["*"] for g in grants):
        raise ValueError("candidate must not contain blanket allow-all network access")
    return {"purpose": "tsidp_repo_candidate_only", "tag_owner": "admin",
            "admin_ui_only": True, "scoped_admin_https_443": True,
            "sts_authorized": False,
            "live_tailnet_policy_verified": False, "enrollment_authorized": False,
            "production_deploy_authorized": False, "release_gate": "NO_GO"}


def check(repo_policy=POLICY, repo_compose=COMPOSE):
    import yaml
    compose = yaml.safe_load(repo_compose.read_text())
    if (set(compose.get("services", {})) != {"idp"} or
            compose["services"]["idp"].get("environment", {}).get("TS_ADVERTISE_TAGS") != "tag:tsidp" or
            compose["services"]["idp"].get("environment", {}).get("TSIDP_ENABLE_STS") != "0"):
        raise ValueError("checked-in IdP advertised tag or STS state mismatch")
    return inspect_policy(repo_policy.read_text(), "tag:tsidp")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        result = check()
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        print(json.dumps({"purpose": "tsidp_repo_candidate_only",
                          "release_gate": "NO_GO", "candidate_valid": False}))
        return 2
    print(json.dumps({**result, "candidate_valid": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
