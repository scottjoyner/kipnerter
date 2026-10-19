import unittest
from scripts.portal_legacy_image_retention_preflight import (
    EXPECTED,MAX_IMAGE_BYTES,MIN_REMAINING_BYTES,validate
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

if __name__=="__main__":
    unittest.main()
