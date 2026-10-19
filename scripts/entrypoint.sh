#!/bin/sh
set -eu

# Apply defaults here so Docker-to-Incus conversion cannot discard them.
export PORT="${PORT:-8080}"
export TS_USERSPACE="${TS_USERSPACE-true}"
export TS_STATE_DIR="${TS_STATE_DIR-/var/lib/tailscale}"
export TS_HOSTNAME="${TS_HOSTNAME-tailquickie}"
export TS_ACCEPT_DNS="${TS_ACCEPT_DNS-false}"
export TS_EXTRA_ARGS="${TS_EXTRA_ARGS---advertise-exit-node --accept-routes --ssh}"
export TS_ENABLE_HEALTH_CHECK="${TS_ENABLE_HEALTH_CHECK-true}"
export TS_ENABLE_METRICS="${TS_ENABLE_METRICS-false}"
export TS_AUTH_ONCE="${TS_AUTH_ONCE-true}"
export TS_KUBE_SECRET="${TS_KUBE_SECRET-}"
# The web supervisor restarts bootstrap if this timeout is ever reached.
export TS_BOOT_TIMEOUT="${TS_BOOT_TIMEOUT-24h}"

case "$PORT" in
    *[!0-9]*)
        echo "PORT must be an integer between 1 and 65535." >&2
        exit 1
        ;;
esac
if [ "${#PORT}" -gt 5 ] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "PORT must be an integer between 1 and 65535." >&2
    exit 1
fi

# The web supervisor owns the official containerboot and native web UI processes.
exec "$@"
