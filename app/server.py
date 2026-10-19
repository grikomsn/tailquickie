#!/usr/bin/env python3
"""Password gate and process supervisor for Tailscale's native browser client."""

import base64
from collections import deque
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit


HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "authorization", "server",
}


class PasswordGate:
    def __init__(self, path):
        config = json.loads(Path(path).read_text())
        if config.get("algorithm") != "scrypt" or config.get("username") != "admin":
            raise ValueError("Invalid web-auth configuration; run scripts/setup-password.py --rotate")
        self.salt = base64.b64decode(config["salt"], validate=True)
        self.verifier = base64.b64decode(config["verifier"], validate=True)
        if len(self.salt) != 16 or len(self.verifier) != 32:
            raise ValueError("Invalid web-auth verifier")
        self.lock = threading.Lock()
        self.failures = deque()
        self.cache = {}
        self.cache_key = secrets.token_bytes(32)

    def authenticate(self, header):
        if not header or len(header) > 4096:
            return 401
        try:
            scheme, value = header.split(" ", 1)
            if scheme.lower() != "basic":
                return 401
            username, password = base64.b64decode(value, validate=True).decode().split(":", 1)
        except (ValueError, UnicodeError):
            return 401
        fingerprint = hmac.digest(self.cache_key, header.encode(), "sha256")
        now = time.monotonic()
        # Serialize scrypt so simultaneous password guesses cannot exhaust RAM.
        with self.lock:
            if self.cache.get(fingerprint, 0) > now:
                return 200
            while self.failures and self.failures[0] < now - 60:
                self.failures.popleft()
            if len(self.failures) >= 10:
                return 429
            candidate = hashlib.scrypt(password.encode(), salt=self.salt, n=16384, r=8, p=1, dklen=32)
            if hmac.compare_digest(candidate, self.verifier) and username == "admin":
                self.cache = {fingerprint: now + 900}
                return 200
            self.failures.append(now)
            return 401


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Services:
    def __init__(self):
        self.env = os.environ.copy()
        self.env.setdefault("TS_LOCAL_ADDR_PORT", f"127.0.0.1:{unused_port()}")
        health = urlsplit("http://" + self.env["TS_LOCAL_ADDR_PORT"])
        if health.hostname not in ("127.0.0.1", "::1", "localhost") or not health.port:
            raise ValueError("TS_LOCAL_ADDR_PORT must be a loopback address and port")
        self.health_host, self.health_port = health.hostname, health.port
        self.web_port = unused_port()
        self.socket = self.env.get("TS_SOCKET", "/var/run/tailscale/tailscaled.sock")
        self.stop = threading.Event()
        self.boot = self.web = None
        self.restarts = 0
        self.thread = threading.Thread(target=self.run, name="tailscale-services")

    @staticmethod
    def spawn(command, env):
        return subprocess.Popen(command, env=env, start_new_session=True)

    @staticmethod
    def terminate(process, timeout):
        if process is None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()

    def healthy(self):
        return all(p is not None and p.poll() is None for p in (self.boot, self.web))

    def run(self):
        next_boot = next_web = 0
        try:
            while not self.stop.wait(0.25):
                now = time.monotonic()
                if self.boot is not None and self.boot.poll() is not None:
                    self.restarts += 1
                    print("Bootstrap exited; retrying while the setup server stays available.", flush=True)
                    self.terminate(self.web, 3)
                    self.terminate(self.boot, 1)
                    self.boot = self.web = None
                    next_boot = now + 1
                if self.boot is None and now >= next_boot:
                    self.boot = self.spawn(["/usr/local/bin/containerboot"], self.env)
                if self.web is not None and self.web.poll() is not None:
                    self.web = None
                    next_web = now + 1
                if self.boot is not None and self.web is None and now >= next_web and Path(self.socket).exists():
                    self.web = self.spawn([
                        "tailscale", "--socket=" + self.socket, "web",
                        "--listen=127.0.0.1:" + str(self.web_port),
                    ], self.env)
        finally:
            self.terminate(self.web, 3)
            self.terminate(self.boot, 22)


class GateServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, password):
        self.password = password
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(address, GateHandler)
        # Bind the public listener before selecting private ports.
        self.services = Services()

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class GateHandler(BaseHTTPRequestHandler):
    server_version = "Tailquickie"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # Do not log authorization headers, query strings, or login URLs.
        print(f"web: {self.command} {urlsplit(self.path).path!r}", file=sys.stderr, flush=True)

    def reply(self, status, message, authenticate=False):
        body = message.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if authenticate:
            self.send_header("WWW-Authenticate", 'Basic realm="Tailquickie setup", charset="UTF-8"')
        if status == 429:
            self.send_header("Retry-After", "60")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        self.handle_request()

    do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_GET

    def handle_request(self):
        try:
            path = urlsplit(self.path)
            if not self.path.startswith("/") or path.netloc:
                return self.reply(400, "Invalid request target.\n")
            if path.path in ("/healthz", "/readyz") and self.command in ("GET", "HEAD"):
                if path.path == "/healthz":
                    healthy = self.server.services.healthy()
                    return self.reply(200 if healthy else 503, "ok\n" if healthy else "starting\n")
                return self.readiness()
            auth = self.server.password.authenticate(self.headers.get("Authorization"))
            if auth != 200:
                return self.reply(auth, "Setup password required.\n", authenticate=auth == 401)
            if path.path == "/status" and self.command in ("GET", "HEAD"):
                return self.status()
            if self.command not in ("GET", "HEAD", "OPTIONS"):
                try:
                    origin = urlsplit(self.headers.get("Origin", ""))
                except ValueError:
                    return self.reply(403, "Invalid origin.\n")
                if origin.scheme not in ("http", "https") or origin.netloc != self.headers.get("Host"):
                    return self.reply(403, "Cross-origin request denied.\n")
            return self.proxy()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True

    def readiness(self):
        services = self.server.services
        connection = http.client.HTTPConnection(services.health_host, services.health_port, timeout=2)
        try:
            connection.request("GET", "/healthz")
            status = connection.getresponse().status
        except (OSError, http.client.HTTPException):
            status = 503
        finally:
            connection.close()
        self.reply(200 if status == 200 else 503, "ready\n" if status == 200 else "not connected\n")

    def status(self):
        services = self.server.services
        status = {
            "bootstrap_running": services.boot is not None and services.boot.poll() is None,
            "web_running": services.web is not None and services.web.poll() is None,
            "bootstrap_restarts": services.restarts,
        }
        try:
            result = subprocess.run(
                ["tailscale", "--socket=" + services.socket, "status", "--json"],
                capture_output=True, text=True, timeout=3,
            )
            node = json.loads(result.stdout)
            status.update({
                "backend_state": node.get("BackendState"),
                "tailnet_ips": node.get("TailscaleIPs", []),
                "health": node.get("Health", []),
            })
        except (OSError, ValueError, subprocess.TimeoutExpired):
            status["backend_state"] = "Unavailable"
        body = (json.dumps(status, indent=2) + "\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def proxy(self):
        if self.headers.get("Transfer-Encoding"):
            return self.reply(400, "Chunked requests are not supported.\n")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.reply(400, "Invalid content length.\n")
        if not 0 <= length <= 65536:
            return self.reply(413, "Request body too large.\n")
        body = self.rfile.read(length) if length else None
        if body is not None and len(body) != length:
            return self.reply(400, "Incomplete request body.\n")
        excluded = HOP_HEADERS | {h.strip().lower() for h in self.headers.get("Connection", "").split(",")}
        headers = {k: v for k, v in self.headers.items() if k.lower() not in excluded}
        connection = http.client.HTTPConnection("127.0.0.1", self.server.services.web_port, timeout=30)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
        except (OSError, http.client.HTTPException):
            connection.close()
            return self.reply(503, "Tailscale's browser interface is starting. Retry shortly.\n")
        try:
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in HOP_HEADERS | {"cache-control", "referrer-policy"}:
                    self.send_header(key, value)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                while chunk := response.read(65536):
                    self.wfile.write(chunk)
        finally:
            connection.close()
            self.close_connection = True


def main():
    password = PasswordGate(Path(__file__).parent / "config/web-auth.json")
    server = GateServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), password)
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda signum, frame: stopped.set())
    server.services.thread.start()
    http_thread = threading.Thread(target=server.serve_forever, daemon=True)
    http_thread.start()
    print("Protected browser setup listening on port " + str(server.server_port), flush=True)
    stopped.wait()
    server.shutdown()
    server.server_close()
    server.services.stop.set()
    server.services.thread.join(30)


if __name__ == "__main__":
    main()
