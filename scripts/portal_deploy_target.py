#!/usr/bin/env python3
"""Fail-closed Tailscale deployment host selection: distinct prod/staging roles.

Only trusted `tailscale status --json` data may authorize a target. Bare
hostnames, untagged IPs and a staging fallback with production tags are never
deployment authority. No network operations or modifications here.
"""
import argparse
import ipaddress
import json
import re
import sys

ROLE_TAG = {
    "production": "tag:kipnerter-prod",
    "staging": "tag:kipnerter-staging",
}
ALL_ROLES = set(ROLE_TAG.values())
VALID_HOST = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")
TS_V4 = ipaddress.ip_network("100.64.0.0/10")


def select(status, environment, preferred_host=""):
    if environment not in ROLE_TAG:
        raise ValueError("unsupported deploy environment")
    if not isinstance(status, dict) or not isinstance(status.get("Peer"), dict):
        raise ValueError("invalid Tailscale status document")
    if preferred_host and not VALID_HOST.fullmatch(preferred_host):
        raise ValueError("preferred host must be a literal tailnet hostname")
    # Staging's GitHub-environment secret must explicitly name a single
    # target: discovery of any arbitrary staging-tagged node isn't enough.
    if environment == "staging" and not preferred_host:
        raise ValueError("staging deploy host must be explicitly configured")
    role = ROLE_TAG[environment]
    eligible = []
    for peer in status["Peer"].values():
        if not isinstance(peer, dict):
            continue
        name = peer.get("HostName")
        tags = peer.get("Tags")
        if (not isinstance(name, str) or not VALID_HOST.fullmatch(name)
                or not isinstance(tags, list) or not all(isinstance(t, str) for t in tags)):
            continue
        role_tags = ALL_ROLES.intersection(tags)
        # A dual-role machine must never serve as a staging rehearsal node.
        if role_tags != {role} or peer.get("Online") is not True:
            continue
        if environment == "production" and not name.startswith("kipnerter-prod-01"):
            continue
        if preferred_host and name != preferred_host:
            continue
        ips = peer.get("TailscaleIPs")
        if not isinstance(ips, list):
            continue
        valid_ips = []
        for ip in ips:
            try:
                addr = ipaddress.ip_address(ip)
            except (TypeError, ValueError):
                continue
            if isinstance(addr, ipaddress.IPv4Address) and addr in TS_V4:
                valid_ips.append(str(addr))
        if len(valid_ips) != 1:
            continue
        eligible.append((name, valid_ips[0]))
    if len(eligible) != 1:
        raise ValueError(f"{environment} requires exactly one online, exclusively tagged deployment host (found {len(eligible)})")
    return eligible[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True, choices=tuple(ROLE_TAG))
    parser.add_argument("--preferred-host", default="")
    args = parser.parse_args()
    try:
        name, ip = select(json.load(sys.stdin), args.environment, args.preferred_host)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise SystemExit("RELEASE HOLD: tagged tailnet target verification failed: " + str(exc)) from None
    # Print only the verified address for scripting. Do not print the original
    # Tailscale status, peer identities, identities, or service credentials.
    print(ip)


if __name__ == "__main__":
    main()
