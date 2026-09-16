FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps/api apps/api
RUN uv sync --frozen --no-dev
COPY alembic.ini ./
COPY fixtures fixtures
COPY evals evals
RUN useradd --create-home app && mkdir -p /data/uploads && chown -R app:app /data /app
USER app
