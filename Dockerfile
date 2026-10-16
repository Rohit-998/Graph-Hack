# Firebreak app image: FastAPI backend + built Mission Control UI on one port.

# --- UI build -------------------------------------------------------------------
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Python runtime ---------------------------------------------------------------
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    FASTEMBED_CACHE_PATH=/app/backend/.cache/fastembed \
    FIREBREAK_UI_DIST=/app/frontend/dist
WORKDIR /app/backend

COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
# Bake the embedding model into the image so first start works offline.
RUN uv run python -c "from firebreak.embeddings import embed; print(len(embed(['warmup'])[0]))"

COPY --from=ui /ui/dist /app/frontend/dist

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "firebreak.api:app", "--host", "0.0.0.0", "--port", "8000"]
