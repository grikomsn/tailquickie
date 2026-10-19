#!/bin/sh
set -eu

# These are a boolean and a Kubernetes Secret name, not baked-in credentials.
export TS_AUTH_ONCE="${TS_AUTH_ONCE-true}"
export TS_KUBE_SECRET="${TS_KUBE_SECRET-}"

# Docker ENV cannot expand a port supplied by the PaaS at runtime.
if [ -z "${TS_LOCAL_ADDR_PORT:-}" ]; then
    port=${PORT:-8080}
    case "$port" in
        *[!0-9]*)
            echo "PORT must be an integer between 1 and 65535." >&2
            exit 1
            ;;
    esac
    if [ "${#port}" -gt 5 ] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
        echo "PORT must be an integer between 1 and 65535." >&2
        exit 1
    fi
    export TS_LOCAL_ADDR_PORT="0.0.0.0:$port"
fi

# Keep the official supervisor as PID 1 so it handles shutdown and state writes.
exec "$@"
