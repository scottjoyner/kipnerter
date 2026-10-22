import copy
import unittest
from scripts.portal_deploy_target import select

PROD = {"HostName":"kipnerter-prod-01","Online":True,
        "Tags":["tag:kipnerter-prod"],"TailscaleIPs":["100.81.2.3", "fd7a:115c:a1e0::1"]}
STAGE = {"HostName":"kipnerter-stage-01","Online":True,
         "Tags":["tag:kipnerter-staging"],"TailscaleIPs":["100.81.2.4"]}


def fixture():
    return {"Peer":{"a":copy.deepcopy(PROD),"b":copy.deepcopy(STAGE)}}


class DeploymentTargetTests(unittest.TestCase):
    def test_exact_tagged_environment_separation(self):
        f = fixture()
        self.assertEqual(select(f,"production"),("kipnerter-prod-01","100.81.2.3"))
        self.assertEqual(select(f,"staging","kipnerter-stage-01"),("kipnerter-stage-01","100.81.2.4"))

    def test_staging_cannot_select_production_or_untagged_host(self):
        for preferred in ("kipnerter-prod-01","100.81.2.3","kipnerter-stage-02", ""):
            with self.subTest(preferred=preferred), self.assertRaises(ValueError):
                select(fixture(), "staging",preferred)
        payload=fixture()
        payload["Peer"]["b"]["Tags"] = []
        with self.assertRaises(ValueError):select(payload,"staging","kipnerter-stage-01")

    def test_no_dual_role_or_offline_node(self):
        for patch in ({"Tags":["tag:kipnerter-staging","tag:kipnerter-prod"]},
                      {"Online":False}, {"TailscaleIPs":["192.168.0.5"]},
                      {"TailscaleIPs":["100.81.2.4","100.81.2.5"]}):
            payload=fixture()
            payload["Peer"]["b"].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                select(payload,"staging","kipnerter-stage-01")

    def test_ambiguous_prod_target_never_selects_last_ip(self):
        payload=fixture()
        duplicate=copy.deepcopy(PROD)
        duplicate.update({"HostName":"kipnerter-prod-01-2","TailscaleIPs":["100.81.2.7"]})
        payload["Peer"]["c"]=duplicate
        with self.assertRaises(ValueError):select(payload,"production")
        self.assertEqual(select(payload,"production","kipnerter-prod-01"),
                         ("kipnerter-prod-01","100.81.2.3"))

    def test_invalid_status_denied(self):
        for document in ({},{"Peer":[]},None):
            with self.assertRaises(ValueError):select(document,"production")
        with self.assertRaises(ValueError):select(fixture(),"preview")


if __name__=="__main__":unittest.main()
