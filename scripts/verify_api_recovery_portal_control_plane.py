#!/usr/bin/env python3
"""Check a proposed gateway against the authenticated portal control-plane API.

Input is local OpenAPI JSON only. No HTTP requests, model execution or writes.
This is a necessary route contract, not sufficient authority for deployment.
"""
import argparse
import json
from pathlib import Path
import sys

REQUIRED = {
    ("GET", "/api/v1/release"),
    ("GET", "/api/v1/control-plane/overview"),
    ("GET", "/api/v1/control-plane/traces"),
    ("GET", "/api/v1/control-plane/nodes"),
    ("GET", "/api/v1/control-plane/models"),
    ("GET", "/api/v1/control-plane/sessions"),
}
ROUTE_METHODS = {"get", "post", "patch", "delete", "put"}


def operations(document):
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
        raise ValueError("invalid OpenAPI document")
    routes = set()
    for path, values in document["paths"].items():
        if not isinstance(path, str) or not isinstance(values, dict):
            raise ValueError("unexpected OpenAPI routes")
        for method in values:
            if method in ROUTE_METHODS:
                routes.add((method.upper(), path))
    return routes


def assess(portal_schema, candidate_schema):
    portal = operations(portal_schema)
    candidate = operations(candidate_schema)
    missing_portal = REQUIRED - portal
    if missing_portal:
        raise ValueError("portal source no longer matches pinned release contract")
    absent = sorted(REQUIRED - candidate)
    return {
        "portal_control_plane_required": len(REQUIRED),
        "portal_control_plane_preserved": len(REQUIRED) - len(absent),
        "missing_methods_and_paths": [{"method": method, "path": path}
                                      for method, path in absent],
        "compatibility": "PASS_CANDIDATE" if not absent else "NO_GO",
        "safe_to_deploy": False,
        "authorization_and_freshness_verified": False,
        "production_modified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--portal", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = assess(json.loads(args.portal.read_text()),
                        json.loads(args.candidate.read_text()))
        print(json.dumps(report, sort_keys=True))
        return 0 if report["compatibility"] == "PASS_CANDIDATE" else 3
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        print(json.dumps({"compatibility": "HOLD_INVALID_SPEC",
                          "safe_to_deploy": False,"production_modified": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
