# syntax=docker/dockerfile:1
FROM tailscale/tailscale:v1.104.4@sha256:ed6480b33c6eb67c9cbd203ed42b9fb57e361986725b6856def71b7a3d9e276c

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
