#!/usr/bin/env python3
"""Fixed-receipt, read-only ciphertext/signature/remote-key check.
No decryption, source production access, enrollment, repair or cutover authority.
"""
from __future__ import annotations
import hashlib,json,os,subprocess,sys,tempfile,stat
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path("/home/scott/.local/state/kipnerter-private-recovery-candidate-20261023")
ID="20261023T064429Z-b4b7402d"
REMOTE=f".local/state/kipnerter-private-backups/{ID}"
MANIFEST_SHA="0901cc4aca7caa50dc625ddd44ad6844181282291eb6ea92ddcfd2146660304b"
SIGNATURE_SHA="a1d8c6d6bb86f5e780d11755cbb1936414c8b8786b227f4bd80000c59b8a4b17"
SIGN_PUB_SHA="4c99445032390fc6b5879fa6812b4f5d57b8f9b085a3e3e496ca43509c857a60"
PG_CIPHER_SHA="f3c5df422f7eade8eb1237d9d4f36433d8b5897bdbfb23dc9f2d0b5f5ea61047"
MINIO_CIPHER_SHA="af4248df3ad6cfe19e5649942a50d225216cb25a5e3f9fab1f1543388f1fe3f9"

def run(cmd,timeout=20):
    return subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                          check=True,timeout=timeout).stdout

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def remote_ciphertext_hashes():
    # Standalone read-only verification; no production-backup module imports.
    if not REMOTE.startswith(".local/state/kipnerter-private-backups/") or ".." in REMOTE:
        raise ValueError("untrusted receipt ID")
    source=("from pathlib import Path\n"
            "import hashlib,json,os\n"
            f"p=Path.home()/{REMOTE!r}\n"
            "assert p.is_dir() and p.stat().st_uid==os.geteuid() and not p.stat().st_mode & 0o077\n"
            "out={}\n"
            "for name in ('postgresql.cms','minio.cms','manifest.json'):\n"
            " f=p/name\n"
            " assert f.is_file() and f.stat().st_uid==os.geteuid() and not f.stat().st_mode & 0o077\n"
            " out[name]=hashlib.sha256(f.read_bytes()).hexdigest()\n"
            "print(json.dumps(out,sort_keys=True))\n")
    reply=subprocess.run(['ssh','-oBatchMode=yes','-oStrictHostKeyChecking=yes',
         '-oConnectTimeout=8','xwing','python3 -'],input=source.encode(),capture_output=True,timeout=20,check=True)
    result=json.loads(reply.stdout)
    if set(result)!={'postgresql.cms','minio.cms','manifest.json'}:
        raise ValueError('untrusted remote inventory')
    return result

def verify_public_certificate():
    cert=ROOT/"lenovo-cert.pem"
    st=cert.stat()
    if st.st_uid!=os.geteuid() or st.st_mode & 0o077 or not stat.S_ISREG(st.st_mode):
        raise ValueError("unsafe recipient certificate file")
    der=run(["openssl","x509","-in",str(cert),"-outform","DER"])
    if hashlib.sha256(der).hexdigest()!="38e2b5ba9ec941c67bdfc4bfc72726ab719187217fb6e7a4547775e8149e0fff":
        raise ValueError("wrong RSA recipient certificate")
    run(["openssl","x509","-in",str(cert),"-noout","-checkend","86400"])

def verified():
    directory=os.lstat(ROOT)
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid()
            or directory.st_mode & 0o077):
        raise ValueError("recovery witness root must be owner-private")
    actual=remote_ciphertext_hashes()
    if (actual["postgresql.cms"]!=PG_CIPHER_SHA or
            actual["minio.cms"]!=MINIO_CIPHER_SHA or
            actual["manifest.json"]!=MANIFEST_SHA):
        raise ValueError("stored ciphertext or manifest changed")
    verify_public_certificate()
    public=ROOT/"lenovo-signing-pub.pem"
    pub_stat=os.lstat(public)
    if (not stat.S_ISREG(pub_stat.st_mode) or pub_stat.st_uid!=os.geteuid()
            or pub_stat.st_mode & 0o077):
        raise ValueError("untrusted signer public-key file")
    der=run(["openssl","pkey","-pubin","-in",str(public),"-outform","DER"])
    if hashlib.sha256(der).hexdigest()!=SIGN_PUB_SHA:
        raise ValueError("signer public key mismatch")
    with tempfile.TemporaryDirectory(prefix="kp-signed-custody-verify-",dir="/dev/shm") as tmp:
        base=Path(tmp)
        assert not base.stat().st_mode & 0o077
        for name in ("manifest.json","manifest.sig"):
            run(["scp","-q","-oBatchMode=yes","-oStrictHostKeyChecking=yes",
                 f"xwing:{REMOTE}/{name}",str(base/name)],timeout=20)
        if digest(base/"manifest.json")!=MANIFEST_SHA or digest(base/"manifest.sig")!=SIGNATURE_SHA:
            raise ValueError("signed manifest changed")
        manifest=json.loads((base/"manifest.json").read_text())
        if (manifest["receipt_id"]!=ID or
                manifest["scope"]!="private_encrypted_nonatomic_recovery" or
                manifest["safe_to_cutover"] is not False or manifest["release_gate"]!="NO_GO" or
                manifest["independent_administrative_custody"] is not False or
                manifest["stored_cipher_sha256"]["postgresql.cms"]!=PG_CIPHER_SHA or
                manifest["stored_cipher_sha256"]["minio.cms"]!=MINIO_CIPHER_SHA):
            raise ValueError("manifest refuses release or doesn't match pinned ciphertext")
        run(["openssl","pkeyutl","-verify","-rawin","-pubin","-inkey",str(public),
             "-in",str(base/"manifest.json"),"-sigfile",str(base/"manifest.sig")],timeout=10)
    result=run(["ssh","-oBatchMode=yes","-oStrictHostKeyChecking=yes",
                "-oConnectTimeout=8","lenovo",
                'for f in "$HOME/.local/state/kipnerter-recovery-custody/v1/key.pem" "$HOME/.local/state/kipnerter-recovery-custody/v1/signing-key.pem"; do test -s "$f" && test "$(stat -c %a "$f")" = 600 || exit 5; done; echo keys_private_present'],timeout=14).decode().strip()
    if result!="keys_private_present":
        raise ValueError("Lenovo private keys not verified")
    return {"classification":"SIGNED_ENCRYPTED_COPY_VERIFIED_NOT_ATOMIC",
            "receipt_id":ID,"ciphertext_sha256_verified":True,
            "manifest_signature_verified":True,"remote_keys_present_and_private":True,
            "plaintext_residue_not_checked_by_this_probe":True,
            "independent_administrative_custody":False,
            "cross_service_point_in_time_consistent":False,
            "safe_to_cutover":False,"release_gate":"NO_GO"}

def main():
    receipt={"checked_utc":datetime.now(timezone.utc).isoformat(),
             "receipt_id":ID,"classification":"CHECK_REQUIRED",
             "safe_to_cutover":False,"release_gate":"NO_GO"}
    try:
        receipt.update(verified())
        code=0
    except Exception as e:
        receipt["failure_class"]=type(e).__name__
        code=3
    with tempfile.NamedTemporaryFile("w",dir=ROOT,prefix=".recovery-status.",delete=False) as f:
        os.fchmod(f.fileno(),0o600)
        json.dump(receipt,f,sort_keys=True,indent=2);f.write("\n")
        name=f.name
    os.replace(name,ROOT/"status.json")
    print(json.dumps(receipt,sort_keys=True))
    return code

if __name__=="__main__":
    sys.exit(main())
