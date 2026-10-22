#!/usr/bin/env python3
"""Read-only, credential-redacting diagnosis for isolated staging tsidp.

Inspect the already existing exact container; never run/start/authenticate a
node, mutate tags/policies, follow URLs, register an OIDC client, or show logs.
The output deliberately cannot expose one-time Tailscale login URLs or keys.
"""
import json
import re
import subprocess
import sys
from scripts import portal_tsidp_bootstrap_readiness as bootstrap

CONTAINER = bootstrap.CONTAINER
IMAGE_SHA = 'sha256:' + bootstrap.IMAGE_DIGEST
MAX_BYTES = 262144
MAX_LINES = 80
CHALLENGE = re.compile(r'https://login\.tailscale\.com/a/[a-zA-Z0-9]+')
TAG_DENIAL = re.compile(r'requested tags \[tag:tsidp\] are invalid or not permitted', re.I)


def safe_command(*args):
    raw = subprocess.check_output(args, timeout=9, stderr=subprocess.DEVNULL)
    if len(raw) > MAX_BYTES:
        raise ValueError('oversized docker response')
    return raw.decode('utf-8', 'replace')


def summarize(container, logs):
    if not isinstance(container, dict) or container.get('Name') != '/' + CONTAINER:
        raise ValueError('incorrect Docker container')
    conf = container.get('Config', {})
    host = container.get('HostConfig', {})
    if container.get('Image') != IMAGE_SHA or conf.get('Image') != bootstrap.IMAGE:
        raise ValueError('incorrect pinned image')
    if (conf.get('User') != 'app:app' or host.get('Privileged') or
            host.get('ReadonlyRootfs') is not True or host.get('CapDrop') != ['ALL'] or
            host.get('PortBindings') or host.get('PublishAllPorts') or
            host.get('NetworkMode') != bootstrap.PROJECT + '_idp_network' or
            host.get('RestartPolicy', {}).get('Name') != 'no' or
            'no-new-privileges:true' not in host.get('SecurityOpt', []) or
            not 0 < int(host.get('Memory', 0)) <= 268435456 or
            not 0 < int(host.get('NanoCpus', 0)) <= 500000000 or
            not 0 < int(host.get('PidsLimit', 0)) <= 128):
        raise ValueError('unqualified container security properties')
    mounts = container.get('Mounts', [])
    if (len(mounts) != 1 or mounts[0].get('Type') != 'volume' or
            mounts[0].get('Name') != bootstrap.PROJECT + '_idp_data' or
            mounts[0].get('Destination') != '/data' or
            mounts[0].get('RW') is not True):
        raise ValueError('unexpected persistence boundary')
    if any(value.startswith(('TS_AUTHKEY=', 'TS_CLIENT_SECRET=', 'NEXTAUTH_SECRET='))
           for value in conf.get('Env', [])):
        raise ValueError('credential unexpectedly embedded in container')
    if type(logs) is not str or len(logs.encode()) > MAX_BYTES:
        raise ValueError('unexpected log payload')
    if any(word in logs.lower() for word in ('ts_authkey=', 'ts_client_secret=')):
        # Still never emit the credential or raw log content.
        raise ValueError('credential found in logs')
    state = container.get('State', {})
    running = state.get('Running') is True
    denied = bool(TAG_DENIAL.search(logs))
    challenge = bool(CHALLENGE.search(logs))
    if denied:
        phase, action = 'TAG_ASSIGNMENT_REJECTED', 'ADMIN_REVIEW_LIVE_TAG_OWNER_AND_APPROVING_IDENTITY'
    elif running and challenge:
        phase, action = 'AWAITING_INTERACTIVE_ADMIN_APPROVAL', 'ADMIN_APPROVE_CURRENT_TAGGED_ENROLLMENT'
    elif running:
        phase, action = 'ENROLLMENT_STATE_UNCONFIRMED', 'CHECK_TAGGED_PEER_AND_PRIVATE_DISCOVERY'
    else:
        phase, action = 'CONTAINER_STOPPED', 'ADMIN_REVIEW_IDP_FAILURE_BEFORE_RESTART'
    return {
        'purpose': 'private_tsidp_enrollment_diagnostic',
        'container_running': running,
        'exact_image_verified': True,
        'isolation_shape_verified': True,
        'fresh_challenge_present': challenge,
        'tag_permission_denial_seen_since_start': denied,
        'enrollment_phase': phase,
        'next_action': action,
        'live_tailnet_policy_verified': False,
        'admin_identity_verified': False,
        'oidc_browser_login_verified': False,
        'production_deploy_authorized': False,
        'release_gate': 'NO_GO',
    }


def diagnose():
    found = json.loads(safe_command('docker', 'inspect', CONTAINER))
    if not isinstance(found, list) or len(found) != 1:
        raise ValueError('wrong container inventory')
    item = found[0]
    started = item.get('State', {}).get('StartedAt')
    if not isinstance(started, str) or not started.startswith('20') or len(started) > 64:
        raise ValueError('untrusted container start time')
    # Docker sends application logs to STDERR, not necessarily STDOUT.
    proc = subprocess.run(
        ['docker', 'logs', '--since', started, '--tail', str(MAX_LINES), CONTAINER],
        capture_output=True, timeout=9, check=True,
    )
    if len(proc.stdout) + len(proc.stderr) > MAX_BYTES:
        raise ValueError('oversized Docker logs')
    log = (proc.stdout + b'\n' + proc.stderr).decode('utf-8', 'replace')
    return summarize(item, log)


def main():
    try:
        report = diagnose()
        code = 0
    except (OSError, ValueError, TypeError, KeyError, IndexError, subprocess.SubprocessError):
        report = {'purpose': 'private_tsidp_enrollment_diagnostic',
                  'enrollment_phase': 'UNKNOWN_HOLD',
                  'release_gate': 'NO_GO', 'production_deploy_authorized': False}
        code = 2
    print(json.dumps(report, sort_keys=True))
    return code

if __name__ == '__main__':
    sys.exit(main())
