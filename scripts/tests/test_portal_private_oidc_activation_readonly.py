"""Offline mock controls: no network or Docker in this test suite."""
import io
import json
import subprocess
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import portal_private_oidc_activation_readonly as m


class FakeHTTP:
    def __init__(self,status=200,url=m.PRIVATE_ORIGIN+'/api/release',content=None):
        self.status=status
        self.url=url
        self.body=io.BytesIO(content if content is not None else
                             json.dumps({'source':'kipnerter-web','revision':m.LIVE_APP_REVISION}).encode())
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def geturl(self):return self.url
    def read(self,n):return self.body.read(n)


def bootstrap(*,enrolled=False,discovery=False):
    return dict(compose_safe=True,runtime_isolated=True,tailnet_enrolled=enrolled,
                oidc_discovery_valid=discovery,oidc_client_registered=False,
                browser_login_verified=False,production_deploy_authorized=False,
                staging_deploy_authorized=False)


def result_path(auth=503,nodes=503,chat=200):
    def get(path):
        return {'/api/release':(200,{'source':'kipnerter-web','revision':m.LIVE_APP_REVISION}),
                '/chat':(chat,None),'/api/auth/providers':(auth,None),
                '/api/portal/nodes':(nodes,None)}[path]
    return get


class PrivateActivationSafety(unittest.TestCase):
    def test_execute_requires_explicit_expected_sha_without_ever_accessing_network(self):
        out=io.StringIO()
        with patch('sys.argv',['activation','--execute']), \
             patch.object(m,'private_get',side_effect=AssertionError('network accessed')), \
             redirect_stdout(out):
            self.assertEqual(m.main(),2)
        result=json.loads(out.getvalue())
        self.assertEqual(result['status'],'HOLD')
        self.assertEqual(result['release_gate'],'NO_GO')

    def test_wrong_revision_or_invalid_operator_sha_never_accepts_live_preview(self):
        bad=['',None,'0'*40,'A'*40,'g'*40,'a'*39,'https://github.com/repo']
        for sha in bad:
            with self.subTest(sha=sha),patch.object(m,'private_get',
                  side_effect=AssertionError('preview read on untrusted SHA')):
                with self.assertRaises(ValueError):m.collect(sha)
        with patch.object(m.socket,'gethostname',return_value=m.HOST), \
             patch.object(m,'private_get',side_effect=result_path()), \
             patch.object(m.bootstrap,'inspect',side_effect=AssertionError('bootstrap called')):
            with self.assertRaisesRegex(ValueError,'qualified exact'):
                m.collect('f'*40)

    def test_valid_new_expected_revision_must_match_actual_server_response(self):
        other='f'*40
        with patch.object(m.socket,'gethostname',return_value=m.HOST), \
             patch.object(m,'private_get',side_effect=(
                 lambda path: (200,{'source':'kipnerter-web','revision':other})
                 if path=='/api/release' else result_path()(path))), \
             patch.object(m.bootstrap,'inspect',return_value=bootstrap()):
            out=m.collect(other)
        self.assertTrue(out['private_revision_verified'])
        self.assertEqual(out['operator_expected_revision'],other)
        self.assertFalse(out['expected_revision_independently_ci_attested'])
        self.assertFalse(out['safe_to_cutover'])

    def test_dry_run_cannot_reach_network(self):
        out=io.StringIO()
        with patch('sys.argv',['activation']),patch.object(m,'collect',side_effect=AssertionError('unexpected')),redirect_stdout(out):
            self.assertEqual(m.main(),3)
        self.assertEqual(json.loads(out.getvalue())['release_gate'],'NO_GO')

    def test_nonapproved_host_cannot_query_preview_or_docker(self):
        with patch.object(m.socket,'gethostname',return_value='kipnerter-prod-01'),patch.object(m,'private_get',side_effect=AssertionError('unexpected')):
            with self.assertRaisesRegex(ValueError,'only x1-370'):m.collect(m.LIVE_APP_REVISION)

    def test_success_unenrolled_always_no_go(self):
        with patch.object(m.socket,'gethostname',return_value=m.HOST), \
             patch.object(m,'private_get',side_effect=result_path()), \
             patch.object(m.bootstrap,'inspect',return_value=bootstrap()):
            r=m.collect(m.LIVE_APP_REVISION)
        self.assertEqual(r['next_action'],'ADMIN_ENROLL_TSIDP')
        self.assertEqual(r['private_provider_http_status'],503)
        self.assertEqual(r['release_gate'],'NO_GO')
        for field in ('safe_to_cutover','real_browser_login_verified','revocation_proven',
                      'client_registration_independently_verified','production_modified'):
            self.assertFalse(r[field])

    def test_discovery_step_never_proves_approval(self):
        cases=[(bootstrap(enrolled=True),503,'ADMIN_REVIEW_TSIDP_TLS_DISCOVERY'),
               (bootstrap(enrolled=True,discovery=True),503,'ADMIN_REGISTER_CLIENT_AND_PROVISION_SECRETS'),
               (bootstrap(enrolled=True,discovery=True),200,'INDEPENDENT_REAL_BROWSER_OIDC_ACCEPTANCE')]
        for b,code,expected in cases:
            with self.subTest(step=expected),patch.object(m.socket,'gethostname',return_value=m.HOST), \
                 patch.object(m,'private_get',side_effect=result_path(auth=code,nodes=503)), \
                 patch.object(m.bootstrap,'inspect',return_value=b):
                r=m.collect(m.LIVE_APP_REVISION)
            self.assertEqual(r['next_action'],expected)
            self.assertFalse(r['real_browser_login_verified'])
            self.assertFalse(r['safe_to_cutover'])

    def test_early_provider_or_node_access_is_denied(self):
        for auth,nodes in ((200,503),(503,401),(503,200)):
            with self.subTest(auth=auth,nodes=nodes),patch.object(m.socket,'gethostname',return_value=m.HOST), \
                 patch.object(m,'private_get',side_effect=result_path(auth=auth,nodes=nodes)), \
                 patch.object(m.bootstrap,'inspect',return_value=bootstrap()):
                with self.assertRaises(ValueError):m.collect(m.LIVE_APP_REVISION)

    def test_wrong_revision_and_failed_chat_denied(self):
        incorrect=lambda path:((200,{'source':'kipnerter-web','revision':'unapproved'})
                               if path=='/api/release' else result_path()(path))
        for get in (incorrect,result_path(chat=503)):
            with patch.object(m.socket,'gethostname',return_value=m.HOST), \
                 patch.object(m,'private_get',side_effect=get), \
                 patch.object(m.bootstrap,'inspect',return_value=bootstrap()):
                with self.assertRaises(ValueError):m.collect(m.LIVE_APP_REVISION)

    def test_invalid_bootstrap_flags_or_claimed_authority_denied(self):
        checks=[{'compose_safe':False},{'runtime_isolated':False},
                {'browser_login_verified':True},{'oidc_client_registered':True},
                {'production_deploy_authorized':True},
                {'tailnet_enrolled':False,'oidc_discovery_valid':True},
                {'tailnet_enrolled':'yes'}, {'real_unreviewed_flag':True}]
        for change in checks:
            item={**bootstrap(),**change}
            if 'real_unreviewed_flag' in change:continue
            with self.subTest(changes=change),patch.object(m.socket,'gethostname',return_value=m.HOST), \
                 patch.object(m,'private_get',side_effect=result_path()), \
                 patch.object(m.bootstrap,'inspect',return_value=item):
                with self.assertRaises(ValueError):m.collect(m.LIVE_APP_REVISION)

    def test_private_routes_fixed_allowlist(self):
        with self.assertRaises(ValueError):m.private_get('https://evil.example/collect')
        with self.assertRaises(ValueError):m.private_get('/api/admin/credentials')
        with self.assertRaises(ValueError):m.private_get('/api/portal/submit')

    def test_redirect_blocked_before_offsite_connection(self):
        def check(handler):
            with self.assertRaisesRegex(ValueError,'redirect'):
                handler.redirect_request(None,None,302,'Moved',{},'https://evil.example/')
            raise ValueError('test complete')
        with self.assertRaisesRegex(ValueError,'test complete'):
            m.private_get('/api/release',opener_factory=check)

    def test_invalid_release_json_is_not_accepted(self):
        cases=[b'[]',b'{}',b'\xff',b'x'*9000,
               b'{"source":"kipnerter-web","revision":"x","revision":"y"}']
        for body in cases:
            def opener(handler):
                class Client:
                    def open(self,request,timeout=8):return FakeHTTP(content=body)
                return Client()
            with self.subTest(size=len(body)),self.assertRaises((ValueError,UnicodeError,json.JSONDecodeError)):
                m.private_get('/api/release',opener_factory=opener)

    def test_http_auth_status_exposed_only_as_status_code(self):
        def opener(handler):
            class Client:
                def open(self,req,timeout=8):
                    self_req=req
                    raise urllib.error.HTTPError(req.full_url,503,'contains secret',None,None)
            return Client()
        self.assertEqual(m.private_get('/api/auth/providers',opener_factory=opener),(503,None))

    def test_error_detail_not_exposed_in_cli_output(self):
        out=io.StringIO()
        with patch('sys.argv',['activation','--execute','--expected-revision',m.LIVE_APP_REVISION]), \
             patch.object(m,'collect',side_effect=ValueError('private credential and token')), \
             redirect_stdout(out):
            self.assertEqual(m.main(),2)
        self.assertEqual(json.loads(out.getvalue())['status'],'HOLD')
        self.assertNotIn('credential',out.getvalue())


if __name__=='__main__':unittest.main()
