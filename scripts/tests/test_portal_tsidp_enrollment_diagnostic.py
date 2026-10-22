"""Offline only: never invokes Docker or Tailscale in unit tests."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import portal_tsidp_enrollment_diagnostic as d
from scripts.tests.test_portal_tsidp_bootstrap_readiness import runtime_fixture


def container_fixture(running=True):
    c = runtime_fixture()
    c.update(Name='/' + d.CONTAINER)
    c['State'].update(Running=running, StartedAt='2026-10-22T15:09:13.553859054Z')
    return c


class EnrollmentDiagnosticControls(unittest.TestCase):
    def test_login_prompt_remains_awaiting_admin_without_revealing_link(self):
        secret_link = 'https://login.tailscale.com/a/123456789abcdef'
        prompt = 'To start this tsnet server, restart with TS_AUTHKEY set, or go to: ' + secret_link
        report = d.summarize(container_fixture(), prompt)
        self.assertEqual(report['enrollment_phase'],'AWAITING_INTERACTIVE_ADMIN_APPROVAL')
        self.assertEqual(report['next_action'],'ADMIN_APPROVE_CURRENT_TAGGED_ENROLLMENT')
        self.assertNotIn(secret_link,json.dumps(report))
        self.assertTrue(report['fresh_challenge_present'])
        self.assertFalse(report['admin_identity_verified'])
        self.assertFalse(report['production_deploy_authorized'])
        self.assertEqual(report['release_gate'],'NO_GO')

    def test_tag_denial_cannot_be_misreported_as_awaiting_approval(self):
        msg = ('To start this tsnet server, restart with TS_AUTHKEY set, or go to: '
               'https://login.tailscale.com/a/123456789abcdef\n'
               'ERROR failed to start tsnet server error="tsnet.Up: backend: '
               'requested tags [tag:tsidp] are invalid or not permitted"')
        for running in (True,False):
            with self.subTest(running=running):
                report=d.summarize(container_fixture(running),msg)
                self.assertEqual(report['enrollment_phase'],'TAG_ASSIGNMENT_REJECTED')
                self.assertTrue(report['tag_permission_denial_seen_since_start'])
                self.assertNotIn('login.tailscale.com',json.dumps(report))

    def test_stopped_without_tag_denial_never_claims_pending_approval(self):
        report=d.summarize(container_fixture(False),'')
        self.assertEqual(report['enrollment_phase'],'CONTAINER_STOPPED')
        self.assertFalse(report['container_running'])
        self.assertEqual(report['release_gate'],'NO_GO')

    def test_no_prompt_running_is_unconfirmed_never_auto_accepted(self):
        report=d.summarize(container_fixture(),'Started server and processing requests')
        self.assertEqual(report['enrollment_phase'],'ENROLLMENT_STATE_UNCONFIRMED')
        self.assertFalse(report['oidc_browser_login_verified'])
        self.assertFalse(report['live_tailnet_policy_verified'])

    def test_invalid_runtime_changes_are_denied(self):
        cases=(lambda c: c.update(Image='sha256:'+'0'*64),
               lambda c: c.update(Name='/production-db'),
               lambda c: c['Config'].update(User='root'),
               lambda c: c['Config'].update(Image='tailscale/tsidp:latest'),
               lambda c: c['HostConfig'].update(Privileged=True),
               lambda c: c['HostConfig'].update(ReadonlyRootfs=False),
               lambda c: c['HostConfig'].update(CapDrop=[]),
               lambda c: c['HostConfig'].update(PortBindings={'443/tcp':[{}]}),
               lambda c: c['HostConfig'].update(NetworkMode='host'),
               lambda c: c['HostConfig'].update(RestartPolicy={'Name':'always'}),
               lambda c: c['HostConfig'].update(PublishAllPorts=True),
               lambda c: c['HostConfig'].update(SecurityOpt=[]),
               lambda c: c['HostConfig'].update(NanoCpus=0),
               lambda c: c['Mounts'].append({'Type':'bind','Destination':'/srv'}),
               lambda c: c['Mounts'][0].update(Name='production_data'),
               lambda c: c['Config']['Env'].append('TS_AUTHKEY=synthetic-not-actual'))
        for change in cases:
            with self.subTest(change=str(change)):
                c=container_fixture();change(c)
                with self.assertRaises(ValueError):d.summarize(c,'')

    def test_too_large_or_sensitive_logs_fail_without_echoing_secrets(self):
        for logs in ('x'*(d.MAX_BYTES+1),'TS_AUTHKEY=would_leak',
                     'TS_CLIENT_SECRET=would_leak'):
            with self.subTest(size=len(logs)),self.assertRaises(ValueError):
                d.summarize(container_fixture(),logs)

    def test_cli_errors_redact_underlying_logs_and_exception(self):
        output=io.StringIO()
        with patch.object(d,'diagnose',side_effect=ValueError('login.tailscale.com/a/private_one_time_secret')),redirect_stdout(output):
            self.assertEqual(d.main(),2)
        self.assertNotIn('private_one_time_secret',output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['enrollment_phase'],'UNKNOWN_HOLD')

    def test_diagnose_consumes_stderr_logs_without_printing_them(self):
        fixture=container_fixture()
        original='https://login.tailscale.com/a/DO_NOT_OUTPUT'
        class Process:
            stdout=b''
            stderr=('To start this tsnet server, or go to: '+original).encode()
        with patch.object(d,'safe_command',return_value=json.dumps([fixture])), patch.object(d.subprocess,'run',return_value=Process()) as proc:
            output=d.diagnose()
        self.assertEqual(output['enrollment_phase'],'AWAITING_INTERACTIVE_ADMIN_APPROVAL')
        self.assertNotIn(original,json.dumps(output))
        args=proc.call_args.args[0]
        self.assertEqual(args[:3],['docker','logs','--since'])
        self.assertEqual(args[-1],d.CONTAINER)


if __name__=='__main__':unittest.main()
