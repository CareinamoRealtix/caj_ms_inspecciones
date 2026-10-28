FROM ghcr.io/astral-sh/uv:0.12.5 AS uv

# tippecanoe genera fincas.pmtiles en el job de sincronización (HU.11/HU.12). Se compila sobre la
# misma base que la imagen final para que el binario encuentre las mismas librerías.
FROM python:3.13-slim AS tippecanoe
ARG TIPPECANOE_VERSION=2.79.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates g++ make libsqlite3-dev zlib1g-dev \
    && git clone --depth 1 --branch ${TIPPECANOE_VERSION} https://github.com/felt/tippecanoe /src \
    && make -C /src -j"$(nproc)" \
    && make -C /src install PREFIX=/opt/tippecanoe

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY --from=uv /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends libsqlite3-0 zlib1g libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=tippecanoe /opt/tippecanoe/bin/tippecanoe /usr/local/bin/tippecanoe

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
