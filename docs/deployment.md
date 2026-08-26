# Deployment preparation

No external deployment, account, DNS, upload or cloud resource was created during final hardening.

## Runtime contract

| Setting | Required value |
|---|---|
| Python | CPython 3.11; Docker pins 3.11.15 |
| Production image | `docker build -t card-testing-sentinel .` |
| Start command | `python scripts/run_app.py` |
| Bind address | `0.0.0.0:8000` |
| Required secret | `CTS_HMAC_SECRET`, private and at least 16 characters |
| Optional external-root override | `CTS_PROJECT_ROOT`; normally unnecessary because the image runs from `/app` |
| Readiness check | `GET /health/ready` |
| Liveness check | `GET /health/live` |
| Persistent mount | `/app/data/runtime` in the Docker image |
| Runtime lock | `requirements-runtime.lock` |

The same HMAC secret and SQLite volume must survive restarts. Changing the HMAC secret breaks protected-identifier continuity; losing the volume loses audit and causal state.

## SQLite constraints

This application must run as one process and one replica while it uses SQLite and the global transition lock. Mount a persistent disk at `/app/data/runtime`, enable provider-level backups or snapshots, and monitor free space. Do not run the image on an ephemeral filesystem: state will disappear on restart or redeploy.

The current Dockerfile runs as the non-root `sentinel` user. Confirm that the selected provider grants that UID write access to the mounted path before accepting traffic.

## Hosting options

- **Render Web Service with a persistent disk:** mount the disk at `/app/data/runtime`. Render documents that service filesystems are ephemeral by default and that persistent disks change deployment behavior, including losing normal zero-downtime deploys. See [Render deployment storage behavior](https://render.com/docs/deploys) and the [Blueprint disk reference](https://render.com/docs/blueprint-spec).
- **Railway service with a Volume:** mount the volume at `/app/data/runtime` and keep one replica. Railway documents that volumes persist across deploys/restarts, prevent replicas, and can cause brief deployment downtime. It also warns that non-root images may need explicit volume-permission handling. See [Railway Volumes](https://docs.railway.com/volumes/reference).
- **Fly.io single Machine with a Fly Volume:** mount a volume at `/app/data/runtime`, keep the SQLite writer on one Machine, and configure independent backups. Fly documents that Machine root filesystems are ephemeral, volumes are hardware-local, attach one-to-one to Machines, and are not automatically replicated. See [Fly Volumes](https://fly.io/docs/volumes/overview/).

Ephemeral-only serverless/container hosting is unsuitable for this SQLite build. For multiple replicas, high availability, cross-region service or production merchant traffic, migrate the repository/state contract to a transactional distributed store before deployment rather than sharing one SQLite file.

## Pre-deployment gate

Before any authorized deployment:

1. Inject `CTS_HMAC_SECRET` through the provider secret manager, never source control.
2. Attach and permission the persistent mount.
3. Start exactly one instance.
4. Require `/health/ready` to return HTTP 200 before routing traffic.
5. Run release verification inside the built image.
6. Exercise one normal and one burst sequence, then restart against the same disk and confirm recovery.
7. Configure volume backup/restore testing and operational monitoring.

External deployment requires separate explicit approval.
