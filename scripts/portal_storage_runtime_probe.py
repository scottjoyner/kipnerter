#!/usr/bin/env python3
"""Disposable, no-network runtime preflight for ONE locally cached research OCI image.

Never checks or alters production containers, credentials, backups, volumes, or ports.
An OCI manifest digest is not a working MinIO server; readiness is not S3 restore.
"""
import json
import re
import secrets
import subprocess
import time

IMAGE = "quay.io/minio/aistor/minio:RELEASE.2026-09-19T17-05-25Z"
EXPECTED_ID = "sha256:107cf2014a9583c74c11e3cdbd6903d89c2244355886b89ce532f4ecae9c23f3"
HEX_ID = re.compile(r"sha256:[a-f0-9]{64}\Z")


def probe(*, runner=subprocess.run, pause=time.sleep, attempts=12):
    """Observe an isolated disposable HTTP readiness endpoint without pulling.

    Never emits the random, synthetic root credentials or raw docker logs.
    A 200 HTTP readiness is not a successful S3 PUT/GET or object restore.
    """
    result = {
        "source": "disposable_local_aistor_research_runtime",
        "candidate": "aistor",
        "expected_image_id": EXPECTED_ID,
        "image_identity_matches_cached_digest": False,
        "container_network": "none",
        "host_ports_published": False,
        "production_mounts_attached": False,
        "synthetic_credentials_only": True,
        "disposable_container_cleanup_verified": False,
        "readiness_http_code": None,
        "status": "HOLD",
        "readiness_http_verified": False,
        "synthetic_s3_roundtrip_verified": False,
        "minio_backup_restoration_verified": False,
        "original_production_minio_image_verified": False,
        "independent_custody_verified": False,
        "production_recovery_approved": False,
    }
    def run(argv, timeout):
        return runner(argv, capture_output=True, timeout=timeout, check=False)
    container = "kp-aistor-isolated-" + secrets.token_hex(6)
    started = False
    try:
        if type(attempts) is not int or not 1 <= attempts <= 20:
            raise ValueError("invalid bounded readiness attempts")
        image = run(["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE], 8)
        identity = image.stdout.decode("ascii", "strict").strip()
        if image.returncode or not HEX_ID.fullmatch(identity) or identity != EXPECTED_ID:
            raise ValueError("reviewed immutable local image unavailable")
        result["image_identity_matches_cached_digest"] = True
        user, password = "scratch" + secrets.token_hex(8), secrets.token_urlsafe(36)
        argv = [
            "docker", "run", "--detach", "--rm", "--name", container,
            "--network", "none", "--read-only", "--pids-limit", "96",
            "--memory", "768m", "--cpus", "0.8",
            "--tmpfs", "/data:rw,nosuid,size=134217728",
            "--tmpfs", "/tmp:rw,nosuid,size=67108864",
            "-e", "MINIO_ROOT_USER=" + user,
            "-e", "MINIO_ROOT_PASSWORD=" + password, "-e", "HOME=/tmp",
            EXPECTED_ID, "server", "/data",
        ]
        launched = run(argv, 16)
        if launched.returncode:
            raise ValueError("disposable image did not start")
        started = True
        for iteration in range(attempts):
            observed = run([
                "docker", "exec", container, "curl", "--silent",
                "--output", "/dev/null", "--write-out", "%{http_code}",
                "--max-time", "2",
                "http://127.0.0.1:9000/minio/health/ready",
            ], 5)
            code = observed.stdout.decode("ascii", "strict").strip()
            if observed.returncode == 0 and code in {"200", "503"}:
                result["readiness_http_code"] = int(code)
                if code == "200":
                    result["readiness_http_verified"] = True
                    result["status"] = "HTTP_READY_ONLY"
                break
            if iteration + 1 < attempts:
                pause(0.35)
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        pass
    finally:
        if started:
            try:
                removed = run(["docker", "rm", "--force", container], 20)
                if removed.returncode != 0:
                    result["status"] = "HOLD_CLEANUP_UNVERIFIED"
                    result["readiness_http_verified"] = False
                else:
                    result["disposable_container_cleanup_verified"] = True
            except (OSError, subprocess.SubprocessError):
                result["status"] = "HOLD_CLEANUP_UNVERIFIED"
                result["readiness_http_verified"] = False
    return result


if __name__ == "__main__":
    report = probe()
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    raise SystemExit(0 if report["status"] == "HTTP_READY_ONLY" else 2)
