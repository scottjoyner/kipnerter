"""Synthetic offline negative controls for private tsidp enrollment witness."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.portal_tsidp_bootstrap_readiness import (
    CONTAINER, DNS_NAME, IMAGE, IMAGE_DIGEST, ORIGIN, PROJECT,
    check_compose, check_runtime, discovery_valid, enrolled, inspect,
)


def compose_fixture():
    return {
        "name": PROJECT,
        "services": {"idp": {
            "image": IMAGE, "container_name": CONTAINER,
            "restart": "no", "read_only": True, "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "cpus": .5, "mem_limit": 268435456, "pids_limit": 128,
            "environment": {
                "TAILSCALE_USE_WIP_CODE": "1", "TS_STATE_DIR": "/data",
                "TS_HOSTNAME": "kipnerter-idp-staging", "TS_ADVERTISE_TAGS": "tag:tsidp",
                "TSIDP_ENABLE_STS": "0",
            },
            "networks": {"idp_network": None},
            "volumes": [{"type": "volume", "source": "idp_data", "target": "/data", "volume": {}}],
        }},
        "networks": {"idp_network": {"name": PROJECT + "_idp_network"}},
        "volumes": {"idp_data": {"name": PROJECT + "_idp_data"}},
    }


def runtime_fixture():
    return {
        "Image": "sha256:" + IMAGE_DIGEST,
        "Config": {"User": "app:app", "Image": IMAGE, "Env": ["TS_STATE_DIR=/data"]},
        "HostConfig": {"Privileged": False, "PublishAllPorts": False,
                       "PortBindings": {}, "ReadonlyRootfs": True,
                       "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"],
                       "NetworkMode": PROJECT + "_idp_network",
                       "RestartPolicy": {"Name": "no"}, "Memory": 268435456,
                       "NanoCpus": 500000000, "PidsLimit": 128},
        "State": {"Running": True},
        "Mounts": [{"Type": "volume", "Name": PROJECT + "_idp_data",
                    "Destination": "/data", "RW": True}],
    }


def discovery_fixture():
    return {"issuer": ORIGIN,
            "jwks_uri": ORIGIN + "/.well-known/jwks.json",
            "authorization_endpoint": ORIGIN + "/authorize",
            "token_endpoint": ORIGIN + "/token"}


class BootstrapSafetyTests(unittest.TestCase):
    def test_exact_reviewed_compose_is_accepted(self):
        self.assertTrue(check_compose(compose_fixture()))

    def test_compose_rejects_priviliges_exposure_and_credentials(self):
        bad_service = [
            {"ports": [{"published": "443", "target": 443}]},
            {"expose": [443]}, {"privileged": True}, {"read_only": False},
            {"cap_add": ["SYS_ADMIN"]}, {"cap_drop": []},
            {"security_opt": []}, {"restart": "always"},
            {"network_mode": "host"}, {"extra_hosts": ["internal:127.0.0.1"]},
            {"volumes_from": ["some-other-service"]},
            {"user": "root"}, {"entrypoint": ["/bin/sh"]},
            {"image": "ghcr.io/tailscale/tsidp:latest"},
            {"mem_limit": 0}, {"mem_limit": 9999999999},
            {"pids_limit": 0}, {"cpus": 4},
            {"secrets": [{"source": "prod_token"}]},
            {"networks": {"idp_network": None, "other": None}},
            {"volumes": [{"type": "bind", "source": "/", "target": "/data"}]},
        ]
        for mutation in bad_service:
            with self.subTest(mutation=mutation):
                conf = compose_fixture()
                conf["services"]["idp"].update(mutation)
                with self.assertRaises(ValueError):check_compose(conf)

    def test_compose_rejects_state_role_and_new_service(self):
        for modify in (
            lambda d: d.update(name="kipnerter"),
            lambda d: d["services"].update(api={}),
            lambda d: d["services"]["idp"]["environment"].update(TS_AUTHKEY="sample-not-a-real-key"),
            lambda d: d["services"]["idp"]["environment"].update(TS_HOSTNAME="prod-idp"),
            lambda d: d["volumes"].update(prod_data={}),
            lambda d: d["networks"]["idp_network"].update(external=True),
            lambda d: d["services"]["idp"]["volumes"][0].update(target="/run/secrets"),
        ):
            with self.subTest(modify=modify):
                conf = compose_fixture(); modify(conf)
                with self.assertRaises(ValueError): check_compose(conf)

    def test_actual_runtime_shape_is_checked(self):
        self.assertTrue(check_runtime(runtime_fixture()))

    def test_actual_runtime_rejects_container_exposure_and_state_tampering(self):
        changes = [
            lambda x: x.update(Image="sha256:" + "0" * 64),
            lambda x: x["Config"].update(User="root"),
            lambda x: x["Config"].update(Image="ghcr.io/tailscale/tsidp:latest"),
            lambda x: x["Config"]["Env"].append("TS_AUTHKEY=secret-would-not-print"),
            lambda x: x["State"].update(Running=False),
            lambda x: x["HostConfig"].update(Privileged=True),
            lambda x: x["HostConfig"].update(ReadonlyRootfs=False),
            lambda x: x["HostConfig"].update(PortBindings={"443/tcp": [{}]}),
            lambda x: x["HostConfig"].update(NetworkMode="host"),
            lambda x: x["HostConfig"].update(RestartPolicy={"Name": "always"}),
            lambda x: x["HostConfig"].update(NanoCpus=0),
            lambda x: x["HostConfig"].update(PidsLimit=0),
            lambda x: x["HostConfig"].update(CapDrop=[]),
            lambda x: x["Mounts"].append({"Type": "bind", "Destination": "/private"}),
            lambda x: x["Mounts"][0].update(RW=False),
            lambda x: x["Mounts"][0].update(Name="production_data"),
        ]
        for modify in changes:
            with self.subTest(modify=modify):
                item=runtime_fixture();modify(item)
                with self.assertRaises(ValueError): check_runtime(item)

    def test_tailnet_requires_exact_online_uniquely_tagged_node(self):
        p={"HostName":"kipnerter-idp-staging","Online":True,"Tags":["tag:tsidp"]}
        self.assertTrue(enrolled({"Peer": {"one": p}}))
        for mutation in (dict(Online=False),dict(Tags=[]),dict(HostName="kipnerter-prod-01")):
            q={**p,**mutation}
            self.assertFalse(enrolled({"Peer":{"one":q}}))
        self.assertFalse(enrolled({"Peer":{"one":p,"two":p}}))
        self.assertFalse(enrolled({"Peer":{}}))

    def test_discovery_requires_exact_issuer_and_no_redirect(self):
        url=ORIGIN+"/.well-known/openid-configuration"
        self.assertTrue(discovery_valid(discovery_fixture(),url))
        self.assertFalse(discovery_valid(discovery_fixture(),"https://elsewhere.example/"))
        for key,value in (
            ("issuer", "https://evil.example"),
            ("jwks_uri", "http://"+DNS_NAME+"/keys"),
            ("jwks_uri", "https://evil.example/keys"),
            ("authorization_endpoint", "https://user:pass@"+DNS_NAME+"/auth"),
            ("authorization_endpoint", "https://"+DNS_NAME+":8443/auth"),
            ("token_endpoint", "https://"+DNS_NAME+":notaport/token"),
            ("token_endpoint", "https://"+DNS_NAME+"/token?dest=evil"),
        ):
            with self.subTest(key=key,value=value):
                item=discovery_fixture();item[key]=value
                self.assertFalse(discovery_valid(item,url))

    def test_never_promotes_bootstrap_to_client_or_public_release(self):
        with patch("scripts.portal_tsidp_bootstrap_readiness.safe_json_command",side_effect=[compose_fixture()]):
            report=inspect(offline=True)
        self.assertTrue(report["compose_safe"])
        self.assertFalse(report["oidc_client_registered"])
        self.assertFalse(report["browser_login_verified"])
        self.assertFalse(report["production_deploy_authorized"])
        self.assertEqual(report["release_gate"],"NO_GO")
        with patch("scripts.portal_tsidp_bootstrap_readiness.safe_json_command",side_effect=[compose_fixture(),[runtime_fixture()],{"Peer":{}}]):
            report=inspect()
        self.assertTrue(report["runtime_isolated"])
        self.assertFalse(report["tailnet_enrolled"])
        self.assertFalse(report["oidc_discovery_valid"])
        self.assertEqual(report["release_gate"],"NO_GO")


if __name__ == "__main__":unittest.main()
