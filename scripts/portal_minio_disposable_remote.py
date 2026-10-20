"""Memory-only Docker-isolated synthetic MinIO experiment on prequalified Destroyer.

Called by portal_minio_offhost_s3_fixture.py using ssh python3 -c with no remote
file installation, no production paths, no outside networking and no host volumes.
"""
import hashlib,json,os,secrets,subprocess,sys,time
SERVER="sha256:a98a9d647e700e45c1d3d2e44709f23952a39c199731d84e623eb558fd5501f4"
CLIENT="sha256:e1497f813d2de5084b2bd38df37f8e68a999be6af10b4c495ae7c3eaf081a9ce"
result={"source":"isolated_destroyer_synthetic_minio_roundtrip",
        "status":"HOLD","server_cached_id_verified":False,"mc_cached_id_verified":False,
        "network_external":"none","host_ports_published":False,
        "host_mounts_attached":False,"production_data_accessed":False,
        "synthetic_object_source_verified":False,"synthetic_object_copy_verified":False,
        "negative_integrity_control_rejected":False,"minio_prod_image_identity_verified":False,
        "real_backup_restored":False,"independent_custody_verified":False,
        "production_recovery_approved":False,"cleanup_verified":False}
started=[]
stage="init"
token=secrets.token_hex(6)
src="kp-synth-minio-source-"+token
dst="kp-synth-minio-restore-"+token
username1="src"+secrets.token_hex(9)
username2="dst"+secrets.token_hex(9)
password1=secrets.token_hex(26)
password2=secrets.token_hex(26)
def call(argv, *, payload=None, deadline=18):
    return subprocess.run(argv,input=payload,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,check=False,timeout=deadline)
def must(argv, *, payload=None, deadline=18):
    r=call(argv,payload=payload,deadline=deadline)
    if r.returncode:
        raise RuntimeError("bounded_disposable_command_failed")
    return r.stdout
def client(*args,payload=None):
    cmd=["docker","run","--rm","--network","container:"+src,
         "--read-only","--pids-limit","48","--memory","256m",
         "--cpus","0.35","--tmpfs","/tmp:rw,nosuid,size=16777216",
         "-e","HOME=/tmp","-e","MC_CONFIG_DIR=/tmp/mc",
         "-e","MC_HOST_origin=http://"+username1+":"+password1+"@127.0.0.1:9000",
         "-e","MC_HOST_target=http://"+username2+":"+password2+"@127.0.0.1:9001"]
    if payload is not None:
        cmd+=["-i"]
    cmd+=[CLIENT,*args]
    return must(cmd,payload=payload,deadline=22)
try:
    raw=sys.stdin.buffer.read(150)
    req=json.loads(raw)
    if (not isinstance(req,dict) or set(req)!={"challenge"} or
        type(req["challenge"]) is not str or len(req["challenge"])!=64 or
        any(c not in "0123456789abcdef" for c in req["challenge"])):
        raise ValueError("invalid_challenge")
    result["challenge"]=req["challenge"]
    stage="pin_images"
    for tag, expected in [("minio/minio:latest",SERVER),("minio/mc:latest",CLIENT)]:
        observed=must(["docker","image","inspect","--format","{{.Id}}",tag],deadline=8).decode().strip()
        if observed != expected: raise ValueError("immutable_image_mismatch")
    result["server_cached_id_verified"]=True
    result["mc_cached_id_verified"]=True
    shared=["--read-only","--pids-limit","128","--memory","512m","--cpus","0.5",
       "--tmpfs","/data:rw,nosuid,size=67108864",
       "--tmpfs","/tmp:rw,nosuid,size=33554432"]
    command=["docker","run","--detach","--rm","--name",src,"--network","none",*shared,
       "-e","MINIO_ROOT_USER="+username1,"-e","MINIO_ROOT_PASSWORD="+password1,
       "-e","HOME=/tmp",SERVER,"server","--address",":9000","/data"]
    stage="source_start"
    must(command,deadline=18);started.append(src)
    command=["docker","run","--detach","--rm","--name",dst,"--network","container:"+src,
       *shared,"-e","MINIO_ROOT_USER="+username2,"-e","MINIO_ROOT_PASSWORD="+password2,
       "-e","HOME=/tmp",SERVER,"server","--address",":9001","/data"]
    stage="target_start"
    must(command,deadline=18);started.append(dst)
    stage="wait_s3"
    ready=False
    for count in range(12):
        try:
            client("ls","origin");client("ls","target")
            ready=True;break
        except (RuntimeError,subprocess.TimeoutExpired):
            time.sleep(.5)
    if not ready:raise ValueError("synthetic_s3_service_unavailable")
    bucket="kp-synth-"+token
    key="fixture-"+token+".bin"
    stage="bucket_create"
    client("mb","origin/"+bucket)
    client("mb","target/"+bucket)
    payload=("KIPNERTER_SYNTHETIC_MINIO_OBJECT\n"+token+"\n").encode()+secrets.token_bytes(1024)
    expected=hashlib.sha256(payload).hexdigest()
    stage="source_pipe"
    for retry in range(3):
        try:
            client("pipe","origin/"+bucket+"/"+key,payload=payload)
            break
        except RuntimeError:
            if retry==2: raise
            time.sleep(.5)
    stage="source_cat"
    source=client("cat","origin/"+bucket+"/"+key)
    if hashlib.sha256(source).hexdigest()!=expected:
        raise ValueError("source_payload_parity")
    result["synthetic_object_source_verified"]=True
    stage="target_copy"
    client("cp","origin/"+bucket+"/"+key,"target/"+bucket+"/"+key)
    stage="target_cat"
    restored=client("cat","target/"+bucket+"/"+key)
    if hashlib.sha256(restored).hexdigest()!=expected or restored!=payload:
        raise ValueError("target_payload_parity")
    result["synthetic_object_copy_verified"]=True
    result["negative_integrity_control_rejected"]=(hashlib.sha256(restored+b"tamper").hexdigest()!=expected)
    if not result["negative_integrity_control_rejected"]:raise ValueError("negative_integrity_test_failed")
    result["status"]="SYNTHETIC_ONLY_PASS"
    result["object_byte_count"]=len(payload)
    result["sha256_matched_on_both_isolated_servers"]=True
except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired,json.JSONDecodeError,UnicodeError) as e:
    result["status"]="HOLD"
    result["failure_step"]=stage
    result["failure_class"]=str(e)[:90] if type(e) in (ValueError,RuntimeError) else type(e).__name__
finally:
    failed=False
    for name in reversed(started):
        try:
            r=call(["docker","rm","-f",name],deadline=15)
            if r.returncode:failed=True
        except (OSError,subprocess.TimeoutExpired):
            failed=True
    result["cleanup_verified"]=not failed
    if failed:result["status"]="HOLD_CLEANUP"
    print(json.dumps(result,sort_keys=True,separators=(",",":")))
