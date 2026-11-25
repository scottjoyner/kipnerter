#!/usr/bin/env bash
# Real deployed spatial S3 adapter on a disposable internal-only MinIO instance.
# This file MUST never contact or alter production MinIO or real credentials.
set -euo pipefail
if [[ "$#" -ne 1 || "$1" != "--execute" ]];then
 echo '{"status":"DRY_RUN_NO_DOCKER_ACCESS","release_gate":"NO_GO","safe_to_cutover":false}'
 exit 3
fi
[[ "$(hostname)" == "x1-370" ]] || exit 4
[[ ! -v DOCKER_HOST && ! -v DOCKER_CONTEXT ]] || exit 4
[[ "$(docker context show)" == "default" ]] || exit 4
api_image=sha256:1624c272977968a700ca6f4b37107c46ec5bd35c7122cd6566fa7b7c8674a8e8
s3_image=sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e
for img in "$api_image" "$s3_image";do
 [[ "$(docker image inspect "$img" --format '{{.Id}}')" == "$img" ]] || exit 5
done
net="kp-s3-scoped-internal-$$"
minio="kp-s3-scoped-minio-$$"
[[ -z "$(docker network ls --format '{{.Name}}' | grep -Fx "$net" || :)" ]]
[[ -z "$(docker ps -a --format '{{.Names}}' | grep -Fx "$minio" || :)" ]]
cleanup(){ docker rm -f "$minio" >/dev/null 2>&1 || :;docker network rm "$net" >/dev/null 2>&1 || :; }
trap cleanup EXIT
root_pw=$(openssl rand -hex 20)
api_pw=$(openssl rand -hex 20)
worker_pw=$(openssl rand -hex 20)
bucket=kp-s3-scoped-test
docker network create --internal --driver bridge "$net" >/dev/null
docker run -d --rm --name "$minio" --network "$net" --read-only \
 --pids-limit 128 --memory 720m --tmpfs /tmp:rw,nosuid,size=64m \
 --tmpfs /data:rw,nosuid,size=196m -e MINIO_ROOT_USER=syntheticroot \
 -e "MINIO_ROOT_PASSWORD=$root_pw" "$s3_image" server /data >/dev/null
ready=0
for _ in $(seq 1 18);do
 if docker exec -e "SYNTHETIC_ROOT_PASSWORD=$root_pw" "$minio" sh -c \
 'HOME=/tmp MC_HOST_local="http://syntheticroot:$SYNTHETIC_ROOT_PASSWORD@127.0.0.1:9000" mc ls local >/dev/null 2>&1';then ready=1;break;fi
 sleep 1
done
[[ "$ready" == 1 ]] || exit 6
# Root operates only inside the disposable MinIO container. Its only job is
# bootstrapping the fictional bucket, user identities and scoped policies.
docker exec -e "SYNTHETIC_ROOT_PASSWORD=$root_pw" -e "SYNTHETIC_API_PASSWORD=$api_pw" \
 -e "SYNTHETIC_WORKER_PASSWORD=$worker_pw" "$minio" sh -c '
 set -eu
 export HOME=/tmp
 export MC_HOST_local="http://syntheticroot:$SYNTHETIC_ROOT_PASSWORD@127.0.0.1:9000"
 mc mb local/kp-s3-scoped-test >/dev/null
 mc admin user add local synthetic_api "$SYNTHETIC_API_PASSWORD" >/dev/null
 mc admin user add local synthetic_worker "$SYNTHETIC_WORKER_PASSWORD" >/dev/null
