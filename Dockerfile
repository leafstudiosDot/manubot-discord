FROM node:26-alpine AS frontend-builder
WORKDIR /app/src/frontend

COPY src/frontend/package.json src/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY src/frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.source=https://github.com/leafstudiosDot/manubot-discord
LABEL org.opencontainers.image.description="A manageable Discord bot"
LABEL org.opencontainers.image.licenses=Apache-2.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/manubot.db \
    BACKUP_DIR=/data/backups \
    MANUBOT_ENV=production

WORKDIR /app

RUN groupadd --system --gid 10001 manubot \
    && useradd --system --uid 10001 --gid manubot --home-dir /app manubot

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=manubot:manubot src ./src
COPY --from=frontend-builder --chown=manubot:manubot /app/src/frontend/dist ./src/frontend/dist

RUN mkdir -p /data/backups && chown -R manubot:manubot /data
VOLUME ["/data"]

USER manubot
WORKDIR /app/src

EXPOSE 6540

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request; port=os.getenv('API_PORT','6540'); urllib.request.urlopen('http://127.0.0.1:'+port+'/healthz', timeout=3)"]

CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]
