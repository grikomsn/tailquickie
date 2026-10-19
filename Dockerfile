# syntax=docker/dockerfile:1
FROM tailscale/tailscale:v1.104.1@sha256:87c55d6be56ad85b3d8bceca5f87f73de288c609131460dd1be1874c250cc41d

# Support service-based startup as well as Docker.
RUN apk add --no-cache openrc python3 tini && \
    printf '\nrc_env_allow="*"\n' >> /etc/rc.conf

WORKDIR /app

COPY --chmod=755 scripts/entrypoint.sh scripts/healthcheck.sh /usr/local/bin/
COPY app/ /app/
COPY config/web-auth.json /app/config/web-auth.json
COPY LICENSE /app/LICENSE

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["/sbin/tini", "-s", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["python3", "/app/server.py"]
