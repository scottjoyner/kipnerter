import io
import tarfile
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.portal_state_snapshot_once import (
    sha256_file, inspect_tar, snapshot, ensure_private, SOURCE_SHA,
)


class GuardedSnapshotTests(unittest.TestCase):
    def tar(self, root, *, name="data/payload.txt", contents=b"sample"):
        path = root/"safe.tar"
        with tarfile.open(path,"w:") as tar:
            info=tarfile.TarInfo(name)
            info.size=len(contents)
            tar.addfile(info,io.BytesIO(contents))
            info2=tarfile.TarInfo("data/second")
            info2.size=1
            tar.addfile(info2,io.BytesIO(b"x"))
        return path

    def test_tar_digest_and_payload_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=self.tar(root)
            digest,size=sha256_file(path)
            self.assertEqual(len(digest),64)
            self.assertEqual(size,path.stat().st_size)
            count,payload=inspect_tar(path)
            self.assertEqual((count,payload),(2,7))

    def test_traversal_tar_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=self.tar(root,name="../../etc/passwd")
            with self.assertRaisesRegex(ValueError,"unsafe"):
                inspect_tar(path)

    def test_absolute_tar_path_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=self.tar(root,name="/root/secret")
            with self.assertRaisesRegex(ValueError,"unsafe"):
                inspect_tar(path)

    def test_symlink_tar_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/"symlink.tar"
            with tarfile.open(path,"w:") as tar:
                item=tarfile.TarInfo("data/linked")
                item.type=tarfile.SYMTYPE
                item.linkname="/etc/shadow"
                tar.addfile(item)
                other=tarfile.TarInfo("data/second")
                other.size=1
                tar.addfile(other,io.BytesIO(b"x"))
            with self.assertRaisesRegex(ValueError,"unsafe"):
                inspect_tar(path)

    def test_missing_verified_source_denied_before_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)/"private"
            base.mkdir(mode=0o700)
            with patch("scripts.portal_state_snapshot_once.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError,"not privately staged"):
                    snapshot(base,staged=Path(directory)/"not-staged")
                run.assert_not_called()

    def test_no_reuse_of_one_shot_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            backup=root/"backup"
            backup.mkdir(mode=0o700)
            expected=backup/("ios17-precutover-"+SOURCE_SHA[:12])
            expected.mkdir()
            staged=root/"staged"
            (staged/"gateway-api").mkdir(parents=True)
            (staged/"gateway-api/Dockerfile").write_text("FROM scratch")
            (staged/".portal-staged.json").write_text("{}")
            with patch("scripts.portal_state_snapshot_once.shutil.disk_usage") as disk:
                disk.return_value=type("Disk",(),{"free":20*1024**3})()
                with patch("scripts.portal_state_snapshot_once.subprocess.run") as run:
                    with self.assertRaises(FileExistsError):
                        snapshot(backup,staged=staged)
                    run.assert_not_called()

    def test_private_dir_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            inside=root/"real";inside.mkdir()
            shortcut=root/"shortcut";shortcut.symlink_to(inside)
            with self.assertRaisesRegex(ValueError,"not private"):
                ensure_private(shortcut)


if __name__ == "__main__":
    unittest.main()
