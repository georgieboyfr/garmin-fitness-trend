# Étape 1 : installation des dépendances (les outils de compilation éventuels restent ici)
FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN python -m venv /venv && /venv/bin/pip install -r requirements.txt

# Étape 2 : image finale, sans pip ni cache
FROM python:3.12-slim

ARG APP_VERSION=0.0.0-dev
LABEL org.opencontainers.image.title="garmin-fitness-trend" \
      org.opencontainers.image.source="https://github.com/georgieboyfr/garmin-fitness-trend" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH" \
    APP_VERSION=${APP_VERSION} \
    DATA_DIR=/data

# utilisateur non-root (UID/GID surchargeables via `user:` dans docker-compose.yml)
RUN useradd --uid 1000 --create-home app && mkdir /data && chown app:app /data

COPY --from=build /venv /venv
WORKDIR /srv
COPY app /srv/app

USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
