# FluxVid

Download video and audio from supported public sources. Plain HTML/CSS/JS frontend (GitHub Pages) plus a separate FastAPI backend that uses yt-dlp and FFmpeg for real extraction and downloads.

Created By Shiv Yogi.

## Project layout

    public/    static frontend (index.html, style.css, app.js, config.js, js/, assets/icons/*.svg)
    backend/   FastAPI app (main.py, downloader.py, config.py), requirements.txt, .env.example, Dockerfile

## Backend setup

Requirements: Python 3.10+ and FFmpeg on PATH (needed to merge video and audio streams and to produce MP3).

    cd backend
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env        # edit FRONTEND_ORIGIN
    uvicorn main:app --env-file .env --port 8000

Install FFmpeg: `sudo apt install ffmpeg`, `brew install ffmpeg`, or from ffmpeg.org on Windows.
Sites change often. Keep yt-dlp current: `pip install -U yt-dlp` (most extraction failures are fixed by updating).

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| FRONTEND_ORIGIN | Comma-separated allowed origins for CORS. `*` is ignored. | localhost:8080 |
| MAX_DOWNLOAD_SIZE | Max bytes per download | 524288000 |
| DOWNLOAD_TIMEOUT | Seconds per extraction or download | 300 |
| TEMP_DIRECTORY | Scratch directory | system temp/fluxvid |
| RATE_LIMIT_PER_MINUTE | Requests per IP per minute | 20 |
| MAX_CONCURRENT_DOWNLOADS | Parallel downloads (extra requests get 503) | 2 |
| TRUST_PROXY | Use X-Forwarded-For behind a trusted proxy | false |

## Frontend setup

No build step. Set the API address in `public/config.js`, then serve the folder:

    cd public && python -m http.server 8080

Open http://localhost:8080 (this origin is allowed by default).

## Run locally

Start the backend on port 8000, serve `public/` on port 8080, open the page, paste a public URL, press Analyze.

## Deploy

**GitHub Pages:** publish the contents of `public/` (for example with a Pages workflow that uploads that folder). Set `window.FLUXVID_API` in `config.js` to your backend's HTTPS URL, and set `FRONTEND_ORIGIN` on the backend to `https://YOUR-USERNAME.github.io` (origin only, no path).

**Backend:** any host that runs Python or Docker and has FFmpeg and outbound internet access. `backend/Dockerfile` installs FFmpeg and starts uvicorn on `$PORT`. Serve it over HTTPS, since Pages is HTTPS and browsers block mixed content. Free tiers with short request timeouts or small disks may cut off long downloads.

## API

All errors use `{"error": {"code": "...", "message": "..."}}` with no stack traces.

- `GET /api/health` returns `{"status":"ok","ffmpeg":true}`.
- `POST /api/info` with `{"url": "..."}` returns title, duration, thumbnail, platform, source_url, `types`, and the `video` and `audio` option lists. Only qualities found in the source are listed.
- `POST /api/download` with `{"url","type":"video|audio","quality":"best|<height or kbps>"}` returns the file. Name format: `[Sanitized Title]_FluxVid-created by shiv yogi.[ext]`. Video is saved as MP4, audio as MP3.

## How it stays safe

URLs must be http/https on ports 80/443, without credentials, and must resolve to public addresses only. yt-dlp runs as a subprocess with an argument list (no shell), a timeout, a size limit and its own temporary folder, which is deleted after the response; a sweeper removes leftovers older than an hour. Requests are rate-limited per IP and concurrency is capped. Quality values are validated and numeric. Titles are sanitized for file names. Download progress in the browser is real (bytes received against Content-Length). The browser holds the file in memory before saving, so very large files can strain low-memory phones; lower MAX_DOWNLOAD_SIZE if needed.

## Troubleshooting

- "Could not reach the FluxVid server": wrong `config.js` address, backend down, or mixed HTTP/HTTPS.
- CORS error in the console: `FRONTEND_ORIGIN` must exactly match the page origin.
- "Unable to process this URL": update yt-dlp; the source may be private, DRM-protected, region-locked or unsupported.
- Downloads rejected with a server error: FFmpeg is missing (check `/api/health`).
- Many sites block data-centre IPs, so a cloud-hosted backend may fail where a home connection works.

## Limitations and legal

Not every site works, and support changes without notice. Private, login-only, DRM-protected and live content is not supported, and nothing here bypasses those protections. Only download content you own, that is in the public domain, or that you have permission to save. You are responsible for following the terms of the source site and the laws that apply to you.
