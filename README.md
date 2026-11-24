# Manubot for Discord

An open-source Discord bot and moderation panel.

This project includes:
- Discord Gateway bot runtime (Python)
- Flask API server (Python) with Flask-Sock WebSockets
- SQLite storage (`manubot.db`)
- React + Vite frontend dashboard (`src/frontend/`)
- Append-only admin activity audit log

## Source file structure

- `src/main.py`: configuration wiring and local development startup
- `src/wsgi.py`: production WSGI entrypoint for Gunicorn
- `src/gunicorn.conf.py`: single-worker, multi-threaded Gunicorn configuration
- `src/config.py`: environment-driven security and runtime settings
- `src/security.py`: origin/CSRF helpers, login rate limiting, input sanitizers
- `src/media.py`: attachment type allowlists and magic-byte sniffing
- `src/audit.py`: audit event service, categories, and metadata sanitizer
- `src/accounts.py`: authentication, sessions, accounts, and permissions
- `src/discord.py`: Discord Gateway connection, heartbeat, reconnect loop
- `src/webback.py`: Flask app factory and API/static routes
- `src/wsback.py`: authenticated WebSocket snapshot streams
- `src/mousetrap.py`: MouseTrap moderation and attachment caching
- `src/database.py`: SQLite schema, migrations, queries, backups, retention
- `src/frontend/`: React + Vite dashboard app
- `tests/`: pytest suite for auth, API, WebSockets, media, audit, and migrations

## Requirements

- Python 3.12 or newer
- Node.js 22 or newer for frontend builds (Docker uses a current Node LTS image)
- Docker only for the container deployment option

## Setup

### 1. Install backend dependencies

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

For tests and dependency auditing:

```powershell
pip install -r requirements-dev.txt
```

### 2. Configure the environment

Copy `.env.example` to `.env` and fill in at least:

```env
TOKEN=your_discord_bot_token
APP_ID=your_discord_application_id
SUPERADMIN_USERNAME=superadmin
SUPERADMIN_PASSWORD=change_me_now
```

Use `SUPERADMIN_PASSWORD_HASH` (bcrypt) instead of a plaintext password when
possible. A plaintext `SUPERADMIN_PASSWORD` is only intended for initial setup
and local development.

Set a persistent `CSRF_SECRET` in production so sessions keep working across
restarts:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 3. Development mode

Run the backend (Discord bot + Flask API):

```powershell
python src/main.py
```

In another terminal, run the Vite dev server:

```powershell
cd src/frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` and `/ws` to
`http://localhost:6540`, and loopback development origins are allowed by
default outside production.

### 4. Production build mode

Build the frontend:

```powershell
cd src/frontend
npm ci
npm run build
```

Then serve the backend with Gunicorn (Linux/macOS, or WSL):

```bash
cd src
gunicorn --config gunicorn.conf.py wsgi:app
```

Flask serves the built React app from `src/frontend/dist` at
`http://localhost:6540/`.

> The Flask development server is disabled when `MANUBOT_ENV=production`.
> Keep exactly **one Gunicorn worker**. The gateway lock prevents a second
> process from opening a duplicate Discord Gateway connection, but health data
> is process-local.

On Windows, use `python src/main.py` for local development or run the Docker
image for production-like deployment.

## Security configuration

### Sessions and CSRF

- Session tokens are stored as SHA-256 digests in SQLite, never as plaintext.
  The original value exists only in the HttpOnly session cookie.
- Existing plaintext sessions are hashed in place during startup migration, so
  active users are not logged out.
- `SESSION_COOKIE_SECURE` defaults to `true` in production. Set it to `false`
  only for deliberate local HTTP testing.
- State-changing API requests require the session-bound CSRF token from
  `GET /api/auth/session` in the `X-CSRF-Token` header. The React frontend
  handles this automatically.
- Unsafe requests with an `Origin` header are checked against the request host
  and `TRUSTED_ORIGINS`. Wildcards are rejected.

If the panel is served from a different public origin (for example behind a
reverse proxy), set:

```env
TRUSTED_ORIGINS=https://panel.example.com
WS_TRUSTED_ORIGINS=https://panel.example.com
```

### Reverse proxy and client IPs

By default the API does **not** trust `X-Forwarded-For`. Enable
`TRUST_PROXY_HEADERS=true` only when a reverse proxy overwrites those headers,
and restrict direct access to the backend port. When enabled, the rightmost
forwarded address is used for rate limiting.

### Login rate limiting

