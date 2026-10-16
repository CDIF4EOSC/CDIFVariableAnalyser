# DDI-CDI Studio (gen2): FastAPI backend + built React editor + qsv readstat.
#
#   docker build -t ddicdi-studio .
#   docker run --rm -p 8000:8000 -e DDI_API_KEY=secret ddicdi-studio
#   open http://localhost:8000/app/
#
# Targets x86_64 Linux (Azure App Service). The qsv release zip is the one with the
# readstat feature; the Homebrew/apt builds lack it.

# TODO: bump to the first release with dathere/qsv#4667 (readstat --sentinels-as). Until
# then the image writes SPSS/SAS user-missing cells empty; the app probes for the option.
ARG QSV_VERSION=23.0.1

# ---- 1. frontend -----------------------------------------------------------------
# Runs on the build machine's own architecture: the output is plain JS, and esbuild
# (a Go binary) crashes under amd64 emulation on Apple Silicon.
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # -> /src/frontend/dist

# ---- 2. qsv ----------------------------------------------------------------------
# Only the glibc build ships the readstat feature (the musl build does not). It needs
# glibc >= 2.39, hence Debian trixie below, and links libwayland-client at runtime.
FROM debian:trixie-slim AS qsv
ARG QSV_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && curl -fsSL -o /tmp/qsv.zip \
       "https://github.com/dathere/qsv/releases/download/${QSV_VERSION}/qsv-${QSV_VERSION}-x86_64-unknown-linux-gnu.zip" \
    && unzip -o /tmp/qsv.zip qsv -d /out \
    && chmod +x /out/qsv

# ---- 3. runtime ------------------------------------------------------------------
FROM python:3.12-slim-trixie AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DDI_QSV_BIN=/usr/local/bin/qsv \
    DDI_WORK_DIR=/tmp/ddicdi-gen2 \
    PORT=8000

WORKDIR /app

# Dependencies first so they cache independently of source edits.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY ddicdi/ ./ddicdi/
RUN uv sync --frozen --no-dev

COPY --from=qsv /out/qsv /usr/local/bin/qsv
RUN qsv --list | grep -q readstat
COPY --from=frontend /src/frontend/dist ./frontend/dist

RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD ["/app/.venv/bin/python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]

# App Service sets WEBSITES_PORT to reach the container; PORT is honoured here for
# platforms that inject it (Container Apps, Cloud Run).
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn ddicdi.api.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
