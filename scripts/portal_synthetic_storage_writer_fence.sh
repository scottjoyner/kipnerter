#!/usr/bin/env bash
# Exact production PostgreSQL/MinIO images, synthetic credentials and ephemeral
# network-none containers. NO production access or coordinated fencing claim.
set -euo pipefail
if [[ "${1:-}" != "--execute" || "$#" != 1 ]]; then
  printf '%s\n' '{"status":"DRY_RUN_NO_DOCKER_ACCESS","release_gate":"NO_GO","safe_to_cutover":false}'
  exit 3
fi
[[ "$(hostname)" == "x1-370" ]] || { echo 'INVALID_HOST';exit 4; }
[[ -z "${DOCKER_HOST:-}" && -z "${DOCKER_CONTEXT:-}" ]] || { echo 'REMOTE_DOCKER_CONTEXT_DENIED';exit 4; }
[[ "$(docker context show)" == "default" ]] || { echo 'NONDEFAULT_DOCKER_CONTEXT_DENIED';exit 4; }
pg_image=sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5
s3_image=sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e
for image in "$pg_image" "$s3_image";do
  [[ "$(docker image inspect "$image" --format '{{.Id}}')" == "$image" ]]
done
pg_name="kipnerter-synthetic-fence-pg-$$"
s3_name="kipnerter-synthetic-fence-s3-$$"
for name in "$pg_name" "$s3_name";do
  [[ -z "$(docker ps -a --format '{{.Names}}' | awk -v n="$name" '$0==n{print}')" ]] || exit 5
done
cleanup() {
  docker rm -f "$pg_name" >/dev/null 2>&1 || :
  docker rm -f "$s3_name" >/dev/null 2>&1 || :
}
trap cleanup EXIT
# MinIO: real policy transitions with entirely fabricated identities.
docker run -d --rm --network none --name "$s3_name" --pids-limit 128 --memory 700m \
 --read-only --tmpfs /tmp:rw,nosuid,size=64m --tmpfs /data:rw,nosuid,size=128m \
 -e MINIO_ROOT_USER=syntheticadmin -e MINIO_ROOT_PASSWORD=syntheticpass12345678 \
 "$s3_image" server /data >/dev/null
ready=0
for _ in $(seq 1 18);do
  if docker exec "$s3_name" sh -c 'HOME=/tmp MC_HOST_local=http://syntheticadmin:syntheticpass12345678@127.0.0.1:9000 mc ls local >/dev/null 2>&1';then ready=1;break;fi
  sleep 1
