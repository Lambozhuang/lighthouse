#!/usr/bin/env python3
"""Create an app user from the command line of the machine that runs the stack.

    python3 scripts/create_user.py                 # asks for email and password
    python3 scripts/create_user.py you@example.com # asks for the password only

There is no sign-up form: Lighthouse is meant for its owner (and whoever they add), so accounts
are created here, with the service key that never leaves the server. The script talks to the
Supabase Auth admin API through the gateway on localhost, which works whether or not sign-up
is open. The password is read without echo and is never printed or stored by this script.

Standard library only, like gen_secrets.py.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        match = LINE.match(line)
        if match:
            env[match.group(1)] = match.group(2).strip().strip("'\"")
    return env


def create_user(base_url: str, service_key: str, email: str, password: str) -> str:
    """Create a confirmed user and return its id. Raises RuntimeError with the server's reason."""
    request = urllib.request.Request(
        f"{base_url}/auth/v1/admin/users",
        data=json.dumps({"email": email, "password": password, "email_confirm": True}).encode(),
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)["id"]
    except urllib.error.HTTPError as error:
        try:
            body = json.load(error)
            reason = body.get("msg") or body.get("message") or body.get("error_description") or str(body)
        except ValueError:
            reason = error.reason
        raise RuntimeError(f"{error.code}: {reason}") from None
    except urllib.error.URLError as error:
        raise RuntimeError(f"cannot reach the gateway at {base_url} ({error.reason}); is the stack up?") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Lighthouse user.")
    parser.add_argument("email", nargs="?")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()

    if not args.env_file.exists():
        print(f"{args.env_file} not found; run scripts/gen_secrets.py first.", file=sys.stderr)
        return 1
    env = read_env(args.env_file)
    service_key = env.get("SERVICE_ROLE_KEY")
    if not service_key:
        print("SERVICE_ROLE_KEY is empty; run scripts/gen_secrets.py first.", file=sys.stderr)
        return 1
    base_url = f"http://127.0.0.1:{env.get('GATEWAY_PORT') or '8000'}"

    email = args.email or input("Email: ").strip()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Password again: "):
        print("The two passwords differ; nothing was created.", file=sys.stderr)
        return 1

    try:
        user_id = create_user(base_url, service_key, email, password)
    except RuntimeError as error:
        print(f"Not created: {error}", file=sys.stderr)
        return 1
    print(f"Created {email} ({user_id}). Sign in with it in the web app.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
