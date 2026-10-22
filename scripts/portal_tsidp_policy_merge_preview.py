#!/usr/bin/env python3
"""Credential-free review of a supplied Tailnet policy: NEVER writes a policy.

This is an offline review helper for a file exported by an administrator. It
is NOT the Tailscale official API validator and never authorizes enrollment.
The output is an intentionally minimal patch plan, not a replacement policy.
"""
import argparse
import json
import sys
from pathlib import Path
from scripts.portal_tsidp_policy_candidate_check import (
    MAX_BYTES, EXPECTED, HTTPS_ADMIN, duplicate_safe_dict, strip_line_comments,
)


def skip_trailing_commas(raw):
    out = []
    quoted = False
    escaped = False
    pos = 0
    while pos < len(raw):
        char = raw[pos]
        if quoted:
            out.append(char)
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
            out.append(char)
        elif char == ',':
            next_pos = pos + 1
            while next_pos < len(raw) and raw[next_pos].isspace():
                next_pos += 1
            if next_pos >= len(raw) or raw[next_pos] not in '}]':
                out.append(char)
        else:
            out.append(char)
        pos += 1
    if quoted:
        raise ValueError('unclosed string')
    return ''.join(out)


def preview(text):
    if type(text) is not str or len(text.encode()) > MAX_BYTES:
        raise ValueError('invalid or oversized policy input')
    doc = json.loads(skip_trailing_commas(strip_line_comments(text)),
                     object_pairs_hook=duplicate_safe_dict)
    if type(doc) is not dict or not isinstance(doc.get('grants'), list):
        raise ValueError('supplied policy is not a valid grants object')
    owners = doc.get('tagOwners', {})
    if not isinstance(owners, dict):
        raise ValueError('invalid tag owners')
    current_owner = owners.get('tag:tsidp')
    if current_owner is not None and current_owner != ['autogroup:admin']:
        raise ValueError('existing tag owner requires an independent review')
    grants = doc['grants']
    if any(type(grant) is not dict for grant in grants):
        raise ValueError('invalid grant')
    exact = sum(grant == EXPECTED for grant in grants)
    if exact > 1:
        raise ValueError('duplicate application grants')
    scoped_https = sum(g == HTTPS_ADMIN for g in grants)
    if scoped_https > 1:
        raise ValueError('duplicate administrator HTTPS transport grant')
    related = [g for g in grants if 'tailscale.com/cap/tsidp' in g.get('app', {})
               or ('tag:tsidp' in g.get('dst', []) and 'app' in g)]
    if any(grant != EXPECTED for grant in related):
        raise ValueError('existing IdP application capabilities require a human review')
    network_everything = any(g.get('src') == ['*'] and g.get('dst') == ['*'] and
                             g.get('ip') == ['*'] for g in grants)
    nodeattrs = doc.get('nodeAttrs', [])
    if not isinstance(nodeattrs, list):
        raise ValueError('invalid nodeAttrs')
    funnel_everyone = any(isinstance(row, dict) and
                          'autogroup:member' in row.get('target', []) and
                          'funnel' in row.get('attr', []) for row in nodeattrs)
    return {
        'purpose': 'tsidp_offline_policy_merge_preview',
        'proposed_add_tag_owner': current_owner is None,
        'proposed_add_admin_ui_grant': exact == 0,
        'proposed_add_admin_https_443_grant': scoped_https == 0,
        'patch_tag_owner': {'tag:tsidp': ['autogroup:admin']} if current_owner is None else {},
        'patch_app_grant': EXPECTED if exact == 0 else None,
        'patch_admin_https_grant': HTTPS_ADMIN if scoped_https == 0 else None,
        'scoped_admin_https_443_grant_present': scoped_https == 1,
        'approved_nonadmin_browser_https_access_verified': False,
        'broad_network_grant_observed': network_everything,
        'funnel_available_to_all_members': funnel_everyone,
        'existing_grants_count': len(grants),
        'preserve_all_existing_policy_sections': True,
        'official_tailnet_policy_validation_performed': False,
        'live_tailnet_policy_changed': False,
        'tailnet_admin_identity_verified': False,
        'tailnet_enrollment_authorized': False,
        'oidc_client_registered': False,
        'release_gate': 'NO_GO',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy-file', required=True,
                        help='path to an operator-exported policy file; read only, no writes')
    args = parser.parse_args(argv)
    try:
        path = Path(args.policy_file)
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise ValueError('unavailable/oversized input')
        report = preview(path.read_text())
        status = 0
    except (ValueError, TypeError, OSError, UnicodeError, json.JSONDecodeError):
        report = {'purpose': 'tsidp_offline_policy_merge_preview',
                  'status': 'HOLD_REVIEW_INPUT', 'release_gate': 'NO_GO',
                  'live_tailnet_policy_changed': False}
        status = 2
    print(json.dumps(report, sort_keys=True))
    return status

if __name__ == '__main__':
    sys.exit(main())
