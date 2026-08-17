# Spatial API release checklist

- [ ] Production GitHub Environment contains the private-repo checkout token and four spatial runtime secrets.
- [ ] `spatial_api_ref` is an exact reviewed `kipnerter-api` commit.
- [ ] `docker compose -f docker-compose.yml -f compose.spatial.yml --profile edge config` succeeds.
- [ ] `api.kipnerter.com/health` continues to serve the platform gateway.
- [ ] `api.kipnerter.com/health/live` and `/health/ready` serve the spatial API.
- [ ] Unauthenticated `/v1/*` requests are rejected while health probes remain reachable.
- [ ] PostGIS and MinIO have persistent named volumes.
- [ ] MinIO ports and console are not published directly.
- [ ] A presigned PUT URL uses `https://api.kipnerter.com/kipnerter-artifacts/...`, never a Docker hostname.
- [ ] One physical RoomPlan export reaches `synced` on iOS and `complete` in the backend.
- [ ] The RoomPlan worker stores a successful processing report.
- [ ] A sanitized real-device JSON fixture is committed to `kipnerter-api` after validation.
