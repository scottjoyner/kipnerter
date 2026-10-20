#!/usr/bin/env python3
"""Read-only fleet-wide exact legacy OCI image ID audit.

Never requests image layers, config JSON, registry credentials, Docker logs,
container environments, production files or mounts; does not pull/run images.
Only existing, approved SSH aliases are queried with host-key checking.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

ROLES = {
    "legacy-api": "sha256:7efc68e54ff1289ee2033440ea0ee176962e3a57e0d24e091a2365ca769d5860",
    "legacy-web": "sha256:5dfd3de1d45260b826d52eb107df8398e872121c9d98ade02540f3917fc78726",
}
HOSTS = ("destroyer", "xwing", "lenovo", "beelink-ryzen-7-mini-pc",
         "deathstar-xps-8920", "scott-optiplex-9030-aio")
HEX = re.compile(r"sha256:[0-9a-f]{64}\Z")
STATUSES = {"EXACT_PRESENT", "EXACT_ABSENT", "DOCKER_INACCESSIBLE",
            "SSH_UNAVAILABLE"}


def remote_command() -> str:
    # Fixed image IDs from the separately verified first-party legacy
    # production receipt. No user-controlled interpolation or private values.
    assert all(HEX.fullmatch(s) for s in ROLES.values())
    api, web = ROLES.values()
    return (
        "if ! command -v docker >/dev/null 2>&1 || "
        "! docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; "
        "then printf 'DOCKER_INACCESSIBLE\\n'; exit 0; fi; "
        "for image in "+api+" "+web+"; do "
        "id=$(docker image inspect --format '{{.Id}}' \"$image\" 2>/dev/null); "
        "if [ \"$id\" = \"$image\" ]; then printf 'EXACT_PRESENT\\n'; "
        "else printf 'EXACT_ABSENT\\n'; fi; done"
    )


def classify_ssh_result(returncode, stdout):
    if returncode != 0:
        return {"docker": "SSH_UNAVAILABLE", "legacy-api": "SSH_UNAVAILABLE",
                "legacy-web": "SSH_UNAVAILABLE"}
    if not isinstance(stdout, (bytes, bytearray)) or len(stdout) > 128:
        raise ValueError("unexpected overlong host response")
    lines = stdout.decode("ascii", "strict").splitlines()
    if lines == ["DOCKER_INACCESSIBLE"]:
        return {"docker": "DOCKER_INACCESSIBLE",
                "legacy-api": "DOCKER_INACCESSIBLE",
                "legacy-web": "DOCKER_INACCESSIBLE"}
    if (len(lines) != 2 or
            any(x not in ("EXACT_PRESENT", "EXACT_ABSENT") for x in lines)):
        raise ValueError("untrusted host image evidence response")
    return {"docker": "AVAILABLE", "legacy-api": lines[0], "legacy-web": lines[1]}


def audit(*, runner=subprocess.run, hosts=HOSTS):
    if (type(hosts) not in (tuple, list) or not hosts or
            len(hosts) > len(HOSTS) or
            len(set(hosts)) != len(hosts) or
            any(h not in HOSTS for h in hosts)):
        raise ValueError("unapproved host scope")
    reports = {}
    for host in hosts:
        cmd = ["ssh", "-T", "-o", "BatchMode=yes",
               "-o", "StrictHostKeyChecking=yes",
               "-o", "ConnectTimeout=5",
               "-o", "ClearAllForwardings=yes",
               "-o", "RequestTTY=no", "--", host, remote_command()]
        try:
            response = runner(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, check=False, timeout=11)
            reports[host] = classify_ssh_result(
                response.returncode, response.stdout)
        except (ValueError, UnicodeError):
            reports[host] = {
                "docker": "UNTRUSTED_RESPONSE",
                "legacy-api": "UNTRUSTED_RESPONSE",
                "legacy-web": "UNTRUSTED_RESPONSE",
            }
        except (OSError, subprocess.SubprocessError):
            reports[host] = {
                "docker": "SSH_UNAVAILABLE",
                "legacy-api": "SSH_UNAVAILABLE",
                "legacy-web": "SSH_UNAVAILABLE",
            }
    present = sorted(f"{host}:{role}" for host, states in reports.items()
                     for role in ROLES if states[role] == "EXACT_PRESENT")
    return {
        "source": "read_only_legacy_oci_fleet_cache_audit",
        "roles_checked": list(ROLES),
        "host_classification": reports,
        "exact_image_cache_hits": present,
        "original_image_bytes_retrieved": False,
        "production_host_probed": False,
        "registries_contacted": False,
        "docker_daemons_modified": False,
        "runnable_rollback_verified": False,
        "independent_admin_custody_verified": False,
        "production_recovery_approved": False,
        "safe_to_cutover": False,
        "next_gate": "owner_review_of_exact_oci_or_independently_reconstructed_rollback",
    }


def main():
    try:
        result = audit()
        print(json.dumps(result, sort_keys=True))
        return 0
    except ValueError:
        print(json.dumps({"status":"HOLD","safe_to_cutover":False},
                         sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
