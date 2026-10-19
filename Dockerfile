# syntax=docker/dockerfile:1
FROM tailscale/tailscale:v1.104.1@sha256:87c55d6be56ad85b3d8bceca5f87f73de288c609131460dd1be1874c250cc41d

ENV TS_USERSPACE=true \
    TS_STATE_DIR=/var/lib/tailscale \
    TS_HOSTNAME=tailquickie \
    TS_ACCEPT_DNS=false \
    TS_ENABLE_HEALTH_CHECK=true \
    TS_ENABLE_METRICS=false

COPY --chmod=755 scripts/entrypoint.sh scripts/healthcheck.sh /usr/local/bin/

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/usr/local/bin/containerboot"]
