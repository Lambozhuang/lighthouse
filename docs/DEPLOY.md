# Running Lighthouse

One `docker compose` project runs everything: a trimmed self-hosted Supabase (Postgres with
pgvector, Auth, REST, gateway, Studio), the Lighthouse API, worker and web app, and a self-hosted
Langfuse for tracing. Developed on macOS with OrbStack; the target is a small Ubuntu box.

You need Docker with Compose v2.20 or newer, Python 3 (only to generate the secrets), about
8 GB of disk for images, and about 2.5 GB of free memory.

## First run

```sh
python3 scripts/gen_secrets.py   # creates .env and fills in every generated secret
$EDITOR .env                     # add ANTHROPIC_API_KEY and OPENROUTER_API_KEY
docker compose up -d             # first start pulls images and builds: a few minutes
docker compose ps -a             # everything "healthy", migrate "Exited (0)"
```

`gen_secrets.py` prints only the names of what it added and never changes a value that is
already set, so it is safe to run again after pulling a version that needs a new variable.
`.env` is gitignored and excluded from the Docker build context. `make help` lists shortcuts
for the commands on this page.

## What is where

| URL | What | Login |
|---|---|---|
| http://localhost:3000 | Web app | An app user, see below |
| http://localhost:8080 | Lighthouse API (`/docs` for the interactive reference) | `Authorization: Bearer <access token>` |
| http://localhost:8000 | Supabase gateway: `/auth/v1/*`, `/rest/v1/*` | `apikey: <ANON_KEY>` header |
| http://localhost:3001 | Supabase Studio: tables, SQL editor, users | Browser asks for `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` |
| http://localhost:3100 | Langfuse: traces | `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` |
| `localhost:5432` | Postgres | user `postgres`, password `POSTGRES_PASSWORD`, database `postgres` |

All values are in `.env`; for example `grep DASHBOARD_ .env` shows the Studio login.

Langfuse starts with an organisation and a project called `lighthouse` already created, and
with the API key pair from `.env` (`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`), so the backend
traces to it without any setup in the UI.

