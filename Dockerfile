# One image for the API and the worker; compose.yaml runs it with different commands.

# --- Build the frontend ----------------------------------------------------------------------
FROM node:24-slim AS web
WORKDIR /web
# Dependencies first: this layer is rebuilt only when they change.
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- The app -----------------------------------------------------------------------------------
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Dependencies first, for the same reason as above. No dev tools, no docling. The cache
# mounts keep uv's download cache out of the image.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY alembic.ini ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev
COPY --from=web /web/dist ./web/dist

# Not root. /data holds uploads waiting to be parsed and cached model answers; compose.yaml
# puts a volume there, shared by the API and the worker.
RUN useradd --create-home alfred && mkdir /data && chown alfred /data
USER alfred
ENV PATH="/app/.venv/bin:$PATH" \
    ALFRED_UPLOAD_DIR=/data/uploads \
    ALFRED_CACHE_DIR=/data/cache

EXPOSE 8000
CMD ["alfred", "serve", "--host", "0.0.0.0"]
