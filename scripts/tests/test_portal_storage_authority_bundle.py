"""Offline contract: bundle emits exact source, but never executes Docker/SSH itself."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from scripts import portal_storage_authority_bundle as m

class BundleControls(unittest.TestCase):
    def test_default_does_not_emit_or_connect(self):
        p=subprocess.run([sys.executable,str(m.ROOT/"portal_storage_authority_bundle.py")],
                         capture_output=True,text=True,timeout=4)
        self.assertEqual(p.returncode,3)
        self.assertEqual(json.loads(p.stdout)["status"],"DRY_RUN_NO_SSH_OR_DOCKER")

    def test_bundle_has_no_runtime_secret_literals(self):
        output=m.emit()
        self.assertIn("pinned_writer_surface",output)
        self.assertIn("pinned_storage_authority",output)
        self.assertNotIn("KIPNERTER_SPATIAL_DB_PASSWORD",output)
        self.assertNotIn("MINIO_ROOT_PASSWORD",output)

    def test_emitted_default_stays_fail_closed(self):
        proc=subprocess.run([sys.executable,"-"],input=m.emit(),
                            capture_output=True,text=True,timeout=8)
        self.assertEqual(proc.returncode,3)
        self.assertEqual(json.loads(proc.stdout)["status"],"DRY_RUN_NO_DOCKER_OR_SQL")

    def test_only_exact_two_inputs(self):
        self.assertEqual(len(m.FILES),2)
        self.assertEqual(m.FILES[0].name,"portal_production_writer_surface_readonly.py")
        self.assertEqual(m.FILES[1].name,"portal_production_storage_authority_readonly.py")
