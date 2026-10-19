# Kipnerter 1.7 — exact live Docker image rollback footprint

As a prerequisite to a reversible legacy Compose cutover, verify that all seven currently running portal, gateway, Caddy, spatial worker/API, PostgreSQL and MinIO containers still have retrievable immutable image IDs on the production Docker daemon. The separately verified prior production baseline was `f33dec732dcdadb246278c257f7dfbb22682b8aa333b22cc1c6e310167e489c7`; do not infer a Git source SHA from this image fingerprint.

This owner-only workflow uses Tailscale's existing production-scoped CI principal, with read-only `docker inspect`/image-size metadata only. It reads **no** container environment values, Docker image layer contents, SQL rows, MinIO objects or private .env files. It does not invoke Docker save, load, build, run or restart, and writes nothing to production. It reports logical image-size ceilings and free disk capacity, not a measured tarball size or a restorable image archive.

Even a passing capacity result is not permission to replace the live web/API containers. An immutable, access-controlled backup of old OCI images, independently verified DB/MinIO backup custody and successful restore, OIDC/operator allowlists, and an explicitly approved legacy→managed migration must still be established before cutover.
