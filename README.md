# tailquickie

Deploy a Tailscale node from a Dockerfile and sign in through a password-protected browser UI. No auth key or environment variables are required.

Uses the official, digest-pinned Tailscale image with userspace networking. Exit-node advertising, subnet-route acceptance, and Tailscale SSH are enabled by default.

## Setup

Generate your setup password before the first build:

```sh
python3 scripts/setup-password.py --rotate
cat .tailquickie-credentials.txt
```

Commit the updated `config/web-auth.json`, which contains only a salted password verifier. Keep `.tailquickie-credentials.txt` private; Git and Docker ignore it. Run the same command to rotate the password.

## Deploy

1. Build from the root `Dockerfile` and keep its default start command.
2. Expose port **8080** (or `$PORT`) through **HTTPS**. Set the health-check path to **`/healthz`**.
3. Mount persistent storage at **`/var/lib/tailscale`**. Use one replica per state directory and keep the service running.
4. Open the service URL, enter username **`admin`** and your setup password, then follow the Tailscale sign-in flow.
5. Approve the exit node in the Tailscale admin console. SSH requires an access rule and an existing container user account.

Persistent storage retains the node's identity across restarts and redeployments. Other applications need their own Tailscale connection or a shared network namespace to use this node.

## Run locally

After setup:

```sh
docker compose up --build -d
# Open http://localhost:8080
```

Compose binds the UI to localhost and stores state in a named volume. `docker compose down` keeps it; adding `-v` deletes it and requires signing in again.

## Configuration

See [`.env.example`](.env.example) for optional settings and [Tailscale's Docker options](https://tailscale.com/docs/features/containers/docker/docker-params) for details. Compose reads `.env` when present.

- `TS_AUTHKEY`: optional automatic enrollment.
- `TS_HOSTNAME`: node name; defaults to `tailquickie`.
- `TS_EXTRA_ARGS`: replaces the default `--advertise-exit-node --accept-routes --ssh` flags.
- `TS_ROUTES`: optional subnet routes; requires admin approval.

With `TS_AUTH_ONCE=true` (the default), extra flags apply during login. For an enrolled node, use `tailscale set` to change those settings.

## Health and status

| Path | Access | Meaning |
| --- | --- | --- |
| `/` | Setup password | Tailscale web UI and sign-in. |
| `/healthz` | Public | Onboarding processes are running, even before login. |
| `/readyz` | Public | Node has a tailnet IP; returns `503` otherwise. |
| `/status` | Setup password | Backend state, IPs, health warnings, and bootstrap retries. |

After deploying, sign in, confirm the device in your tailnet, and test the intended peer or exit route. A healthy HTTP endpoint alone does not verify routing.

## Development

Requires Docker and Python 3:

```sh
docker build --check .
docker compose --env-file .env.example config --quiet
docker build -t tailquickie:test .
python3 tests/smoke.py
```

Smoke tests run offline and cover browser access, authentication, health checks, process supervision, state retention, and OpenRC startup. Real account enrollment and routing require deployment checks.

## License

[MIT](LICENSE)
