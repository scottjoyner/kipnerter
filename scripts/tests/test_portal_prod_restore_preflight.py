"""Negative controls for read-only Kipnerter production restore preflight."""
import unittest

from scripts.portal_prod_restore_preflight import (
    classify, mount_state, select_containers, POSTGRES_TARGET, MINIO_TARGET,
)


def fixtures():
    containers = [
        {"name":"kipnerter-spatial-postgres-1","running":True},
        {"name":"kipnerter-spatial-minio-1","running":True},
        {"name":"unrelated-service","running":True},
    ]
    mounts = {
        "postgres":[{"Destination": POSTGRES_TARGET,
                     "Type":"volume","Name":"kipnerter_spatial_postgres_data",
                     "RW":True}],
        "minio":[{"Destination":MINIO_TARGET,
                  "Type":"volume","Name":"kipnerter_spatial_minio_data",
                  "RW":True}],
    }
    binaries = {"pg_dump":True, "pg_restore":True, "minio":True,"mc":True}
    return containers,mounts,binaries


class RestorePreflightTests(unittest.TestCase):
    def test_healthy_mounts_never_imply_restore_go(self):
        rows,mounts,bins=fixtures()
        outcome=classify(rows,mounts,bins,68*1024**3,staged_source_exists=True)
        self.assertTrue(outcome["postgres_dump_binary_present"])
        self.assertTrue(outcome["free_disk_at_least_4gib"])
        self.assertFalse(outcome["postgres_backup_completed"])
        self.assertFalse(outcome["minio_backup_completed"])
        self.assertFalse(outcome["independent_backup_custody_verified"])
        self.assertFalse(outcome["safe_to_cutover"])

    def test_duplicate_prod_container_is_denied(self):
        rows,_,_=fixtures()
        with self.assertRaisesRegex(ValueError,"duplicate"):
            select_containers(rows+[rows[0]])

    def test_stopped_data_service_is_denied(self):
        rows,_,_=fixtures()
        rows[1]["running"]=False
        with self.assertRaisesRegex(ValueError,"running"):
            select_containers(rows)

    def test_data_bind_mount_cannot_replace_volume(self):
        _,mounts,_=fixtures()
        mounts["minio"][0]["Type"]="bind"
        with self.assertRaises(ValueError):
            mount_state(mounts["minio"],MINIO_TARGET,"spatial_minio_data")

    def test_wrong_destination_cannot_replace_postgres_volume(self):
        _,mounts,_=fixtures()
        mounts["postgres"][0]["Destination"]="/backup"
        with self.assertRaisesRegex(ValueError,"exactly one"):
            mount_state(mounts["postgres"],POSTGRES_TARGET,"spatial_postgres_data")

    def test_missing_minio_backup_client_is_explicitly_no_go(self):
        rows,mounts,bins=fixtures()
        bins["mc"]=False
        data=classify(rows,mounts,bins,68*1024**3,staged_source_exists=False)
        self.assertFalse(data["minio_backup_client_binary_present"])
        self.assertFalse(data["three_source_private_stage_present"])
        self.assertFalse(data["safe_to_cutover"])

    def test_low_disk_does_not_qualify_restore(self):
        rows,mounts,bins=fixtures()
        data=classify(rows,mounts,bins,1*1024**3,staged_source_exists=True)
        self.assertFalse(data["free_disk_at_least_4gib"])
        self.assertFalse(data["safe_to_cutover"])

    def test_volumes_not_registered_as_named_cannot_qualify(self):
        _,mounts,_=fixtures()
        mounts["postgres"][0]["Name"]="someone_else_pg"
        with self.assertRaises(ValueError):
            mount_state(mounts["postgres"],POSTGRES_TARGET,"spatial_postgres_data")


if __name__=="__main__":
    unittest.main()
