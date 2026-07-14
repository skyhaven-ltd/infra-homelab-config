FROM python:3.13.14-slim-bookworm

ARG UV_VERSION=0.11.21

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

RUN pip install --no-cache-dir "uv==${UV_VERSION}" \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --home-dir /app --create-home app \
    && install -d -o app -g app /data

WORKDIR /app

COPY --chown=app:app pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=app:app src ./src
RUN uv sync --frozen --no-dev

USER 10001:10001

EXPOSE 8080

CMD ["uvicorn", "--factory", "knowledge_mcp.server:create_app_from_env", "--host", "0.0.0.0", "--port", "8080"]

