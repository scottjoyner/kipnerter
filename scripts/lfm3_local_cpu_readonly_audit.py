#!/usr/bin/env python3
"""Read-only host audit: no credentials, Docker changes, or private payloads."""
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

def hold(message):
    print("HOLD: " + message)
    raise SystemExit(3)

if subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip() != "kipnerter":
    hold("unexpected SSH principal")
def inspect(name):
    try:
        raw=subprocess.check_output(["docker","inspect",name], timeout=12, stderr=subprocess.DEVNULL)
        item=json.loads(raw)[0]
    except Exception:
        hold("real staging container missing or inspect unavailable")
    return item

web=inspect("kipnerter-lfm3-local-web")
model=inspect("kipnerter-lfm3-local-cpu")
expected_web="sha256:e539c1b888e1148ff34ce00d50ac8a9638b7ff6d6df8918ce27b429026804587"
expected_model="sha256:c0a11067c72bb1eb330b8bddbf9869274c195e596bf4fae55fd527102e644b85"
for item,expected,maximum in ((web,expected_web,384*1024*1024),(model,expected_model,1536*1024*1024)):
    state=item.get("State") or {}
    limits=item.get("HostConfig") or {}
    labels=(item.get("Config") or {}).get("Labels") or {}
    if not state.get("Running") or state.get("OOMKilled") or item.get("Image")!=expected:
        hold("pinned staged service is not running healthy")
    if labels.get("com.docker.compose.project")!="kipnerter-lfm3-local-real":
        hold("unexpected container project")
    if not 0<int(limits.get("Memory") or 0)<=maximum:
        hold("container exceeds reviewed memory cap")

web_nets=(web.get("NetworkSettings") or {}).get("Networks") or {}
model_nets=(model.get("NetworkSettings") or {}).get("Networks") or {}
if len(model_nets)!=1 or not any(n.endswith("_model_only") for n in model_nets):
    hold("model is not exclusively on private-only network")
if not any(n.endswith("_model_only") for n in web_nets) or not any(n.endswith("_web_loopback") for n in web_nets):
    hold("web model/internal and host bridge split missing")
ports=(web.get("NetworkSettings") or {}).get("Ports") or {}
bindings=ports.get("3000/tcp")
if bindings!=[{"HostIp":"127.0.0.1","HostPort":"3356"}]:
    hold("web is not exclusively bound to host loopback")
if any(v for v in ((model.get("NetworkSettings") or {}).get("Ports") or {}).values()):
    hold("model port unexpectedly published")

origin="http://127.0.0.1:3356"
try:
    with urllib.request.urlopen(origin+"/chat",timeout=10) as response:
        if response.status!=200 or b"Message Kipnerter" not in response.read(250000):
            hold("deployed browser chat is not healthy")
except (OSError,ValueError):
    hold("browser chat unreachable")
payload=json.dumps({"messages":[{"role":"user","content":"What is 2 + 2? Reply with the digit 4."}]}).encode()
request=urllib.request.Request(origin+"/api/chat/completions", data=payload, method="POST",
    headers={"Content-Type":"application/json"})
for attempt in range(5):
    try:
        with urllib.request.urlopen(request,timeout=54) as response:
            raw=response.read(32769)
            if len(raw)>32768: hold("oversized generated response")
            answer=json.loads(raw)
            text=answer.get("reply")
            if response.status!=200 or answer.get("model")!="LFM3-1.7B" or not isinstance(text,str) or not re.search(r"\b4\b",text) or "SIMULATED DEMO RESPONSE" in text or "LOCAL HTTP FIXTURE" in text:
                hold("actual model response failed acceptance")
        break
    except urllib.error.HTTPError as e:
        if e.code not in (429,503) or attempt==4: hold("live model HTTP failure")
        time.sleep(5)
    except (OSError,ValueError):
        hold("live model response unreadable")
else:
    hold("no live generation")
print("LIVE_REAL_LFM3_STAGE_PASS: persistent Next.js + official model-generated answer")
print("runtime=real-lfm3-1.7b-q4-k-m staging_host_port=127.0.0.1:3356")
print("web_memory_cap_mib=384 model_memory_cap_mib=1536 public_traffic_changed=no")
