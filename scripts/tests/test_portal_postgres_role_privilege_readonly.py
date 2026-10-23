"""Synthetic bounded-data negative controls; no production Docker or SQL calls."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch
from scripts import portal_postgres_role_privilege_readonly as m

class RoleCensusTests(unittest.TestCase):
    def test_default_cannot_run_docker(self):
        out = io.StringIO()
        with patch.object(m, "inspect_counts", side_effect=AssertionError("called")):
            with contextlib.redirect_stdout(out):
                self.assertEqual(m.main([]), 3)
        self.assertEqual(json.loads(out.getvalue())["status"], "DRY_RUN_NO_DOCKER_OR_SQL")

    def test_wrong_host_rejected(self):
        with patch.object(m.socket, "gethostname", return_value="wrong"):
            with patch.object(m, "inspect_counts", side_effect=AssertionError("called")):
                self.assertEqual(m.main(["--inspect-live"]), 3)

    def test_docker_target_override_rejected(self):
        with patch.object(m.socket, "gethostname", return_value=m.HOST):
            with patch.dict(m.os.environ, {"DOCKER_HOST":"tcp://remote:2375"}):
                with patch.object(m, "inspect_counts", side_effect=AssertionError("called")):
                    self.assertEqual(m.main(["--inspect-live"]), 3)

    def test_command_allowlist(self):
        with patch.object(m.subprocess, "run", side_effect=AssertionError("executed")):
            with self.assertRaises(ValueError):
                m.run_readonly(["docker", "exec", "-it", m.PG, "sh"])

    def test_mocked_superuser_sample(self):
        def read(command):
            if command == m.INSPECT: return m.IMAGE
            if command[-1] == m.ROLE_SQL: return "15|1|1|1|1"
            if command[-1] == m.SESSION_SQL: return "3|3"
            raise AssertionError("unexpected command")
        report = m.inspect_counts(read=read)
        self.assertEqual(report["login_roles"], 1)
        self.assertEqual(report["observed_superuser_client_backends"], 3)
        self.assertEqual(report["status"], "HOLD_SUPERUSER_LOGIN_PRODUCTION")
        self.assertFalse(report["client_connection_attribution_proven"])
        self.assertEqual(report["release_gate"], "NO_GO")
        self.assertNotIn("kipnerter", json.dumps(report))

    def test_clean_counts_never_authorize_release(self):
        def read(command):
            return m.IMAGE if command == m.INSPECT else ("15|3|0|0|0" if command[-1] == m.ROLE_SQL else "2|0")
        report = m.inspect_counts(read=read)
        self.assertEqual(report["status"], "HOLD_EXTERNAL_WRITERS_UNPROVEN")
        self.assertFalse(report["postgres_writes_fenced"])
        self.assertFalse(report["safe_to_cutover"])

    def test_bad_image_rejected(self):
        with self.assertRaises(ValueError):
            m.inspect_counts(read=lambda _: "changed-image")

    def test_malformed_counts_rejected(self):
        for s in ("", "5|1|other|1|1", "5|1|2|1|1", "5|1|1|0", "5|1|1|1|1\\nSECRET"):
            with self.subTest(s=s), self.assertRaises(ValueError):
                m.parse_counts(s, 5)

    def test_stdout_is_bounded_and_raw_stderr_is_not_exposed(self):
        class Fake:
            returncode = 1
            stdout = b""
        with self.assertRaises(ValueError) as e:
            m.run_readonly(m.INSPECT, runner=lambda *args, **kwargs: Fake())
        self.assertNotIn("password", str(e.exception).lower())

    def test_no_mutating_sql(self):
        for q in (m.ROLE_SQL, m.SESSION_SQL):
            self.assertTrue(q.startswith("SELECT "))
            for disallowed in ("DELETE ", "DROP ", "UPDATE ", "ALTER ", "INSERT "):
                self.assertNotIn(disallowed, q)
