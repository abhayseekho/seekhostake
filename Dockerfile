# Swim-bet portal — React (Vite) SPA built in a node stage, served by FastAPI (uvicorn) in a
# python stage. Self-contained build context = repo root. Railway: Dockerfile at repo root.

# ── stage 1: build the React frontend ──────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build            # → /fe/dist

# ── stage 2: python API ────────────────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api.py engine.py store.py seed.py ./
COPY --from=frontend /fe/dist /app/frontend/dist

EXPOSE 8080
CMD uvicorn api:app --host 0.0.0.0 --port ${PORT:-8080}
