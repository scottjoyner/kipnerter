#!/usr/bin/env python3
"""Owner-triggered Stage A firewall setup ONLY. Never create a Droplet.

Requires protected GitHub 'production' environment credentials. The quarantine
firewall/tag are deterministic and never attached to existing Droplets.
No backup conversion, Droplet creation, DNS, production config, or restores.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote

SNAPSHOT_ID = 250354430
PROD_ID = 593032509
CREATED_UTC = "2026-10-18T12:08:13Z"
TAG = "kp-dr-quarantine-20261018-250354430"
NAME = "kp-dr-deny-all-20261018-250354430"
CONFIRM = "APPLY_FIREWALL_ONLY_250354430_NO_DROPLET"
API_HOST = "https://api.digitalocean.com"

def rules(direction):
    endpoint = "sources" if direction == "inbound" else "destinations"
    return [
        {
            "protocol": protocol,
            "action": "deny",
            # DigitalOcean API requires ports on every rule; ICMP uses "0".
            "ports": "1-65535" if protocol in ("tcp", "udp") else "0",
            endpoint: {"addresses": ["0.0.0.0/0", "::/0"]},
        }
        for protocol in ("tcp", "udp", "icmp")
    ]

def required_firewall():
    return {
        "name": NAME,
        "tags": [TAG],
        "droplet_ids": [],
        "inbound_rules": rules("inbound"),
        "outbound_rules": rules("outbound"),
    }

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("provider redirect rejected before forwarding credential")


class API:
    def __init__(self, token):
        if not isinstance(token, str) or len(token.strip()) < 12:
            raise ValueError("protected DO credential unavailable")

        self.token = token
        self.opener = urllib.request.build_opener(_NoRedirect)

    def request(self, method, path, payload=None, allow_404=False):
        if method not in ("GET", "POST") or not path.startswith("/v2/"):
            raise ValueError("unapproved API request")
        if method == "POST" and path not in ("/v2/tags", "/v2/firewalls"):
            raise ValueError("operation outside Stage A")
        if path.count("//") or "?" in path and method == "POST":
            raise ValueError("invalid API path")
        raw = None if payload is None else json.dumps(
            payload, sort_keys=True, separators=(",", ":")).encode("utf8")
        req = urllib.request.Request(
            API_HOST + path, data=raw,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with self.opener.open(req, timeout=14) as reply:
                if reply.geturl().split("/v2/")[0] != API_HOST:
                    raise ValueError("provider redirected request")
                body = reply.read(1024 * 1024 + 1)
                if len(body) > 1024 * 1024:
                    raise ValueError("unbounded provider response")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and allow_404:
                return None
            # Never print body/headers: can include private account details.
            raise ValueError(f"DigitalOcean {method} request rejected (HTTP {exc.code})") from None

def _list_all(api, resource):
    gathered = []
    page = 1
    while page <= 10:
        info = api.request("GET", f"/v2/{resource}?page={page}&per_page=200")
        items = info.get(resource)
        total = info.get("meta", {}).get("total")
        if (not isinstance(items, list) or type(total) is not int
                or total < 0 or total > 2000):
            raise ValueError("incomplete provider inventory")
        gathered.extend(items)
        if len(gathered) == total:
            return gathered
        if len(gathered) > total or not items:
            raise ValueError("inconsistent provider inventory pagination")
        page += 1
    raise ValueError("provider inventory exceeds safe page window")

def _check_snapshot(api):
    value = api.request("GET", f"/v2/images/{SNAPSHOT_ID}")
    obj = value.get("image", {})
    if (type(obj.get("id")) is not int or obj["id"] != SNAPSHOT_ID
            or obj.get("type") != "snapshot"
            or obj.get("status") != "available"
            or obj.get("created_at") != CREATED_UTC
            or "nyc3" not in obj.get("regions", [])):
        raise ValueError("October 18 historical snapshot not as expected")

def _check_droplets(api):
    droplets = _list_all(api, "droplets")
    ids = set()
    production = False
    if not droplets:
        raise ValueError("production droplet missing")
    for obj in droplets:
        ident = obj.get("id")
        tags = obj.get("tags")
        if type(ident) is not int or ident in ids or not isinstance(tags, list):
            raise ValueError("invalid provider droplet inventory")
        ids.add(ident)
        if TAG in tags:
            raise ValueError("quarantine tag is currently applied to a droplet")
        if ident == PROD_ID:
            if obj.get("name") != "kipnerter-prod-01" or obj.get("status") != "active":
                raise ValueError("production identity unexpectedly changed")
            production = True
    if not production:
        raise ValueError("protected production droplet not found")

def _check_tag(api, *, must_exist=False):
    obj = api.request("GET", "/v2/tags/" + quote(TAG, safe=""), allow_404=True)
    if obj is None:
        if must_exist:
            raise ValueError("quarantine tag missing")
        return False
    tag = obj.get("tag")
    if not isinstance(tag, dict) or tag.get("name") != TAG:
        raise ValueError("quarantine tag identity mismatch")
    resources = tag.get("resources")
    if not isinstance(resources, dict):
        raise ValueError("tag association count missing")
    for category in ("droplets", "images", "volumes", "volume_snapshots", "databases"):
        detail = resources.get(category)
        if detail is not None and (not isinstance(detail, dict) or detail.get("count") != 0):
            raise ValueError("quarantine tag assigned to another resource")
    if not isinstance(resources.get("droplets"), dict) or resources["droplets"].get("count") != 0:
        raise ValueError("quarantine tag droplet count cannot be verified")
    return True

def _rule_set(values, endpoint):
    if not isinstance(values, list) or len(values) != 3:
        raise ValueError("expected exact three deny rules in each direction")
    signatures = set()
    for rule in values:
        if not isinstance(rule, dict) or rule.get("action") != "deny":
            raise ValueError("quarantine contains non-deny traffic rules")
        protocol = rule.get("protocol")
        expected_ports = "1-65535" if protocol in ("tcp", "udp") else "0"
        # Do not infer an absent ICMP ports value. API readback must
        # explicitly confirm "0" even though ICMP has no transport ports.
        raw_ports = rule.get("ports")
        if protocol not in ("tcp", "udp", "icmp") or raw_ports != expected_ports:
            raise ValueError("quarantine protocol/ports incomplete")
        target = rule.get(endpoint)
        if (not isinstance(target, dict)
                or set(target.get("addresses", [])) != {"0.0.0.0/0", "::/0"}
                or len(target.get("addresses", [])) != 2
                or any(k != "addresses" and v for k,v in target.items())):
            raise ValueError("quarantine network range mismatch")
        if protocol in signatures:
            raise ValueError("duplicate deny rule")
        signatures.add(protocol)
    if signatures != {"tcp", "udp", "icmp"}:
        raise ValueError("incomplete quarantine deny policy")

def _check_firewall(obj):
    if (not isinstance(obj, dict) or obj.get("name") != NAME
            or obj.get("tags") != [TAG] or obj.get("droplet_ids") != []
            or obj.get("status") != "succeeded" or obj.get("pending_changes") != []):
        raise ValueError("cloud firewall is not isolated and final")
    _rule_set(obj.get("inbound_rules"), "sources")
    _rule_set(obj.get("outbound_rules"), "destinations")
    if not isinstance(obj.get("id"), str) or len(obj["id"]) != 36:
        raise ValueError("firewall UUID unavailable")
    return obj["id"]

def _existing_firewall(api):
    matches = [f for f in _list_all(api,"firewalls")
               if f.get("name") == NAME or TAG in f.get("tags", [])]
    if len(matches) > 1:
        raise ValueError("ambiguous overlapping recovery firewalls")
    if not matches:
        return None
    fw = api.request("GET", "/v2/firewalls/" + quote(matches[0]["id"], safe=""))
    _check_firewall(fw.get("firewall"))
    return fw["firewall"]["id"]

def stage_a(api, mode="inventory", confirm=""):
    if mode not in ("inventory", "apply"):
        raise ValueError("unapproved action")
    if mode == "apply" and confirm != CONFIRM:
        raise ValueError("explicit owner approval marker missing")
    _check_snapshot(api)
    _check_droplets(api)
    tagged = _check_tag(api)
    existing = _existing_firewall(api)
    if existing is not None and not tagged:
        raise ValueError("firewall tag resource missing")
    if mode == "inventory":
        return {"status":"FIREWALL_VERIFIED" if existing else "FIREWALL_NOT_INSTALLED",
                "firewall_verified": bool(existing), "write_attempted":False,
                "droplet_created":False,"production_modified":False,
                "snapshot_id":SNAPSHOT_ID,"safe_to_restore":False}
    if existing:
        return {"status":"FIREWALL_ALREADY_VERIFIED","firewall_verified":True,
                "write_attempted":False,"droplet_created":False,
                "production_modified":False,"snapshot_id":SNAPSHOT_ID,
                "safe_to_restore":False}
    # Repeat live droplet check just before first mutation.
    _check_droplets(api)
    if not tagged:
        api.request("POST","/v2/tags", {"name":TAG})
        _check_tag(api,must_exist=True)
    # Recheck for manual actor races. Any existing config MUST match.
    if _existing_firewall(api):
        raise ValueError("concurrent firewall mutation detected; retry inventory")
    _check_droplets(api)
    api.request("POST","/v2/firewalls", required_firewall())
    for attempt in range(12):
        try:
            installed = _existing_firewall(api)
            if installed:
                _check_tag(api, must_exist=True)
                _check_droplets(api)
                return {"status":"FIREWALL_INSTALLED_VERIFIED",
                        "firewall_verified":True, "write_attempted":True,
                        "droplet_created":False, "production_modified":False,
                        "snapshot_id":SNAPSHOT_ID,"safe_to_restore":False}
        except ValueError:
            if attempt == 11:
                raise
        time.sleep(2)
    raise ValueError("firewall not authoritatively verified")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("inventory","apply"), required=True)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        result = stage_a(API(os.environ.get("DIGITALOCEAN_ACCESS_TOKEN", "")),
                         args.mode, args.confirm)
    except (ValueError, urllib.error.URLError, TimeoutError, OSError):
        print(json.dumps({"status":"HOLD","firewall_verified":False,
                          "safe_to_restore":False,"droplet_created":False}))
        return 2
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
