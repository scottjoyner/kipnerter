#!/usr/bin/env python3
"""Read-only bounded OCI/Docker archive digest-tree verifier for two exact storage images.

Run with python3 -m scripts.portal_stateful_oci_archive_verify --role <role> < archive.
Does not unpack, import, contact Docker, or access a registry.
Does not prove a database restore, container launch, or independent custody.
"""
import argparse
import json
import sys
import tarfile

from scripts import portal_legacy_oci_archive_verify as v

# Exact read-only Docker running-image IDs observed on kipnerter-prod-01, 2026-10-21.
# This is same-operator evidence, not proof of independently witnessed recovery.
ROLES = {
    "spatial-minio": "sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e",
    "spatial-postgres": "sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5",
}
ROOT_INDEX='application/vnd.oci.image.index.v1+json'
OCI_MANIFEST='application/vnd.oci.image.manifest.v1+json'
DOCKER_LIST='application/vnd.docker.distribution.manifest.list.v2+json'
DOCKER_MANIFEST='application/vnd.docker.distribution.manifest.v2+json'
DOCKER_CONFIG='application/vnd.docker.container.image.v1+json'

def check(stream, expected):
 blobs,docs,count,layers=v._archive(stream)
 root=docs.get('index.json')
 if not isinstance(root,dict) or root.get('schemaVersion')!=2 or root.get('mediaType')!=ROOT_INDEX or len(root.get('manifests',[]))!=1:
  raise ValueError('invalid root OCI index')
 d=root['manifests'][0]
 original=v._descriptor(d,blobs,allowed={ROOT_INDEX,DOCKER_LIST,OCI_MANIFEST,DOCKER_MANIFEST})
 obj=docs.get(original)
 if d['mediaType'] in (ROOT_INDEX,DOCKER_LIST):
  if not isinstance(obj,dict) or obj.get('schemaVersion')!=2 or obj.get('mediaType')!=d['mediaType']:
   raise ValueError('invalid nested image index')
  manifest= obj.get('manifests')
  if not isinstance(manifest,list) or len(manifest)>64:
   raise ValueError('unbounded nested descriptors')
  selected=[x for x in manifest if isinstance(x,dict) and isinstance(x.get('platform'),dict) and
    x['platform'].get('os')=='linux' and x['platform'].get('architecture')=='amd64' and
    x['platform'].get('variant') in (None,'')]
  if len(selected)!=1:raise ValueError('ambiguous linux/amd64 image')
  d=selected[0]
  manifest_digest=v._descriptor(d,blobs,allowed={OCI_MANIFEST,DOCKER_MANIFEST})
 else:manifest_digest=original
 manifest=docs.get(manifest_digest)
 if not isinstance(manifest,dict): raise ValueError('missing image manifest')
 # Reuse the independently tested bounded layer/config verifier. Its legacy
 # constants are restored even when validation rejects untrusted metadata.
 previous_manifest, previous_config = v.MANIFEST, v.CONFIG
 try:
  v.MANIFEST = manifest['mediaType']
  v.CONFIG = {DOCKER_MANIFEST: DOCKER_CONFIG,
              OCI_MANIFEST: 'application/vnd.oci.image.config.v1+json'}[manifest['mediaType']]
  cfg,blob_layers = v._validate_manifest(manifest,blobs,docs,layers)
 finally:
  v.MANIFEST, v.CONFIG = previous_manifest, previous_config
 if 'sha256:'+original!=expected and 'sha256:'+cfg!=expected:
  raise ValueError('original image ID does not match expected production ID')
 compat=docs.get('manifest.json')
 if not isinstance(compat,list) or len(compat)!=1:
  raise ValueError('missing compatibility manifest')
 if compat[0].get('Config')!='blobs/sha256/'+cfg or compat[0].get('Layers')!=['blobs/sha256/'+x for x in blob_layers]:
  raise ValueError('Docker manifest disagrees with OCI blobs')
 if docs.get('oci-layout',{}).get('imageLayoutVersion')!='1.0.0':raise ValueError('bad OCI layout')
 return {'status':'OCI_CONTENT_TREE_VERIFIED_NOT_RESTORED','expected_running_image_id':expected,
         'root_saved_image_identity':'sha256:'+original,
         'linux_amd64_manifest':'sha256:'+manifest_digest,
         'saved_layer_count':len(blob_layers),'archive_member_count':count,
         'all_included_blob_hashes_verified':True,
         'uncompressed_layer_diffids_verified':True,
         'registry_provenance_independent':False,
         'production_data_included':False,'live_restore_verified':False,
         'independent_admin_custody':False,
         'production_modified':False,'safe_to_cutover':False}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=tuple(ROLES))
    args = parser.parse_args()
    try:
        report=check(sys.stdin.buffer,ROLES[args.role])
        report["role"] = args.role
        report["archive_sha256_claimed_by_untrusted_input"] = False
        print(json.dumps(report,sort_keys=True))
        return 0
    except (ValueError,KeyError,TypeError,OSError,tarfile.TarError,EOFError) as exc:
        print(json.dumps({"status":"HOLD","error_type":type(exc).__name__,
                          "safe_to_cutover":False,"production_modified":False},sort_keys=True))
        return 2

if __name__=='__main__':
    sys.exit(main())
