FROM python:3.13.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --home-dir /app --create-home app

WORKDIR /app
COPY --chown=app:app src ./src

USER 10001:10001

EXPOSE 8088

CMD ["python", "-m", "wake_console"]

