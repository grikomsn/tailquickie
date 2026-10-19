# tailquickie

Deploy a standalone Tailscale node from this repository to a Docker-capable PaaS. Set an auth key, attach a state volume, and deploy. The image runs the official Tailscale supervisor with userspace networking, so it needs no privileged mode, `NET_ADMIN`, or `/dev/net/tun`.

Based on [`tailscale/tailscale:v1.104.1`](https://github.com/tailscale/tailscale/releases/tag/v1.104.1), the latest stable release checked on October 19, 2026. The Dockerfile pins the multi-platform image digest. Dependabot checks for image and GitHub Actions updates weekly.

## Deploy

1. Generate an [auth key](https://tailscale.com/docs/features/access-control/auth-keys) in your Tailscale admin console. For a lasting node, leave **Ephemeral** off. Use a tagged key for a server, and enable **Pre-approved** if your tailnet requires device approval. A single-use key works with persistent state; a reusable key also permits recovery if that state is lost.
2. Connect this repository to a PaaS as a Docker service. Use the root `Dockerfile` and its default start command.
3. Set `TS_AUTHKEY` as a runtime secret and choose `TS_HOSTNAME`, for example `tailquickie-singapore`. Never supply the key as a build argument or commit it.
4. Mount a persistent volume at **`/var/lib/tailscale`**. Run **one replica per volume**; each independent node needs its own state and hostname. Keep the service always running and disable scale-to-zero or sleeping.
5. Configure an HTTP health check at **`/healthz`** on the platform's `PORT` (defaults to `8080`). Allow at least 60 seconds for startup. Confirm the hostname appears online in the Tailscale admin console.

Only the health endpoint needs the platform's HTTP listener; no public domain or inbound Tailscale port is required. Outbound internet access to Tailscale's control/relay services is required. Restricted UDP can force relayed connections; see [Tailscale connection types](https://tailscale.com/docs/reference/connection-types).

### Railway

Import the GitHub repository, set `TS_AUTHKEY` and `TS_HOSTNAME`, and add a volume mounted at `/var/lib/tailscale` **before the first successful deployment**. `railway.json` selects the Dockerfile, `/healthz`, and restart-on-failure with up to ten retries. Leave the start command unset. Railway supplies `PORT`; you can also set it explicitly to `8080`.

Volume creation and secrets are dashboard steps, not provisions in `railway.json`. Railway checks readiness during deployment only; use separate monitoring if you need ongoing alerts. See [config as code](https://docs.railway.com/config-as-code/reference) and [health checks](https://docs.railway.com/deployments/healthchecks).

### Render

Create a **Blueprint** from this repository. `render.yaml` creates the Docker web service and a 1 GB state disk, and prompts for `TS_AUTHKEY`. Set a distinct `TS_HOSTNAME` if deploying multiple services.

The Blueprint selects the paid `0.5c-512mb` plan because persistent disks require a paid service. Review the plan and storage charges before creating it. The service uses Render's `PORT` and `/healthz`. A disk-backed service has brief downtime during deployments. See [Blueprint configuration](https://render.com/docs/blueprint-spec), [compute plans](https://render.com/docs/compute-plans), and [persistent disks](https://render.com/docs/disks).

### Other platforms

Use a long-running Docker service or worker with a persistent filesystem and outbound network access. Supply the secret and volume above. For an HTTP service, configure its health path explicitly: `/` intentionally returns `404`. For workers, the HTTP port need not be published. Request-based serverless services that suspend the container are a poor fit for an always-online node.

If persistence is unavailable, use a **reusable, ephemeral** auth key instead. Each new filesystem registers a fresh node, so its IP/identity can change; the offline ephemeral device is later removed. This is an alternative deployment model, not a persistent node.

### Dalang / Docker-to-Incus hosts

Dalang's deployment log shows it extracts the Docker image into an Incus system container and creates `/etc/init.d/dalang-app` and `/app/start.sh`. The official Tailscale image lacks `/app` and OpenRC. This project's image includes OpenRC and uses `/app` as its working directory so those startup files can be created. OpenRC preserves the container's runtime environment, including Tailscale credentials and `PORT`, when launching the service. Normal Docker deployments still start `containerboot` directly as PID 1.

Keep the detected start command `/usr/local/bin/entrypoint.sh /usr/local/bin/containerboot`, set the application's port to `8080`, supply `TS_AUTHKEY` as a runtime variable, and retain `/var/lib/tailscale` across deployments. If the platform does not preserve Docker `ENV` metadata during conversion, explicitly set `TS_STATE_DIR=/var/lib/tailscale`, `TS_USERSPACE=true`, and `TS_ENABLE_HEALTH_CHECK=true` in its runtime settings as well.

The log's `HEALTHCHECK is not supported for OCI image format` warning means the builder discarded Docker's health-check metadata; configure the platform's HTTP probe to request `/healthz` separately. A request to `/` returns `404`. The storage-limit warning about overriding a profile device is a separate host configuration issue. A successful image import or proxy registration does not confirm the application started: check `/healthz` and the Tailscale admin console after redeploying.

The regression test simulates OpenRC service creation, registration, startup, and shutdown inside Docker. It does not reproduce Dalang's full Incus conversion, cgroup delegation, runtime-variable injection, or actual tailnet enrollment. See [Alpine OpenRC documentation](https://wiki.alpinelinux.org/wiki/OpenRC) for the service manager used by this compatibility layer.

## Run locally

```sh
cp .env.example .env
# Edit .env and replace TS_AUTHKEY.
docker compose up --build -d
docker compose logs -f
```

```sh
curl --fail http://127.0.0.1:8080/healthz
docker compose exec tailscale tailscale status
docker compose exec tailscale tailscale ip -4
```

Compose publishes the health port on localhost and stores identity in a named volume. `docker compose down` retains it; `docker compose down -v` deletes it and the next start needs a valid enrollment key.

## Configuration

All official [Tailscale Docker environment variables](https://tailscale.com/docs/features/containers/docker/docker-params) pass through unchanged. `.env.example` includes common optional settings. Compose loads `.env`; hosted services use their own runtime variables.

| Variable | Project default | Purpose |
| --- | --- | --- |
| `TS_AUTHKEY` | unset | Enrollment secret for a new node; stored state can authenticate subsequent starts. |
| `TS_HOSTNAME` | `tailquickie` | Name shown in the tailnet. |
| `TS_STATE_DIR` | `/var/lib/tailscale` | Persistent identity directory; match your volume mount if changed. |
| `TS_AUTH_ONCE` | `true` | Reuse authenticated state on restart. |
| `TS_USERSPACE` | `true` | Run without a kernel tunnel device. |
| `TS_ACCEPT_DNS` | `false` | Keep the platform's resolver. |
| `PORT` | `8080` | Runtime HTTP health port. |
| `TS_LOCAL_ADDR_PORT` | `0.0.0.0:$PORT` | Explicit override for the health listener; match the PaaS health port. |
| `TS_ENABLE_HEALTH_CHECK` | `true` | Enable readiness checks; keep enabled for the supplied Docker/PaaS checks. |
| `TS_ENABLE_METRICS` | `false` | Keep unauthenticated `/metrics` disabled on the HTTP listener. |

`/healthz` returns `200` when the node has a tailnet IP and `503` before that. It does not prove connectivity to another peer. The public listener exposes readiness only by default; it is not a Tailscale proxy or dashboard.

After successful enrollment, you may remove `TS_AUTHKEY` while retaining the state volume. State contains private keys: protect it as a secret, do not share it between running instances, and back it up securely. If you revoke the node, lose state, or need to reauthenticate, provide a valid key again.

### Exit nodes and subnet routes

The default is an ordinary node. To offer internet egress, set:

```dotenv
TS_EXTRA_ARGS=--advertise-exit-node
```

Approve the exit node in the Tailscale admin console, then select it on your client. To advertise a network reachable **from this container**, set `TS_ROUTES=10.0.0.0/24` and approve the route. Tailnet access rules and provider networking restrictions still apply. To combine flags, put them in the same `TS_EXTRA_ARGS` value, for example `--advertise-exit-node --advertise-tags=tag:server`.

Set `TS_EXTRA_ARGS` before first enrollment. With `TS_AUTH_ONCE=true`, upstream only applies those extra flags during login; changing them on an already-enrolled volume does not rerun login. For an existing node, use the service's shell to run `tailscale set --advertise-exit-node=true` (locally: `docker compose exec tailscale tailscale set --advertise-exit-node=true`). `TS_HOSTNAME`, `TS_ACCEPT_DNS`, and `TS_ROUTES` do update on restart. See the [pinned upstream startup code](https://github.com/tailscale/tailscale/blob/v1.104.1/cmd/containerboot/tailscaled.go).

[Userspace routers](https://tailscale.com/docs/reference/kernel-vs-userspace-routers) support TCP/UDP forwarding and relayed pings, with limitations for other protocols. For heavier routing workloads, use a host that supports kernel networking: set `TS_USERSPACE=false`, expose `/dev/net/tun`, grant the required network capabilities, and configure IP forwarding. The supplied PaaS configs use userspace mode.

### Accessing services

This repository deploys the node itself. To reach another tailnet service from an application in the same container/network namespace, enable `TS_SOCKS5_SERVER=127.0.0.1:1055` or `TS_OUTBOUND_HTTP_PROXY_LISTEN=127.0.0.1:1055` and configure that application's proxy settings. [Userspace networking](https://tailscale.com/docs/concepts/userspace-networking) does not transparently route every process's outbound traffic.

For inbound access, add your application and configure [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve) using `TS_SERVE_CONFIG`. A separately deployed PaaS service does not automatically share this node's network. Keep unauthenticated proxy listeners off the public internet.

## Verify and update

Requires Docker and Python 3, with no Tailscale credentials:

```sh
docker build --check .
docker compose --env-file .env.example config --quiet
docker build -t tailquickie:test .
python3 tests/smoke.py
```

The smoke test checks port handling, command passthrough, daemon startup with all Linux capabilities dropped, readiness failure before login, disabled metrics, state retention, clean shutdown, and OpenRC service launches. It runs without network access and does not authenticate against a live tailnet. After deployment, verify a real enrollment, restart with the same volume, and test the peer or exit route you intend to use.

To update Tailscale, verify the current stable release and multi-platform digest, change the Dockerfile's tag and digest together, run these checks, and redeploy with the existing state volume.

## Sources

Research checked on October 19, 2026:

- [Official Docker image and tags](https://hub.docker.com/r/tailscale/tailscale)
- [Tailscale standalone Docker guide](https://tailscale.com/docs/features/containers/docker/how-to/connect-docker-standalone)
- [Tailscale Docker configuration](https://tailscale.com/docs/features/containers/docker/docker-params)
- [Existing Render Tailscale template](https://render.com/templates/tailscale)
- [Existing Railway Tailscale template](https://railway.com/deploy/tailscale-1)

These templates informed the deployment pattern; this project uses the official image and supervisor directly.
