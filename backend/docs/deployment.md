# Deployment guide

## 1. Local development

```bash
cd backend
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                   # dev defaults work as-is
docker compose up -d db                                # PostgreSQL 16 on localhost:5432 (+ mahayagya_test DB)
alembic upgrade head
python -m scripts.seed_all                             # 16 sessions, 2,151 Kunds, 34,416 capacity rows
python -m scripts.create_admin --email you@example.org --name "Your Name"   # prompts for the password
uvicorn app.main:app --reload                          # http://localhost:8000/docs
```

Everything in Docker:

```bash
docker compose up -d --build                # db + api
docker compose exec api alembic upgrade head
docker compose exec api python -m scripts.seed_all
docker compose exec api python -m scripts.create_admin --email you@example.org --name "Your Name"
```

Alternatively set `RUN_MIGRATIONS=true RUN_SEED=true` on the `api` service. The entrypoint
then runs both (idempotently) before starting uvicorn.

## 2. Production checklist

| Item | How |
|---|---|
| Secrets | `JWT_SECRET_KEY` (≥ 32 random characters), `DATA_ENCRYPTION_KEY` (a Fernet key). The app **refuses to start** in `APP_ENV=production` with default or empty values. Keep them in the platform's secret store, never in Git. |
| CORS | `CORS_ALLOWED_ORIGINS=https://<your-site>` (`*` is refused in production). |
| HTTPS | Terminate TLS at the load balancer or CDN, and set `ENABLE_HSTS=true`. Run uvicorn with `--proxy-headers --forwarded-allow-ips=<LB CIDR>` (the image does this through the `FORWARDED_ALLOW_IPS` env var) so that rate limits see real client IPs. |
| Hosts | `TRUSTED_HOSTS=api.example.org`. |
| Docs | `ENABLE_DOCS=false` if the API docs must not be public. |
| Workers | `WEB_CONCURRENCY` = 2-4 per vCPU-pair. Size the DB pool so that instances × workers × (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`) stays well below the pooler or database connection limit. |
| Rate limits | With more than one instance, set `RATE_LIMIT_BACKEND=redis` and `REDIS_URL`, and also apply per-IP limits at the WAF/CDN. |
| Migrations | Run `alembic upgrade head` as a one-off job **before** rolling out new instances, using the owner role (`MIGRATIONS_DATABASE_URL`). |
| Least privilege | Run `scripts/sql/least_privilege.sql` once (as the owner) and point `DATABASE_URL` at `mahayagya_app`. |
| Seeding | `python -m scripts.seed_all` once. It is idempotent and verifies the counts (exit code 1 if they are wrong). |
| First admin | `python -m scripts.create_admin …` (interactive prompt, or `--password-stdin` from a secret manager). Never pass the password as an argument. |
| Background jobs | Schedule `POST /admin/maintenance/purge-idempotency-secrets` (or a small script) hourly to drop expired replay secrets. Run `python -m scripts.verify_integrity` daily and on demand. |
| Reports | `REPORTS_DIR` must be a persistent volume. With several instances, generate reports on one designated instance or switch the storage to object storage (see the limitations). |
| Backups | Use managed PITR (Supabase/RDS) **and** a nightly `pg_dump` (see the runbook). Excel exports are not backups. |
| Front door | CDN for the static React site, a WAF with bot protection and per-IP limits, and a waiting room or queue for the registration launch. |
| Traffic separation | Deploy separate API instance groups for `/scanner/*` (event days) and for public registration, behind different hostnames or paths. |

## 3. Connecting Supabase (when the credentials are available)

The backend talks to Supabase **only through PostgreSQL** (`DATABASE_URL`). No Supabase
client library is used and no key is ever sent to a browser.

1. In the Supabase dashboard, open **Project Settings → Database → Connection string**.
   * **Migrations / admin scripts**: use the *direct* connection (port 5432) or the
     *session pooler*. Set it as `MIGRATIONS_DATABASE_URL`.
   * **API runtime**: use the *transaction pooler* (Supavisor, port 6543) and set
     `DB_DISABLE_PREPARED_STATEMENTS=true` (prepared statements are not supported in
     transaction mode). The session pooler also works and needs no flag.
   * Append `?sslmode=require` to the URL. `postgres://` and `postgresql://` URLs are
     accepted and converted automatically to the psycopg driver.
2. Run the migrations and seed:
   ```bash
   MIGRATIONS_DATABASE_URL='postgresql://postgres.<ref>:<password>@<host>:5432/postgres?sslmode=require' alembic upgrade head
   DATABASE_URL='<same direct URL>' python -m scripts.seed_all
   ```
3. Harden the exposed API roles (Supabase SQL editor, as `postgres`): run
   `scripts/sql/supabase_hardening.sql`. RLS is already enabled with no policies for
   `anon`/`authenticated` (migration 0002), and this script also revokes their table
   privileges.
4. Least privilege for the API: run `scripts/sql/least_privilege.sql` (via psql with
   `-v app_password=…`), then set `DATABASE_URL` to the pooler URL with the user
   `mahayagya_app.<project-ref>` (Supavisor user format) and that password.
5. `SUPABASE_URL`, `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY` are placeholders for
   future features (for example storing reports in Supabase Storage). The API does not need
   them today. **The service-role key must never be given to a frontend or exposed by any
   endpoint.**
6. Check: `GET /api/v1/health/ready` should return `"status": "ready"` and
   `"migration": "0002"`.

Supabase notes:

* Everything used is standard PostgreSQL: triggers, constraint triggers, advisory locks,
  `FOR NO KEY UPDATE`, partial and expression indexes, and RLS.
* Custom settings (`mahayagya.*`) are set per transaction with
  `set_config(..., true)`, which is compatible with transaction pooling.
* Size the pool for the Supabase plan's connection limit. Measured peak: 37 connections for
  4 workers.

## 4. Container image

* Base image is `python:3.12-slim`, running as the non-root user `appuser` (uid 10001),
  with a health check on `/api/v1/health`.
* `ENTRYPOINT docker-entrypoint.sh` runs migrations and seeding when `RUN_MIGRATIONS` or
  `RUN_SEED` is `true`, then starts `uvicorn --workers $WEB_CONCURRENCY --proxy-headers`.
* Build with `docker build -t mahayagya-api .`

## 5. Venue local server (offline check-in)

A small Linux box or laptop on the venue LAN/Wi-Fi with Docker:

```bash
# .env on the local server
APP_ENV=production
OFFLINE_NODE_MODE=true
OFFLINE_NODE_ID=venue-main
CLOUD_API_BASE_URL=https://api.example.org
CLOUD_SYNC_EMAIL=<supervisor account>
CLOUD_SYNC_PASSWORD=<from secret store>
JWT_SECRET_KEY=<local secret>      DATA_ENCRYPTION_KEY=<local key>
CORS_ALLOWED_ORIGINS=http://<scanner-pwa-origin>

docker compose up -d --build
docker compose exec api alembic upgrade head && docker compose exec api python -m scripts.seed_all
# local scanner accounts (assigned to the session being scanned)
docker compose exec api python -m scripts.create_admin --email gate1@example.org --name "Gate 1" --role SCANNER --session 1
# before the session, while online:
docker compose exec api python -m scripts.offline_node preload --session-id 1
# whenever connectivity is available (cron every minute is fine; it is idempotent):
docker compose exec api python -m scripts.offline_node sync
```

The operational procedures are in `docs/operations-runbook.md`.
