#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    request_headers = {"Accept": "application/json"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        parsed: dict[str, Any]
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw.decode(errors="replace")}
        raise RuntimeError(f"{method} {url} -> HTTP {exc.code}: {parsed}") from exc


def expect_status(actual: int, expected: set[int], step: str) -> None:
    if actual not in expected:
        raise RuntimeError(f"{step}: expected {sorted(expected)}, got {actual}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Kipnerter spatial API release smoke test")
    parser.add_argument("--base-url", default=os.getenv("KIPNERTER_SPATIAL_BASE_URL", "https://api.kipnerter.com"))
    parser.add_argument("--token", default=os.getenv("KIPNERTER_SPATIAL_API_KEY"))
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if not args.token:
        parser.error("--token or KIPNERTER_SPATIAL_API_KEY is required")

    base = args.base_url.rstrip("/")
    run_id = uuid4().hex
    installation_id = f"release-smoke-{run_id}"
    client_scan_id = f"release-smoke-scan-{run_id}"

    for path in ("/health/live", "/health/ready", "/version"):
        status, payload = request_json("GET", base + path)
        expect_status(status, {200}, path)
        print(f"PASS {path}: {payload}")

    status, device = request_json(
        "POST",
        base + "/v1/devices/register",
        token=args.token,
        payload={
            "installation_id": installation_id,
            "name": "Release smoke client",
            "platform": "smoke",
            "app_version": "release-smoke",
            "capabilities": ["roomplan"],
        },
        headers={"Idempotency-Key": f"device-{run_id}"},
    )
    expect_status(status, {200, 201}, "device registration")
    device_id = device["id"]
    print(f"PASS device={device_id}")

    status, property_item = request_json(
        "POST",
        base + "/v1/properties",
        token=args.token,
        payload={"name": f"Release Smoke {run_id[:8]}", "metadata": {"smoke": True, "run_id": run_id}},
        headers={"Idempotency-Key": f"property-{run_id}"},
    )
    expect_status(status, {201}, "property create")
    property_id = property_item["id"]
    print(f"PASS property={property_id}")

    scan_payload = {
        "device_id": device_id,
        "property_id": property_id,
        "kind": "roomplan",
        "client_scan_id": client_scan_id,
        "captured_at": datetime.now(UTC).isoformat(),
        "coordinate_frame": "roomplan-release-smoke-v1",
        "metadata": {"smoke": True, "run_id": run_id},
    }
    status, scan = request_json(
        "POST",
        base + "/v1/scans",
        token=args.token,
        payload=scan_payload,
        headers={"Idempotency-Key": f"scan-{run_id}"},
    )
    expect_status(status, {201}, "scan create")
    scan_id = scan["id"]

    status, replay = request_json(
        "POST",
        base + "/v1/scans",
        token=args.token,
        payload=scan_payload,
        headers={"Idempotency-Key": f"scan-{run_id}"},
    )
    expect_status(status, {201}, "scan idempotency replay")
    if replay["id"] != scan_id:
        raise RuntimeError("idempotency replay returned a different scan")
    print(f"PASS scan={scan_id} idempotency replay")

    roomplan = {
        "identifier": f"release-smoke-{run_id}",
        "version": 1,
        "walls": [
            {
                "identifier": "wall-1",
                "dimensions": [3.0, 2.5, 0.1],
                "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            }
        ],
        "doors": [],
        "windows": [],
        "openings": [],
        "objects": [],
        "floors": [],
        "sections": [],
        "smoke_metadata": {"run_id": run_id},
    }
    artifact_bytes = json.dumps(roomplan, separators=(",", ":"), sort_keys=True).encode()
    artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()

    status, upload = request_json(
        "POST",
        base + f"/v1/scans/{scan_id}/artifacts",
        token=args.token,
        payload={
            "kind": "roomplan_json",
            "filename": "release-smoke-roomplan.json",
            "content_type": "application/json",
            "byte_size": len(artifact_bytes),
            "sha256": artifact_sha,
            "metadata": {"smoke": True, "run_id": run_id},
        },
        headers={"Idempotency-Key": f"artifact-{run_id}"},
    )
    expect_status(status, {201}, "artifact declare")
    artifact_id = upload["artifact_id"]

    put_req = urllib.request.Request(
        upload["url"], data=artifact_bytes, headers=dict(upload.get("headers") or {}), method="PUT"
    )
    try:
        with urllib.request.urlopen(put_req, timeout=60) as response:
            if response.status not in {200, 201, 204}:
                raise RuntimeError(f"presigned PUT returned {response.status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"presigned PUT -> HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
    print(f"PASS presigned upload artifact={artifact_id} bytes={len(artifact_bytes)} sha256={artifact_sha}")

    status, verified = request_json(
        "POST",
        base + f"/v1/artifacts/{artifact_id}/verify",
        token=args.token,
        payload={},
        headers={"Idempotency-Key": f"verify-{run_id}"},
    )
    expect_status(status, {200}, "artifact verify")
    if verified["id"] != artifact_id:
        raise RuntimeError("verify returned a different artifact")
    print("PASS artifact verification")

    status, completed = request_json(
        "POST",
        base + f"/v1/scans/{scan_id}/complete",
        token=args.token,
        payload={"artifact_ids": [artifact_id]},
        headers={"Idempotency-Key": f"complete-{run_id}"},
    )
    expect_status(status, {200}, "scan complete")
    if completed.get("state") != "complete":
        raise RuntimeError(f"scan did not complete: {completed}")
    print("PASS scan completion")

    cursor = None
    saw_completed_change = False
    for _ in range(10):
        url = base + "/v1/sync/changes?limit=500"
        if cursor:
            url += "&cursor=" + urllib.parse.quote(cursor, safe="")
        status, page = request_json("GET", url, token=args.token)
        expect_status(status, {200}, "sync changes")
        for change in page.get("changes", []):
            if change.get("entity_id") == scan_id and change.get("operation") == "complete":
                saw_completed_change = True
                break
        cursor = page.get("next_cursor")
        if saw_completed_change or not page.get("has_more"):
            break
    if not saw_completed_change:
        raise RuntimeError("completed scan was not visible in incremental sync")
    print("PASS incremental sync observes completed scan")

    result = {
        "run_id": run_id,
        "base_url": base,
        "device_id": device_id,
        "property_id": property_id,
        "scan_id": scan_id,
        "artifact_id": artifact_id,
        "artifact_sha256": artifact_sha,
        "completed_at": completed.get("completed_at"),
    }
    encoded = json.dumps(result, indent=2, sort_keys=True)
    print(encoded)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise
