"""Synthetic production writer-surface controls. No real Docker/SSH."""
import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import portal_production_writer_surface_readonly as w


def fixture(*,extra=False):
    names=sorted(w.EXPECTED)
    if extra:names.append('unreviewed-background-writer')
    output=[]
    for i,name in enumerate(names):
        nets={w.FRONTEND:{}} if name in {'kipnerter-api-1','kipnerter-web-1','kipnerter-caddy-1'} else {w.SPATIAL:{}}
        if name in {'kipnerter-spatial-api-1',w.MINIO}:nets={w.FRONTEND:{},w.SPATIAL:{}}
        ident=w.IMAGE.get(name,'sha256:'+'a'*64)
        client=(name in {'kipnerter-spatial-api-1','kipnerter-spatial-worker-1'})
        configured=['KIPNERTER_DATABASE_URL=synthetic-db-url',
                    'KIPNERTER_S3_ACCESS_KEY_ID=synthetic-access-key',
                    'KIPNERTER_S3_SECRET_ACCESS_KEY=synthetic-secret'] if client else []
        output.append({'Id':f'{i+1:064x}','Name':'/'+name,'Image':ident,
                       'State':{'Running':True},'NetworkSettings':{'Networks':nets},
                       'Config':{'Env':['DATABASE_PASSWORD=NEVER_OUTPUT','S3_SECRET_ACCESS_KEY=NEVER_OUTPUT',*configured]},
                       'HostConfig':{'NetworkMode':'kipnerter_spatial_backend','Privileged':False},
                       'Mounts':([
                           {'Type':'volume','Source':('/var/lib/docker/volumes/'+name+'/_data'),
                            'Destination':'/data','RW':True}]
                         if name in {w.POSTGRES,w.MINIO} else [])})
    return output


