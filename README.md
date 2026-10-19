# tailquickie

Deploy a Tailscale node to a Docker-capable PaaS and sign it in through your browser. No PaaS environment editor or Tailscale auth key is required. The public page is protected with a separate setup password.

The image uses the official, digest-pinned [`tailscale/tailscale:v1.104.1`](https://github.com/tailscale/tailscale/releases/tag/v1.104.1), checked on October 19, 2026. Userspace networking needs no privileged mode, `NET_ADMIN`, or `/dev/net/tun`. Exit-node advertising, accepting subnet routes, and Tailscale SSH remain enabled by default.

## Deploy and sign in

1. Connect this repository to your PaaS using the root `Dockerfile`. Keep its detected start command. The application listens on port **8080**, or the platform's `PORT` when provided.
2. Publish the service through the platform's **HTTPS** URL. Use **`/healthz`** for its HTTP health check.
3. Open that URL. Your browser prompts for username **`admin`** and the generated setup password. For this checkout, the password is in **`.tailquickie-credentials.txt`**, a private local file ignored by Git and Docker.
4. The page behind that password is Tailscale's native web client. Choose **Connect** or **Sign in** and follow the Tailscale login link to authorize the node in your tailnet. This signs the node in without `TS_AUTHKEY`.
5. Confirm the node is online in the Tailscale admin console. Approve its exit-node advertisement before selecting it on a client. Tailscale SSH also needs an appropriate SSH access rule and an existing user account in the container.
6. Preserve **`/var/lib/tailscale`** across restarts and redeployments. Each node needs its own state directory and one running instance. Keep the service always running, with sleeping or scale-to-zero disabled.

The setup password protects this public device-login interface; your Tailscale account login authorizes the device itself. Use HTTPS for a remote deployment. The local loopback URL can use HTTP for development.

## Setup password

Only a salted scrypt password verifier is committed in `config/web-auth.json`. The plaintext password is generated locally and written to `.tailquickie-credentials.txt` with owner-only permissions. It is not included in the image or Git history.

If you fork or clone the project and do not have its setup password, generate your own **before building or deploying**:

```sh
python3 scripts/setup-password.py --rotate
cat .tailquickie-credentials.txt
```

Commit the updated `config/web-auth.json` and rebuild. Keep the plaintext credentials file private. Rotation changes the setup password without deleting the node's Tailscale identity. Existing browser credentials may need to be replaced when the browser prompts again.

The gateway requires the password for the native web UI, its APIs, and `/status`. It limits concurrent requests and failed password attempts, and rejects cross-origin writes. Native UI and daemon-health listeners bind only to loopback. No first-visitor signup or publicly readable login link is exposed.

## Health and diagnostics

| Path | Access | Meaning |
| --- | --- | --- |
| `/` | Setup password | Native Tailscale browser client and interactive login. |
| `/healthz` | Public | `200` when bootstrap and the native UI processes are running; suitable for deployment checks before login. |
| `/readyz` | Public | `200` once Tailscale reports a tailnet IP, otherwise `503`. It does not prove peer or exit-route connectivity. |
| `/status` | Setup password | Backend state, tailnet IPs, health warnings, and bootstrap restart count. Useful when the platform has no runtime logs. |

**The meaning of `/healthz` changed:** it now checks onboarding availability, so the PaaS does not kill a deployment while you are signing in. Use `/readyz` to monitor enrollment separately.

The supervisor runs the official `containerboot` and `tailscale web` together. Bootstrap gets a 24-hour login window and restarts if it exits, while the password gate stays available. A small init process reaps child processes and forwards shutdown signals. No Tailscale key is baked into the Dockerfile.

## Dalang / Docker-to-Incus hosts

Dalang converts the Docker root filesystem into an Incus system container and generates OpenRC service files. The image includes OpenRC and `/app`. Startup defaults live in the entrypoint script, so they still apply if conversion drops Docker's `ENV` metadata. OpenRC preserves the runtime environment.

Redeploy the latest commit and let Dalang detect the new command:

```text
/sbin/tini -s -- /usr/local/bin/entrypoint.sh python3 /app/server.py
```

Keep the public port at **8080**, open the HTTPS URL, enter the setup password, and use the native Tailscale login page. No dashboard environment fields are needed. The Incus container's filesystem may survive a restart, but identity retention across a redeploy still depends on Dalang preserving `/var/lib/tailscale`.

Dalang's `HEALTHCHECK is not supported for OCI image format` warning means it discarded Docker's health-check metadata. Configure the HTTP probe at `/healthz` if the platform supports it. Its storage-limit warning about overriding a profile device is a separate host configuration issue.

A service-start success message does not prove the process stayed alive. If the URL returns `502`, first confirm Dalang deployed the new command rather than its previously cached command. Once the gate loads, `/status` provides diagnostics without a platform log viewer.

## Railway and Render

`railway.json` selects the Dockerfile and `/healthz`. Add a persistent volume at `/var/lib/tailscale`; secrets and volume creation remain dashboard settings. A public HTTPS domain is needed for browser onboarding. Railway only checks health during deployment. See [Railway configuration](https://docs.railway.com/config-as-code/reference) and [health checks](https://docs.railway.com/deployments/healthchecks).

For Render, create a Blueprint from this repository. `render.yaml` creates the service with a 1 GB state disk and `/healthz`. It does not prompt for a Tailscale key. The paid `0.5c-512mb` plan is selected because persistent disks require paid services; review its charges before creating it. See [Render Blueprints](https://render.com/docs/blueprint-spec) and [persistent disks](https://render.com/docs/disks).

## Run locally

For a new clone, generate a password as described above. Then:

```sh
docker compose up --build -d
# Open http://localhost:8080 and use the setup credentials.
curl --fail http://localhost:8080/healthz
docker compose exec tailscale tailscale status
```

Compose publishes the public UI only on loopback and uses a named volume for state. `.env` is optional. `docker compose down` retains identity; `docker compose down -v` deletes the volume and requires a new device login.

## Optional environment settings

Platforms with runtime variables can still use the official [Tailscale Docker options](https://tailscale.com/docs/features/containers/docker/docker-params). `.env.example` documents common choices. No values are required for browser onboarding.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8080` | Public password-gated UI and health endpoints. |
| `TS_AUTHKEY` | unset | Optional automatic enrollment instead of interactive login. |
| `TS_HOSTNAME` | `tailquickie` | Name shown in the tailnet. |
| `TS_STATE_DIR` | `/var/lib/tailscale` | Persistent identity directory; match your volume if changed. |
| `TS_USERSPACE` | `true` | Avoid a kernel tunnel device. |
| `TS_AUTH_ONCE` | `true` | Reuse authenticated state on restart. |
| `TS_ACCEPT_DNS` | `false` | Keep the platform's resolver. |
| `TS_EXTRA_ARGS` | `--advertise-exit-node --accept-routes --ssh` | Default node features. |
| `TS_BOOT_TIMEOUT` | `24h` | Login/bootstrap timeout before the web supervisor retries. |
| `TS_ENABLE_HEALTH_CHECK` | `true` | Keep enabled for `/readyz`. |
| `TS_ENABLE_METRICS` | `false` | Keep daemon metrics disabled. |

`TS_LOCAL_ADDR_PORT` is selected automatically on loopback for internal readiness checks. If overridden, it must remain a loopback address and use a different port from the public UI. The native web client uses another private port selected automatically.

`TS_EXTRA_ARGS` replaces all default flags. With `TS_AUTH_ONCE=true`, upstream applies those flags during login, not on every restart. For an already-enrolled node, use `tailscale set --advertise-exit-node --accept-routes --ssh` if you need to apply them. `TS_HOSTNAME`, `TS_ACCEPT_DNS`, and `TS_ROUTES` update on restart. See the [pinned startup implementation](https://github.com/tailscale/tailscale/blob/v1.104.1/cmd/containerboot/tailscaled.go).

To advertise a subnet reachable from the container, set `TS_ROUTES=10.0.0.0/24` and approve it in the admin console. Userspace routers support TCP/UDP forwarding and relayed pings, with limitations for other protocols. See [userspace routing](https://tailscale.com/docs/reference/kernel-vs-userspace-routers). An application in a separate PaaS service does not automatically share this node's network.

## Verification

Requires Docker and Python 3, without a real Tailscale account or enrollment key:

```sh
docker build --check .
docker compose --env-file .env.example config --quiet
docker build -t tailquickie:test .
python3 tests/smoke.py
```

Tests exercise the real native web client, password protection, API access, cross-origin rejection, failed-login limiting, pre-login liveness, readiness failure, bootstrap retries, state retention, shutdown, and simulated OpenRC startup. One browser test runs with a 128 MiB memory limit. These isolated tests have no network access and do not prove real account enrollment, live Incus conversion, or performance under routing load.

After deploying, finish a real browser login, confirm the device in your tailnet, restart it with the same state, and test your intended peer or exit route. Dependabot checks the pinned image and GitHub Actions weekly.

## Sources

- [Tailscale device web interface](https://tailscale.com/docs/features/client/device-web-interface)
- [Tailscale CLI web command](https://tailscale.com/docs/reference/tailscale-cli#web)
- [Tailscale Docker configuration](https://tailscale.com/docs/features/containers/docker/docker-params)
- [Alpine OpenRC](https://wiki.alpinelinux.org/wiki/OpenRC)
