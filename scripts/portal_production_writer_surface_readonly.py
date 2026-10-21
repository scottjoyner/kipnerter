#!/usr/bin/env python3
"""Production writer-surface discovery ONLY. Never installs a write fence.

Run once over the approved read-only Tailscale SSH principal as:
  tailscale ssh kipnerter@100.82.144.33 'python3 - --inspect-live' < THIS_FILE

Output contains Docker service identities/network names and safety booleans,
never environment values, credentials, SQL rows or object contents. Absence
of a reader or a quiet window DOES NOT mean writers were fenced.
"""
from __future__ import annotations
import argparse
import json
import socket
import subprocess
import sys

HOST='kipnerter-prod-01'
EXPECTED={
 'kipnerter-spatial-api-1', 'kipnerter-spatial-worker-1',
 'kipnerter-spatial-postgres-1','kipnerter-spatial-minio-1',
 'kipnerter-api-1','kipnerter-web-1','kipnerter-caddy-1',
}
POSTGRES='kipnerter-spatial-postgres-1'
MINIO='kipnerter-spatial-minio-1'
IMAGE={
 POSTGRES:'sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5',
 MINIO:'sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e',
}
SPATIAL='kipnerter_spatial_backend'
FRONTEND='kipnerter_frontend'


def safe_docker(argv,*,runner=subprocess.run):
    if (not argv or argv[0]!='docker' or not
            (argv==['docker','ps','--no-trunc','-q'] or
             (argv[1:3]==['inspect','--type=container'] and len(argv)>3))):
        raise ValueError('only Docker ps/inspect read-only operations allowed')
    p=runner(argv,capture_output=True,timeout=12,check=False)
    if p.returncode or len(p.stdout)>2_000_000:
        raise ValueError('untrusted Docker read-only response')
    return p.stdout.decode('utf-8','strict')


def collect(*,runner=subprocess.run):
    identifiers=safe_docker(['docker','ps','--no-trunc','-q'],runner=runner).splitlines()
    if len(identifiers)<len(EXPECTED) or len(identifiers)>60 or len(set(identifiers))!=len(identifiers):
        raise ValueError('unexpected running container inventory')
    if not all(len(i)==64 and all(ch in '0123456789abcdef' for ch in i) for i in identifiers):
        raise ValueError('invalid Docker identity from ps')
    objects=json.loads(safe_docker(['docker','inspect','--type=container',*identifiers],runner=runner))
    if (not isinstance(objects,list) or len(objects)!=len(identifiers) or
            set(x.get('Id') for x in objects)!=set(identifiers)):
        raise ValueError('ambiguous Docker inspect inventory')
    return objects


def analyze(objects):
    if not isinstance(objects,list) or len(objects)>60:
        raise ValueError('invalid inventory')
    names={}
    for o in objects:
        if not isinstance(o,dict) or not isinstance(o.get('Name'),str):
            raise ValueError('malformed container')
        name=o['Name'].strip('/')
        if name in names or '/' in name or len(name)>128:
            raise ValueError('ambiguous container name')
        if not isinstance(o.get('NetworkSettings',{}).get('Networks'),dict):
            raise ValueError('network inventory missing')
        names[name]=o
    missing=sorted(EXPECTED-set(names))
    extra=sorted(set(names)-EXPECTED)
    for name, expected_image in IMAGE.items():
        if name in names and names[name].get('Image')!=expected_image:
            raise ValueError('exact running storage-image identity drift')
    shared={}
    for name,obj in names.items():
        if obj.get('State',{}).get('Running') is not True:
            raise ValueError('not all inventoried containers running')
        networks=set(obj['NetworkSettings']['Networks'])
        shared[name]=networks
    pg_peers=sorted(n for n,nets in shared.items() if n!=POSTGRES and POSTGRES in shared
                    and (nets & shared[POSTGRES]))
    minio_peers=sorted(n for n,nets in shared.items() if n!=MINIO and MINIO in shared
                       and (nets & shared[MINIO]))
    # Network access is a POTENTIAL path. This DOES NOT infer credentials,
    # write privileges, outstanding requests or writer admission receipts.
    findings={
        'status':'WRITER_SURFACE_READ_ONLY_OBSERVED_NOT_FENCED',
        'observed_host':HOST,
        'running_containers':len(names),
        'all_seven_expected_containers_present':not missing,
        'missing_expected_containers':missing,
        'extra_unreviewed_containers':extra,
        'postgis_image_pinned':POSTGRES in names,
        'minio_image_pinned':MINIO in names,
        'postgres_network_client_candidates':pg_peers,
        'minio_network_client_candidates':minio_peers,
        'postgres_spatial_internal_network_present':SPATIAL in shared.get(POSTGRES,set()),
        'minio_spatial_internal_network_present':SPATIAL in shared.get(MINIO,set()),
        'minio_frontend_network_present':FRONTEND in shared.get(MINIO,set()),
        'spatial_api_running':'kipnerter-spatial-api-1' in names,
        'spatial_worker_running':'kipnerter-spatial-worker-1' in names,
        'storage_clients_admission_revoked':False,
        'writer_credentials_revoked':False,
        'network_access_fenced':False,
        'running_clients_drained':False,
        'postgres_writes_fenced':False,
        'minio_writes_fenced':False,
        'atomic_multi_service_checkpoint_proven':False,
        'independent_administrative_custody':False,
        'safe_to_cutover':False,
        'release_gate':'NO_GO',
        'production_modified':False,
    }
    if missing or extra or len(pg_peers)<1 or len(minio_peers)<1:
        findings['status']='HOLD_UNEXPECTED_WRITER_SURFACE'
    return findings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspect-live',action='store_true')
    args=parser.parse_args()
    if not args.inspect_live:
        print(json.dumps({'status':'DRY_RUN_NO_DOCKER_OPERATION','release_gate':'NO_GO',
                          'safe_to_cutover':False,'production_modified':False},sort_keys=True))
        return 3
    if socket.gethostname()!=HOST:
        print(json.dumps({'status':'HOLD_HOST_NOT_PRODUCTION','release_gate':'NO_GO',
                          'safe_to_cutover':False,'production_modified':False},sort_keys=True))
        return 3
    try:
        report=analyze(collect())
        code=0 if report['status']=='WRITER_SURFACE_READ_ONLY_OBSERVED_NOT_FENCED' else 2
    except (OSError,ValueError,KeyError,TypeError,UnicodeError,subprocess.SubprocessError) as e:
        report={'status':'HOLD','error_class':type(e).__name__,
                'release_gate':'NO_GO','safe_to_cutover':False,'production_modified':False}
        code=2
    print(json.dumps(report,sort_keys=True))
    return code


if __name__=='__main__':
    sys.exit(main())
