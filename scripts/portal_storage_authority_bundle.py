#!/usr/bin/env python3
"""Emit a pinned, self-contained read-only production authority census source.

No Docker, SSH or production inspection occurs locally. The emitted Python
source can be streamed over an explicitly approved SSH transport into the
production host. It embeds only source files, never application credentials.
"""
from __future__ import annotations
import argparse
import base64
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
FILES=(
    ROOT/"portal_production_writer_surface_readonly.py",
    ROOT/"portal_production_storage_authority_readonly.py",
)

def emit():
    code=[p.read_bytes() for p in FILES]
    if any(not c or len(c)>80_000 for c in code):
        raise ValueError("untrusted source size")
    lines=[
       "import base64,sys,types",
       "pkg=types.ModuleType('scripts');pkg.__path__=[];sys.modules['scripts']=pkg",
       "mod=types.ModuleType('scripts.portal_production_writer_surface_readonly')",
       "sys.modules['scripts.portal_production_writer_surface_readonly']=mod",
       "setattr(pkg,'portal_production_writer_surface_readonly',mod)",
       "exec(compile(base64.b64decode('"+base64.b64encode(code[0]).decode("ascii")+"'),'pinned_writer_surface','exec'),mod.__dict__)",
       "exec(compile(base64.b64decode('"+base64.b64encode(code[1]).decode("ascii")+"'),'pinned_storage_authority','exec'),{'__name__':'__main__'})",
    ]
    return "\n".join(lines)+"\n"

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--emit-remote-source",action="store_true")
    args=p.parse_args()
    if not args.emit_remote_source:
        print(json.dumps({"status":"DRY_RUN_NO_SSH_OR_DOCKER",
              "release_gate":"NO_GO","safe_to_cutover":False},sort_keys=True))
        return 3
    print(emit(),end="")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
