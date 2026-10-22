"""Offline negative controls; never talks to the Tailscale control plane."""
import copy
import json
import unittest
from unittest.mock import patch

from scripts import portal_tsidp_policy_candidate_check as m


class TsidpPolicyCandidateTests(unittest.TestCase):
    def setUp(self):
        self.raw = m.POLICY.read_text()
        self.model = json.loads(m.strip_line_comments(self.raw))

    def test_checked_in_compose_tag_sts_and_reviewed_candidate(self):
        result = m.check()
        self.assertTrue(result['admin_ui_only'])
        self.assertTrue(result['scoped_admin_https_443'])
        self.assertEqual(result['tag_owner'],'admin')
        for key in ('sts_authorized','live_tailnet_policy_verified',
                    'enrollment_authorized','production_deploy_authorized'):
            self.assertFalse(result[key])
        self.assertEqual(result['release_gate'],'NO_GO')

    def test_no_extra_network_or_token_authority_to_tsidp(self):
        for changed in (
            {'ip':['*']},
            {'src':['*']},
            {'dst':['*']},
            {'app':{'tailscale.com/cap/tsidp':[{'allow_admin_ui':True,'users':['*']}] }},
            {'app':{'tailscale.com/cap/tsidp':[{'allow_admin_ui':True,'resources':['*']}] }},
            {'app':{'tailscale.com/cap/tsidp':[{'allow_admin_ui':False}] }},
        ):
            with self.subTest(changed=changed):
                doc = copy.deepcopy(self.model)
                grant = next(i for i in doc['grants'] if i == m.EXPECTED)
                grant.update(changed)
                with self.assertRaises(ValueError):
                    m.inspect_policy(json.dumps(doc),'tag:tsidp')

    def test_rejects_missing_tag_or_any_other_owner(self):
        for owner in (None, [], ['autogroup:member'], ['*'],
                      ['tag:kipnerter-prod'], ['autogroup:admin','autogroup:member']):
            with self.subTest(owner=owner):
                doc=copy.deepcopy(self.model)
                if owner is None:del doc['tagOwners']['tag:tsidp']
                else:doc['tagOwners']['tag:tsidp']=owner
                with self.assertRaises(ValueError):
                    m.inspect_policy(json.dumps(doc),'tag:tsidp')

    def test_early_wildcard_grant_rejected_not_added_to_sample(self):
        for field in ('src','dst'):
            doc=copy.deepcopy(self.model)
            doc['grants'].append({'src':['*'],'dst':['*'],'ip':['*']})
            with self.assertRaises(ValueError):
                m.inspect_policy(json.dumps(doc),'tag:tsidp')

    def test_duplicate_ts_grant_or_other_tagged_access_denied(self):
        for grant in (m.EXPECTED,m.HTTPS_ADMIN,{'src':['autogroup:member'],
                                 'dst':['tag:tsidp'],'ip':['*']},
                      {'src':['autogroup:admin'],'dst':['tag:tsidp'],
                       'app':{'tailscale.com/cap/tsidp':[{'allow_admin_ui':True}]},
                       'ip':['tcp:443']}):
            doc=copy.deepcopy(self.model)
            doc['grants'].append(copy.deepcopy(grant))
            with self.subTest(grant=grant),self.assertRaises(ValueError):
                m.inspect_policy(json.dumps(doc),'tag:tsidp')

    def test_tls_transport_grant_cannot_expand_to_all_users_or_all_ports(self):
        for changed in ({'src':['*']},{'dst':['*']},{'ip':['*']},
                        {'ip':['tcp:80','tcp:443']},{'ip':['tcp:22']},
                        {'src':['autogroup:member']}):
            doc=copy.deepcopy(self.model)
            grant=next(g for g in doc['grants'] if g==m.HTTPS_ADMIN)
            grant.update(changed)
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                m.inspect_policy(json.dumps(doc),'tag:tsidp')
        doc=copy.deepcopy(self.model)
        doc['grants'].remove(m.HTTPS_ADMIN)
        with self.assertRaisesRegex(ValueError,'HTTPS'):
            m.inspect_policy(json.dumps(doc),'tag:tsidp')

    def test_hujson_comments_do_not_break_url_literals_or_escaped_strings(self):
        example='{"url":"https://example.test/o//path", // this is removed\n"quoted":"text \\\" // still string"}'
        obj=json.loads(m.strip_line_comments(example))
        self.assertEqual(obj['url'],'https://example.test/o//path')
        self.assertTrue(obj['quoted'].endswith('// still string'))

    def test_duplicate_fields_invalid_json_and_overlong_policy_denied(self):
        for text in ('{"tagOwners":{},"tagOwners":{}}','{"unterminated":',
                     '"unterminated','['+'x'*m.MAX_BYTES+']'):
            with self.subTest(example=text[:30]),self.assertRaises(ValueError):
                m.inspect_policy(text,'tag:tsidp')

    def test_candidate_never_approves_actual_tailnet_policy(self):
        good=m.inspect_policy(self.raw,'tag:tsidp')
        self.assertNotIn('live_tailnet_policy_updated',good)
        self.assertFalse(good['live_tailnet_policy_verified'])
        self.assertFalse(good['production_deploy_authorized'])
        self.assertEqual(good['release_gate'],'NO_GO')

    def test_sts_toggle_or_unexpected_advertised_tag_denied(self):
        class StubFile:
            def __init__(self,contents):self.contents=contents
            def read_text(self):return self.contents
        compose=m.COMPOSE.read_text()
        for changed in (compose.replace('TSIDP_ENABLE_STS: \'0\'','TSIDP_ENABLE_STS: \'1\''),
                        compose.replace('TS_ADVERTISE_TAGS: tag:tsidp','TS_ADVERTISE_TAGS: tag:prod')):
            with self.subTest(changed=changed[-100:]),self.assertRaises(ValueError):
                m.check(repo_compose=StubFile(changed))


if __name__=='__main__':unittest.main()
