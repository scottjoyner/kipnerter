#!/usr/bin/env bash
# Real spatial ORM smoke test against exact deployed API/PostGIS images.
# All data/roles/credentials are synthetic. No production access or mounts.
set -euo pipefail
if [[ "$#" -ne 1 || "$1" != "--execute" ]]; then
  printf '%s\n' '{"status":"DRY_RUN_NO_DOCKER_ACCESS","safe_to_cutover":false,"release_gate":"NO_GO"}'
  exit 3
fi
[[ "$(hostname)" == "x1-370" ]] || { echo HOLD_UNAPPROVED_HOST; exit 4; }
[[ -z "${DOCKER_HOST:-}" && -z "${DOCKER_CONTEXT:-}" ]] || { echo HOLD_REMOTE_DOCKER; exit 4; }
[[ "$(docker context show)" == "default" ]] || { echo HOLD_DOCKER_CONTEXT; exit 4; }
app_image=sha256:1624c272977968a700ca6f4b37107c46ec5bd35c7122cd6566fa7b7c8674a8e8
pg_image=sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5
[[ "$(docker image inspect "$app_image" --format '{{.Id}}')" == "$app_image" ]]
[[ "$(docker image inspect "$pg_image" --format '{{.Id}}')" == "$pg_image" ]]
network="kp-real-schema-roles-$$"
postgres="kp-real-schema-postgres-$$"
[[ -z "$(docker network ls --format '{{.Name}}' | grep -Fx "$network" || :)" ]]
[[ -z "$(docker ps -a --format '{{.Names}}' | grep -Fx "$postgres" || :)" ]]
cleanup() {
  docker rm -f "$postgres" >/dev/null 2>&1 || :
  docker network rm "$network" >/dev/null 2>&1 || :
}
trap cleanup EXIT
# Synthetic, per-execution identities. None is retained or printed.
admin_password=$(openssl rand -hex 20)
api_password=$(openssl rand -hex 20)
worker_password=$(openssl rand -hex 20)
docker network create --internal --driver bridge "$network" >/dev/null
docker run -d --rm --name "$postgres" --network "$network" --read-only \
  --pids-limit 128 --memory 850m \
  --tmpfs /tmp:rw,nosuid,size=16m \
  --tmpfs /var/run/postgresql:rw,nosuid,size=16m \
  --tmpfs /var/lib/postgresql/data:rw,nosuid,size=196m \
  -e POSTGRES_DB=spatial_synthetic \
  -e POSTGRES_USER=spatial_synthetic_root \
  -e "POSTGRES_PASSWORD=$admin_password" "$pg_image" >/dev/null
ready=0
for _ in $(seq 1 25); do
  if docker exec "$postgres" pg_isready -h 127.0.0.1 -U spatial_synthetic_root >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 1
done
[[ "$ready" == 1 ]] || exit 5
docker exec "$postgres" psql -q -v ON_ERROR_STOP=1 -U spatial_synthetic_root \
  -d spatial_synthetic -c 'CREATE EXTENSION IF NOT EXISTS postgis' >/dev/null
# Load the ACTUAL installed production spatial ORM; no application service starts.
docker run --rm -i --network "$network" --read-only \
  --pids-limit 128 --memory 850m --tmpfs /tmp:rw,nosuid,size=32m \
  -e "SYNTHETIC_ADMIN_DSN=postgresql+asyncpg://spatial_synthetic_root:$admin_password@$postgres:5432/spatial_synthetic" \
  --entrypoint python "$app_image" - <<'PY'
import asyncio, json, os
from sqlalchemy.ext.asyncio import create_async_engine
from kipnerter_api.models import Base
import kipnerter_api.spatial_models, kipnerter_api.processing_models

async def main():
    engine = create_async_engine(os.environ["SYNTHETIC_ADMIN_DSN"])
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    assert len(Base.metadata.tables) == 12
    assert sum(len(t.foreign_key_constraints) for t in Base.metadata.tables.values()) == 13
    print(json.dumps({"status":"ISOLATED_REAL_ORM_SCHEMA_CREATED",
        "tables":12,"foreign_key_constraints":13,
        "production_modified":False,"release_gate":"NO_GO"},sort_keys=True))
asyncio.run(main())
PY
docker exec "$postgres" psql -q -v ON_ERROR_STOP=1 -U spatial_synthetic_root \
  -d spatial_synthetic -c "
  CREATE ROLE synthetic_spatial_api LOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS PASSWORD '$api_password';
  CREATE ROLE synthetic_spatial_worker LOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS PASSWORD '$worker_password';
  GRANT USAGE ON SCHEMA public TO synthetic_spatial_api,synthetic_spatial_worker;
  GRANT SELECT, INSERT ON TABLE public.devices TO synthetic_spatial_api;
  GRANT SELECT, INSERT ON TABLE public.outbox_events TO synthetic_spatial_worker;" >/dev/null
# Execute real SQLAlchemy ORM insert/select operations as two separate scoped roles.
docker run --rm -i --network "$network" --read-only \
  --pids-limit 128 --memory 850m --tmpfs /tmp:rw,nosuid,size=32m \
  -e "SYNTHETIC_API_DSN=postgresql+asyncpg://synthetic_spatial_api:$api_password@$postgres:5432/spatial_synthetic" \
  -e "SYNTHETIC_WORKER_DSN=postgresql+asyncpg://synthetic_spatial_worker:$worker_password@$postgres:5432/spatial_synthetic" \
  --entrypoint python "$app_image" - <<'PY'
import asyncio, json, os
from uuid import uuid4
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import create_async_engine
from kipnerter_api.models import DeviceModel, OutboxEventModel

async def main():
    api = create_async_engine(os.environ["SYNTHETIC_API_DSN"])
    worker = create_async_engine(os.environ["SYNTHETIC_WORKER_DSN"])
    async with api.begin() as conn:
        await conn.execute(insert(DeviceModel).values(
            installation_id="synthetic-"+uuid4().hex, platform="ios", capabilities=[]))
    async with worker.begin() as conn:
        await conn.execute(insert(OutboxEventModel).values(
            aggregate_type="synthetic", aggregate_id=uuid4(),
            event_type="synthetic.integration",payload={}))
    async with api.connect() as conn:
        assert (await conn.execute(select(DeviceModel.id))).first()
    async with worker.connect() as conn:
        assert (await conn.execute(select(OutboxEventModel.id))).first()
    async def denied(engine, sql):
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql))
        except Exception:
            return True
        return False
    assert await denied(api, "SELECT * FROM public.outbox_events LIMIT 1")
    assert await denied(worker, "SELECT * FROM public.devices LIMIT 1")
    assert await denied(api, "CREATE TABLE public.synthetic_escalation (id integer)")
    assert await denied(worker, "CREATE ROLE synthetic_unwanted_role")
    await api.dispose()
    await worker.dispose()
    print(json.dumps({"status":"REAL_SPATIAL_ORM_SCOPED_ROLE_SMOKE_PASS",
        "api_device_orm_insert_select":True,
        "worker_outbox_orm_insert_select":True,
        "cross_service_select_denied":True,
        "schema_ddl_denied":True,"role_admin_denied":True,
        "production_modified":False,"writer_fence_proven":False,
        "safe_to_cutover":False,"release_gate":"NO_GO"},sort_keys=True))
asyncio.run(main())
PY
