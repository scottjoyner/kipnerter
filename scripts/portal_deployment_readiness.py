#!/usr/bin/env python3
"""Deny-only deployment readiness check; does not contact production or print secrets.

The exact planned release SHA is required, since this workflow's own checkout
SHA is different. An apparent "ready" result is not a rollback rehearsal, OIDC
login proof, source digest, or independent operator authorization.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from typing import Mapping

SHA = re.compile(r"^[0-9a-f]{40}$")
REQUIRED = (
    "TS_OAUTH_CLIENT_ID", "TS_OAUTH_SECRET",
    "KIPNERTER_API_REPO_TOKEN", "KIPNERTER_SPATIAL_API_KEY",
    "KIPNERTER_SPATIAL_DB_PASSWORD", "KIPNERTER_SPATIAL_S3_ACCESS_KEY_ID",
    "KIPNERTER_SPATIAL_S3_SECRET_ACCESS_KEY",
    "NEXTAUTH_SECRET", "TSIDP_ISSUER", "TSIDP_CLIENT_ID", "TSIDP_CLIENT_SECRET",
    "KIPNERTER_ALLOWED_EMAILS", "KIPNERTER_ALLOWED_TSIDP_SUBJECTS",
    "FLEET_MONITOR_BASE_URL", "FLEET_MONITOR_TOKEN", "KIPNERTER_GATEWAY_TOKEN",
    "KIPNERTER_CUTOVER_APPROVED_SHA", "KIPNERTER_DATA_RECOVERY_WITNESS_SHA",
)
STAGING = ("KIPNERTER_DEPLOY_HOST", "KIPNERTER_DEPLOY_USER")


def classify(environment: str, expected_sha: str, values: Mapping[str, str]) -> dict:
    if environment not in ("staging", "production"):
        raise ValueError("unsupported environment")
    if not SHA.fullmatch(expected_sha):
        raise ValueError("expected portal revision must be a lowercase 40-hex SHA")
    names = REQUIRED + (STAGING if environment == "staging" else ())
    missing = sorted(name for name in names if not values.get(name))
    invalid: list[str] = []
    for name in ("KIPNERTER_CUTOVER_APPROVED_SHA", "KIPNERTER_DATA_RECOVERY_WITNESS_SHA"):
        if values.get(name) and values.get(name) != expected_sha:
            invalid.append(name + "_REVISION_MISMATCH")
    lengths = {
        "NEXTAUTH_SECRET":32, "KIPNERTER_SPATIAL_API_KEY":32,
        "KIPNERTER_SPATIAL_DB_PASSWORD":20,
        "KIPNERTER_SPATIAL_S3_SECRET_ACCESS_KEY":32,
        "FLEET_MONITOR_TOKEN":32, "KIPNERTER_GATEWAY_TOKEN":32,
    }
    for name, minimum in lengths.items():
        if values.get(name) and len(values[name]) < minimum:
            invalid.append(name + "_TOO_SHORT")
    for name in ("TSIDP_ISSUER", "FLEET_MONITOR_BASE_URL"):
        if values.get(name) and not values[name].startswith("https://"):
            invalid.append(name + "_MUST_BE_HTTPS")
    if environment == "staging" and values.get("KIPNERTER_DEPLOY_USER") == "root":
        invalid.append("KIPNERTER_DEPLOY_USER_ROOT_DENIED")
    if values.get("KIPNERTER_SPATIAL_DB_PASSWORD") and not re.fullmatch(
        r"[A-Za-z0-9._~-]+", values["KIPNERTER_SPATIAL_DB_PASSWORD"]
    ):
        invalid.append("KIPNERTER_SPATIAL_DB_PASSWORD_UNSAFE_FORMAT")
    # Operator attestations are necessary but not sufficient. Do not equate
    # environment secret configuration with real backup/identity evidence.
    return {
        "environment": environment,
        "planned_portal_sha": expected_sha,
        "configured_key_count": len(names) - len(missing),
        "required_key_count": len(names),
        "missing_secret_names": missing,
        "invalid_secret_checks": sorted(invalid),
        "configuration_gate": "PASS_CANDIDATE" if not (missing or invalid) else "NO_GO",
        "authorized_for_cutover": False,
        "oidc_live_login_verified": False,
        "data_restore_rehearsal_verified": False,
        "production_modified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True, choices=["staging", "production"])
    parser.add_argument("--planned-sha", required=True)
    args = parser.parse_args()
    try:
        report = classify(args.environment, args.planned_sha, os.environ)
    except ValueError:
        print("Readiness preflight invalid arguments; no production action", file=sys.stderr)
        return 2
    payload = json.dumps(report, sort_keys=True)
    print(payload)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write("### Kipnerter deploy configuration — no mutations\\n\\n")
            out.write("Status: **" + report["configuration_gate"] + "**\\n\\n")
            out.write("Missing keys: " + (", ".join(report["missing_secret_names"]) or "none") + "\\n\\n")
            out.write("Invalid checks: " + (", ".join(report["invalid_secret_checks"]) or "none") + "\\n\\n")
            out.write("Real OIDC, data recovery and live release authorization remain separate proof gates.\\n")
    return 0 if report["configuration_gate"] == "PASS_CANDIDATE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
