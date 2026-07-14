# Playwright base image ships Chromium + all OS dependencies, so headless
# JavaScript retailers (Currys, Very, Amazon) work out of the box.
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite database and logs live here; mounted as a volume in compose.
VOLUME ["/app/data"]

CMD ["python", "app.py"]
