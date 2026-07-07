# ComptaPro — Dockerfile
# Image legere Python 3.13 Alpine (~25 Mo) + stdlib only
FROM python:3.13-alpine

LABEL maintainer="ComptaPro"
LABEL description="Logiciel de comptabilite francais PCG — 33 modules, 130+ routes, 0 dependance"

RUN apk add --no-cache curl tini

WORKDIR /app

# Copy only the comptable package
COPY comptable/ ./comptable/

# Persistent data directory
RUN mkdir -p /data

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8080/api/exercices || exit 1

ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV COMPTAPRO_DB_PATH=/data/comptabilite.db
ENV COMPTAPRO_PORT=8080

# Entrypoint: init DB then serve
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/sbin/tini", "--", "/entrypoint.sh"]
