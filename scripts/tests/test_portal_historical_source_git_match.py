"""Synthetic-only negative tests. Never access production or Docker."""
import hashlib
import unittest
from scripts.portal_historical_source_git_match import allowed, verify, DOCKER

def fixture():
    members = {
        "docker-compose.yml": b"compose",
        "compose.spatial.yml": b"spatial",
        "apps/api/Dockerfile": b"FROM python",
        "apps/web/Dockerfile": b"FROM node",
    }
    members.update({f"apps/api/app/source_{i}.py": str(i).encode() for i in range(11)})
    return members

def digest(members):
    h = hashlib.sha256()
    for name, body in sorted(members.items()):
        h.update(name.encode() + b"\x00" + hashlib.sha256(body).digest())
    return h.hexdigest()

def docker(members):
    return {name: hashlib.sha256(members[name]).hexdigest() for name in DOCKER}

class IntegrityTests(unittest.TestCase):
    def test_synthetic_approval_does_not_approve_release(self):
        src = fixture()
        result = verify(src, expected_sha=digest(src), docker=docker(src))
        self.assertEqual(result["source_file_count"], 15)
        self.assertFalse(result["safe_to_cutover"])
        self.assertFalse(result["original_oci_images_recovered"])

    def test_modified_file_rejected(self):
        src = fixture()
        original = digest(src)
        src["apps/api/app/source_0.py"] = b"tamper"
        with self.assertRaisesRegex(ValueError, "Git source"):
            verify(src, expected_sha=original, docker=docker(src))

    def test_dockerfile_witness_rejected(self):
        src = fixture()
        pins = docker(src)
        pins["apps/web/Dockerfile"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "Dockerfile"):
            verify(src, expected_sha=digest(src), docker=pins)

    def test_missing_compose_rejected(self):
        src = fixture()
        src.pop("compose.spatial.yml")
        with self.assertRaises(ValueError):
            verify(src, expected_sha=digest(src), expected_count=14, docker=docker(src))

    def test_bad_names_rejected(self):
        for path in ("../escape.py", "/etc/passwd", "apps/api/../../../passwd",
                     "apps/api/.env", "apps/api/private.key", "apps/web/node_modules/a.js",
                     "apps/api/id_rsa", "unrelated/a.py"):
            with self.subTest(path=path):
                self.assertFalse(allowed(path))

    def test_unapproved_extra_rejected(self):
        src = fixture()
        src["apps/api/admin.pem"] = b"sensitive"
        with self.assertRaises(ValueError):
            verify(src, expected_sha=digest(src), expected_count=16, docker=docker(src))

    def test_wrong_count_rejected(self):
        src = fixture()
        with self.assertRaises(ValueError):
            verify(src, expected_sha=digest(src), expected_count=16, docker=docker(src))