'
docker exec -i "$minio" sh -c 'umask 077; cat >/tmp/scoped-api.json' <<'JSON'
{"Version":"2012-10-17","Statement":[
{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::kp-s3-scoped-test"]},
{"Effect":"Allow","Action":["s3:GetObject","s3:PutObject"],"Resource":["arn:aws:s3:::kp-s3-scoped-test/*"]}]}
JSON
docker exec -i "$minio" sh -c 'umask 077; cat >/tmp/scoped-worker.json' <<'JSON'
{"Version":"2012-10-17","Statement":[
{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::kp-s3-scoped-test"]},
{"Effect":"Allow","Action":["s3:GetObject"],"Resource":["arn:aws:s3:::kp-s3-scoped-test/*"]}]}
JSON
docker exec -e "SYNTHETIC_ROOT_PASSWORD=$root_pw" "$minio" sh -c '
 set -eu
 export HOME=/tmp
 export MC_HOST_local="http://syntheticroot:$SYNTHETIC_ROOT_PASSWORD@127.0.0.1:9000"
 mc admin policy create local syntheticapi /tmp/scoped-api.json >/dev/null
 mc admin policy create local syntheticworker /tmp/scoped-worker.json >/dev/null
 mc admin policy attach local syntheticapi --user synthetic_api >/dev/null
 mc admin policy attach local syntheticworker --user synthetic_worker >/dev/null
'
# Actual deployed S3ObjectStorage class exercised under synthetic API identity.
docker run --rm -i --network "$net" --read-only --pids-limit 128 --memory 720m \
 --tmpfs /tmp:rw,nosuid,size=32m --entrypoint python \
 -e KIPNERTER_ENVIRONMENT=development -e KIPNERTER_S3_BUCKET=kp-s3-scoped-test \
 -e "KIPNERTER_S3_ENDPOINT_URL=http://$minio:9000" \
 -e KIPNERTER_S3_ACCESS_KEY_ID=synthetic_api \
 -e "KIPNERTER_S3_SECRET_ACCESS_KEY=$api_pw" "$api_image" - <<'PY'
import asyncio,json,hashlib
from botocore.exceptions import ClientError
from kipnerter_api.storage import S3ObjectStorage
async def main():
 storage=S3ObjectStorage()
 await storage.ensure_bucket()
 payload=b"synthetic-scoped-api-write"
 digest=hashlib.sha256(payload).hexdigest()
 await asyncio.to_thread(storage.client.put_object,Bucket=storage.bucket,
       Key="synthetic/artifact.bin",Body=payload,Metadata={"sha256":digest})
 assert await storage.stat("synthetic/artifact.bin")== (len(payload),digest)
 received=b""
 async for part in storage.open("synthetic/artifact.bin"):received+=part
 assert received==payload
 signed=await storage.presign_put(key="synthetic/new.bin",content_type="application/octet-stream",sha256=digest)
 assert "X-Amz-Signature" in signed
 try:
  await asyncio.to_thread(storage.client.delete_object,Bucket=storage.bucket,Key="synthetic/artifact.bin")
 except ClientError:pass
 else:raise AssertionError("synthetic API unexpectedly deleted object")
 try:
  await asyncio.to_thread(storage.client.create_bucket,Bucket="synthetic-unauthorized")
 except ClientError:pass
 else:raise AssertionError("synthetic API unexpectedly created bucket")
 print(json.dumps({"status":"REAL_SPATIAL_S3_API_SCOPED_UPLOAD_READ_PRESIGN_PASS",
 "head_bucket_allowed":True,"put_read_allowed":True,
 "delete_denied":True,"bucket_create_denied":True,
 "production_modified":False,"release_gate":"NO_GO"},sort_keys=True))
asyncio.run(main())
PY
# Same actual deployed adapter with separate, strictly read-only worker user.
docker run --rm -i --network "$net" --read-only --pids-limit 128 --memory 720m \
 --tmpfs /tmp:rw,nosuid,size=32m --entrypoint python \
 -e KIPNERTER_ENVIRONMENT=development -e KIPNERTER_S3_BUCKET=kp-s3-scoped-test \
 -e "KIPNERTER_S3_ENDPOINT_URL=http://$minio:9000" \
 -e KIPNERTER_S3_ACCESS_KEY_ID=synthetic_worker \
 -e "KIPNERTER_S3_SECRET_ACCESS_KEY=$worker_pw" "$api_image" - <<'PY'
import asyncio,json,hashlib
from botocore.exceptions import ClientError
from kipnerter_api.storage import S3ObjectStorage
async def main():
 storage=S3ObjectStorage()
 await storage.ensure_bucket()
 contents=b""
 async for part in storage.open("synthetic/artifact.bin"):contents+=part
 assert contents==b"synthetic-scoped-api-write"
 assert await storage.stat("synthetic/artifact.bin") == (len(contents),hashlib.sha256(contents).hexdigest())
 async def deny(method,**kwargs):
  try:await asyncio.to_thread(method,**kwargs)
  except ClientError:return
  raise AssertionError("synthetic worker unexpectedly authorized a write")
 await deny(storage.client.put_object,Bucket=storage.bucket,Key="synthetic/worker-write.bin",Body=b"denied")
 await deny(storage.client.delete_object,Bucket=storage.bucket,Key="synthetic/artifact.bin")
 await deny(storage.client.create_bucket,Bucket="synthetic-worker-bucket")
 print(json.dumps({"status":"REAL_SPATIAL_S3_WORKER_SCOPED_READ_ONLY_PASS",
   "head_bucket_allowed":True,"get_stat_allowed":True,
   "put_delete_create_denied":True,"production_modified":False,
   "source_writes_fenced":False,"safe_to_cutover":False,
   "release_gate":"NO_GO"},sort_keys=True))
asyncio.run(main())
PY
echo SCOPED_S3_DISPOSABLE_TEST_COMPLETE
