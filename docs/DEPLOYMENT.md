# Production deployment

StatusForge is designed to run behind a TLS-terminating reverse proxy. Do not expose PostgreSQL or Redis publicly.

## Prerequisites

- Docker Engine with Compose plugin
- A reverse proxy such as Caddy, Nginx, or Traefik
- A public DNS record for the web application
- SMTP credentials if users must receive verification and password-reset links

## Configure

Copy `.env.example` to `.env`, then set at least:

```dotenv
APP_ENV=production
APP_URL=https://status.example.com
API_URL=https://api.status.example.com
SECRET_KEY=<a unique, cryptographically random value>
POSTGRES_PASSWORD=<a unique database password>
DATABASE_URL=postgresql+psycopg://statusforge:<password>@postgres:5432/statusforge
CORS_ORIGINS=https://status.example.com
EMAIL_FROM=monitoring@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_USERNAME=<smtp-user>
SMTP_PASSWORD=<smtp-password>
```

Keep `.env` outside source control. `ALLOW_PRIVATE_MONITORS` must remain `false` unless workers run within an explicitly isolated trusted network.

## Run

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8000/ready
```

Configure the reverse proxy to serve the web container on port `3000` and the API on port `8000`, enforce HTTPS, and forward the original `Host` and `X-Forwarded-For` headers.

## Backup and recovery

PostgreSQL is the source of truth. Back up its named Docker volume or run a scheduled logical backup:

```bash
docker compose exec -T postgres pg_dump -U statusforge statusforge > statusforge.sql
```

Test restoration in a separate environment before relying on a backup. Redis is not a durable data store; its loss can delay queued checks but must not lose monitor configuration or history.

## Upgrade

```bash
git pull --ff-only
docker compose build
docker compose up -d
```

The API service runs Alembic migrations before serving traffic. Review release notes and back up PostgreSQL before every upgrade.