Failed logins are rate-limited per normalized username and client address.
Limits are temporary (`LOGIN_RATE_LIMIT_BLOCK_SECONDS`) and never permanently
disable an account. Tune with:

```env
LOGIN_RATE_LIMIT_ENABLED=true
LOGIN_RATE_LIMIT_ATTEMPTS=5
LOGIN_RATE_LIMIT_WINDOW_SECONDS=300
LOGIN_RATE_LIMIT_BLOCK_SECONDS=900
```

### Upload and attachment limits

Direct-message uploads enforce per-file, count, and total request limits. Set:

```env
MAX_REQUEST_BYTES=33554432
MAX_DM_FILE_BYTES=8388608
MAX_DM_ATTACHMENTS=10
```

MouseTrap attachment caching only downloads from an explicit HTTPS allowlist,
never follows redirects, applies connect/read timeouts, streams with strict
byte limits, and validates media signatures. Only allowlisted image and video
types are stored and inline-rendered.

```env
MOUSETRAP_CDN_ALLOWLIST=cdn.discordapp.com,media.discordapp.net
MOUSETRAP_MAX_ATTACHMENT_BYTES=8388608
MOUSETRAP_MAX_MESSAGE_BYTES=25165824
MOUSETRAP_MAX_ATTACHMENTS=10
MOUSETRAP_MAX_CONCURRENT_DOWNLOADS=4
```

## Admin activity audit log

The **Audit Logs** page records privileged activity in an append-only table:

- Sign-ins, failed sign-ins, and sign-outs
- Account creation, moderator permission changes, password changes/resets
- Session revocation
- Direct-message send/delete actions
- MouseTrap configuration changes
- Database regeneration

Superadmins always have access. Admins have access by role. Moderators need the
`audit_view` permission. The page supports category, action, actor, target,
free-text, and date filters plus pagination and metadata details.

Audit metadata is sanitized before storage. Passwords, tokens, cookies,
authorization headers, file bytes, and message bodies are never recorded.

Optional retention (0 disables pruning):

```env
AUDIT_LOG_RETENTION_DAYS=0
EVENT_RETENTION_DAYS=0
MOUSETRAP_LOG_RETENTION_DAYS=0
```

## Database backups

Database regeneration creates a consistent SQLite backup before deleting
captured gateway events. Accounts, sessions, audit records, MouseTrap
configuration, and MouseTrap logs are preserved.

```env
BACKUP_DIR=src/backups
BACKUP_RETENTION=5
```

Backups contain sensitive data (account hashes, DMs, audit records). Keep the
backup directory private and out of public static paths.

## Docker

Build a production image (the frontend is built inside Docker):

```powershell
docker build -t manubot:latest .
```

Run with your `.env` and a persistent data volume:

```powershell
docker run --rm -p 6540:6540 --env-file .env -v ${PWD}/data:/data manubot:latest
```

### Docker Compose

Compose uses:
- `.env` for secrets/config (`TOKEN`, `APP_ID`, optional `API_PORT`)
- `./data` bind mount for persistent SQLite and backups at `/data`
- non-root runtime, read-only root filesystem, dropped capabilities, and a
  `/healthz` health check

Start:

```powershell
docker compose up --build -d
```

Logs:

```powershell
docker compose logs -f
```

Stop:

```powershell
docker compose down
```

### `.env` in Docker

- Do not copy `.env` into the image.
- Keep `.env` on the host and pass it at runtime:
  - `docker run --env-file .env ...`
  - or `env_file: .env` in Compose (already configured)
- Explicit `environment:` values in `docker-compose.yml` win over `env_file`.

## Testing and dependency checks

Backend:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pip_audit -r requirements.txt
```

Frontend:

```powershell
cd src/frontend
npm ci
npm audit --audit-level=high
npm run build
npx tsc --noEmit
```

CI runs these checks in `.github/workflows/security_checks.yml`. Dependabot is
configured for pip, npm, GitHub Actions, and Docker updates.

## Version bump automation

Frontend UI version is generated from `src/frontend/package.json` during the
Vite build, so there are no hardcoded `v0.0.x` strings in React files.

From `src/frontend/`:

```powershell
npm run version:patch
npm run version:minor
npm run version:major
```

Or sync directly from a git tag:

```powershell
npm run version:sync-tag
npm run version:sync-tag -- v0.0.3
```

## License

Manubot for Discord is licensed under the Apache License 2.0. See `LICENSE` and
`NOTICE`. Contributors retain their copyright and submit contributions under
the same license; no separate CLA is required.
