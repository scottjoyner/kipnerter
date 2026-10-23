#!/usr/bin/env python3
"""Bounded, count-only production PostgreSQL privilege census; no role-name output."""
from __future__ import annotations
import argparse
import json
import os
import re
import socket
import subprocess

HOST = "kipnerter-prod-01"
PG = "kipnerter-spatial-postgres-1"
IMAGE = "sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5"
ROLE_SQL = ("SELECT count(*),count(*) FILTER(WHERE rolcanlogin),"
            "count(*) FILTER(WHERE rolcanlogin AND rolsuper),"
            "count(*) FILTER(WHERE rolcanlogin AND rolcreaterole),"
            "count(*) FILTER(WHERE rolcanlogin AND rolbypassrls) FROM pg_roles")
SESSION_SQL = ("SELECT count(*) FILTER(WHERE s.backend_type='client backend'),"
               "count(*) FILTER(WHERE s.backend_type='client backend' AND r.rolsuper) "
               "FROM pg_stat_activity s LEFT JOIN pg_roles r ON s.usename=r.rolname "
               "WHERE s.datname=current_database()")
INSPECT = ["docker", "inspect", "--format", "{{.Image}}", PG]
PREFIX = ["docker", "exec", "-u", "postgres", PG, "psql", "-X", "-qAt", "-v",
          "ON_ERROR_STOP=1", "-U", "kipnerter", "-d", "kipnerter", "-c"]

def run_readonly(argv, *, runner=subprocess.run):
    if argv not in (INSPECT, PREFIX + [ROLE_SQL], PREFIX + [SESSION_SQL]):
        raise ValueError("unapproved Docker or SQL operation")
    result = runner(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=12, check=False)
    if result.returncode or len(result.stdout) > 1024:
        raise ValueError("untrusted bounded read-only result")
    return result.stdout.decode("ascii", "strict").strip()

def parse_counts(raw, expected):
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]+(?:\|[0-9]+)*", raw):
        raise ValueError("invalid aggregate shape")
    parts = raw.split("|")
    if len(parts) != expected:
        raise ValueError("wrong number of aggregates")
    values = [int(p) for p in parts]
    if any(v > 100000 for v in values) or any(v > values[0] for v in values[1:]):
        raise ValueError("inconsistent aggregate")
    if expected == 5 and any(v > values[1] for v in values[2:]):
        raise ValueError("privileged login subset invalid")
    return values

def inspect_counts(*, read=run_readonly):
    if read(INSPECT) != IMAGE:
        raise ValueError("production image drift")
    roles = parse_counts(read(PREFIX + [ROLE_SQL]), 5)
    sessions = parse_counts(read(PREFIX + [SESSION_SQL]), 2)
    return {
        "status": ("HOLD_SUPERUSER_LOGIN_PRODUCTION" if roles[2] or sessions[1]
                   else "HOLD_EXTERNAL_WRITERS_UNPROVEN"),
        "role_count": roles[0], "login_roles": roles[1],
        "login_superusers": roles[2], "login_role_administrators": roles[3],
        "login_rls_bypass_roles": roles[4],
        "observed_client_backends": sessions[0],
        "observed_superuser_client_backends": sessions[1],
        "client_connection_attribution_proven": False,
        "other_storage_writers_excluded": False,
        "production_modified": False, "postgres_writes_fenced": False,
        "minio_writes_fenced": False, "safe_to_cutover": False, "release_gate": "NO_GO",
    }

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-live", action="store_true")
    args = parser.parse_args(argv)
    def hold(status, exit_code):
        print(json.dumps({"status": status, "production_modified": False,
                          "safe_to_cutover": False, "release_gate": "NO_GO"}, sort_keys=True))
        return exit_code
    if not args.inspect_live:
        return hold("DRY_RUN_NO_DOCKER_OR_SQL", 3)
    if socket.gethostname() != HOST:
        return hold("HOLD_HOST_IDENTITY_MISMATCH", 3)
    if any(os.environ.get(key) for key in ("DOCKER_HOST", "DOCKER_CONTEXT")):
        return hold("HOLD_DOCKER_TARGET_OVERRIDE", 3)
    try:
        print(json.dumps(inspect_counts(), sort_keys=True))
        return 0
    except Exception:
        return hold("HOLD_UNTRUSTED_ROLE_AGGREGATES", 2)

if __name__ == "__main__":
    raise SystemExit(main())
