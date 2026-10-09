# Build context: the backend/ folder (use when Render Root Directory is 'backend')
FROM denoland/deno:bin AS deno

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp/cache \
    TEMP_DIRECTORY=/tmp/fluxvid

# FFmpeg merges video+audio and makes MP3. Deno is the JavaScript runtime yt-dlp uses for YouTube.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=deno /deno /usr/local/bin/deno

WORKDIR /srv
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

RUN useradd --create-home --uid 10001 fluxvid \
    && mkdir -p /tmp/fluxvid /tmp/cache \
    && chown -R fluxvid /tmp/fluxvid /tmp/cache
USER fluxvid

# Render injects PORT (default 10000). Bind 0.0.0.0 so the platform can reach the server.
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
