#!/usr/bin/env python3
"""Offline preflight of an owner-controlled DO disaster-recovery clone.

NO API calls, droplet creation, firewall updates, downloads or prod reads.
Snapshot cloning is permitted only after the deny-all firewall is created,
effective status verified, tag non-overlap checked and costs explicitly approved.
This program only returns a candidate request; it never submits it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

SNAPSHOT_ID = 250354430
PRODUCTION_ID = 593032509
EXPECTED_CREATED = "2026-10-18T12:08:13Z"
EXPECTED_REGION = "nyc3"
RECOVERY_TAG = "kp-dr-quarantine-20261018-250354430"
FIREWALL_NAME = "kp-dr-deny-all-20261018-250354430"
OWNER_APPROVAL = "AUTHORIZE_BILLABLE_ISOLATED_RESTORE_250354430"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")


def _obj(value, key):
    if not isinstance(value, dict):
        raise ValueError("invalid provider response object")
    item = value.get(key)
    if not isinstance(item, dict):
        raise ValueError("provider response not canonical")
    return item


def _empty_list(value, key):
    if not isinstance(value.get(key), list) or value[key]:
        raise ValueError("quarantine firewall contains rules or unverified changes")


def _deny_everything_rule(fw: dict, direction: str) -> None:
    key = "inbound_rules" if direction == "in" else "outbound_rules"
    endpoint = "sources" if direction == "in" else "destinations"
    rules = fw.get(key)
    if not isinstance(rules, list) or len(rules) != 1:
        raise ValueError("firewall must have exactly one explicit deny-all rule per direction")
    rule = rules[0]
    if (not isinstance(rule, dict) or rule.get("protocol") != "all" or
            rule.get("action") != "deny" or
            rule.get("ports") not in (None, "", "0", 0)):
        raise ValueError("firewall must explicitly deny every IP protocol")
    targets = rule.get(endpoint)
    if (not isinstance(targets, dict) or
            set(targets) != {"addresses"} or
            not isinstance(targets.get("addresses"), list) or
            set(targets["addresses"]) != {"0.0.0.0/0", "::/0"} or
            len(targets["addresses"]) != 2):
        raise ValueError("firewall deny-all must cover IPv4 and IPv6")


def verify_readbacks(snapshot_response: dict, firewall_response: dict,
                     droplets_response: dict, approval: str):
    if approval != OWNER_APPROVAL:
        raise ValueError("owner authorization for billed restoration missing")

    snapshot = _obj(snapshot_response, "image")
    if (type(snapshot.get("id")) is not int or snapshot["id"] != SNAPSHOT_ID or
            snapshot.get("type") != "snapshot" or
            snapshot.get("status") != "available" or
            snapshot.get("created_at") != EXPECTED_CREATED or
            snapshot.get("regions") != [EXPECTED_REGION] or
            type(snapshot.get("min_disk_size")) is not int or
            snapshot["min_disk_size"] > 80 or
            snapshot["min_disk_size"] < 1):
        raise ValueError("recovery snapshot identity or suitability changed")

    fw = _obj(firewall_response, "firewall")
    if (not isinstance(fw.get("id"), str) or
            not UUID.fullmatch(fw["id"]) or
            fw.get("name") != FIREWALL_NAME or
            fw.get("status") != "succeeded" or
            fw.get("tags") != [RECOVERY_TAG]):
        raise ValueError("quarantine firewall is absent, nonfinal or untrusted")
    for direction in ("in", "out"):
        _deny_everything_rule(fw, direction)
    for key in ("droplet_ids", "pending_changes"):
        _empty_list(fw, key)

    if not isinstance(droplets_response, dict):
        raise ValueError("droplet readback unavailable")
    nodes = droplets_response.get("droplets")
    if not isinstance(nodes, list) or not nodes or len(nodes) > 1000:
        raise ValueError("complete existing Droplet inventory is required")
    seen = set()
    prod = 0
    for node in nodes:
        if not isinstance(node, dict) or type(node.get("id")) is not int:
            raise ValueError("ambiguous Droplet identity")
        if node["id"] in seen:
            raise ValueError("duplicated Droplet inventory identity")
        seen.add(node["id"])
        tags = node.get("tags")
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValueError("Droplet tags unavailable")
        if RECOVERY_TAG in tags:
            raise ValueError("recovery tag already assigned to a live Droplet")
        if node["id"] == PRODUCTION_ID:
            prod += 1
            if node.get("name") != "kipnerter-prod-01" or node.get("status") != "active":
                raise ValueError("unexpected production Droplet identity")
    if prod != 1:
        raise ValueError("cannot establish production isolation boundary")

    return {
        "status": "RECOVERY_FIREWALL_PREFLIGHT_OK_NO_CLONE_CREATED",
        "snapshot_id": SNAPSHOT_ID,
        "source_created_utc": EXPECTED_CREATED,
        "region": EXPECTED_REGION,
        "quarantine_tag": RECOVERY_TAG,
        "firewall_readback_succeeded": True,
        "firewall_all_inbound_rules_denied": True,
        "firewall_all_outbound_rules_denied": True,
        "deny_rules_override_other_firewall_allows": True,
        "existing_droplet_tags_disjoint": True,
        "owner_cost_approval_token_checked": True,
        "protected_create_request": {
            "Name": "kipnerter-dr-20261018-quarantine",
            "Region": EXPECTED_REGION,
            "ImageID": SNAPSHOT_ID,
            "Size": "s-2vcpu-4gb",
            "Tags": [RECOVERY_TAG],
            "Backup": False,
            "Monitoring": False,
        },
        "restore_submitted": False,
        "boot_network_isolation_physically_confirmed": False,
        "running_historical_services_recovered": False,
        "database_or_object_store_restore_verified": False,
        "production_modified": False,
        "safe_to_cutover": False,
    }


def load_exact_json(path: Path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 2 * 1024**2:
        raise ValueError("missing, linked or unbounded provider readback")
    def no_duplicates(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise ValueError("duplicate provider response field")
            obj[k] = v
        return obj
    return json.loads(path.read_bytes(), object_pairs_hook=no_duplicates)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-readback", type=Path, required=True)
    parser.add_argument("--firewall-readback", type=Path, required=True)
    parser.add_argument("--droplets-readback", type=Path, required=True)
    parser.add_argument("--owner-approval", required=True,
                        help="Exact owner approval phrase; never an API credential.")
    args = parser.parse_args()
    try:
        result = verify_readbacks(
            load_exact_json(args.image_readback),
            load_exact_json(args.firewall_readback),
            load_exact_json(args.droplets_readback),
            args.owner_approval,
        )
    except (ValueError, OSError, UnicodeError):
        print(json.dumps({"status": "HOLD", "restore_submitted": False,
                          "production_modified": False, "safe_to_cutover": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
