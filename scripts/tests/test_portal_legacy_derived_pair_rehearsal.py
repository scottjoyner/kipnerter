"""Synthetic fail-closed controls for derived historical API+web Docker rehearsal.

Tests do not use Docker, open network sockets, or access live service data.
"""
import copy
import unittest
from unittest.mock import patch

from scripts.portal_legacy_derived_pair_rehearsal import (
    DEFAULT_IDS, HARDENED_WEB_ID, pin_image, validate_container, start, remove_owned, rehearse,
)

ID = "a" * 64

def fixture(role="api"):
    image = DEFAULT_IDS[role]
    user = "65532:65532" if role == "api" else "10001:10001"
    name = "kp-derived-legacy-" + role + "-1234567890abcdef-initial"
    return {
        "Id": ID, "Image": image, "Name": "/" + name,
        "State": {"Running": True},
        "Config": {"Image": image, "User": user, "Volumes": None,
                   "Env": ["RESEARCH_SYNTHETIC=1"]},
        "HostConfig": {
            "NetworkMode": "none", "ReadonlyRootfs": True,
            "Privileged": False, "CapDrop": ["ALL"],
            "PortBindings": {}, "Binds": None, "VolumesFrom": None,
            "PidsLimit": 96, "Memory": 536870912 if role == "api" else 805306368,
            "SecurityOpt": ["no-new-privileges"],
            "RestartPolicy": {"Name": "no"},
            "Tmpfs": {"/tmp": "rw,nosuid,size=33554432"},
        },
        "Mounts": [],
    }

def validate(doc, role="api"):
    user = "65532:65532" if role == "api" else "10001:10001"
    name = "kp-derived-legacy-" + role + "-1234567890abcdef-initial"
    validate_container(doc, image_id=DEFAULT_IDS[role], user=user, name=name)

class ResearchSafetyTests(unittest.TestCase):
    def test_synthetic_container_full_isolation_passes(self):
        validate(fixture())
        validate(fixture("web"), "web")

    def test_refuse_mutable_tag_and_malformed_image(self):
        for bad in ("node:22-alpine", "latest", "sha256:bad", "", "sha256:"+"X"*64):
            with self.subTest(image=bad), self.assertRaises(ValueError):
                pin_image(bad)

    def test_image_cache_identity_rebound_denied(self):
        with patch("scripts.portal_legacy_derived_pair_rehearsal.docker",
                   return_value="sha256:"+"a"*64):
            with self.assertRaisesRegex(ValueError, "absent or changed"):
                pin_image(DEFAULT_IDS["web"])

    def test_network_port_and_privilege_fail_closed(self):
        variants = (
            ("NetworkMode", "bridge"), ("ReadonlyRootfs", False),
            ("Privileged", True), ("PortBindings", {"3000/tcp":[{"HostPort":"3000"}]}),
            ("Binds", ["/srv/prod:/data:ro"]), ("VolumesFrom", ["real-prod"]),
            ("CapDrop", []), ("PidsLimit", 0), ("Memory", 0),
            ("SecurityOpt", []), ("Tmpfs", {"/tmp":"rw,nosuid,size=0"}),
            ("RestartPolicy", {"Name":"always"}),
        )
        for key, value in variants:
            with self.subTest(key=key):
                doc=fixture()
                doc["HostConfig"][key] = value
                with self.assertRaises(ValueError):
                    validate(doc)

    def test_implicit_volume_or_foreign_mount_denied(self):
        for change in (
            lambda doc: doc["Config"].update(Volumes={"/data":{}}),
            lambda doc: doc.update(Mounts=[{"Type":"volume","Destination":"/data"}]),
        ):
            doc=fixture()
            change(doc)
            with self.assertRaises(ValueError):
                validate(doc)

    def test_injected_container_identity_fails(self):
        variants=(
            ("Id", "container-name"), ("Image", DEFAULT_IDS["web"]),
            ("Name", "/production-service"),
        )
        for field,bad in variants:
            doc=fixture()
            doc[field]=bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(doc)

    def test_wrong_image_user_or_stopped_container_denied(self):
        for field,bad in (("Image",DEFAULT_IDS["web"]),("User","root")):
            doc=fixture()
            doc["Config"][field]=bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(doc)
        doc=fixture()
        doc["State"]["Running"]=False
        with self.assertRaises(ValueError):
            validate(doc)

    def test_no_arbitrary_container_name_or_role(self):
        with patch("scripts.portal_legacy_derived_pair_rehearsal.docker") as d:
            for role,name in (("unknown","kp-derived-legacy-api-1234567890abcdef-initial"),
                              ("api","kipnerter-spatial-postgres-1"),
                              ("web","kp-derived-legacy-api-1234567890abcdef-initial")):
                with self.subTest(role=role,name=name),self.assertRaises(ValueError):
                    start(role,DEFAULT_IDS["api"],name,set())
            d.assert_not_called()

    def test_owned_container_id_must_be_unambiguous(self):
        with patch("scripts.portal_legacy_derived_pair_rehearsal.docker") as d:
            with self.assertRaises(ValueError):
                remove_owned({"kipnerter-spatial-postgres-1"},sigkill=True)
            d.assert_not_called()

    def test_derived_pair_can_never_be_reported_as_original_oci_or_cutover(self):
        with patch("scripts.portal_legacy_derived_pair_rehearsal.pin_image"):
            with patch("scripts.portal_legacy_derived_pair_rehearsal.start",
                       side_effect=["a"*64,"b"*64]*2):
                with patch("scripts.portal_legacy_derived_pair_rehearsal.qualify"):
                    with patch("scripts.portal_legacy_derived_pair_rehearsal.remove_owned",
                               side_effect=lambda owned,**kw: owned.clear()):
                        result=rehearse(DEFAULT_IDS["api"],DEFAULT_IDS["web"])
        self.assertTrue(result["status"].startswith("SOURCE_DERIVED_PAIR_RESTART_PASS"))
        for field in ("safe_to_cutover","historical_original_oci_images_recovered",
                      "cross_version_portal_auth_route_parity_verified",
                      "web_npm_security_review_passed",
                      "independent_custody_verified"):
            self.assertFalse(result[field])

    def test_hardened_web_is_pinned_without_implying_prod_security_approval(self):
        with patch("scripts.portal_legacy_derived_pair_rehearsal.pin_image"):
            with patch("scripts.portal_legacy_derived_pair_rehearsal.start",
                       side_effect=["a"*64, "b"*64] * 2):
                with patch("scripts.portal_legacy_derived_pair_rehearsal.qualify"):
                    with patch("scripts.portal_legacy_derived_pair_rehearsal.remove_owned",
                               side_effect=lambda owned, **kw: owned.clear()):
                        result = rehearse(DEFAULT_IDS["api"], HARDENED_WEB_ID)
        self.assertTrue(result["hardened_web_npm_audit_at_research_build_passed"])
        self.assertFalse(result["web_npm_security_review_passed"])
        self.assertFalse(result["safe_to_cutover"])
        self.assertFalse(result["historical_original_oci_images_recovered"])

    def test_api_and_web_id_cannot_be_the_same(self):
        with self.assertRaises(ValueError):
            rehearse(DEFAULT_IDS["api"],DEFAULT_IDS["api"])

if __name__ == "__main__":
    unittest.main()
