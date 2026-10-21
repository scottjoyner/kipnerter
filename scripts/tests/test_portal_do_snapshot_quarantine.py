"""No network or production resources: quarantine restore gate regression controls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.portal_do_snapshot_quarantine import (
    verify_readbacks, load_exact_json,
    OWNER_APPROVAL, RECOVERY_TAG, FIREWALL_NAME, SNAPSHOT_ID, PRODUCTION_ID,
)

FIREWALL_UUID = "6e745ed6-4b77-4669-8b0d-4fc0da51f902"


def deny_rules(endpoint):
    return [{
        "protocol": protocol, "action": "deny",
        **({"ports": "1-65535"} if protocol in ("tcp", "udp") else {}),
        endpoint: {"addresses": ["0.0.0.0/0", "::/0"]},
    } for protocol in ("tcp", "udp", "icmp")]


def fixture():
    image = {"image": {
        "id": SNAPSHOT_ID, "type": "snapshot", "status": "available",
        "created_at": "2026-10-18T12:08:13Z",
        "regions": ["nyc3"], "min_disk_size": 80
    }}
    firewall = {"firewall": {
        "id": FIREWALL_UUID, "name": FIREWALL_NAME, "status": "succeeded",
        "tags": [RECOVERY_TAG],
        "inbound_rules": deny_rules("sources"),
        "outbound_rules": deny_rules("destinations"),
        "droplet_ids": [], "pending_changes": [],
    }}
    droplets = {"droplets": [{
        "id": PRODUCTION_ID, "name": "kipnerter-prod-01", "status": "active",
        "tags": ["kipnerter", "production"],
    }]}
    return image, firewall, droplets


class QuarantineTests(unittest.TestCase):
    def result(self, *args):
        return verify_readbacks(*args, approval=OWNER_APPROVAL)

    def test_positive_readbacks_are_only_a_request_not_a_clone(self):
        result = self.result(*fixture())
        self.assertEqual(result["status"],
                         "RECOVERY_FIREWALL_PREFLIGHT_OK_NO_CLONE_CREATED")
        self.assertEqual(result["snapshot_id"], SNAPSHOT_ID)
        self.assertEqual(result["protected_create_request"]["Tags"], [RECOVERY_TAG])
        self.assertEqual(result["protected_create_request"]["ImageID"], SNAPSHOT_ID)
        self.assertFalse(result["restore_submitted"])
        self.assertFalse(result["boot_network_isolation_physically_confirmed"])
        self.assertFalse(result["running_historical_services_recovered"])
        self.assertFalse(result["safe_to_cutover"])

    def test_missing_owner_approval_fails(self):
        args = fixture()
        for phrase in ("", "yes", "allow", "AUTHORIZE_BILLABLE_ISOLATED_RESTORE_999"):
            with self.subTest(phrase=phrase), self.assertRaises(ValueError):
                verify_readbacks(*args, approval=phrase)

    def test_snapshot_cannot_substitute_latest_backup_or_mismatched_date(self):
        for field, bad in (("id", 250649653), ("type", "backup"),
                           ("status", "new"), ("created_at", "2026-10-19T00:00:00Z"),
                           ("regions", ["nyc1"]), ("min_disk_size", 120),
                           ("min_disk_size", True)):
            with self.subTest(field=field, bad=bad):
                img, fw, droplets = fixture()
                img["image"][field] = bad
                with self.assertRaises(ValueError):
                    self.result(img, fw, droplets)

    def test_firewall_with_any_allow_rule_denied(self):
        for field in ("inbound_rules", "outbound_rules"):
            with self.subTest(field=field):
                img, fw, droplets = fixture()
                fw["firewall"][field].append({
                    "protocol": "tcp", "ports": "1-65535", "action": "allow",
                })
                with self.assertRaises(ValueError):
                    self.result(img, fw, droplets)

    def test_missing_explicit_deny_rule_rejected(self):
        for direction in ("inbound_rules", "outbound_rules"):
            image, fw, droplets = fixture()
            fw["firewall"][direction] = []
            with self.subTest(direction=direction), self.assertRaises(ValueError):
                self.result(image, fw, droplets)

    def test_all_ipv4_and_ipv6_all_protocols_are_required(self):
        for direction, sources in (
            ("inbound_rules", "sources"),
            ("outbound_rules", "destinations"),
        ):
            for mutation in ("omit_ipv6", "allow", "unknown_protocol", "partial_port",
                             "untrusted_address"):
                img, fw, droplets = fixture()
                rule = fw["firewall"][direction][0]
                if mutation == "omit_ipv6":
                    rule[sources]["addresses"] = ["0.0.0.0/0"]
                elif mutation == "allow":
                    rule["action"] = "allow"
                elif mutation == "unknown_protocol":
                    rule["protocol"] = "gre"
                elif mutation == "partial_port":
                    rule["ports"] = "443"
                else:
                    rule[sources]["addresses"] = ["1.2.3.0/24", "::/0"]
                with self.subTest(direction=direction, mutation=mutation):
                    with self.assertRaises(ValueError):
                        self.result(img, fw, droplets)

    def test_each_required_protocol_rule_must_be_present_once(self):
        for direction in ("inbound_rules", "outbound_rules"):
            for problem in ("missing_icmp", "duplicate_tcp"):
                image, fw, droplets = fixture()
                if problem == "missing_icmp":
                    fw["firewall"][direction].pop()
                else:
                    fw["firewall"][direction][2] = copy.deepcopy(
                        fw["firewall"][direction][0])
                with self.subTest(direction=direction, problem=problem):
                    with self.assertRaises(ValueError):
                        self.result(image, fw, droplets)

    def test_firewall_with_unknown_status_tag_or_id_denied(self):
        for key, val in (
            ("status", "waiting"), ("status", "failed"),
            ("tags", ["production"]), ("tags", [RECOVERY_TAG, "production"]),
            ("id", "unverified"), ("name", "kipnerter-prod"),
        ):
            with self.subTest(key=key, val=val):
                img, fw, droplets = fixture()
                fw["firewall"][key] = val
                with self.assertRaisesRegex(ValueError, "firewall"):
                    self.result(img, fw, droplets)

    def test_unsettled_firewall_changes_denied(self):
        for key, val in (
            ("droplet_ids", [PRODUCTION_ID]), ("pending_changes", [{"status": "waiting"}]),
        ):
            img, fw, droplets = fixture()
            fw["firewall"][key] = val
            with self.assertRaisesRegex(ValueError, "firewall"):
                self.result(img, fw, droplets)

    def test_recovery_tag_cannot_exist_on_production_or_other_droplet(self):
        for target_id in (PRODUCTION_ID, 999999999):
            img, fw, droplets = fixture()
            if target_id == PRODUCTION_ID:
                droplets["droplets"][0]["tags"].append(RECOVERY_TAG)
            else:
                droplets["droplets"].append({
                    "id": target_id, "name": "unrelated-test", "status": "active",
                    "tags": [RECOVERY_TAG],
                })
            with self.subTest(target=target_id), self.assertRaisesRegex(ValueError, "tag"):
                self.result(img, fw, droplets)

    def test_unknown_prod_identity_or_missing_prod_denied(self):
        for problem in ("missing", "renamed", "inactive", "duplicated"):
            img, fw, droplets = fixture()
            if problem == "missing":
                droplets["droplets"] = [{
                    "id": 101, "name": "unrelated", "status": "active", "tags": []
                }]
            elif problem == "renamed":
                droplets["droplets"][0]["name"] = "other"
            elif problem == "inactive":
                droplets["droplets"][0]["status"] = "off"
            else:
                droplets["droplets"].append(copy.deepcopy(droplets["droplets"][0]))
            with self.subTest(problem=problem), self.assertRaises(ValueError):
                self.result(img, fw, droplets)

    def test_missing_firewall_metadata_cannot_be_assumed_safe(self):
        for key in ("inbound_rules", "outbound_rules", "droplet_ids",
                    "pending_changes", "status", "tags"):
            img, fw, droplets = fixture()
            del fw["firewall"][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.result(img, fw, droplets)

    def test_untrusted_provider_json_duplicate_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "fixture.json"
            src.write_text('{"image": {"id": 1, "id": 2}}')
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_exact_json(src)

    def test_untrusted_json_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "actual.json"
            original.write_text(json.dumps(fixture()[0]))
            alias = Path(tmp) / "alias.json"
            alias.symlink_to(original)
            with self.assertRaises(ValueError):
                load_exact_json(alias)

    def test_quarantine_terraform_template_contains_no_clone_or_egress(self):
        root = Path(__file__).resolve().parents[2]
        tf = (root / "infra/digitalocean/terraform/recovery-quarantine/main.tf").read_text()
        for forbidden in ('resource "digitalocean_droplet"',
                          "terraform apply", "user_data"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, tf)
        self.assertIn('resource "digitalocean_firewall" "quarantine"', tf)
        self.assertIn('prevent_destroy = true', tf)
        self.assertIn('tags = [digitalocean_tag.quarantine.name]', tf)
        self.assertEqual(tf.count('action           = "deny"'), 3)
        self.assertEqual(tf.count('action                = "deny"'), 3)
        for protocol in ("tcp", "udp", "icmp"):
            self.assertIn('protocol         = "' + protocol + '"', tf)
            self.assertIn('protocol              = "' + protocol + '"', tf)
        self.assertIn('port_range       = "1-65535"', tf)
        self.assertIn('port_range            = "1-65535"', tf)
        self.assertIn('source_addresses = ["0.0.0.0/0", "::/0"]', tf)
        self.assertIn('destination_addresses = ["0.0.0.0/0", "::/0"]', tf)


if __name__ == "__main__":
    unittest.main()