class WriterSurfaceSafety(unittest.TestCase):
    def test_approved_expected_containers_fixed(self):
        self.assertEqual(len(w.EXPECTED),7)
        self.assertEqual(set(w.IMAGE),{w.POSTGRES,w.MINIO})
        self.assertTrue(all(len(i)==71 and i.startswith('sha256:') for i in w.IMAGE.values()))

    def test_default_invokes_no_docker(self):
        out=io.StringIO()
        with patch('sys.argv',['read_only']),patch.object(w,'collect',side_effect=AssertionError('docker called')),redirect_stdout(out):
            self.assertEqual(w.main(),3)
        result=json.loads(out.getvalue())
        self.assertEqual(result['release_gate'],'NO_GO')
        self.assertFalse(result['production_modified'])

    def test_only_exact_production_host_may_inspect(self):
        out=io.StringIO()
        with patch('sys.argv',['read_only','--inspect-live']),patch.object(w.socket,'gethostname',return_value='x1-370'),patch.object(w,'collect',side_effect=AssertionError('docker called')),redirect_stdout(out):
            self.assertEqual(w.main(),3)
        self.assertEqual(json.loads(out.getvalue())['status'],'HOLD_HOST_NOT_PRODUCTION')

    def test_exact_live_topology_does_not_assert_fencing(self):
        report=w.analyze(fixture())
        self.assertEqual(report['status'],'WRITER_SURFACE_READ_ONLY_OBSERVED_NOT_FENCED')
        self.assertEqual(report['running_containers'],7)
        self.assertTrue(report['minio_frontend_network_present'])
        self.assertTrue(report['postgres_spatial_internal_network_present'])
        self.assertEqual(report['extra_unreviewed_containers'],[])
        self.assertEqual(report['postgres_network_peers_with_client_credentials'],['kipnerter-spatial-api-1','kipnerter-spatial-worker-1'])
        self.assertEqual(report['minio_network_peers_with_client_credentials'],['kipnerter-spatial-api-1','kipnerter-spatial-worker-1'])
        self.assertFalse(report['server_side_write_authorization_verified'])
        self.assertFalse(report['other_storage_credential_paths_excluded'])
        self.assertEqual(report['missing_expected_containers'],[])
        self.assertEqual(report['release_gate'],'NO_GO')
        for k in ('postgres_writes_fenced','minio_writes_fenced','storage_clients_admission_revoked',
                  'writer_credentials_revoked','network_access_fenced','running_clients_drained',
                  'atomic_multi_service_checkpoint_proven','independent_administrative_custody',
                  'safe_to_cutover','production_modified'):
            self.assertFalse(report[k],k)
        self.assertNotIn('NEVER_OUTPUT',json.dumps(report))

    def test_expected_runtime_mount_shape_is_not_a_storage_write_fence(self):
        output=w.analyze(fixture())
        self.assertTrue(output['runtime_mount_namespace_inventory_complete'])
        for field in ('direct_storage_mount_candidates','docker_control_socket_candidates',
                      'host_network_candidates','privileged_runtime_candidates',
                      'nonstorage_bind_mount_candidates'):
            self.assertEqual(output[field],[])
        self.assertFalse(output['noncontainer_external_writers_excluded'])
        self.assertFalse(output['atomic_multi_service_checkpoint_proven'])

    def test_shared_storage_volume_is_hold_and_source_path_never_printed(self):
        items=fixture()
        storage=next(x for x in items if x['Name']=='/'+w.MINIO)
        worker=next(x for x in items if x['Name']=='/kipnerter-spatial-worker-1')
        mount=dict(storage['Mounts'][0]);mount['Destination']='/mnt/other';mount['RW']=False
        worker['Mounts'].append(mount)
        output=w.analyze(items)
        self.assertEqual(output['status'],'HOLD_UNEXPECTED_WRITER_SURFACE')
        self.assertEqual(output['direct_storage_mount_candidates'],['kipnerter-spatial-worker-1'])
        self.assertNotIn(mount['Source'],json.dumps(output))
        self.assertFalse(output['minio_writes_fenced'])

    def test_storage_parent_and_child_bind_aliases_hold_even_if_readonly(self):
        for changed in ('/var/lib/docker',
                        '/var/lib/docker/volumes/kipnerter-spatial-minio-1/_data/subdir',
                        '/var/lib/docker/volumes'):
            items=fixture()
            worker=next(o for o in items if o['Name']=='/kipnerter-spatial-worker-1')
            worker['Mounts'].append({'Type':'bind','Source':changed,
                                     'Destination':'/mnt/private','RW':False})
            with self.subTest(source_kind=changed.rsplit('/',1)[-1]):
                report=w.analyze(items)
                self.assertEqual(report['status'],'HOLD_UNEXPECTED_WRITER_SURFACE')
                self.assertIn('kipnerter-spatial-worker-1',report['direct_storage_mount_candidates'])
                self.assertNotIn(changed,json.dumps(report))
                self.assertFalse(report['minio_writes_fenced'])

    def test_nonoverlapping_prefix_is_not_misclassified_as_shared_storage(self):
        original='/var/lib/docker/volumes/kipnerter-spatial-minio-1/_data'
        similar=original+'-unrelated'
        self.assertFalse(w.paths_overlap(original,similar))
        items=fixture()
        worker=next(o for o in items if o['Name']=='/kipnerter-spatial-worker-1')
        worker['Mounts'].append({'Type':'bind','Source':similar,
                                 'Destination':'/mnt/not-the-same','RW':False})
        result=w.analyze(items)
        self.assertEqual(result['direct_storage_mount_candidates'],[])
        # A new bind mount still demands operator review independently.
        self.assertEqual(result['status'],'HOLD_UNEXPECTED_WRITER_SURFACE')

    def test_untrusted_mount_path_segments_fail_closed(self):
        for source in ('relative/path','/var//lib/docker','/var/lib/../docker',
                       '/var/lib/./docker','/var/lib/docker/','/var/lib/\x00docker',
                       '/var/lib/docker/../secrets'):
            items=fixture()
            worker=next(o for o in items if o['Name']=='/kipnerter-spatial-worker-1')
            worker['Mounts'].append({'Type':'bind','Source':source,
                                     'Destination':'/mnt/safe','RW':True})
            with self.subTest(source_kind=source[:10]),self.assertRaisesRegex(ValueError,'untrusted runtime mount path'):
                w.analyze(items)

    def test_shared_storage_type_alias_still_hold(self):
        items=fixture()
        storage=next(o for o in items if o['Name']=='/'+w.MINIO)
        worker=next(o for o in items if o['Name']=='/kipnerter-spatial-worker-1')
        worker['Mounts'].append({'Type':'bind','Source':storage['Mounts'][0]['Source'],
                                 'Destination':'/mnt/alternate','RW':True})
        report=w.analyze(items)
        self.assertIn('kipnerter-spatial-worker-1',report['direct_storage_mount_candidates'])
        self.assertEqual(report['status'],'HOLD_UNEXPECTED_WRITER_SURFACE')

    def test_docker_socket_mount_is_critical_holding_candidate(self):
        items=fixture()
        worker=next(x for x in items if x['Name']=='/kipnerter-spatial-worker-1')
        worker['Mounts'].append({'Type':'bind','Source':'/var/run/docker.sock',
                                 'Destination':'/var/run/docker.sock','RW':True})
        output=w.analyze(items)
        self.assertEqual(output['status'],'HOLD_UNEXPECTED_WRITER_SURFACE')
        self.assertEqual(output['docker_control_socket_candidates'],['kipnerter-spatial-worker-1'])
        self.assertNotIn('/var/run/docker.sock',json.dumps(output))

    def test_host_network_privileged_and_unknown_binds_are_hold(self):
        for mutate,field in (
            (lambda o:o['HostConfig'].update(NetworkMode='host'),'host_network_candidates'),
            (lambda o:o['HostConfig'].update(Privileged=True),'privileged_runtime_candidates'),
            (lambda o:o['Mounts'].append({'Type':'bind','Source':'/srv/secret/real-path',
                                          'Destination':'/opt/access','RW':False}),
             'nonstorage_bind_mount_candidates'),
        ):
            items=fixture()
            worker=next(x for x in items if x['Name']=='/kipnerter-spatial-worker-1')
            mutate(worker)
            output=w.analyze(items)
            self.assertEqual(output['status'],'HOLD_UNEXPECTED_WRITER_SURFACE')
            self.assertIn('kipnerter-spatial-worker-1',output[field])
            self.assertNotIn('/srv/secret/real-path',json.dumps(output))
            self.assertFalse(output['safe_to_cutover'])

    def test_privileged_or_host_mode_storage_services_are_hold(self):
        for field,val,key in (('Privileged',True,'privileged_runtime_candidates'),
                              ('NetworkMode','host','host_network_candidates')):
            items=fixture()
            storage=next(x for x in items if x['Name']=='/'+w.MINIO)
            storage['HostConfig'][field]=val
            report=w.analyze(items)
            self.assertEqual(report['status'],'HOLD_UNEXPECTED_WRITER_SURFACE')
            self.assertIn(w.MINIO,report[key])

    def test_unknown_mounts_or_untrusted_runtime_metadata_are_denied(self):
        for corrupt in (
            lambda o:o.pop('Mounts'),
            lambda o:o['Mounts'].append({'Type':'invalid','Source':'/tmp',
                                          'Destination':'/data','RW':True}),
            lambda o:o['Mounts'].append({'Type':'bind','Source':'/tmp',
                                          'Destination':'../bad','RW':True}),
            lambda o:o['Mounts'].append({'Type':'bind','Source':'/tmp',
                                          'Destination':'/data','RW':'false'}),
            lambda o:o.pop('HostConfig'),
            lambda o:o['HostConfig'].update(NetworkMode=None),
            lambda o:o['HostConfig'].update(Privileged='false'),
        ):
            items=fixture()
            worker=next(x for x in items if x['Name']=='/kipnerter-spatial-worker-1')
            corrupt(worker)
            with self.subTest(corrupt=str(corrupt)),self.assertRaises((ValueError,TypeError)):
                w.analyze(items)

    def test_unexpected_shared_storage_identifiers_are_denied(self):
        items=fixture()
        storage=next(x for x in items if x['Name']=='/'+w.MINIO)
        storage['Mounts'][0]['Source']='/protected/sensitive-secret-DO-NOT-PRINT'
        other=next(x for x in items if x['Name']=='/'+w.POSTGRES)
        other['Mounts'][0]['Source']=storage['Mounts'][0]['Source']
        with self.assertRaisesRegex(ValueError,'ambiguous storage mount'):
            w.analyze(items)

    def test_minio_frontend_exposes_multiple_potential_clients(self):
        report=w.analyze(fixture())
        self.assertIn('kipnerter-caddy-1',report['minio_network_client_candidates'])
        self.assertIn('kipnerter-web-1',report['minio_network_client_candidates'])
        self.assertIn('kipnerter-spatial-worker-1',report['postgres_network_client_candidates'])

    def test_missing_client_secret_fails_closed(self):
        for absent in ('KIPNERTER_DATABASE_URL','KIPNERTER_S3_SECRET_ACCESS_KEY',
                       'KIPNERTER_S3_ACCESS_KEY_ID'):
            with self.subTest(absent=absent):
                items=fixture()
                for obj in items:
                    if obj['Name']=='/kipnerter-spatial-worker-1':
                        obj['Config']['Env']=[e for e in obj['Config']['Env']
                                              if not e.startswith(absent+'=')]
                result=w.analyze(items)
                self.assertEqual(result['status'],'HOLD_UNEXPECTED_WRITER_SURFACE')
                self.assertFalse(result['safe_to_cutover'])

    def test_empty_client_secret_fails_closed(self):
        items=fixture()
        for obj in items:
            if obj['Name']=='/kipnerter-spatial-api-1':
                obj['Config']['Env']=[e.partition('=')[0]+'=' if e.startswith('KIPNERTER_DATABASE_URL=') else e
                                      for e in obj['Config']['Env']]
        result=w.analyze(items)
        self.assertEqual(result['status'],'HOLD_UNEXPECTED_WRITER_SURFACE')

    def test_environment_values_are_not_printed(self):
        items=fixture()
        report=w.analyze(items)
        raw=json.dumps(report)
        for secret in ('synthetic-secret','synthetic-access-key','synthetic-db-url',
                       'NEVER_OUTPUT','DATABASE_PASSWORD','S3_SECRET_ACCESS_KEY'):
            self.assertNotIn(secret,raw)
        self.assertTrue(report['storage_client_credential_presence_only'])
        self.assertFalse(report['server_side_write_authorization_verified'])

    def test_duplicate_environment_key_fails_closed(self):
        items=fixture()
        items[0]['Config']['Env']+=['DATABASE_PASSWORD=FAKE_OVERRIDE']
        with self.assertRaisesRegex(ValueError,'duplicates'):
            w.analyze(items)

    def test_malformed_environment_fields_fail_closed(self):
        for broken in (None,'string',[],['MISSING_EQUALS'],['=without_key'],
                       ['KIPNERTER_DATABASE_URL='+'X'*20000]):
            with self.subTest(broken=type(broken).__name__):
                items=fixture()
                items[0]['Config']['Env']=broken
                if broken == []:continue # empty Env is legal on unrelated services
                with self.assertRaises(ValueError):w.analyze(items)

    def test_unexpected_container_is_hold(self):
        report=w.analyze(fixture(extra=True))
        self.assertEqual(report['status'],'HOLD_UNEXPECTED_WRITER_SURFACE')
        self.assertEqual(report['extra_unreviewed_containers'],['unreviewed-background-writer'])
        self.assertFalse(report['safe_to_cutover'])

    def test_missing_required_worker_denies_clean_snapshot_claim(self):
        objs=[i for i in fixture() if i['Name']!='/kipnerter-spatial-worker-1']
        report=w.analyze(objs)
        self.assertEqual(report['status'],'HOLD_UNEXPECTED_WRITER_SURFACE')
        self.assertIn('kipnerter-spatial-worker-1',report['missing_expected_containers'])

    def test_image_identity_drift_rejected(self):
        objs=fixture()
        for i in objs:
            if i['Name']=='/'+w.MINIO:i['Image']='sha256:'+'f'*64
        with self.assertRaisesRegex(ValueError,'identity drift'):w.analyze(objs)

    def test_network_missing_rejected(self):
        objs=fixture()
        objs[0]['NetworkSettings']['Networks']=None
        with self.assertRaisesRegex(ValueError,'network inventory missing'):w.analyze(objs)

    def test_storage_network_lost_leaves_release_no_go(self):
        objs=fixture()
        for i in objs:
            if i['Name']=='/'+w.MINIO:i['NetworkSettings']['Networks']={'disconnected':{}}
        result=w.analyze(objs)
        self.assertEqual(result['status'],'HOLD_UNEXPECTED_WRITER_SURFACE')
        self.assertFalse(result['minio_frontend_network_present'])

    def test_duplicated_names_rejected(self):
        objs=fixture();objs[0]['Name']=objs[1]['Name']
        with self.assertRaisesRegex(ValueError,'ambiguous'):w.analyze(objs)

    def test_stop_or_exited_container_rejected(self):
        objs=fixture();objs[0]['State']['Running']=False
        with self.assertRaisesRegex(ValueError,'not all'):w.analyze(objs)

    def test_invalid_commands_not_allowed(self):
        for cmd in (['docker','stop',w.MINIO],['docker','exec',w.POSTGRES,'psql'],
                    ['docker','network','disconnect'],['docker','run','--rm'],
                    ['docker','inspect'],['docker','ps','-q']):
            with self.subTest(cmd=cmd),patch.object(w.subprocess,'run',side_effect=AssertionError('Docker called')):
                with self.assertRaises(ValueError):w.safe_docker(cmd)

    def test_ambiguous_or_partial_docker_response_fails_closed(self):
        ids=[f'{i+1:064x}' for i in range(7)]
        payload='\n'.join(ids)+'\n'
        incorrect=json.dumps(fixture()[:-1]).encode()
        def fake(cmd,**kwargs):
            result=payload.encode() if cmd==['docker','ps','--no-trunc','-q'] else incorrect
            return subprocess.CompletedProcess(cmd,0,stdout=result,stderr=b'')
        with self.assertRaisesRegex(ValueError,'ambiguous Docker inspect'):
            w.collect(runner=fake)

    def test_read_only_production_report_from_mock_commands(self):
        data=fixture()
        def fake(argv,**kwargs):
            if argv==['docker','ps','--no-trunc','-q']:
                body=('\n'.join(x['Id'] for x in data)+'\n').encode()
            else:
                self.assertEqual(argv[:3],['docker','inspect','--type=container'])
                body=json.dumps(data).encode()
            return subprocess.CompletedProcess(argv,0,stdout=body,stderr=b'')
        report=w.analyze(w.collect(runner=fake))
        self.assertEqual(report['status'],'WRITER_SURFACE_READ_ONLY_OBSERVED_NOT_FENCED')
        self.assertFalse(report['atomic_multi_service_checkpoint_proven'])

    def test_internal_exception_output_sanitized(self):
        out=io.StringIO()
        with patch('sys.argv',['read_only','--inspect-live']), \
             patch.object(w.socket,'gethostname',return_value=w.HOST), \
             patch.object(w,'collect',side_effect=ValueError('SECRET_SHOULD_NOT_ESCAPE')), \
             redirect_stdout(out):
            self.assertEqual(w.main(),2)
        self.assertNotIn('SECRET_SHOULD_NOT_ESCAPE',out.getvalue())
        self.assertEqual(json.loads(out.getvalue())['status'],'HOLD')

if __name__=='__main__':unittest.main()
