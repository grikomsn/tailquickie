#!/bin/sh
set -eu

# Docker health checks get the original environment, not entrypoint exports.
address=${TS_LOCAL_ADDR_PORT:-0.0.0.0:${PORT:-8080}}
case "$address" in
    0.0.0.0:*|:*) address="127.0.0.1:${address##*:}" ;;
    \[::\]:*) address="[::1]:${address##*:}" ;;
esac

exec wget -q -T 4 -O /dev/null "http://$address/healthz"
