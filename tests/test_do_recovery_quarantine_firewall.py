"""Offline negative tests: Stage A creates only a firewall and unique tag."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.do_recovery_quarantine_firewall import (
    SNAPSHOT_ID, PROD_ID, CREATED_UTC, TAG, NAME, CONFIRM, stage_a,
    required_firewall, _check_firewall,
)

class Fake:
    def __init__(self, existing=False):
        self.operations=[]
        self.have_tag=existing
        self.have_firewall=existing
        self.droplets=[{"id": PROD_ID,"name":"kipnerter-prod-01",
                        "status":"active","tags":["kipnerter","production"]}]
        self.snapshot={"id":SNAPSHOT_ID,"type":"snapshot","status":"available",
                       "created_at":CREATED_UTC,"regions":["nyc3"]}
        self.firewall={**required_firewall(),
                       "id":"96c2200f-b7a0-430f-92d6-45ff66b42d93",
                       "status":"succeeded","pending_changes":[]}

    def request(self,method,path,payload=None,allow_404=False):
        self.operations.append((method,path))
        if method=="GET":
            if path==f"/v2/images/{SNAPSHOT_ID}":
                return {"image":copy.deepcopy(self.snapshot)}
            if path.startswith("/v2/droplets?"):
                return {"droplets":copy.deepcopy(self.droplets),
                        "meta":{"total":len(self.droplets)}}
            if path=="/v2/tags/"+TAG:
                return ({"tag":{"name":TAG,
                        "resources":{"droplets":{"count":0}}}}
                        if self.have_tag else None)
            if path.startswith("/v2/firewalls?"):
                return {"firewalls":[copy.deepcopy(self.firewall)] if self.have_firewall else [],
                        "meta":{"total":int(self.have_firewall)}}
            if path=="/v2/firewalls/"+self.firewall["id"]:
                return {"firewall":copy.deepcopy(self.firewall)}
        if method=="POST":
            if path=="/v2/tags":
                assert payload=={"name":TAG}
                self.have_tag=True
                return {"tag":{"name":TAG}}
            if path=="/v2/firewalls":
                assert payload==required_firewall()
                self.have_firewall=True
                return {"firewall":copy.deepcopy(self.firewall)}
        raise AssertionError(f"unplanned API operation: {method} {path}")

    @property
    def writes(self):
        return [p for p in self.operations if p[0]=="POST"]

class FirewallStageATests(unittest.TestCase):
    def test_inventory_never_posts(self):
        fake=Fake()
        result=stage_a(fake,"inventory")
        self.assertEqual(result["status"],"FIREWALL_NOT_INSTALLED")
        self.assertEqual(fake.writes,[])
        self.assertFalse(result["safe_to_restore"])

    def test_approval_required_before_any_requests(self):
        for marker in ("","yes","APPROVE_FULL_DEPLOY"):
            with self.subTest(marker=marker):
                f=Fake()
                with self.assertRaises(ValueError):
                    stage_a(f,"apply",marker)
                self.assertEqual(f.operations,[])

    def test_only_tag_and_firewall_created(self):
        f=Fake()
        with patch("scripts.do_recovery_quarantine_firewall.time.sleep"):
            result=stage_a(f,"apply",CONFIRM)
        self.assertEqual(f.writes,[("POST","/v2/tags"),("POST","/v2/firewalls")])
        self.assertEqual(result["status"],"FIREWALL_INSTALLED_VERIFIED")
        self.assertFalse(result["droplet_created"])
        self.assertFalse(result["safe_to_restore"])

    def test_existing_exact_rule_is_idempotent(self):
        f=Fake(existing=True)
        result=stage_a(f,"apply",CONFIRM)
        self.assertEqual(result["status"],"FIREWALL_ALREADY_VERIFIED")
        self.assertEqual(f.writes,[])

    def test_snapshot_identity_fail_closed(self):
        for key,value in (("id",250649653),("type","backup"),
                          ("created_at","2026-10-19T00:00:00Z"),
                          ("status","new"),("regions",["nyc1"])):
            f=Fake()
            f.snapshot[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                stage_a(f,"apply",CONFIRM)
            self.assertEqual(f.writes,[])

    def test_prod_identity_and_tag_guard(self):
        for kind in ("tag","name","inactive","missing"):
            f=Fake()
            if kind=="tag":
                f.droplets[0]["tags"].append(TAG)
            elif kind=="name":
                f.droplets[0]["name"]="unrecognized-prod"
            elif kind=="inactive":
                f.droplets[0]["status"]="off"
            else:f.droplets=[]
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                stage_a(f,"apply",CONFIRM)
            self.assertEqual(f.writes,[])

    def test_existing_allow_rule_or_prod_tag_denied(self):
        for kind in ("allow","prod_tag","associated"):
            f=Fake(existing=True)
            if kind=="allow":
                f.firewall["inbound_rules"][0]["action"]="allow"
            elif kind=="prod_tag":
                f.firewall["tags"]=["production"]
            else:
                f.firewall["droplet_ids"]=[PROD_ID]
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                stage_a(f,"apply",CONFIRM)
            self.assertEqual(f.writes,[])

    def test_incomplete_protocols_and_address_ranges_rejected(self):
        for kind in ("no_udp","no_ipv6","wrong_ports","duplicate","foreign_source"):
            obj=Fake().firewall
            if kind=="no_udp":obj["outbound_rules"].pop()
            elif kind=="no_ipv6":
                obj["inbound_rules"][0]["sources"]["addresses"]=["0.0.0.0/0"]
            elif kind=="wrong_ports":
                obj["inbound_rules"][0]["ports"]="443"
            elif kind=="duplicate":
                obj["outbound_rules"][1]=copy.deepcopy(obj["outbound_rules"][0])
            else:obj["outbound_rules"][0]["destinations"]["tags"]=["production"]
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                _check_firewall(obj)

    def test_workflow_manual_master_only_and_protected(self):
        root=Path(__file__).resolve().parents[1]
        workflow=(root/".github/workflows/recovery-firewall-stage-a.yml").read_text()
        self.assertIn("workflow_dispatch:",workflow)
        self.assertIn("environment: production",workflow)
        self.assertIn("refs/heads/master",workflow)
        self.assertIn("concurrency:",workflow)
        for forbidden in ("pull_request:", "push:", "terraform apply",
                          "droplet create","digitalocean_droplet"):
            self.assertNotIn(forbidden,workflow)
        code=(root/"scripts/do_recovery_quarantine_firewall.py").read_text()
        self.assertNotIn('POST", "/v2/droplets"',code)

if __name__=="__main__":
    unittest.main()