Ports are bound to `127.0.0.1`. Nothing is reachable from another machine until you change
`BIND_ADDRESS` (see [On a server](#on-a-server)).

## The first app user

App users live in Supabase Auth. There is no mail server in this setup, so a new account is
confirmed immediately. Either use the sign-up form of the web app, or:

```sh
curl -s http://localhost:8000/auth/v1/signup \
  -H "apikey: $(grep '^ANON_KEY=' .env | cut -d= -f2)" \
  -H 'Content-Type: application/json' \
  -d '{"email": "you@example.com", "password": "a-long-password"}'
```

or in Studio: Authentication, Users, Add user.

Once your account exists, close sign-up: set `DISABLE_SIGNUP=true` in `.env` and run
`docker compose up -d auth`. More users can still be added from Studio.

## Everyday commands

```sh
docker compose logs -f api worker      # follow the backend
docker compose up -d --build           # after pulling new code
docker compose run --rm migrate        # apply new SQL migrations (also runs on every `up`)
docker compose down                    # stop; data stays in named volumes
```

## Reset everything

```sh
docker compose down -v                 # stop and delete all volumes: database, users, traces
docker compose up -d
```

Keep `.env` when you do this. To also get new secrets, delete `.env` and run `gen_secrets.py`
again, but only together with `down -v`: the passwords are stored inside the database volumes
when they are first created, so new secrets do not match old volumes.

## Containers and memory

Idle, shortly after start, measured with `docker stats --no-stream` on an Apple Silicon laptop
(OrbStack, 16 GB). Expect similar numbers on x86.

| Container | Image | What it does | Memory |
|---|---|---|---|
| `db` | `supabase/postgres:17.6.1.136` | Postgres 17 with pgvector and the Supabase roles | 70 MB |
| `auth` | `supabase/gotrue:v2.197.0` | Sign-up, sign-in, issues JWTs | 14 MB |
| `rest` | `postgrest/postgrest:v14.18` | REST API over the `public` schema | 95 MB |
| `kong` | `kong/kong:3.9.3` | Gateway on 8000, Studio login on 3001 | 82 MB |
| `meta` | `supabase/postgres-meta:v0.100.0` | Catalog API used by Studio | 120 MB |
| `studio` | `supabase/studio:2026.11.02-sha-a05e7ec` | Admin UI | 225 MB |
| `migrate` | built from `docker/backend.Dockerfile` | Applies SQL migrations, then exits | 0 |
| `api` | same image | FastAPI on 8080 | 50 MB |
| `worker` | same image | Turns inbox items into notes | about the same as `api` |
| `web` | built from `docker/web.Dockerfile` | Caddy serving the static build | about 15 MB |
| `langfuse-web` | `langfuse/langfuse:4.77.0` | Langfuse UI and API | 620 to 860 MB |
| `langfuse-worker` | `langfuse/langfuse-worker:4.77.0` | Langfuse background jobs | 370 to 420 MB |
| `langfuse-clickhouse` | `clickhouse/clickhouse-server:26.3.62.3` | Trace storage | 300 to 350 MB |
| `langfuse-postgres` | `postgres:17` | Langfuse users, projects, keys | 40 to 75 MB |
| `langfuse-minio` | `cgr.dev/chainguard/minio` | Object storage for raw events | 60 to 80 MB |
| `langfuse-redis` | `redis:7` | Langfuse queues | 10 MB |

Total: 2.2 to 2.3 GB, of which Langfuse is about 1.6 GB and everything else under 700 MB.
Where a range is given, the two readings were taken a minute and ten minutes after start.

The `worker` and `web` rows are estimates: those two services were not part of the stack when
the measurements were taken.

## On a server

**Memory on an 8 GB machine.** Everything fits. If memory gets tight, turn things off in this
order:

1. Langfuse, about 1.6 GB. Delete the `include:` block at the top of `docker-compose.yml` and empty
   `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` in `.env`. The app works the same, without
   traces. A middle way is to keep it installed and start it only when you want to look at
   traces: `docker compose stop langfuse-web langfuse-worker langfuse-clickhouse` frees most
   of it.
2. Studio and its catalog API, 350 MB: `docker compose stop studio meta`. Start them again
   when you need the admin UI; nothing else depends on them.
3. The limits in `docker-compose.langfuse.yml` (`mem_limit`, `LANGFUSE_NODE_HEAP_MB`) and
   `infra/langfuse/clickhouse-low-memory.xml` can be lowered further; they are set for comfort,
   not for the minimum.

**Reaching it from other devices.** In `.env`:

- `BIND_ADDRESS=0.0.0.0` (or the server's LAN address) publishes the ports beyond localhost.
- `VITE_API_URL`, `VITE_SUPABASE_URL`, `SITE_URL` and `LANGFUSE_PUBLIC_URL` must be the URLs a
  browser on the other device uses, e.g. `http://server.lan:8080`. The two `VITE_` values are
  compiled into the web app: run `docker compose up -d --build` after changing them.
- `CORS_ORIGINS` must list the web app's URL, e.g. `'["http://server.lan:3000"]'`.
- Set `DISABLE_SIGNUP=true`.

With `BIND_ADDRESS=0.0.0.0` Postgres (5432) is published too. On a network you do not fully
trust, remove the `ports:` entry of `db` or firewall it. Everything here is plain HTTP; for
access from outside the home network put a TLS reverse proxy or a VPN in front.

## When something goes wrong

- **A service is not healthy.** `docker compose ps -a`, then `docker compose logs <service>`.
- **`auth` restarts with "must be owner" or password errors after a failed first start.** The
  database volume was initialised half-way, or with different secrets. Postgres only runs its
  init scripts on an empty volume, so start clean: `docker compose down -v && docker compose up -d`.
- **Compose stops with "run scripts/gen_secrets.py".** A required secret is missing from
  `.env`; the script adds it.
- **The web app cannot sign in after changing a URL or the anon key.** Rebuild it:
  `docker compose up -d --build web`.
