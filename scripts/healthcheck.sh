#!/bin/sh
set -eu

# Onboarding must stay healthy before the node joins the tailnet.
exec wget -q -T 4 -O /dev/null "http://127.0.0.1:${PORT:-8080}/healthz"
