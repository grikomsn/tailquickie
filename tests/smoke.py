#!/usr/bin/env python3
"""Exercise the built image without credentials or access to a real tailnet."""

import json
import os
import subprocess
import time
import unittest


IMAGE = os.environ.get("TEST_IMAGE", "tailquickie:test")


def docker(*args, check=True):
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=45
    )
    if check and result.returncode:
        raise AssertionError("Docker command failed:\n" + result.stdout + result.stderr)
    return result


class ContainerSmokeTests(unittest.TestCase):
    def wait_for_readiness_server(self, name, port):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = docker(
                "exec", name, "wget", "-S", "-T", "1", "-O", "/dev/null",
                f"http://127.0.0.1:{port}/healthz", check=False
            )
            if "503 Service Unavailable" in result.stderr:
                return
            time.sleep(0.25)
        logs = docker("logs", name)
        self.fail("Readiness server did not start:\n" + logs.stdout + logs.stderr)

    def test_runtime_port_and_command_passthrough(self):
        for port in (None, "10000", "65535"):
            with self.subTest(port=port):
                env = [] if port is None else ["-e", f"PORT={port}"]
                result = docker(
                    "run", "--rm", "--network", "none", *env,
                    IMAGE, "printenv", "TS_LOCAL_ADDR_PORT"
                )
                self.assertEqual(result.stdout.strip(), f"0.0.0.0:{port or '8080'}")

    def test_invalid_ports_fail_before_startup(self):
        for port in ("0", "65536", "nope", "-1", "99999999999999999999"):
            with self.subTest(port=port):
                result = docker(
                    "run", "--rm", "--network", "none", "-e", f"PORT={port}",
                    IMAGE, check=False
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("PORT must be an integer", result.stderr)

    def test_explicit_health_address_takes_precedence(self):
        result = docker(
            "run", "--rm", "--network", "none",
            "-e", "PORT=unused", "-e", "TS_LOCAL_ADDR_PORT=127.0.0.1:9090",
            IMAGE, "printenv", "TS_LOCAL_ADDR_PORT"
        )
        self.assertEqual(result.stdout.strip(), "127.0.0.1:9090")

    def test_unprivileged_daemon_readiness_state_and_shutdown(self):
        name = f"tailquickie-smoke-{os.getpid()}"
        volume = f"{name}-state"
        docker("volume", "create", volume)
        self.addCleanup(docker, "volume", "rm", volume, check=False)
        self.addCleanup(docker, "rm", "-f", name, check=False)
        run_args = (
            "run", "-d", "--name", name, "--network", "none", "--cap-drop", "ALL",
            "-v", f"{volume}:/var/lib/tailscale", "-e", "PORT=10000",
            "-e", "TS_EXTRA_ARGS=--login-server=http://127.0.0.1:9", IMAGE
        )
        docker(*run_args)

        self.wait_for_readiness_server(name, 10000)
        self.assertEqual(docker("exec", name, "cat", "/proc/1/comm").stdout.strip(), "containerboot")
        self.assertNotEqual(docker("exec", name, "/usr/local/bin/healthcheck.sh", check=False).returncode, 0)
        metrics = docker(
            "exec", name, "wget", "-S", "-T", "1", "-O", "/dev/null",
            "http://127.0.0.1:10000/metrics", check=False
        )
        self.assertIn("404 Not Found", metrics.stderr)

        def machine_key():
            state = docker("exec", name, "cat", "/var/lib/tailscale/tailscaled.state")
            return json.loads(state.stdout)["_machinekey"]

        key = machine_key()
        self.assertTrue(key)
        docker("stop", "--time", "30", name)
        self.assertEqual(docker("inspect", "-f", "{{.State.ExitCode}}", name).stdout.strip(), "0")
        docker("rm", name)
        docker(*run_args)
        self.wait_for_readiness_server(name, 10000)
        self.assertEqual(machine_key(), key)

    def test_openrc_service_launch(self):
        """Simulate the service files a Docker-to-Incus converter generates."""
        name = f"tailquickie-openrc-{os.getpid()}"
        self.addCleanup(docker, "rm", "-f", name, check=False)
        docker(
            "run", "-d", "--init", "--name", name, "--network", "none", "--cap-drop", "ALL",
            # Writable scratch space for OpenRC, without emulating cgroup enforcement.
            "--tmpfs", "/sys/fs/cgroup:mode=755",
            "-e", "PORT=10000", "-e", "TS_HOSTNAME=openrc-smoke",
            "-e", "TS_EXTRA_ARGS=--login-server=http://127.0.0.1:9",
            IMAGE, "/bin/sleep", "600"
        )
        setup = '''set -eu
test "$PWD" = /app
test -d /etc/init.d
cat > /app/start.sh <<'SCRIPT'
#!/bin/sh
exec /usr/local/bin/entrypoint.sh /usr/local/bin/containerboot
SCRIPT
cat > /etc/init.d/dalang-app <<'SERVICE'
#!/sbin/openrc-run
command="/app/start.sh"
command_background=true
pidfile="/run/dalang-app.pid"
output_log="/tmp/dalang-app.log"
error_log="/tmp/dalang-app.log"
start_pre() {
    test "$PORT" = 10000 && test "$TS_HOSTNAME" = openrc-smoke
}
SERVICE
chmod +x /app/start.sh /etc/init.d/dalang-app
# Docker is not running an init system. Simulate its initialized runlevel.
mkdir -p /run/openrc
touch /run/openrc/softlevel
rc-update add dalang-app default
rc-service dalang-app start
'''
        docker("exec", name, "/bin/sh", "-c", setup)
        self.wait_for_readiness_server(name, 10000)
        docker("exec", name, "rc-service", "dalang-app", "status")
        docker("exec", name, "rc-service", "dalang-app", "stop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
