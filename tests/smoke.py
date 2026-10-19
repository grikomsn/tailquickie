#!/usr/bin/env python3
"""Exercise browser onboarding without credentials or access to a real tailnet."""

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

IMAGE = os.environ.get("TEST_IMAGE", "tailquickie:test")
TEST_PASSWORD = "test-only-browser-password"
AUTH = "Basic " + base64.b64encode(("admin:" + TEST_PASSWORD).encode()).decode()
FLAGS = "--advertise-exit-node --accept-routes --ssh --login-server=http://127.0.0.1:9"


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=45)
    if check and result.returncode:
        raise AssertionError("Docker command failed:\n" + result.stdout + result.stderr)
    return result


class ContainerSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="tailquickie-tests-")
        cls.auth_file = Path(cls.temp.name) / "web-auth.json"
        salt = b"test-salt-16byte"
        cls.auth_file.write_text(json.dumps({
            "username": "admin", "algorithm": "scrypt",
            "salt": base64.b64encode(salt).decode(),
            "verifier": base64.b64encode(hashlib.scrypt(
                TEST_PASSWORD.encode(), salt=salt, n=16384, r=8, p=1, dklen=32
            )).decode(),
        }))
        cls.addClassCleanup(cls.temp.cleanup)

    def start_container(self, label, *extra, command=()):
        name = f"tailquickie-{label}-{os.getpid()}"
        self.addCleanup(docker, "rm", "-f", name, check=False)
        docker(
            "run", "-d", "--name", name, "--network", "none", "--cap-drop", "ALL",
            "-v", f"{self.auth_file}:/app/config/web-auth.json:ro",
            "-e", "PORT=10000", "-e", "TS_EXTRA_ARGS=" + FLAGS,
            *extra, IMAGE, *command,
        )
        return name

    def request(self, name, path="/", *, method="GET", headers=None, body=None):
        code = '''import http.client, json, sys
options=json.loads(sys.argv[1])
c=http.client.HTTPConnection("127.0.0.1",10000,timeout=35)
c.request(options["method"],options["path"],body=options["body"],headers=options["headers"])
r=c.getresponse()
print(json.dumps({"status":r.status,"headers":dict(r.getheaders()),"body":r.read().decode(errors="replace")}))
c.close()
'''
        result = docker("exec", name, "python3", "-c", code, json.dumps({
            "path": path, "method": method, "headers": headers or {}, "body": body,
        }), check=False)
        return json.loads(result.stdout) if result.returncode == 0 else {"status": 0, "body": result.stderr}

    def wait_for(self, name, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.2)
        logs = docker("logs", name)
        self.fail("Container did not become ready:\n" + logs.stdout + logs.stderr)

    def wait_for_ui(self, name):
        self.wait_for(name, lambda: self.request(name, headers={"Authorization": AUTH})["status"] == 200)

    def test_runtime_defaults_without_docker_env_metadata(self):
        output = docker("run", "--rm", "--network", "none", IMAGE, "env").stdout.splitlines()
        environment = dict(line.split("=", 1) for line in output)
        self.assertEqual(environment["PORT"], "8080")
        self.assertEqual(environment["TS_STATE_DIR"], "/var/lib/tailscale")
        self.assertEqual(environment["TS_USERSPACE"], "true")
        self.assertEqual(environment["TS_BOOT_TIMEOUT"], "24h")
        self.assertEqual(environment["TS_EXTRA_ARGS"], "--advertise-exit-node --accept-routes --ssh")
        self.assertNotIn("TS_AUTHKEY", environment)
        self.assertEqual(docker("run", "--rm", "--network", "none", "-e", "PORT=65535", IMAGE, "printenv", "PORT").stdout.strip(), "65535")

    def test_invalid_ports_fail_before_startup(self):
        for port in ("0", "65536", "nope", "-1", "99999999999999999999"):
            with self.subTest(port=port):
                result = docker("run", "--rm", "--network", "none", "-e", f"PORT={port}", IMAGE, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn("PORT must be an integer", result.stderr)

    def test_password_gate_native_ui_and_csrf(self):
        name = self.start_container("browser", "--memory", "128m")
        self.wait_for_ui(name)
        public = self.request(name)
        self.assertEqual(public["status"], 401)
        self.assertIn("Basic", public["headers"]["WWW-Authenticate"])
        self.assertEqual(self.request(name, "/api/data")["status"], 401)
        self.assertEqual(self.request(name, "/status")["status"], 401)
        self.assertEqual(self.request(name, headers={"Authorization": "Basic YWRtaW46d3Jvbmc="})["status"], 401)
        page = self.request(name, headers={"Authorization": AUTH})
        self.assertIn("<html", page["body"].lower())
        self.assertIn("no-store", page["headers"]["Cache-Control"])
        data = self.request(name, "/api/data", headers={"Authorization": AUTH})
        self.assertEqual(data["status"], 200)
        self.assertIsInstance(json.loads(data["body"]), dict)
        self.assertEqual(self.request(name, "/healthz")["status"], 200)
        self.assertEqual(self.request(name, "/readyz")["status"], 503)
        docker("exec", name, "/usr/local/bin/healthcheck.sh")
        denied = self.request(name, "/api/up", method="POST", headers={
            "Authorization": AUTH, "Origin": "https://someone-else.example",
        }, body="{}")
        self.assertEqual(denied["status"], 403)
        accepted = self.request(name, "/api/not-a-route", method="POST", headers={
            "Authorization": AUTH, "Host": "setup.example", "Origin": "https://setup.example",
            "Content-Type": "application/json",
        }, body="{}")
        self.assertEqual(accepted["status"], 404)
        responses = [self.request(name, headers={"Authorization": "Basic YWRtaW46d3Jvbmc="})["status"] for _ in range(11)]
        self.assertIn(429, responses)
        self.assertEqual(self.request(name, headers={"Authorization": AUTH})["status"], 200)
        docker("stop", "--time", "30", name)
        self.assertEqual(docker("inspect", "-f", "{{.State.ExitCode}}", name).stdout.strip(), "0")
        self.assertFalse(json.loads(docker("inspect", name).stdout)[0]["State"]["OOMKilled"])

    def test_pending_login_survives_bootstrap_timeout(self):
        name = self.start_container("timeout", "-e", "TS_BOOT_TIMEOUT=5s")
        self.wait_for_ui(name)

        def recovered():
            status = self.request(name, "/status", headers={"Authorization": AUTH})
            if status["status"] != 200 or json.loads(status["body"])["bootstrap_restarts"] == 0:
                return False
            return self.request(name, headers={"Authorization": AUTH})["status"] == 200

        self.wait_for(name, recovered)
        self.assertEqual(self.request(name, "/readyz")["status"], 503)

    def test_state_survives_container_replacement(self):
        volume = f"tailquickie-state-{os.getpid()}"
        docker("volume", "create", volume)
        self.addCleanup(docker, "volume", "rm", volume, check=False)
        name = self.start_container("state", "-v", f"{volume}:/var/lib/tailscale")
        self.wait_for_ui(name)

        def machine_key(container):
            return json.loads(docker("exec", container, "cat", "/var/lib/tailscale/tailscaled.state").stdout)["_machinekey"]

        key = machine_key(name)
        docker("stop", "--time", "30", name)
        docker("rm", name)
        replacement = self.start_container("replacement", "-v", f"{volume}:/var/lib/tailscale")
        self.wait_for_ui(replacement)
        self.assertEqual(machine_key(replacement), key)

    def test_openrc_service_launch(self):
        name = self.start_container("openrc", "--init", "--tmpfs", "/sys/fs/cgroup:mode=755", command=("/bin/sleep", "600"))
        setup = '''set -eu
cat > /app/start.sh <<'SCRIPT'
#!/bin/sh
exec /sbin/tini -s -- /usr/local/bin/entrypoint.sh python3 /app/server.py
SCRIPT
cat > /etc/init.d/tailquickie-app <<'SERVICE'
#!/sbin/openrc-run
command="/app/start.sh"
command_background=true
pidfile="/run/tailquickie-app.pid"
output_log="/tmp/tailquickie-app.log"
error_log="/tmp/tailquickie-app.log"
SERVICE
chmod +x /app/start.sh /etc/init.d/tailquickie-app
mkdir -p /run/openrc
touch /run/openrc/softlevel
rc-update add tailquickie-app default
rc-service tailquickie-app start
'''
        docker("exec", name, "/bin/sh", "-c", setup)
        self.wait_for_ui(name)
        self.assertEqual(self.request(name)["status"], 401)
        docker("exec", name, "rc-service", "tailquickie-app", "stop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