done
[[ "$ready" == 1 ]] || exit 6
docker exec "$s3_name" sh -c '
 set -eu
 export HOME=/tmp MC_HOST_local=http://syntheticadmin:syntheticpass12345678@127.0.0.1:9000
 mc mb local/fence-test --ignore-existing >/dev/null
 mc admin user add local writerunit syntheticWriterPass12345 >/dev/null
 mc admin policy attach local readwrite --user writerunit >/dev/null
 MC_HOST_writer=http://writerunit:syntheticWriterPass12345@127.0.0.1:9000 sh -c "printf before | mc pipe writer/fence-test/first.txt >/dev/null"
 mc admin policy detach local readwrite --user writerunit >/dev/null
 mc admin policy attach local readonly --user writerunit >/dev/null
 if MC_HOST_writer=http://writerunit:syntheticWriterPass12345@127.0.0.1:9000 sh -c "printf denied | mc pipe writer/fence-test/new.txt >/dev/null 2>&1";then exit 9;fi
 readback=$(MC_HOST_writer=http://writerunit:syntheticWriterPass12345@127.0.0.1:9000 mc cat writer/fence-test/first.txt)
 test "$readback" = before
 if MC_HOST_writer=http://writerunit:syntheticWriterPass12345@127.0.0.1:9000 mc rm writer/fence-test/first.txt >/dev/null 2>&1;then exit 10;fi
'
echo SYNTHETIC_MINIO_ROLE_PUT_DELETE_DENIED_READ_ALLOWED=PASS
# PostgreSQL: same pinned storage image; table-level grants are not a global fence.
docker run -d --rm --network none --name "$pg_name" --pids-limit 128 --memory 700m \
 --read-only --tmpfs /tmp:rw,nosuid,size=16m \
 --tmpfs /var/run/postgresql:rw,nosuid,size=16m \
 --tmpfs /var/lib/postgresql/data:rw,nosuid,size=128m \
 -e POSTGRES_PASSWORD=syntheticOnlyPass "$pg_image" >/dev/null
ready=0
for _ in $(seq 1 24);do
  if docker exec "$pg_name" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1;then ready=1;break;fi
  sleep 1
done
[[ "$ready" == 1 ]] || exit 7
docker exec -u postgres "$pg_name" psql -X -v ON_ERROR_STOP=1 -q -U postgres -d postgres -c "
 CREATE TABLE public.synthetic_fence (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, payload text);
 CREATE ROLE synthetic_app LOGIN PASSWORD 'syntheticAppOnlyPass';
 GRANT SELECT,INSERT,UPDATE,DELETE ON public.synthetic_fence TO synthetic_app;
 GRANT USAGE,SELECT ON SEQUENCE public.synthetic_fence_id_seq TO synthetic_app;" >/dev/null
docker exec -e PGPASSWORD=syntheticAppOnlyPass "$pg_name" psql -X -v ON_ERROR_STOP=1 -q -U synthetic_app -h 127.0.0.1 -d postgres -c "INSERT INTO public.synthetic_fence(payload) VALUES ('before');" >/dev/null
docker exec -u postgres "$pg_name" psql -X -v ON_ERROR_STOP=1 -q -U postgres -d postgres -c "
 REVOKE INSERT,UPDATE,DELETE ON public.synthetic_fence FROM synthetic_app;
 REVOKE USAGE ON SEQUENCE public.synthetic_fence_id_seq FROM synthetic_app;" >/dev/null
if docker exec -e PGPASSWORD=syntheticAppOnlyPass "$pg_name" psql -X -v ON_ERROR_STOP=1 -q -U synthetic_app -h 127.0.0.1 -d postgres -c "INSERT INTO public.synthetic_fence(payload) VALUES ('denied');" >/dev/null 2>&1;then exit 12;fi
if docker exec -e PGPASSWORD=syntheticAppOnlyPass "$pg_name" psql -X -v ON_ERROR_STOP=1 -q -U synthetic_app -h 127.0.0.1 -d postgres -c "UPDATE public.synthetic_fence SET payload='denied';" >/dev/null 2>&1;then exit 13;fi
count=$(docker exec -e PGPASSWORD=syntheticAppOnlyPass "$pg_name" psql -X -v ON_ERROR_STOP=1 -qAt -U synthetic_app -h 127.0.0.1 -d postgres -c "SELECT count(*) FROM public.synthetic_fence;")
[[ "$count" == 1 ]] || exit 14
# Deliberately prove owner bypass still exists, to preclude false release approval.
docker exec -u postgres "$pg_name" psql -X -v ON_ERROR_STOP=1 -q -U postgres -d postgres -c "INSERT INTO public.synthetic_fence(payload) VALUES ('owner_bypass');" >/dev/null
echo SYNTHETIC_POSTGRES_ROLE_INSERT_UPDATE_DENIED_SELECT_ALLOWED=PASS
echo PRIVILEGED_DATABASE_OWNER_BYPASS_STILL_EXISTS=true
printf '%s\n' '{"status":"SYNTHETIC_STORAGE_ROLE_WRITE_DENIAL_PASS_NOT_FENCED","postgres_application_writes_denied":true,"minio_application_writes_denied":true,"privileged_bypass_still_exists":true,"source_writes_fenced":false,"cross_service_atomicity_proven":false,"production_modified":false,"safe_to_cutover":false,"release_gate":"NO_GO"}'
