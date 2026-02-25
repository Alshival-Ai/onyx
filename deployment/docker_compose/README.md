# Welcome to Onyx

To set up Onyx there are several options, Onyx supports the following for deployment:
1. Quick guided install via the install.sh script
2. Pulling the repo and running `docker compose up -d` from the deployment/docker_compose directory
  - Note, it is recommended to copy over the env.template file to .env and edit the necessary values
3. For large scale deployments leveraging Kubernetes, there are two options, Helm or Terraform.

This README focuses on the easiest guided deployment which is via install.sh.

**For more detailed guides, please refer to the documentation: https://docs.onyx.app/deployment/overview**

## install.sh script

```
curl -fsSL https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose/install.sh > install.sh && chmod +x install.sh && ./install.sh
```

This provides a guided installation of Onyx via Docker Compose. It will deploy the latest version of Onyx
and set up the volumes to ensure data is persisted across deployments or upgrades.

The script will create an onyx_data directory, all necessary files for the deployment will be stored in
there. Note that no application critical data is stored in that directory so even if you delete it, the
data needed to restore the app will not be destroyed.

The data about chats, users, etc. are instead stored as named Docker Volumes. This is managed by Docker
and where it is stored will depend on your Docker setup. You can always delete these as well by running
the install.sh script with --delete-data.

To shut down the deployment without deleting, use install.sh --shutdown.

### Upgrading the deployment
Onyx maintains backwards compatibility across all minor versions following SemVer. If following the install.sh script (or through Docker Compose), you can
upgrade it by first bringing down the containers. To do this, use `install.sh --shutdown`
(or `docker compose down` from the directory with the docker-compose.yml file).

After the containers are stopped, you can safely upgrade by either re-running the `install.sh` script (if you left the values as default which is latest,
then it will automatically update to latest each time the script is run). If you are more comfortable running docker compose commands, you can also run
commands directly from the directory with the docker-compose.yml file. First verify the version you want in the environment file (see below),
(if using `latest` tag, be sure to run `docker compose pull`) and run `docker compose up` to restart the services on the latest version

### Environment variables
The Docker Compose files try to look for a .env file in the same directory. The `install.sh` script sets it up from a file called env.template which is
downloaded during the initial setup. Feel free to edit the .env file to customize your deployment. The most important / common changed values are
located near the top of the file.

IMAGE_TAG is the version of Onyx to run. It is recommended to leave it as latest to get all updates with each redeployment.

## Enabling Craft in Source-Based Dev Deployments

If you are running from source with `docker-compose.yml` / `docker-compose.dev.yml` (instead of prebuilt `craft-latest` images), you must enable Craft in both runtime env and backend image build.

1. Set the following in `deployment/docker_compose/.env`:

```bash
ENABLE_CRAFT=true
CODE_INTERPRETER_BETA_ENABLED=true
CODE_INTERPRETER_BASE_URL=http://code-interpreter:8000
```

2. Rebuild backend images with Craft enabled at build-time (preferred via `tools/bake.sh`):

```bash
ENABLE_CRAFT=true ./tools/bake.sh backend --compose-restart --compose-file docker-compose.dev.yml
```

Compose fallback (equivalent explicit commands):

```bash
cd deployment/docker_compose
ENABLE_CRAFT=true docker compose -f docker-compose.yml -f docker-compose.dev.yml build api_server background mcp_server
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate api_server background mcp_server code-interpreter web_server nginx
```

3. Verify health:

```bash
docker exec onyx-api_server-1 env | grep -E 'ENABLE_CRAFT|CODE_INTERPRETER_BASE_URL'
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs --tail=120 code-interpreter
docker exec onyx-api_server-1 python -c "import urllib.request; print(urllib.request.urlopen('http://code-interpreter:8000/health').read().decode())"
```

Expected code-interpreter health response:

```json
{"status":"ok"}
```

Notes:
- The first Craft startup can take several minutes while template dependencies are prepared.
- In this dev stack, app traffic should be checked via the dev domain (`https://dev.starwoodgpt.prosourceit.app/`) instead of raw localhost routes.
- To force a one-time web template dependency refresh, set `CRAFT_FORCE_TEMPLATE_NPM_INSTALL=true` for the startup.

## Container Health Troubleshooting

### MinIO healthcheck

Some MinIO images do not include `curl`, so using `curl -f http://localhost:9000/minio/health/live`
in compose healthchecks can mark an otherwise healthy MinIO container as `unhealthy`.

This repo now uses:

```yaml
healthcheck:
  test: ["CMD", "mc", "ready", "local"]
```

for MinIO healthchecks in compose files.

### Vespa configserver lock / stale session recovery

If `index` stays unhealthy and logs show errors like lock timeouts or remote session load failures
from Vespa configserver, you can recover by resetting Vespa configserver and ZooKeeper state.

1. Stop dependent containers (`index`, and usually `api_server`).
2. Back up the Vespa volume paths before any change.
3. Reset:
   - `/vespa/db/vespa/config_server`
   - `/vespa/zookeeper/version-2`
4. Start `index` again, then restart `api_server` and `nginx`.

Example (replace volume name if different):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml stop index api_server
docker run --rm -v onyx_vespa_volume:/vespa alpine sh -lc '
  ts=$(date +%Y%m%d%H%M%S)
  backup=/vespa/recovery-backup-$ts
  mkdir -p "$backup"
  cp -a /vespa/db/vespa/config_server "$backup"/config_server || true
  cp -a /vespa/zookeeper/version-2 "$backup"/zookeeper-version-2 || true
  rm -rf /vespa/db/vespa/config_server /vespa/zookeeper/version-2
'
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d index api_server nginx
```
