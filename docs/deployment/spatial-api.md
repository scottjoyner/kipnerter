# Spatial API production deployment

`kipnerter-api` is deployed as a private-source service behind the existing Kipnerter public edge. It does not replace the existing platform gateway.

## Public routing

`api.kipnerter.com` remains the single public API origin:

- `/api/v1/*` and other existing gateway routes -> platform `api`
- `/v1/*`, `/health/live`, `/health/ready`, `/version` -> `spatial-api`
- `/kipnerter-artifacts/*` -> private MinIO service for SigV4-signed object operations only

MinIO ports and its console are never published directly. Presigned URLs are generated against `https://api.kipnerter.com` while the backend uses `http://spatial-minio:9000` internally.

## Persistent services

The production overlay adds:

- `spatial-api`
- `spatial-worker`
- PostgreSQL 16 + PostGIS 3.4
- MinIO object storage

PostgreSQL and MinIO use named Docker volumes. The worker consumes transactional `scan.completed` events and normalizes verified RoomPlan JSON artifacts.

## Required production secrets

Configure these in the protected `production` GitHub Environment:

- `KIPNERTER_API_REPO_TOKEN` — read-only token able to check out the private `scottjoyner/kipnerter-api` repository
- `KIPNERTER_SPATIAL_API_KEY` — minimum 32-character bearer token used by the internal TestFlight client
- `KIPNERTER_SPATIAL_DB_PASSWORD` — minimum 20-character PostgreSQL password; use URL-safe characters
- `KIPNERTER_SPATIAL_S3_ACCESS_KEY_ID` — MinIO access key
- `KIPNERTER_SPATIAL_S3_SECRET_ACCESS_KEY` — minimum 32-character MinIO secret

Existing Tailscale/deployment secrets remain required by the normal Kipnerter deploy workflow.

## Immutable source contract

The deploy workflow accepts an exact `spatial_api_ref`. GitHub Actions checks out that exact private commit, verifies its SHA, bundles it with the public control plane, then transfers the combined immutable source tree to the production node over Tailscale. The production host therefore does not need GitHub credentials.

## First device enrollment

Kipnerter iOS defaults to `https://api.kipnerter.com`. A finalized RoomPlan remains local until a spatial bearer token is present. If an unsynced finalized export exists and the token is missing, the app asks for the token once and stores it in the iOS Keychain. Per-room autosaves never trigger server completion.

For the first internal TestFlight validation:

1. deploy the production overlay and verify `/health/live` and `/health/ready`;
2. install/open the current internal TestFlight build;
3. capture and save one RoomPlan;
4. enter `KIPNERTER_SPATIAL_API_KEY` in the secure enrollment prompt;
5. verify the manifest progresses to `synced`;
6. verify Postgres contains the completed scan and processing report;
7. preserve a sanitized copy of the real RoomPlan JSON as the backend regression fixture.

## Rollback

The spatial databases/object volumes are persistent and are not removed by `docker compose up -d --remove-orphans`. An application rollback should deploy a previously validated platform + spatial backend SHA pair. Do not use `docker compose down -v` in production.
