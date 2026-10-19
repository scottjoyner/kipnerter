#!/usr/bin/env python3
"""Deny-only staging credential preflight for the STATELESS fleet-chat preview.

Intentionally does not ask for spatial, MinIO, recovery, or production
cutover secrets. A configuration PASS never permits an actual deployment.
"""
import argparse
import json
import os
import re
from urllib.parse import urlsplit

REQUIRED = (
    "TS_OAUTH_CLIENT_ID", "TS_OAUTH_SECRET",
    "NEXTAUTH_SECRET", "TSIDP_ISSUER", "TSIDP_CLIENT_ID", "TSIDP_CLIENT_SECRET",
    "KIPNERTER_ALLOWED_EMAILS", "KIPNERTER_ALLOWED_TSIDP_SUBJECTS",
    "FLEET_MONITOR_BASE_URL", "FLEET_MONITOR_TOKEN", "KIPNERTER_GATEWAY_TOKEN",
    "KIPNERTER_DEPLOY_HOST", "KIPNERTER_DEPLOY_USER",
)
SHA = re.compile(r"[a-f0-9]{40}\Z")
HOST = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")
USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}\Z")
EMAIL = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\Z")


def _https_origin(value, require_tsidp=False, allow_monitor_port=False):
    if not isinstance(value, str) or len(value) > 256:
        return False
    try:
        u = urlsplit(value)
        if (u.scheme != "https" or not u.hostname or u.username or
                u.password or u.port not in ((None, 443, 8448) if allow_monitor_port else (None, 443)) or
                u.path not in ("", "/") or u.query or u.fragment):
            return False
    except ValueError:
        return False
    host = u.hostname
    if host == "localhost" or host.endswith(".localhost"):
        return False
    if require_tsidp and not host.endswith(".ts.net"):
        return False
    return True


def _csv(value, predicate):
    if not isinstance(value, str) or not value or len(value) > 8192:
        return False
    items = value.split(",")
    return (0 < len(items) <= 32 and all(
        item == item.strip() and bool(predicate(item))
        and not any(c.isspace() for c in item) for item in items)
        and len(set(items)) == len(items))


def classify(revision, values):
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        raise ValueError("exact lowercase portal SHA required")
    missing = sorted(k for k in REQUIRED if not values.get(k))
    invalid = []
    lengths = {"NEXTAUTH_SECRET": 32, "TSIDP_CLIENT_SECRET": 16,
               "FLEET_MONITOR_TOKEN": 32, "KIPNERTER_GATEWAY_TOKEN": 32}
    for key, minimum in lengths.items():
        if values.get(key) and (not isinstance(values[key], str) or
                                len(values[key]) < minimum or
                                "\n" in values[key] or "\r" in values[key]):
            invalid.append(key + "_INVALID")
    if values.get("TSIDP_ISSUER") and not _https_origin(values["TSIDP_ISSUER"], True):
        invalid.append("TSIDP_ISSUER_INVALID")
    if values.get("FLEET_MONITOR_BASE_URL") and not _https_origin(values["FLEET_MONITOR_BASE_URL"], True, True):
        invalid.append("FLEET_MONITOR_BASE_URL_INVALID")
    emails = values.get("KIPNERTER_ALLOWED_EMAILS")
    if emails and not _csv(emails, lambda s: EMAIL.fullmatch(s) is not None and s == s.lower()):
        invalid.append("KIPNERTER_ALLOWED_EMAILS_INVALID")
    subs = values.get("KIPNERTER_ALLOWED_TSIDP_SUBJECTS")
    if subs and not _csv(subs, lambda s: 3 <= len(s) <= 200 and all(
            c.isprintable() and c not in "\t\r\n" for c in s)):
        invalid.append("KIPNERTER_ALLOWED_TSIDP_SUBJECTS_INVALID")
    host = values.get("KIPNERTER_DEPLOY_HOST")
    if host and (not HOST.fullmatch(host) or host.startswith("kipnerter-prod")):
        invalid.append("KIPNERTER_DEPLOY_HOST_INVALID")
    user = values.get("KIPNERTER_DEPLOY_USER")
    if user and (not USER.fullmatch(user) or user == "root"):
        invalid.append("KIPNERTER_DEPLOY_USER_INVALID")
    # Neither absent storage approval secrets nor present ones change these holds.
    return {
        "purpose": "stateless_staging_fleet_chat_config_only",
        "planned_sha": revision,
        "required_count": len(REQUIRED),
        "configured_count": len(REQUIRED) - len(missing),
        "missing_setting_names": missing,
        "invalid_checks": sorted(invalid),
        "configuration_gate": "NO_GO" if (missing or invalid) else "PASS_CANDIDATE",
        "requires_spatial_or_minio_credentials": False,
        "staging_host_identity_verified": False,
        "real_browser_oidc_verified": False,
        "signed_restore_verified": False,
        "production_deploy_authorized": False,
        "public_ingress_authorized": False,
        "production_modified": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--planned-sha", required=True)
    args = parser.parse_args()
    try:
        receipt = classify(args.planned_sha, os.environ)
    except (TypeError, ValueError):
        print("NO_GO: invalid stateless candidate SHA")
        return 2
    print(json.dumps(receipt, sort_keys=True))
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Stateless fleet-chat staging configuration (no writes)\n")
            f.write("Gate: **" + receipt["configuration_gate"] + "**.\n\n")
            f.write("Missing: " + (", ".join(receipt["missing_setting_names"]) or "none") + "\n\n")
            f.write("Invalid checks: " + (", ".join(receipt["invalid_checks"]) or "none") + "\n\n")
            f.write("No real sign-in, staging host, runtime rollout, or production approval proven.\n")
    return 0 if receipt["configuration_gate"] == "PASS_CANDIDATE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
