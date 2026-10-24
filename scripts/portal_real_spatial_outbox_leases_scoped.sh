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
 GRANT SELECT,UPDATE ON TABLE public.outbox_events TO synthetic_worker;" >/dev/null
docker run --rm -i --network "$net" --read-only --pids-limit 128 --memory 700m \
 --tmpfs /tmp:rw,nosuid,size=32m \
 -e "SYNTHETIC_API_DSN=postgresql+asyncpg://synthetic_api:$api_pw@$pg:5432/spatial_synthetic" \
 -e "SYNTHETIC_WORKER_DSN=postgresql+asyncpg://synthetic_worker:$worker_pw@$pg:5432/spatial_synthetic" \
 -e "SYNTHETIC_MIGRATOR_DSN=postgresql+asyncpg://spatial_migrator:$admin_pw@$pg:5432/spatial_synthetic" \
 --entrypoint python "$app" - <<'PY'
import asyncio,json,os
from uuid import uuid4
from sqlalchemy import insert,select,text
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from kipnerter_api.models import DeviceModel,OutboxEventModel
from kipnerter_api.outbox import OutboxDispatcher
async def main():
 api=create_async_engine(os.environ["SYNTHETIC_API_DSN"])
 worker=create_async_engine(os.environ["SYNTHETIC_WORKER_DSN"])
 migrator=create_async_engine(os.environ["SYNTHETIC_MIGRATOR_DSN"])
 async with api.begin() as conn:
  await conn.execute(insert(DeviceModel).values(
   installation_id="synthetic-"+uuid4().hex,platform="ios",capabilities=[]))
 async with migrator.begin() as conn:
  for event_type in ("synthetic.ok","synthetic.unhandled"):
   await conn.execute(insert(OutboxEventModel).values(
    aggregate_type="synthetic",aggregate_id=uuid4(),event_type=event_type,payload={"synthetic":True}))
 called=[]
 async def handle_ok(payload):
  assert payload=={"synthetic":True}
  called.append("ok")
 factory=async_sessionmaker(worker,expire_on_commit=False)
 dispatch=OutboxDispatcher(factory,{"synthetic.ok":handle_ok},
   worker_id="synthetic-least-privileged",max_attempts=1,batch_size=10)
 first=await dispatch.dispatch_once()
 second=await dispatch.dispatch_once()
 assert first==2 and second==0 and called==["ok"]
 async with worker.connect() as conn:
  rows=(await conn.execute(text(
   "SELECT event_type, published_at IS NOT NULL AS published, "
   "dead_lettered_at IS NOT NULL AS dead, attempts, "
   "locked_by IS NULL AS lease_released FROM outbox_events ORDER BY event_type"
  ))).all()
 assert len(rows)==2
 observations={r[0]:(r[1],r[2],r[3],r[4]) for r in rows}
 assert observations["synthetic.ok"]==(True,False,0,True),observations
 assert observations["synthetic.unhandled"]==(False,True,1,True),observations
 # Explicit transient-failure path: reschedule only synthetic data under the
 # disposable migrator, then prove the real dispatcher eventually acknowledges.
 async with migrator.begin() as conn:
  await conn.execute(insert(OutboxEventModel).values(
   aggregate_type="synthetic",aggregate_id=uuid4(),
   event_type="synthetic.retry",payload={"synthetic":True}))
 attempt=[0]
 async def flaky(payload):
  assert payload=={"synthetic":True}
  attempt[0]+=1
  if attempt[0]==1:
   raise RuntimeError("synthetic transient failure")
 retry=OutboxDispatcher(factory,{"synthetic.retry":flaky},
   worker_id="synthetic-retry",max_attempts=2,batch_size=10)
 assert await retry.dispatch_once()==1
 assert await retry.dispatch_once()==0  # retry delay respected
 async with migrator.begin() as conn:
  await conn.execute(text(
   "UPDATE outbox_events SET next_attempt_at=now()-interval '1 second' "
   "WHERE event_type='synthetic.retry'"
  ))
 assert await retry.dispatch_once()==1 and attempt==[2]
 async with worker.connect() as conn:
  retried=(await conn.execute(text(
   "SELECT published_at IS NOT NULL, dead_lettered_at IS NOT NULL, "
   "attempts, locked_by IS NULL FROM outbox_events "
   "WHERE event_type='synthetic.retry'"
  ))).one()
 assert tuple(retried)==(True,False,1,True),tuple(retried)
 async def denied(engine,sql):
  try:
   async with engine.begin() as conn:await conn.execute(text(sql))
  except Exception:return True
  return False
 for engine,sql in (
  (api,"SELECT count(*) FROM public.outbox_events"),
  (worker,"INSERT INTO public.outbox_events (id,aggregate_id,aggregate_type,event_type,payload,created_at,attempts) VALUES (gen_random_uuid(),gen_random_uuid(),'x','x','{}',now(),0)"),
  (worker,"SELECT count(*) FROM public.devices"),
  (worker,"ALTER TABLE public.outbox_events ADD COLUMN pwned int"),
  (worker,"SET ROLE spatial_migrator"),
  (worker,"UPDATE alembic_version SET version_num='wrong'"),
 ):
  assert await denied(engine,sql),sql+" unexpectedly authorized"
 await api.dispose();await worker.dispose();await migrator.dispose()
 print(json.dumps({"status":"REAL_SPATIAL_OUTBOX_DISPATCHER_SCOPED_PASS",
   "handled_events":1,"dead_lettered_missing_handler_events":1,
   "claimed_events":first,"duplicate_reclaims":second,
   "transient_retry_attempts":attempt[0],
   "transient_retry_published_after_delay":True,
   "both_leases_released":True,"cross_service_select_denied":True,
   "worker_insert_denied":True,"schema_or_migrator_escalation_denied":True,
   "production_modified":False,"source_writes_fenced":False,
   "safe_to_cutover":False,"release_gate":"NO_GO"},sort_keys=True))
asyncio.run(main())
PY
echo SCOPED_OUTBOX_DISPATCHER_TEST_COMPLETE
