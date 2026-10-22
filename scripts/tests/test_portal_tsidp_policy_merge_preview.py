"""All local-only, no Tailscale API or Docker access."""
import copy
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from scripts import portal_tsidp_policy_merge_preview as m


USER_LIKE_POLICY = '''{
 // synthetic test fixture mimicking user-shared trailing commas
 "grants": [
  {"src":["*"],"dst":["*"],"ip":["*"],},
 ],
 "ssh": [{"src":["test.member@example.invalid"],"dst":["autogroup:self"],
          "users":["autogroup:nonroot"],"action":"check",},],
 "nodeAttrs": [{"target":["autogroup:member"],"attr":["funnel"],},],
 "tagOwners":{"tag:other":["autogroup:admin"],
              "tag:tsidp":["autogroup:admin"],},
}'''


class PolicyMergePreviewTests(unittest.TestCase):
    def test_synthetic_live_like_policy_requires_only_ui_grant(self):
        report = m.preview(USER_LIKE_POLICY)
        self.assertFalse(report['proposed_add_tag_owner'])
        self.assertTrue(report['proposed_add_admin_ui_grant'])
        self.assertEqual(report['patch_app_grant'], m.EXPECTED)
        self.assertEqual(report['patch_tag_owner'], {})
        self.assertTrue(report['broad_network_grant_observed'])
        self.assertTrue(report['funnel_available_to_all_members'])
        self.assertFalse(report['live_tailnet_policy_changed'])
        self.assertEqual(report['release_gate'], 'NO_GO')
        self.assertNotIn('test.member@example.invalid', json.dumps(report))

    def test_missing_tag_proposes_only_admin_owner_and_grant(self):
        src = USER_LIKE_POLICY.replace('"tag:tsidp":["autogroup:admin"],','')
        report = m.preview(src)
        self.assertEqual(report['patch_tag_owner'], {'tag:tsidp':['autogroup:admin']})
        self.assertEqual(report['patch_app_grant'], m.EXPECTED)

    def test_exact_grant_already_present_causes_no_added_grant(self):
        doc=json.loads(m.skip_trailing_commas(m.strip_line_comments(USER_LIKE_POLICY)))
        doc['grants'].append(copy.deepcopy(m.EXPECTED))
        report=m.preview(json.dumps(doc))
        self.assertIsNone(report['patch_app_grant'])
        self.assertFalse(report['proposed_add_admin_ui_grant'])
        self.assertEqual(report['existing_grants_count'], 2)
        self.assertTrue(report['broad_network_grant_observed'])

    def test_other_tag_ownership_and_any_privileged_capability_require_review(self):
        d=json.loads(m.skip_trailing_commas(m.strip_line_comments(USER_LIKE_POLICY)))
        for owners in ([], ['*'],['autogroup:member'], ['tag:kipnerter-ci'],
                       ['autogroup:admin','autogroup:member']):
            x=copy.deepcopy(d)
            x['tagOwners']['tag:tsidp']=owners
            with self.subTest(owner=owners),self.assertRaises(ValueError):
                m.preview(json.dumps(x))
        for change in (
            {'src':['*'],'dst':['tag:tsidp'], 'app': {'tailscale.com/cap/tsidp':[{'allow_admin_ui':True}]}},
            {'src':['autogroup:admin'],'dst':['tag:tsidp'], 'app': {'tailscale.com/cap/tsidp':[{'allow_admin_ui':True,'users':['*']}]}}
        ):
            x=copy.deepcopy(d)
            x['grants'].append(change)
            with self.subTest(app=change),self.assertRaises(ValueError):
                m.preview(json.dumps(x))

    def test_duplicate_grant_and_invalid_shapes_fail_closed(self):
        d=json.loads(m.skip_trailing_commas(m.strip_line_comments(USER_LIKE_POLICY)))
        d['grants'].extend([m.EXPECTED,m.EXPECTED])
        with self.assertRaises(ValueError):m.preview(json.dumps(d))
        for source in ('[]', '{}', '{"grants":{}}',
                       '{"grants":[],"grants":[]}',
                       '{"grants":[{}],"tagOwners":[]}',
                       '{"grants":[null]}'):
            with self.subTest(source=source),self.assertRaises((TypeError,ValueError)):
                m.preview(source)

    def test_quoted_url_and_comma_are_never_truncated(self):
        raw='{"grants":[],"tagOwners":{"tag:tsidp":["autogroup:admin"],},'+\
            '"notes":"https://example.invalid/a//b,}",}// hello\n'
        parsed=json.loads(m.skip_trailing_commas(m.strip_line_comments(raw)))
        self.assertEqual(parsed['notes'],'https://example.invalid/a//b,}')
        self.assertFalse(m.preview(raw)['proposed_add_tag_owner'])

    def test_unchanged_input_and_no_write_on_cli(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'supplied-policy.hujson'
            p.write_text(USER_LIKE_POLICY)
            before=p.read_bytes()
            out=StringIO()
            with redirect_stdout(out):
                result=m.main(['--policy-file',str(p)])
            self.assertEqual(result,0)
            self.assertEqual(before,p.read_bytes())
            self.assertNotIn('test.member@example.invalid',out.getvalue())
            self.assertEqual(json.loads(out.getvalue())['release_gate'],'NO_GO')

    def test_missing_or_garbage_file_does_not_print_error_or_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            bad=Path(td)/'bad.hujson'
            bad.write_text('{"grants":[],"private":"SECRET_test","private":"SECRET_test"}')
            for input_path in (bad,Path(td)/'not-found'):
                out=StringIO()
                with redirect_stdout(out):
                    self.assertEqual(m.main(['--policy-file',str(input_path)]),2)
                self.assertNotIn('SECRET_test',out.getvalue())
                self.assertEqual(json.loads(out.getvalue())['status'],'HOLD_REVIEW_INPUT')


if __name__=='__main__': unittest.main()
