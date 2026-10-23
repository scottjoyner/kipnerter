#!/usr/bin/env bash
# Disposable least-privilege API/worker roles on the exact PostgreSQL image.
# No production connection, host mounts, external network, persistent data,
# static credentials, privileged release claim, or role mutation outside scratch.
set -euo pipefail
if [[ "${1:-}" != "--execute" || "$#" -ne 1 ]]; then
  printf '%s\n' '{"status":"DRY_RUN_NO_DOCKER_ACCESS","release_gate":"NO_GO","safe_to_cutover":false}'
  exit 3
fi
[[ "$(hostname)" == "x1-370" ]] || { echo 'HOLD_WRONG_HOST'; exit 4; }
[[ -z "${DOCKER_HOST:-}" && -z "${DOCKER_CONTEXT:-}" ]] || { echo 'HOLD_DOCKER_REDIRECT'; exit 4; }
[[ "$(docker context show)" == "default" ]] || { echo 'HOLD_DOCKER_CONTEXT'; exit 4; }
image=sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5
[[ "$(docker image inspect "$image" --format '{{.Id}}')" == "$image" ]]
name="kipnerter-disposable-scoped-roles-$$"
[[ -z "$(docker ps -a --format '{{.Names}}' | grep -Fx "$name" || :)" ]]
cleanup(){ docker rm -f "$name" >/dev/null 2>&1 || :; }
trap cleanup EXIT
root_secret=$(openssl rand -hex 20)
api_secret=$(openssl rand -hex 20)
worker_secret=$(openssl rand -hex 20)
docker run -d --rm --name "$name" --network none --read-only \
  --pids-limit 128 --memory 768m \
  --tmpfs /tmp:rw,nosuid,size=16m \
  --tmpfs /var/run/postgresql:rw,nosuid,size=16m \
  --tmpfs /var/lib/postgresql/data:rw,nosuid,size=128m \
  -e "POSTGRES_PASSWORD=$root_secret" "$image" >/dev/null
ready=0
for _ in $(seq 1 24); do
  if docker exec "$name" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[[ "$ready" == 1 ]] || exit 5
# All accounts and SQL fixtures are synthetic; generated credential text never
# reaches stdout and is not written to a host filesystem or Git.
docker exec -u postgres "$name" psql -X -q -v ON_ERROR_STOP=1 -U postgres -d postgres -c "
 CREATE ROLE synthetic_api LOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS PASSWORD '$api_secret';
 CREATE ROLE synthetic_worker LOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS PASSWORD '$worker_secret';
 CREATE SCHEMA api_data;
 CREATE SCHEMA worker_data;
 CREATE TABLE api_data.jobs (id integer PRIMARY KEY, payload text);
 CREATE TABLE worker_data.events (id integer PRIMARY KEY, payload text);
 GRANT USAGE ON SCHEMA api_data TO synthetic_api;
 GRANT USAGE ON SCHEMA worker_data TO synthetic_worker;
 GRANT SELECT, INSERT, UPDATE ON api_data.jobs TO synthetic_api;
 GRANT SELECT, INSERT, UPDATE ON worker_data.events TO synthetic_worker;
" >/dev/null
query(){ local role="$1" secret="$2" sql="$3";
  docker exec -e "PGPASSWORD=$secret" "$name" psql -X -qAt -v ON_ERROR_STOP=1 -U "$role" -h 127.0.0.1 -d postgres -c "$sql" 2>/dev/null;
}
deny(){ local role="$1" secret="$2" sql="$3";
  if query "$role" "$secret" "$sql" >/dev/null 2>&1; then echo "UNEXPECTED_SYNTHETIC_PRIVILEGE"; exit 10; fi
}
query synthetic_api "$api_secret" "INSERT INTO api_data.jobs VALUES (1,'api-only');" >/dev/null
query synthetic_worker "$worker_secret" "INSERT INTO worker_data.events VALUES (1,'worker-only');" >/dev/null
[[ "$(query synthetic_api "$api_secret" "SELECT count(*) FROM api_data.jobs;")" == 1 ]]
[[ "$(query synthetic_worker "$worker_secret" "SELECT count(*) FROM worker_data.events;")" == 1 ]]
echo SCOPED_API_AND_WORKER_WRITES=PASS
deny synthetic_api "$api_secret" "SELECT count(*) FROM worker_data.events;"
deny synthetic_worker "$worker_secret" "SELECT count(*) FROM api_data.jobs;"
deny synthetic_api "$api_secret" "INSERT INTO worker_data.events VALUES (2,'denied');"
deny synthetic_worker "$worker_secret" "INSERT INTO api_data.jobs VALUES (2,'denied');"
echo CROSS_SERVICE_READ_AND_WRITE_DENIED=PASS
deny synthetic_api "$api_secret" "CREATE TABLE api_data.unauthorized (x int);"
deny synthetic_worker "$worker_secret" "CREATE TABLE worker_data.unauthorized (x int);"
deny synthetic_api "$api_secret" "CREATE ROLE unwanted_role;"
deny synthetic_worker "$worker_secret" "ALTER ROLE synthetic_worker SUPERUSER;"
deny synthetic_api "$api_secret" "SET ROLE postgres;"
echo ROLE_ADMIN_DDL_AND_ELEVATION_DENIED=PASS
attributes=$(docker exec -u postgres "$name" psql -X -qAt -v ON_ERROR_STOP=1 -U postgres -d postgres -c "
 SELECT count(*) || '|' ||
  count(*) FILTER (WHERE rolcanlogin AND NOT rolsuper AND NOT rolcreaterole
                        AND NOT rolcreatedb AND NOT rolbypassrls AND NOT rolinherit)
 FROM pg_roles WHERE rolname IN ('synthetic_api','synthetic_worker');")
[[ "$attributes" == "2|2" ]]
memberships=$(docker exec -u postgres "$name" psql -X -qAt -v ON_ERROR_STOP=1 -U postgres -d postgres -c "
 SELECT count(*) FROM pg_auth_members
 WHERE member IN (SELECT oid FROM pg_roles WHERE rolname IN ('synthetic_api','synthetic_worker'));")
[[ "$memberships" == 0 ]]
echo BOTH_LOGINS_NONPRIVILEGED_AND_NO_INHERITED_MEMBERSHIP=PASS
printf '%s\n' '{"status":"SYNTHETIC_SCOPED_API_WORKER_AUTHORIZATION_PASS","api_non_superuser":true,"worker_non_superuser":true,"cross_service_access_denied":true,"privileged_role_operations_denied":true,"production_modified":false,"source_writes_fenced":false,"safe_to_cutover":false,"release_gate":"NO_GO"}'
