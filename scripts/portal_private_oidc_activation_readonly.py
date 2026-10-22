#!/usr/bin/env python3
"""One-shot, credential-free private OIDC activation checkpoint.

The checker cannot join a Tailnet, register an OIDC client, obtain JWTs,
assert real browser login, authorize production release or change storage.
Only runs on the existing qualified x1-370 observer with --execute.
"""
from __future__ import annotations
import argparse
import json
import re
import socket
import sys
import urllib.error
import urllib.request
from scripts import portal_tsidp_bootstrap_readiness as bootstrap

HOST = 'x1-370'
PRIVATE_ORIGIN = 'https://x1-370.tailcb8954.ts.net:8449'
# Current known CI-green private preview. Operator must still supply a SHA.
LIVE_APP_REVISION = '4601684b67320e4ccc6c4fa981ed41687f95d288'
MAX_JSON = 8192


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('unexpected private preview HTTP redirect')


def private_get(path: str, *, opener_factory=urllib.request.build_opener) -> tuple[int,dict | None]:
    """Fetch fixed private read-only routes, refuse redirects, cap body."""
    if path not in ('/api/release','/api/auth/providers','/api/portal/nodes','/chat'):
        raise ValueError('route not explicitly approved')
    url = PRIVATE_ORIGIN + path
    opener = opener_factory(NoRedirect())
    request = urllib.request.Request(url, headers={'Cache-Control':'no-store'}, method='GET')
    try:
        response = opener.open(request, timeout=8)
    except urllib.error.HTTPError as err:
        if err.code in (401,403,503):
            return err.code,None
        raise ValueError('unexpected HTTP failure') from None
    with response:
        if response.geturl() != url or response.status not in (200,401,403,503):
            raise ValueError('unexpected response status or origin')
        status = response.status
        if path != '/api/release':
            return status,None
        if status != 200:
            return status,None
        body = response.read(MAX_JSON + 1)
        if len(body)>MAX_JSON:
            raise ValueError('release response exceeds cap')
        def no_duplicate_keys(pairs):
            result={}
            for name,value in pairs:
                if name in result:raise ValueError('duplicate JSON release field')
                result[name]=value
            return result
        result=json.loads(body,object_pairs_hook=no_duplicate_keys)
        if type(result) is not dict or set(result)!={'source','revision'}:
            raise ValueError('untrusted release metadata')
        return status,result


def collect(expected_revision: str) -> dict:
    # Bind every execution to the immutable deployed revision, never trust
    # whichever SHA the live server returns as its own approval.
    if (type(expected_revision) is not str or
            re.fullmatch(r'[a-f0-9]{40}', expected_revision) is None or
            expected_revision == '0'*40):
        raise ValueError('explicit exact 40-hex Git SHA required')
    if socket.gethostname()!=HOST:
        raise ValueError('only x1-370 may qualify private OIDC activation')
    rev_status,release = private_get('/api/release')
    if rev_status!=200 or release!={'source':'kipnerter-web','revision':expected_revision}:
        raise ValueError('private portal is not serving qualified exact app revision')
    chat_status,_ = private_get('/chat')
    provider_status,_ = private_get('/api/auth/providers')
    nodes_status,_ = private_get('/api/portal/nodes')
    if chat_status!=200 or provider_status not in (200,503) or nodes_status not in (401,403,503):
        raise ValueError('private route authorization state unexpected')
    state=bootstrap.inspect(offline=False)
    expected={'compose_safe','runtime_isolated','tailnet_enrolled','oidc_discovery_valid',
              'oidc_client_registered','browser_login_verified',
              'production_deploy_authorized','staging_deploy_authorized'}
    if not expected.issubset(state) or any(type(state[k]) is not bool for k in expected):
        raise ValueError('bootstrap state is incomplete')
    if not state['compose_safe'] or not state['runtime_isolated']:
        raise ValueError('bootstrap isolation is not verified')
    if not state['tailnet_enrolled'] and state['oidc_discovery_valid']:
        raise ValueError('untrusted discovery without enrollment')
    if any(state[k] for k in ('oidc_client_registered','browser_login_verified',
                              'production_deploy_authorized','staging_deploy_authorized')):
        raise ValueError('bootstrap unexpectedly self-reports unsupported authority')
    if not state['tailnet_enrolled']:
        next_action='ADMIN_ENROLL_TSIDP'
        if provider_status!=503 or nodes_status!=503:
            raise ValueError('authentication exposed before IdP enrollment')
    elif not state['oidc_discovery_valid']:
        next_action='ADMIN_REVIEW_TSIDP_TLS_DISCOVERY'
        if provider_status!=503 or nodes_status!=503:
            raise ValueError('authentication exposed before IdP discovery')
    elif provider_status==503:
        next_action='ADMIN_REGISTER_CLIENT_AND_PROVISION_SECRETS'
    else:
        next_action='INDEPENDENT_REAL_BROWSER_OIDC_ACCEPTANCE'
    return {
        'status':'PRIVATE_ACTIVATION_OBSERVED_NOT_AUTHORIZED',
        'private_revision_verified':True,
        'operator_expected_revision':expected_revision,
        'expected_revision_independently_ci_attested':False,
        'private_chat_http_200':True,
        'private_provider_http_status':provider_status,
        'private_nodes_http_status':nodes_status,
        'bootstrap_isolated':True,
        'tailnet_enrolled':state['tailnet_enrolled'],
        'oidc_discovery_valid':state['oidc_discovery_valid'],
        'client_registration_independently_verified':False,
        'real_browser_login_verified':False,
        'revocation_proven':False,
        'independent_recovery_custody':False,
        'production_modified':False,
        'safe_to_cutover':False,
        'release_gate':'NO_GO',
        'next_action':next_action,
    }


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--expected-revision',default=None,
                        help='explicit immutable 40-hex deployment SHA, independently reviewed')
    args=parser.parse_args()
    if not args.execute:
        print(json.dumps({'status':'DRY_RUN_NO_NETWORK_OR_DOCKER','release_gate':'NO_GO',
                          'safe_to_cutover':False},sort_keys=True))
        return 3
    try:
        result=collect(args.expected_revision)
        code=0
    except (ValueError,TypeError,KeyError,UnicodeError,OSError,
            json.JSONDecodeError,urllib.error.URLError) as exc:
        result={'status':'HOLD','error_class':type(exc).__name__,
                'release_gate':'NO_GO','safe_to_cutover':False}
        code=2
    print(json.dumps(result,sort_keys=True))
    return code

if __name__=='__main__':
    sys.exit(main())
