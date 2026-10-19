#!/usr/bin/env python3
"""Generate a setup password; commit its verifier, keep the password locally."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rotate", action="store_true", help="replace the existing setup password")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    config = root / "config/web-auth.json"
    credentials = root / ".tailquickie-credentials.txt"
    if not args.rotate and (config.exists() or credentials.exists()):
        parser.error("A setup password already exists. Use --rotate to replace it.")
    password = secrets.token_urlsafe(24)
    salt = secrets.token_bytes(16)
    verifier = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({
        "username": "admin",
        "algorithm": "scrypt",
        "salt": base64.b64encode(salt).decode(),
        "verifier": base64.b64encode(verifier).decode(),
    }, indent=2) + "\n")
    fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write("Tailquickie browser setup\nUsername: admin\nPassword: " + password + "\n")
        output.write("Keep this file private. It is ignored by Git and Docker.\n")
    print("Password verifier written to " + str(config))
    print("Private credentials written to " + str(credentials))


if __name__ == "__main__":
    main()
