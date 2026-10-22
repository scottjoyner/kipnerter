"""Static no-secret-before-review controls for manual staging readiness.

No GitHub token, tailnet identity, network access or deployment required.
"""
import re
import unittest
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parents[1] /
            ".github/workflows/portal-stateless-staging-readiness.yml")
PIN = re.compile(r"EXPECTED_PORTAL_SHA:\s+([a-f0-9]{40})")
REVIEW_BLOBS = (
    "scripts/portal_stateless_readiness.py",
    "scripts/portal_fleet_preview_preflight.py",
    "scripts/portal_deploy_target.py",
    "scripts/portal_oidc_preflight.py",
    "tests/test_portal_stateless_readiness.py",
    "docker-compose.yml",
    "compose.fleet-preview.yml",
    "apps/web/lib/auth.js",
    "apps/web/lib/tsidp-config.mjs",
    "apps/web/tests/tsidp-runtime-config.test.mjs",
)


def audit(workflow):
    """Return safety regressions; do not execute any checkout or source script."""
    problems = []
    expected = PIN.search(workflow)
    if not expected:
        problems.append("missing immutable exact SHA")
        return problems
    sha = expected.group(1)
    if "workflow_dispatch:" not in workflow or "inputs:" in workflow:
        problems.append("manual workflow must not accept checkout input")
    if "github.ref == 'refs/heads/master'" not in workflow:
        problems.append("non-default branch could access staging environment")
    if "github.actor == github.repository_owner" not in workflow:
        problems.append("owner guard missing")
    if not re.search(r"\bref:\s+" + sha + r"\b", workflow):
        problems.append("reviewed checkout not fixed to exact SHA")
    if "persist-credentials: false" not in workflow:
        problems.append("checkout credentials may persist")
    if ("Verify revision and pre-reviewed script identities before secrets"
            not in workflow):
        problems.append("missing pre-secret integrity gate")
    verify_at = workflow.find("Verify revision and pre-reviewed script identities before secrets")
    source_tests_at = workflow.find("Execute isolated deny-only unit and Compose tests")
    first_secret_at = workflow.find("${{ secrets.")
    if not (0 <= verify_at < source_tests_at < first_secret_at):
        problems.append("review/test stages not before protected secrets")
    for path in REVIEW_BLOBS:
        if f'git rev-parse HEAD:{path}' not in workflow:
            problems.append(f"unreviewed source: {path}")
    if ("run: python3 scripts/portal_stateless_readiness.py --planned-sha"
            not in workflow):
        problems.append("expected preflight missing")
    if ("no SSH" not in workflow or
            "tailscale ping --timeout=8s" not in workflow):
        problems.append("read-only staging role check lost")
    return problems


class TrustedStagingWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_reviewed_manual_workflow_is_safe_to_qualify(self):
        self.assertEqual(audit(self.workflow), [])

    def test_user_supplied_checkout_sha_is_rejected(self):
        dangerous = self.workflow.replace(
            "ref: 999f3caa49da73b89b5534c2f9037a78bc799797",
            "ref: ${{ inputs.planned_portal_sha }}")
        self.assertIn("reviewed checkout not fixed to exact SHA", audit(dangerous))

    def test_branch_dispatch_must_not_override_master_review(self):
        dangerous = self.workflow.replace(
            " && github.ref == 'refs/heads/master'", "")
        self.assertIn("non-default branch could access staging environment", audit(dangerous))

    def test_unreviewed_source_cannot_run_before_secrets(self):
        dangerous = self.workflow.replace(
            "Verify revision and pre-reviewed script identities before secrets",
            "Check source later")
        self.assertIn("missing pre-secret integrity gate", audit(dangerous))

    def test_removal_of_nested_auth_guard_requires_review(self):
        dangerous = self.workflow.replace(
            'test "$(git rev-parse HEAD:apps/web/lib/auth.js)"',
            'test "$(git rev-parse HEAD:apps/web/lib/unknown.js)"')
        self.assertIn("unreviewed source: apps/web/lib/auth.js", audit(dangerous))

    def test_secrets_must_not_be_loaded_before_integrity_checks(self):
        target = "      - name: Verify revision and pre-reviewed script identities before secrets"
        dangerous = self.workflow.replace(
            target, "      - name: Inject injected secrets\n"
            "        env:\n"
            "          BAD: ${{ secrets.TSIDP_CLIENT_SECRET }}\n" + target)
        self.assertIn("review/test stages not before protected secrets", audit(dangerous))


if __name__ == "__main__":
    unittest.main()
