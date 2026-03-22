# Manubot

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

Flask will serve the built React app from `src/frontend/dist` on:
- `http://localhost:6540/` (dashboard)
- `http://localhost:6540/api/health`
- `http://localhost:6540/api/events`

## Environment variables

Use your `.env` file:

```env
TOKEN=your_discord_bot_token
APP_ID=your_discord_application_id
API_PORT=6540
```
