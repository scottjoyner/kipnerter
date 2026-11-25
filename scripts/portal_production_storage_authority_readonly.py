#!/usr/bin/env python3
"""Read-only production storage-authority census; never prints credentials or role names.

Runs on the exact production host ONLY when explicitly opted in. Docker ps and
inspect, and a bounded SELECT of PostgreSQL login-role catalog are the only
operations. This is not a write fence, account rotation, or release authority.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import socket
import subprocess
from urllib.parse import urlsplit, unquote
from scripts import portal_production_writer_surface_readonly as surface

PG = "kipnerter-spatial-postgres-1"
S3 = "kipnerter-spatial-minio-1"
CLIENTS = ("kipnerter-spatial-api-1", "kipnerter-spatial-worker-1")
CATALOG_SQL = (
    "SELECT rolname,rolsuper,rolcanlogin,rolcreaterole,rolbypassrls "
    "FROM pg_roles WHERE rolcanlogin ORDER BY rolname"
)
KNOWN_FLAGS = frozenset(("t", "f"))

def environment(obj):
    entries = obj.get("Config", {}).get("Env")
    if not isinstance(entries, list) or len(entries) > 256:
        raise ValueError("unsafe service environment inventory")
    result = {}
    for entry in entries:
        if not isinstance(entry, str) or "=" not in entry or len(entry) > 16384:
            raise ValueError("untrusted environment shape")
        name, _, value = entry.partition("=")
        if not name or len(name)>128 or name in result or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*",name):
            raise ValueError("ambiguous environment")
        result[name] = value
    return result

def pg_principal(raw):
    if not isinstance(raw, str) or not 0<len(raw)<=4096 or any(ord(c)<32 for c in raw):
        raise ValueError("untrusted database connection configuration")
    try:
        parts = urlsplit(raw)
        if parts.scheme not in ("postgres", "postgresql", "postgresql+asyncpg") or not parts.hostname or not parts.path:
            raise ValueError("unsupported PostgreSQL URL")
        user = unquote(parts.username or "")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,62}", user):
            raise ValueError("ambiguous database principal")
        return user
    except Exception:
        raise ValueError("invalid PostgreSQL principal configuration") from None

def parse_catalog(raw):
    if not isinstance(raw,bytes) or len(raw)>8192:
        raise ValueError("invalid bounded role catalog")
    result = {}
    try:
        text = raw.decode("utf-8","strict")
        for line in text.splitlines():
            items = line.split("|")
            if (len(items)!=5 or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,62}",items[0])
                    or any(v not in KNOWN_FLAGS for v in items[1:]) or items[0] in result):
                raise ValueError("invalid role catalog row")
            if items[2]!="t":
                raise ValueError("unexpected non-login role")
            result[items[0]] = {"superuser":items[1]=="t", "create_role":items[3]=="t",
                                "bypass_rls":items[4]=="t"}
    except Exception:
        raise ValueError("untrusted role catalog response") from None
    if not result or len(result)>60:
        raise ValueError("invalid login role count")
    return result

def classify(environments, catalog, surface_state):
    if (surface_state.get("status")!="WRITER_SURFACE_READ_ONLY_OBSERVED_NOT_FENCED"
            or surface_state.get("release_gate")!="NO_GO"
            or surface_state.get("running_containers")!=7):
        raise ValueError("unqualified Docker writer surface")
    if set(environments)!={PG,S3,*CLIENTS} or not catalog:
        raise ValueError("incomplete storage authorities")
    root = environments[S3].get("MINIO_ROOT_USER")
    if not root or len(root)>128:
        raise ValueError("MinIO root identity unavailable")
    db_principals = []
    s3_root_bindings = 0
    s3_root_password_matches = 0
    privileged_db = 0
    for client in CLIENTS:
        env=environments[client]
        username=pg_principal(env.get("KIPNERTER_DATABASE_URL"))
        role=catalog.get(username)
        if role is None:
            raise ValueError("configured DB role not found in catalog")
        db_principals.append(username)
        privileged_db+=bool(role["superuser"] or role["create_role"] or role["bypass_rls"])
        s3_id=env.get("KIPNERTER_S3_ACCESS_KEY_ID")
        if not s3_id or not env.get("KIPNERTER_S3_SECRET_ACCESS_KEY") or len(s3_id)>128:
            raise ValueError("incomplete object-store authority binding")
        s3_root_bindings+=bool(s3_id==root)
        s3_root_password_matches+=bool(
            s3_id==root and
            env["KIPNERTER_S3_SECRET_ACCESS_KEY"]==
            environments[S3].get("MINIO_ROOT_PASSWORD")
        )
    superusers=sum(bool(role["superuser"]) for role in catalog.values())
    return {
      "status":"HOLD_PRIVILEGED_STORAGE_CLIENT_AUTHORITY" if privileged_db or s3_root_bindings else "HOLD_EXTERNAL_STORAGE_AUTHORITY_UNPROVEN",
      "production_modified":False,"release_gate":"NO_GO","safe_to_cutover":False,
      "client_bindings_checked":len(CLIENTS),
      "postgres_login_roles":len(catalog),"postgres_login_superuser_roles":superusers,
      "postgres_configured_clients_using_privileged_roles":privileged_db,
      "postgres_app_clients_same_login":len(set(db_principals))==1,
      "s3_app_clients_using_root_access_identifier":s3_root_bindings,
      "s3_app_clients_using_root_credential_pair":s3_root_password_matches,
      "s3_other_admin_or_external_access_excluded":False,
      "all_actual_connected_sessions_attributed":False,
      "postgres_writes_fenced":False,"minio_writes_fenced":False,
      "cross_service_point_in_time_consistent":False,
      "independent_administrative_custody":False,
    }

def live_report():
    objects=surface.collect()
    topo=surface.analyze(objects)
    entries={obj["Name"].strip("/"):obj for obj in objects}
    selected={name:environment(entries[name]) for name in (PG,S3,*CLIENTS)}
    command=["docker","exec","-u","postgres",PG,"psql","-X","-qAt","-v","ON_ERROR_STOP=1",
             "-F","|","-U","kipnerter","-d","kipnerter","-c",CATALOG_SQL]
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=12,check=True)
    return classify(selected,parse_catalog(result.stdout),topo)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-live",action="store_true")
    args=parser.parse_args()
    if not args.inspect_live:
        print(json.dumps({"status":"DRY_RUN_NO_DOCKER_OR_SQL","production_modified":False,
          "safe_to_cutover":False,"release_gate":"NO_GO"},sort_keys=True))
        return 3
    if socket.gethostname()!=surface.HOST:
        print(json.dumps({"status":"HOLD_UNAPPROVED_HOST","production_modified":False,
          "safe_to_cutover":False,"release_gate":"NO_GO"},sort_keys=True))
        return 3
    if any(os.environ.get(k) for k in ("DOCKER_HOST","DOCKER_CONTEXT")):
        print(json.dumps({"status":"HOLD_DOCKER_TARGET_OVERRIDE",
            "production_modified":False,"safe_to_cutover":False,"release_gate":"NO_GO"},sort_keys=True))
        return 3
    try:
        print(json.dumps(live_report(),sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"status":"HOLD_UNTRUSTED_STORAGE_AUTHORITY_INVENTORY",
          "production_modified":False,"safe_to_cutover":False,"release_gate":"NO_GO"},sort_keys=True))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
