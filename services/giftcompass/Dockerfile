FROM python:3.12.11-slim@sha256:27f90d79cc85e9b7b2560063ef44fa0e9eaae7a7c3f5a9f74563065c5477cc24

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY giftcompass.py .
COPY templates templates
COPY static static

RUN useradd --create-home --uid 10001 app && mkdir /data && chown app:app /data
USER app
VOLUME ["/data"]
EXPOSE 8080
CMD ["waitress-serve", "--host=0.0.0.0", "--port=8080", "--call", "giftcompass:create_app"]
