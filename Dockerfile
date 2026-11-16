# syntax=docker/dockerfile:1
FROM tailscale/tailscale:v1.104.7@sha256:72c1e19e0aedca96b8533bbb0b4368564410ff20b17e53b804eb6c1f04a31be4

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
