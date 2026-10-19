import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from scripts.portal_prod_layout_inventory import analyze

class ProductionLayoutTests(unittest.TestCase):
    def test_empty_tree_is_no_go(self):
        with tempfile.TemporaryDirectory() as d:
            r=analyze(Path(d),disk=SimpleNamespace(free=8*1024**3))
            self.assertEqual(r["current_entry_kind"],"missing")
            self.assertFalse(r["safe_to_cutover"])
            self.assertFalse(r["data_restore_verified"])

    def test_legacy_directory_not_promoted_implicitly(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/"current").mkdir()
            r=analyze(p,disk=SimpleNamespace(free=8*1024**3))
            self.assertEqual(r["current_entry_kind"],"directory")
            self.assertFalse(r["managed_pointer_present"])

    def test_managed_symlink_does_not_prove_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/"releases").mkdir();(p/"releases"/"123").mkdir()
            (p/"current").symlink_to(p/"releases"/"123")
            r=analyze(p,disk=SimpleNamespace(free=8*1024**3))
            self.assertTrue(r["managed_pointer_present"])
            self.assertFalse(r["safe_to_cutover"])

    def test_disk_space_is_not_safe_to_cutover(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            r=analyze(p,disk=SimpleNamespace(free=1*1024**3))
            self.assertFalse(r["sufficient_disk_for_snapshot"])
            self.assertFalse(r["safe_to_cutover"])

if __name__=="__main__":
    unittest.main()
