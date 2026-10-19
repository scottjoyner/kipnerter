import unittest
import contextlib
import io
import json
import subprocess
from unittest.mock import patch
from scripts.portal_legacy_image_retention_preflight import (
    EXPECTED,MAX_IMAGE_BYTES,MIN_REMAINING_BYTES,validate,main
)


def examples():
    containers={}
    images={}
    for index,name in enumerate(EXPECTED):
        identity="sha256:"+format(index+1,"064x")
        containers[name]={
            "running":True,"image":identity,
            "project":"kipnerter","working_dir":"/opt/kipnerter",
            "service":name.removeprefix("kipnerter-"),
        }
        images[identity]=125*1024**2
    return containers,images


class ImageRetentionTests(unittest.TestCase):
    def test_valid_host_only_informs_capacity(self):
        c,i=examples()
        x=validate(c,i,68*1024**3)
        self.assertEqual(x["expected_live_roles_verified"],7)
        self.assertEqual(x["unique_images_present"],7)
        self.assertTrue(x["conservative_local_image_retention_capacity"])
        self.assertEqual(len(x["image_service_baseline_fingerprint_sha256"]),64)
        self.assertFalse(x["image_archive_created"])
        self.assertFalse(x["safe_to_cutover"])

    def test_missing_running_container_rejected(self):
        c,i=examples()
        c.pop(next(iter(c)))
        with self.assertRaisesRegex(ValueError,"container"):
            validate(c,i,68*1024**3)

    def test_stopped_current_container_rejected(self):
        c,i=examples()
        c[EXPECTED[0]]["running"]=False
        with self.assertRaisesRegex(ValueError,"identity"):
            validate(c,i,68*1024**3)

    def test_cross_project_container_rejected(self):
        c,i=examples()
        c[EXPECTED[1]]["project"]="unapproved"
        with self.assertRaisesRegex(ValueError,"identity"):
            validate(c,i,68*1024**3)

    def test_image_tag_instead_of_digest_rejected(self):
        c,i=examples()
        c[EXPECTED[2]]["image"]="latest"
        with self.assertRaisesRegex(ValueError,"identity"):
            validate(c,i,68*1024**3)

    def test_missing_image_content_rejected(self):
        c,i=examples()
        i.pop(next(iter(i)))
        with self.assertRaisesRegex(ValueError,"missing image"):
            validate(c,i,68*1024**3)

    def test_large_image_declined(self):
        c,i=examples()
        i[next(iter(i))]=MAX_IMAGE_BYTES+1
        with self.assertRaisesRegex(ValueError,"disk-size"):
            validate(c,i,68*1024**3)

    def test_insufficient_free_space_stays_unqualified(self):
        c,i=examples()
        x=validate(c,i,MIN_REMAINING_BYTES+1)
        self.assertFalse(x["conservative_local_image_retention_capacity"])
        self.assertFalse(x["safe_to_cutover"])

    def test_duplicate_layer_identity_not_double_counted(self):
        c,i=examples()
        identity=c[EXPECTED[0]]["image"]
        old=c[EXPECTED[1]]["image"]
        c[EXPECTED[1]]["image"]=identity
        i.pop(old)
        x=validate(c,i,68*1024**3)
        self.assertEqual(x["unique_images_present"],6)


    def test_uncached_live_image_does_not_trigger_pull_or_export(self):
        calls=[]
        def fake_command(args, *, timeout=10):
            calls.append(args)
            if args[1]=="inspect":
                position=EXPECTED.index(args[-1])+1
                return ("true|sha256:"+format(position,"064x")+
                        "|kipnerter|/opt/kipnerter|worker")
            if args[1:3]==["image","inspect"]:
                if args[-1]=="sha256:"+format(1,"064x"):
                    raise subprocess.CalledProcessError(1,args)
                return args[-1]+"|125000000"
            raise AssertionError("unexpected Docker action")
        storage=type("Disk",(),{"free":68*1024**3})()
        with patch("scripts.portal_legacy_image_retention_preflight.command",
                   side_effect=fake_command), patch(
                   "scripts.portal_legacy_image_retention_preflight.shutil.disk_usage",
                   return_value=storage):
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                result=main()
        self.assertEqual(result,3)
        report=json.loads(out.getvalue())
        self.assertEqual(report["uncached_image_role_positions"],[1])
        self.assertEqual(report["unique_cached_image_ids"],6)
        self.assertFalse(report["image_archive_created"])
        self.assertFalse(report["safe_to_cutover"])
        self.assertNotIn("sha256:",out.getvalue())
        self.assertTrue(all(a[1:3] in (["image","inspect"],
                                       ["inspect","--format"]) for a in calls))

if __name__=="__main__":
    unittest.main()
