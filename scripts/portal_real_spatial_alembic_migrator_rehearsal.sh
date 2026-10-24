#!/usr/bin/env bash
# Real deployed Alembic migrations on an entirely synthetic offline PostGIS DB.
set -euo pipefail
if [[ "$#" -ne 1 || "$1" != "--execute" ]];then
 echo '{"status":"DRY_RUN_NO_DOCKER_ACCESS","release_gate":"NO_GO","safe_to_cutover":false}';exit 3
fi
[[ "$(hostname)" == "x1-370" ]] || exit 4
[[ ! -v DOCKER_HOST && ! -v DOCKER_CONTEXT ]] || exit 4
[[ "$(docker context show)" == "default" ]] || exit 4
app=sha256:1624c272977968a700ca6f4b37107c46ec5bd35c7122cd6566fa7b7c8674a8e8
pgimage=sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5
for img in "$app" "$pgimage";do
 [[ "$(docker image inspect "$img" --format '{{.Id}}')" == "$img" ]] || exit 5
done
net="kp-alembic-internal-$$"
pg="kp-alembic-scratch-pg-$$"
[[ -z "$(docker network ls --format '{{.Name}}' | grep -Fx "$net" || :)" ]] || exit 5
[[ -z "$(docker ps -a --format '{{.Names}}' | grep -Fx "$pg" || :)" ]] || exit 5
cleanup(){ docker rm -f "$pg" >/dev/null 2>&1 || :; docker network rm "$net" >/dev/null 2>&1 || :; }
trap cleanup EXIT
admin_pw=$(openssl rand -hex 20)
api_pw=$(openssl rand -hex 20)
worker_pw=$(openssl rand -hex 20)
docker network create --internal --driver bridge "$net" >/dev/null
docker run -d --rm --name "$pg" --network "$net" --read-only \
 --pids-limit 128 --memory 850m --tmpfs /tmp:rw,nosuid,size=16m \
 --tmpfs /var/run/postgresql:rw,nosuid,size=16m \
 --tmpfs /var/lib/postgresql/data:rw,nosuid,size=196m \
 -e POSTGRES_DB=spatial_synthetic -e POSTGRES_USER=spatial_migrator \
 -e "POSTGRES_PASSWORD=$admin_pw" "$pgimage" >/dev/null
ready=0
for _ in $(seq 1 25);do
 if docker exec "$pg" pg_isready -h 127.0.0.1 -U spatial_migrator >/dev/null 2>&1;then ready=1;break;fi
 sleep 1
done
[[ "$ready" == 1 ]] || exit 6
docker run --rm --network "$net" --read-only --pids-limit 128 --memory 700m \
 --tmpfs /tmp:rw,nosuid,size=32m -e KIPNERTER_ENVIRONMENT=development \
 -e "KIPNERTER_DATABASE_URL=postgresql+asyncpg://spatial_migrator:$admin_pw@$pg:5432/spatial_synthetic" \
 --entrypoint alembic "$app" upgrade head >/dev/null
head=$(docker exec "$pg" psql -X -qAt -v ON_ERROR_STOP=1 -U spatial_migrator -d spatial_synthetic -c 'SELECT version_num FROM alembic_version')
[[ "$head" == "20260817_0004" ]] || { echo UNEXPECTED_ALEMBIC_HEAD;exit 7; }
tables=$(docker exec "$pg" psql -X -qAt -v ON_ERROR_STOP=1 -U spatial_migrator -d spatial_synthetic \
 -c "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('spatial_ref_sys','alembic_version')")
[[ "$tables" == 12 ]] || { echo UNEXPECTED_MIGRATED_SCHEMA;exit 7; }
echo REAL_ALEMBIC_FOUR_MIGRATIONS_TO_HEAD=PASS
docker exec "$pg" psql -X -q -v ON_ERROR_STOP=1 -U spatial_migrator -d spatial_synthetic -c "
 CREATE ROLE synthetic_api LOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS PASSWORD '$api_pw';
 CREATE ROLE synthetic_worker LOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS PASSWORD '$worker_pw';
 GRANT USAGE ON SCHEMA public TO synthetic_api,synthetic_worker;
 GRANT SELECT,INSERT ON TABLE public.devices TO synthetic_api;
 GRANT SELECT,INSERT,UPDATE ON TABLE public.outbox_events TO synthetic_worker;" >/dev/null
docker run --rm -i --network "$net" --read-only --pids-limit 128 --memory 700m \
 --tmpfs /tmp:rw,nosuid,size=32m \
 -e "SYNTHETIC_API_DSN=postgresql+asyncpg://synthetic_api:$api_pw@$pg:5432/spatial_synthetic" \
 -e "SYNTHETIC_WORKER_DSN=postgresql+asyncpg://synthetic_worker:$worker_pw@$pg:5432/spatial_synthetic" \
 --entrypoint python "$app" - <<'PY'
import asyncio,json,os
from uuid import uuid4
from sqlalchemy import insert,select,text
from sqlalchemy.ext.asyncio import create_async_engine
from kipnerter_api.models import DeviceModel,OutboxEventModel
async def check():
 api=create_async_engine(os.environ["SYNTHETIC_API_DSN"])
 worker=create_async_engine(os.environ["SYNTHETIC_WORKER_DSN"])
 async with api.begin() as c:
  await c.execute(insert(DeviceModel).values(installation_id="scratch-"+uuid4().hex,platform="ios",capabilities=[]))
 async with worker.begin() as c:
  await c.execute(insert(OutboxEventModel).values(aggregate_type="scratch",aggregate_id=uuid4(),event_type="scratch.event",payload={}))
 async with api.connect() as c:assert (await c.execute(select(DeviceModel.id))).first()
 async with worker.connect() as c:assert (await c.execute(select(OutboxEventModel.id))).first()
 async def denied(engine,sql):
  try:
   async with engine.begin() as c:await c.execute(text(sql))
  except Exception:return True
  return False
 for engine,sql in (
  (api,"SELECT count(*) FROM public.outbox_events"),
  (worker,"SELECT count(*) FROM public.devices"),
  (api,"ALTER TABLE public.devices ADD COLUMN pwned int"),
  (worker,"DROP TABLE public.outbox_events"),
  (api,"CREATE ROLE synthetic_admin_escalation"),
  (worker,"SET ROLE spatial_migrator"),
  (api,"UPDATE alembic_version SET version_num='wrong'"),
 ):
  assert await denied(engine,sql),sql+" should have been denied"
 await api.dispose();await worker.dispose()
 print(json.dumps({"status":"REAL_ALEMBIC_MIGRATED_SCOPED_ORM_PASS",
  "api_device_insert_select":True,"worker_outbox_insert_select":True,
  "cross_role_table_access_denied":True,"schema_change_denied":True,
  "alembic_version_tampering_denied":True,"production_modified":False,
  "migration_authority_separated":True,"source_writes_fenced":False,
  "safe_to_cutover":False,"release_gate":"NO_GO"},sort_keys=True))
asyncio.run(check())
PY
echo SCRATCH_MIGRATION_TEST_COMPLETE
