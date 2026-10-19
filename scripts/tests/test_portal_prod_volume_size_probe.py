import unittest
from scripts.portal_prod_volume_size_probe import parse_du,check_capacity

GIB=1024**3

class VolumeSizeTests(unittest.TestCase):
    def test_valid_aggregate_du_output(self):
        self.assertEqual(parse_du("12345\t/data", "/data"), 12345*1024)

    def test_refuse_mismatched_or_hostile_du_output(self):
        for value in ("", "0 /data", "123 /other", "-1 /data",
                      "123 /data\n123 /etc/shadow", "abc /data", "123 /data;id"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_du(value,"/data")

    def test_local_capacity_is_not_restore_authorization(self):
        result=check_capacity(1*GIB,1*GIB,68*GIB)
        self.assertTrue(result["conservative_local_backup_capacity"])
        self.assertFalse(result["backup_written"])
        self.assertFalse(result["safe_to_cutover"])
        self.assertFalse(result["external_backup_custody_verified"])

    def test_insufficient_local_space_is_explicit_no_go(self):
        result=check_capacity(10*GIB,35*GIB,68*GIB)
        self.assertFalse(result["conservative_local_backup_capacity"])
        self.assertFalse(result["safe_to_cutover"])

    def test_reject_negative_size(self):
        with self.assertRaises(ValueError):
            check_capacity(-1,1024,2*GIB)

if __name__=="__main__":
    unittest.main()
