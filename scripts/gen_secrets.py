#!/usr/bin/env python3
"""Fill in the generated secrets in `.env`.

    python3 scripts/gen_secrets.py            # creates .env from .env.example if needed
    python3 scripts/gen_secrets.py --env-file path/to/.env

Only variables that are missing or empty are filled in. Values that are already set are never
changed and never printed: the output is just the *names* of the variables that were added, so
it is safe to run in a shared terminal or in CI logs. Running it twice changes nothing the
second time.

Standard library only, so it runs before any dependency is installed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import string
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALPHANUMERIC = string.ascii_letters + string.digits
TEN_YEARS = 10 * 365 * 24 * 3600

# KEY=value, optionally prefixed with `export`. Comment lines do not match.
LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def password(length: int = 32) -> str:
    """Letters and digits only, so the value needs no escaping in URLs, YAML or shell."""
    return "".join(secrets.choice(ALPHANUMERIC) for _ in range(length))


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_jwt(claims: dict[str, object], secret: str) -> str:
    """An HS256 JSON Web Token: base64url(header).base64url(claims).base64url(HMAC-SHA256)."""
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join(b64url(json.dumps(part, separators=(",", ":")).encode()) for part in (header, claims))
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{b64url(signature)}"


def jwt_role(token: str, secret: str) -> str | None:
    """The `role` claim if `token` is a valid HS256 JWT for `secret`, else None."""
    try:
        signing_input, signature = token.rsplit(".", 1)
        expected = b64url(hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = signing_input.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("role")
    except (ValueError, IndexError, AttributeError):
        return None


def api_key(role: str) -> Callable[[dict[str, str]], str]:
    """A Supabase API key: a long-lived JWT whose only job is to name a Postgres role."""

    def make(env: dict[str, str]) -> str:
        now = int(time.time())
        return sign_jwt({"role": role, "iss": "supabase", "iat": now, "exp": now + TEN_YEARS}, env["JWT_SECRET"])

    return make


# Every generated variable, in dependency order: a generator may read the ones above it.
GENERATED: list[tuple[str, Callable[[dict[str, str]], str]]] = [
    # Supabase
    ("POSTGRES_PASSWORD", lambda env: password(32)),
    ("JWT_SECRET", lambda env: password(64)),
    ("ANON_KEY", api_key("anon")),
    ("SERVICE_ROLE_KEY", api_key("service_role")),
    ("DASHBOARD_PASSWORD", lambda env: password(24)),
    ("PG_META_CRYPTO_KEY", lambda env: password(48)),
    # Lighthouse backend when it runs on the host instead of in compose
    ("DATABASE_URL", lambda env: f"postgresql://postgres:{env['POSTGRES_PASSWORD']}@localhost:5432/postgres"),
    # Web app: the anon key is public by design, the browser needs it
    ("VITE_SUPABASE_ANON_KEY", lambda env: env["ANON_KEY"]),
    # Langfuse: the project key pair is provisioned on first start and used by the backend
    ("LANGFUSE_PUBLIC_KEY", lambda env: f"pk-lf-{uuid.uuid4()}"),
    ("LANGFUSE_SECRET_KEY", lambda env: f"sk-lf-{uuid.uuid4()}"),
    ("LANGFUSE_INIT_USER_PASSWORD", lambda env: password(24)),
    ("LANGFUSE_NEXTAUTH_SECRET", lambda env: password(48)),
    ("LANGFUSE_SALT", lambda env: password(48)),
    ("LANGFUSE_ENCRYPTION_KEY", lambda env: secrets.token_hex(32)),  # must be 64 hex characters
    ("LANGFUSE_POSTGRES_PASSWORD", lambda env: password(32)),
    ("LANGFUSE_CLICKHOUSE_PASSWORD", lambda env: password(32)),
    ("LANGFUSE_REDIS_PASSWORD", lambda env: password(32)),
    ("LANGFUSE_MINIO_PASSWORD", lambda env: password(32)),
]


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value.split(" #", 1)[0].strip()  # unquoted values may carry a trailing comment


def parse(lines: list[str]) -> tuple[dict[str, str], dict[str, int]]:
    """Values by name, and the line each name was last set on."""
    values: dict[str, str] = {}
    positions: dict[str, int] = {}
    for index, line in enumerate(lines):
        match = LINE.match(line)
        if match:
            values[match.group(1)] = unquote(match.group(2))
            positions[match.group(1)] = index
    return values, positions


def consistency_warnings(env: dict[str, str]) -> list[str]:
    """Things that were already set but do not fit together. Names only, never values."""
    warnings: list[str] = []
    for name, role in (("ANON_KEY", "anon"), ("SERVICE_ROLE_KEY", "service_role")):
        if jwt_role(env[name], env["JWT_SECRET"]) != role:
            warnings.append(f"{name} is not a token for role '{role}' signed with JWT_SECRET; clear it and run again")
    if env["VITE_SUPABASE_ANON_KEY"] != env["ANON_KEY"]:
        warnings.append("VITE_SUPABASE_ANON_KEY differs from ANON_KEY; the web app will be rejected by the gateway")
    if len(env["JWT_SECRET"]) < 40:
        warnings.append("JWT_SECRET is shorter than 40 characters")
    if "@localhost" in env["DATABASE_URL"] and env["POSTGRES_PASSWORD"] not in env["DATABASE_URL"]:
        warnings.append(
            "DATABASE_URL does not use POSTGRES_PASSWORD; running the backend on the host will fail to connect "
            "(inside docker compose it is overridden, so that still works)"
        )
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill in the generated secrets in .env.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env", help="file to fill in (default: .env)")
    args = parser.parse_args()
    env_file: Path = args.env_file
    example = ROOT / ".env.example"

    if env_file.exists():
        text = env_file.read_text()
    elif example.exists():
        text = example.read_text()
        print(f"created {env_file.name} from {example.name}")
    else:
        text = ""
        print(f"created {env_file.name}")

    lines = text.splitlines()
    env, positions = parse(lines)
    added: list[str] = []
    appended: list[str] = []
    for name, generate in GENERATED:
        if env.get(name):
            continue
        env[name] = generate(env)
        if name in positions:  # an empty `NAME=` line: fill it in where it is
            lines[positions[name]] = f"{name}={env[name]}"
        else:
            appended.append(f"{name}={env[name]}")
        added.append(name)
    if appended:
        lines += ["", "# --- Added by scripts/gen_secrets.py ---", *appended]

    if added or not env_file.exists():
        # Write next to the target and rename, so a crash cannot leave a half-written .env.
        temporary = env_file.with_name(env_file.name + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write("\n".join(lines) + "\n")
        os.replace(temporary, env_file)
    os.chmod(env_file, 0o600)  # readable by the owner only

    if added:
        print(f"added {len(added)} value(s) to {env_file.name}:")
        for name in added:
            print(f"  {name}")
    else:
        print(f"nothing to add: every generated value in {env_file.name} is already set")
    for warning in consistency_warnings(env):
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
