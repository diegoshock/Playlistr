FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="Playlistr" \
      org.opencontainers.image.description="Playlists for Navidrome using artist genres from MusicBrainz and Wikidata" \
      org.opencontainers.image.source="https://github.com/diegoshock/docker-playlists"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYLISTR_DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 1000 playlistr \
    && useradd --uid 1000 --gid playlistr --no-create-home playlistr \
    && mkdir /data && chown playlistr:playlistr /data

COPY --chown=playlistr:playlistr app ./app
RUN chmod -R a+rX /app
USER playlistr
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-proxy-headers"]
