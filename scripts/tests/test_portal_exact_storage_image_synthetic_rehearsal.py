"""Offline deny-only controls. Never starts a Docker container or reads prod."""
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import portal_exact_storage_image_synthetic_rehearsal as m


class ExactStorageSyntheticSafety(unittest.TestCase):
    def test_expected_images_are_exactly_the_running_production_ids(self):
        self.assertEqual(set(m.IMAGES), {"postgres", "minio"})
        for tag, ident in m.IMAGES.values():
            self.assertTrue(ident.startswith("sha256:"))
            self.assertEqual(len(ident),71)
            self.assertTrue(tag.endswith(("16-3.4", ":latest")))

    def test_postgres_argv_isolated_and_rootless(self):
        a=m.args_for("postgres","safe-scratch","syntheticuser","syntheticpasswd")
        self.assertTrue(m.validate_argv(a) is None)
        self.assertIn("999:999",a)
        self.assertIn("--read-only",a)
        self.assertEqual(a[a.index("--network")+1],"none")
        self.assertTrue(all(v not in a for v in ("--privileged", "-v", "--publish", "-p")))

    def test_minio_argv_isolated_and_exact_pinned_image(self):
        a=m.args_for("minio","safe-scratch","syntheticuser","syntheticpasswd")
        self.assertTrue(m.validate_argv(a) is None)
        self.assertEqual(a[a.index("--user")+1],"10001:10001")
        self.assertEqual(a[a.index("--network")+1],"none")
        self.assertEqual(a.count("--tmpfs"),2)
        self.assertEqual(a[a.index("--rm")+1],"-d")
        self.assertIn(m.IMAGES['minio'][1],a)

    def test_injected_exposure_and_mounts_denied(self):
        for bad in (("-p","9090:9000"), ("--volume","/production:/data"),
                    ("--mount","type=bind,src=/,dst=/data"),
                    ("--privileged",), ("--network=host",), ("--publish=9000",)):
            with self.subTest(bad=bad):
                args=m.args_for("minio","safe-scratch","user","pwd")+list(bad)
                with self.assertRaises(ValueError):m.validate_argv(args)

    def test_removed_security_flag_denied(self):
        for which in ("--network", "--read-only", "--cap-drop", "--security-opt", "--pids-limit"):
            with self.subTest(flag=which):
                args=m.args_for("postgres","safe-scratch","user","pwd")
                args.remove(which)
                with self.assertRaises(ValueError):m.validate_argv(args)

    def test_wrong_isolation_values_denied(self):
        for which,substitute in (("--network","bridge"),("--cap-drop","NONE"),
                                 ("--security-opt","seccomp:unconfined")):
            with self.subTest(flag=which):
                args=m.args_for("postgres","safe-scratch","user","pwd")
                args[args.index(which)+1]=substitute
                with self.assertRaises(ValueError):m.validate_argv(args)

    def test_duplicate_security_flag_denied(self):
        a=m.args_for('postgres','safe-scratch','user','pwd')
        for duplicate in (['--network','host'], ['--cap-drop','NONE'],
                          ['--user','0:0']):
            with self.subTest(duplicate=duplicate):
                with self.assertRaises(ValueError):m.validate_argv(a+duplicate)

    def test_failed_post_start_inspection_removes_exact_container_id(self):
        cid='e'*64
        with patch.object(m,'call',return_value=(cid+'\n').encode()), \
             patch.object(m,'inspect_container',side_effect=ValueError('denied')), \
             patch.object(m,'remove') as cleanup:
            with self.assertRaises(ValueError):
                m.start('postgres','safe-scratch','syntheticuser','syntheticpwd')
        cleanup.assert_called_once_with(cid)

    def test_mutated_running_image_fails_closed(self):
        with patch.object(m,'call',return_value=b'sha256:'+b'0'*64+b'\n'):
            self.assertFalse(m.image_ready('minio'))
        with patch.object(m,'call',side_effect=ValueError('synthetic')):
            self.assertFalse(m.image_ready('postgres'))

    def test_runtime_docker_inspect_rejects_wrong_image_network_and_mount(self):
        import copy
        expected={"Image":m.IMAGES['minio'][1],"HostConfig":{
            "NetworkMode":"none","ReadonlyRootfs":True,"Privileged":False,
            "PortBindings":{},"CapDrop":["ALL"],"PidsLimit":128,
            "SecurityOpt":["no-new-privileges:true"]},"Mounts":[]}
        with patch.object(m,'call',return_value=json.dumps([expected]).encode()):
            m.inspect_container('synthetic-id','minio')
        bad=[lambda x:x.update(Image=m.IMAGES['postgres'][1]),
             lambda x:x['HostConfig'].update(NetworkMode='host'),
             lambda x:x['HostConfig'].update(ReadonlyRootfs=False),
             lambda x:x['HostConfig'].update(Privileged=True),
             lambda x:x['HostConfig'].update(PortBindings={'9000/tcp':[{}]}),
             lambda x:x['HostConfig'].update(CapDrop=[]),
             lambda x:x['HostConfig'].update(PidsLimit=100000),
             lambda x:x['HostConfig'].update(PidsLimit=0),
             lambda x:x['HostConfig'].update(SecurityOpt=[]),
             lambda x:x['Mounts'].append({'Type':'volume','Destination':'/data'}),
             lambda x:x['Mounts'].append({'Type':'bind','Destination':'/data'})]
        for change in bad:
            with self.subTest(change=change):
                item=copy.deepcopy(expected);change(item)
                with patch.object(m,'call',return_value=json.dumps([item]).encode()):
                    with self.assertRaises(ValueError):m.inspect_container('synthetic-id','minio')

    def test_default_is_deny_only_and_does_not_touch_docker(self):
        out=io.StringIO()
        with patch('sys.argv',['probe']), patch.object(m,'call',side_effect=AssertionError('Docker called')),redirect_stdout(out):
            self.assertEqual(m.main(),3)
        state=json.loads(out.getvalue())
        self.assertEqual(state['release_gate'],'NO_GO')
        self.assertFalse(state['executable_proof'])
        self.assertFalse(state['production_modified'])

    def test_other_host_cannot_start_scratch(self):
        out=io.StringIO()
        with patch('sys.argv',['probe','--execute']), patch.object(m.socket,'gethostname',return_value='kipnerter-prod-01'),patch.object(m,'call',side_effect=AssertionError('Docker called')),redirect_stdout(out):
            self.assertEqual(m.main(),3)
        self.assertEqual(json.loads(out.getvalue())['state'],'DENIED_NOT_ALLOWLISTED_TEST_HOST')

    def test_missing_image_fails_closed_before_any_docker_run(self):
        out=io.StringIO()
        with patch('sys.argv',['probe','--execute']),patch.object(m.socket,'gethostname',return_value=m.HOST),patch.object(m,'image_ready',return_value=False),patch.object(m,'start',side_effect=AssertionError('started a container')),redirect_stdout(out):
            self.assertEqual(m.main(),2)
        state=json.loads(out.getvalue())
        self.assertEqual(state['release_gate'],'NO_GO')
        self.assertFalse(state['production_data_restored'])
        self.assertFalse(state['safe_to_cutover'])

    def test_cleanup_on_postgres_failure(self):
        with patch.object(m,'start',return_value='a'*64),patch.object(m,'call',side_effect=ValueError('failed')),patch.object(m.time,'sleep',return_value=None),patch.object(m,'remove') as cleanup:
            with self.assertRaises(ValueError):m.postgres_synthetic()
        cleanup.assert_called_once_with('a'*64)

    def test_cleanup_both_minio_containers_when_probe_fails(self):
        with patch.object(m,'start',side_effect=['a'*64,'b'*64]),patch.object(m,'call',side_effect=ValueError('failed')),patch.object(m.time,'sleep',return_value=None),patch.object(m,'remove') as cleanup:
            with self.assertRaises(ValueError):m.minio_synthetic()
        self.assertEqual(cleanup.call_count,2)


if __name__=='__main__':unittest.main()
