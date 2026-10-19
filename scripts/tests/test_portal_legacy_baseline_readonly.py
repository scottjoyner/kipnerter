import unittest

from scripts.portal_legacy_baseline_readonly import (
    EXPECTED,VOLUMES,qualified,match_mounts,
)


def fixtures():
    records={}
    for role in EXPECTED:
        records[role]={
            "running":True,"image":"sha256:"+"a"*64,
            "project":"kipnerter","service":role.replace("kipnerter-",""),
            "working_directory":"/opt/kipnerter",
        }
    mounts={
        name:[{"Type":"volume","Destination":target,
               "Name":"kipnerter_"+suffix,"RW":True}]
        for name,(suffix,target) in VOLUMES.items()
    }
    source={"private_env_0600_or_more_restrictive":True,
            "docker-compose.yml":"b"*64,
            "compose.spatial.yml":"c"*64,"stage_present":True}
    return records,mounts,source


class LegacyBaselineTests(unittest.TestCase):
    def test_verified_legacy_never_authorizes_cutover(self):
        records,mounts,source=fixtures()
        report=qualified(records,mounts,source,True,False)
        self.assertEqual(report["running_compose_containers_verified"],7)
        self.assertTrue(report["candidate_ready_for_independent_review"])
        self.assertEqual(len(report["container_image_service_fingerprint_sha256"]),64)
        self.assertFalse(report["backup_independent_custody"])
        self.assertFalse(report["safe_to_cutover"])

    def test_missing_running_gateway_refuses(self):
        records,mounts,source=fixtures()
        del records["kipnerter-api-1"]
        report=qualified(records,mounts,source,True,False)
        self.assertFalse(report["candidate_ready_for_independent_review"])
        self.assertIn("kipnerter-api-1",report["missing_container_roles"])

    def test_mutated_image_identity_denied(self):
        records,mounts,source=fixtures()
        records["kipnerter-web-1"]["image"]="latest"
        report=qualified(records,mounts,source,True,False)
        self.assertFalse(report["candidate_ready_for_independent_review"])
        self.assertIn("kipnerter-web-1_COMPOSE_IDENTITY",report["invalid_checks"])

    def test_other_project_directory_denied(self):
        records,mounts,source=fixtures()
        records["kipnerter-caddy-1"]["working_directory"]="/tmp/unapproved"
        report=qualified(records,mounts,source,True,False)
        self.assertFalse(report["candidate_ready_for_independent_review"])

    def test_state_volume_bind_rejected(self):
        records,mounts,source=fixtures()
        mounts["kipnerter-spatial-minio-1"][0]["Type"]="bind"
        report=qualified(records,mounts,source,True,False)
        self.assertIn("kipnerter-spatial-minio-1_STATE_VOLUME_UNQUALIFIED",
                      report["invalid_checks"])

    def test_duplicate_state_mount_denied(self):
        records,mounts,source=fixtures()
        mounts["kipnerter-spatial-postgres-1"].append(
            mounts["kipnerter-spatial-postgres-1"][0].copy())
        self.assertFalse(qualified(records,mounts,source,True,False)
                         ["candidate_ready_for_independent_review"])

    def test_missing_prior_state_receipt_denied(self):
        records,mounts,source=fixtures()
        self.assertFalse(qualified(records,mounts,source,False,False)
                         ["candidate_ready_for_independent_review"])

    def test_staged_source_absent_denied(self):
        records,mounts,source=fixtures()
        source["stage_present"]=False
        self.assertFalse(qualified(records,mounts,source,True,False)
                         ["candidate_ready_for_independent_review"])

    def test_unsafe_private_env_denied(self):
        records,mounts,source=fixtures()
        source["private_env_0600_or_more_restrictive"]=False
        report=qualified(records,mounts,source,True,False)
        self.assertIn("LEGACY_PRIVATE_ENV_PERMISSIONS",report["invalid_checks"])

    def test_managed_link_not_forged_into_legacy(self):
        records,mounts,source=fixtures()
        report=qualified(records,mounts,source,True,True)
        self.assertFalse(report["candidate_ready_for_independent_review"])
        self.assertIn("LEGACY_MANAGED_POINTER_ALREADY_PRESENT",report["invalid_checks"])

if __name__=="__main__":
    unittest.main()
