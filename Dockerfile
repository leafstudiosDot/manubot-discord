FROM node:20-alpine AS frontend-builder
WORKDIR /app/src/frontend

COPY src/frontend/package.json ./
COPY src/frontend/bun.lockb ./
RUN npm install

COPY src/frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY --from=frontend-builder /app/src/frontend/dist ./src/frontend/dist

EXPOSE 6540

CMD ["python", "src/main.py"]
