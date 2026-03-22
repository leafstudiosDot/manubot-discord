# Manubot for Discord

An open-source Discord bot

This project now includes:
- Discord Gateway bot runtime (Python)
- Flask API server (Python)
- SQLite storage (`manubot.db`)
- React + Vite frontend dashboard (`src/frontend/`)

## Source file structure

- `src/main.py`: startup/orchestration (loads env, starts Flask thread, runs Discord loop)
- `src/discord.py`: Discord Gateway connection, heartbeat, reconnect loop
- `src/webback.py`: Flask app factory and API/static routes
- `src/database.py`: SQLite schema setup and event read/write helpers
- `src/frontend/`: React + Vite dashboard app

## 1) Install backend dependencies

```powershell
pip install -r requirements.txt
```

## 2) Development mode

Run backend (Discord bot + Flask API):

```powershell
python src/main.py
```

In another terminal run frontend dev server:

```powershell
cd src/frontend
npm install
npm run dev
```

Open: `http://localhost:5173`

## 3) Production build mode

Build frontend once:

```powershell
cd src/frontend
npm install
npm run build
```

Then run backend:

```powershell
python src/main.py
```

Flask will serve the built React app from `src/frontend/dist`
- `http://localhost:6540/` (dashboard)

## Environment variables

Use your `.env` file:

```env
TOKEN=your_discord_bot_token
APP_ID=your_discord_application_id
API_PORT=6540
DB_PATH=src/manubot.db
```

`DB_PATH` is optional for local non-Docker runs.

## 4) Docker (single image)

Build a production image (frontend is built inside Docker):

```powershell
docker build -t manubot:latest .
```

Run the image with your `.env`:

```powershell
docker run --rm -p 6540:6540 --env-file .env manubot:latest
```

Open: `http://localhost:6540`

## 5) Docker Compose (recommended)

Compose uses:
- `.env` for secrets/config (`TOKEN`, `APP_ID`, optional `API_PORT`)
- `./data` bind mount for persistent SQLite file at `/data/manubot.db`

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

## `.env` in Docker

- Do not copy `.env` into the image.
- Keep `.env` on host and pass it at runtime:
  - `docker run --env-file .env ...`
  - or `env_file: .env` in Compose (already configured in `docker-compose.yml`)
- If you use Compose and also set values in `environment:`, those explicit `environment` values win over `env_file` values for same keys.
