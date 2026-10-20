"""Reject altered production image references, mounts and rollback claims."""
import copy
import unittest

from scripts.portal_legacy_rootfs_export_preflight import (
    ROLES, MIN_FREE, validate,
)


def fixture():
    rows = {}
    cache = {}
    for name, (ref, image) in ROLES.items():
        rows[name] = {
            "running": True, "project": "kipnerter",
            "source_ref": ref, "image": image, "mount_count": 0,
            "rootfs_bytes": 188780544 if name.endswith("api-1") else 561524736,
            "writable_bytes": 954368 if name.endswith("api-1") else 2727936,
        }
        cache[name] = {
            "old_image_cached": False, "current_tag_present": True,
            "current_tag_image": "sha256:" + ("a" if name.endswith("api-1") else "b") * 64,
        }
    return rows, cache, 68 * 1024**3


class RootfsPreflightTests(unittest.TestCase):
    def test_valid_scoped_candidate_still_never_approves_release(self):
        rows, images, free = fixture()
        result = validate(rows, images, free)
        self.assertEqual(result["status"], "ROOTFS_EXPORT_FEASIBLE_ONLY")
        self.assertEqual(result["legacy_roles_verified"], 2)
        self.assertFalse(result["candidate_rootfs_export_created"])
        self.assertFalse(result["rootfs_export_equivalent_to_old_oci_image"])
        self.assertFalse(result["isolated_rollback_test_passed"])
        self.assertFalse(result["safe_to_cutover"])
        self.assertFalse(result["production_modified"])
        self.assertNotIn("7efc", str(result))

    def test_expected_original_image_ids_are_pinned(self):
        rows, images, free = fixture()
        for name in ROLES:
            with self.subTest(role=name):
                r = copy.deepcopy(rows)
                r[name]["image"] = "sha256:" + "c" * 64
                with self.assertRaises(ValueError):
                    validate(r, images, free)

    def test_changed_tag_or_mount_is_denied(self):
        for change in ("source_ref", "mount_count", "running", "project"):
            rows, images, free = fixture()
            first = next(iter(ROLES))
            rows[first][change] = {"source_ref": "another",
                                   "mount_count": 1, "running": False,
                                   "project": "other"}[change]
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(rows, images, free)

    def test_missing_role_or_unexpected_role_denied(self):
        rows, images, free = fixture()
        rows.pop(next(iter(rows)))
        with self.assertRaises(ValueError):
            validate(rows, images, free)
        rows, images, free = fixture()
        rows["unknown"] = {}
        with self.assertRaises(ValueError):
            validate(rows, images, free)

    def test_uncached_original_and_different_tag_are_required(self):
        for key, value in [("old_image_cached", True),
                           ("current_tag_present", False),
                           ("current_tag_image", "malformed")]:
            rows, images, free = fixture()
            first = next(iter(ROLES))
            images[first][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(rows, images, free)
        rows, images, free = fixture()
        first = next(iter(ROLES))
        images[first]["current_tag_image"] = rows[first]["image"]
        with self.assertRaises(ValueError):
            validate(rows, images, free)

    def test_free_space_and_rootfs_size_bounds(self):
        for invalid in [0, MIN_FREE - 1, "huge"]:
            rows, images, _ = fixture()
            with self.subTest(free=invalid), self.assertRaises(ValueError):
                validate(rows, images, invalid)
        for key, invalid in [("rootfs_bytes", 3 * 1024**3),
                             ("rootfs_bytes", 0),
                             ("writable_bytes", 700 * 1024**2),
                             ("writable_bytes", -1)]:
            rows, images, free = fixture()
            rows[next(iter(ROLES))][key] = invalid
            with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                validate(rows, images, free)

    def test_no_output_suggests_runnable_rollback(self):
        rows, images, free = fixture()
        report = validate(rows, images, free)
        for field in ("recovered_container_launch_metadata",
                      "source_archive_already_independently_verified",
                      "rootfs_export_equivalent_to_old_oci_image",
                      "isolated_rollback_test_passed", "safe_to_cutover"):
            self.assertIs(report[field], False)


if __name__ == "__main__":
    unittest.main()
