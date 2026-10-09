# FluxVid

Download video and audio from supported public sources. Created By Shiv Yogi.

- Frontend: plain HTML/CSS/JS in `docs/` (GitHub Pages, no build step)
- Backend: Python FastAPI + yt-dlp + FFmpeg in `backend/` (Docker, Render)
- Files are saved as `Original_Name_FluxVid-created by shiv yogi.mp4` or `.mp3`

## Features

- Analyze a public link: title, thumbnail, duration, source, and only the qualities the source really offers
- Video or audio mode (MP4 or MP3), chosen on the home screen
- Recommended quality: the best video up to 1080p (sharp on phones, moderate size), or best audio
- Size estimates, shown only when the source reports sizes (or, for MP3, from duration and bitrate). Options over the server limit are disabled and say so
- Real progress from the server: bytes downloaded, a percentage only when the real total is known, and a separate "Processing" stage for merging or converting
- Cancel at any time. Cancelling stops the download on the server and deletes its files
- Server status pill and cold-start handling: free hosting sleeps when idle, so FluxVid wakes it and waits instead of failing
- Remembers your last mode and preferred video height (no settings page needed)
- Recent links and download history, stored only in your browser, each with a clear button; history items can be re-opened
- Paste button that analyzes the link right away
- Install FluxVid on Android (Chrome menu, Install app) and use Share on a video in another app to send it to FluxVid
- Keyboard and screen-reader support, reduced-motion support, and an offline app shell

## Folder structure

    FluxVid/
    ├── Dockerfile                  build context = repository root (Render default)
    ├── render.yaml                 optional Render Blueprint
    ├── .dockerignore  .gitignore
    ├── README.md
    ├── docs/                       frontend (GitHub Pages serves this folder)
    │   ├── index.html  style.css  app.js  config.js
    │   ├── manifest.webmanifest  sw.js
    │   ├── js/  api.js  icons.js  store.js  format.js
    │   └── assets/  icons.svg  logo.svg  icon-192.png  icon-512.png  icon-maskable-512.png
    ├── backend/
    │   ├── Dockerfile              build context = backend/ (only for Root Directory = backend)
    │   ├── requirements.txt  requirements-dev.txt  .env.example  .dockerignore
    │   ├── app/  main.py  config.py  errors.py  urls.py  naming.py  formats.py
    │   │         runner.py  info.py  jobs.py  schemas.py
    │   └── tests/                  Python tests plus a fake yt-dlp used only by tests
    └── tests/frontend/frontend.test.mjs

## How a download works

1. `POST /api/info` returns metadata and options.
2. `POST /api/jobs` starts a download and returns a job id at once (HTTP 202).
3. The page polls `GET /api/jobs/{id}` every second. The server reads yt-dlp's own progress output.
4. When the job is ready, the browser fetches `GET /api/jobs/{id}/file`. It streams straight to your phone's download manager, not through page memory.
5. The file is deleted when the job expires (`JOB_TTL`, default 15 minutes), when you cancel, or on failure.

Every request is short, so free-hosting request time limits do not cut off long downloads.

## Deploy the backend on Render

I could not run Render or Docker from here, so these settings are written from the actual file layout and checked by tests, not verified on Render. Check the first deploy log.

### Option 1 (recommended): repository root

In your existing service: Settings, Build & Deploy.

| Setting | Value |
|---|---|
| Language / Runtime | Docker |
| Branch | main |
| Root Directory | leave empty |
| Dockerfile Path | `./Dockerfile` |
| Docker Build Context Directory | `.` |
| Health Check Path | `/api/health` |
| Instance type | Free |

### Option 2: Root Directory = backend

| Setting | Value |
|---|---|
| Root Directory | `backend` |
| Dockerfile Path | `./Dockerfile` |
| Docker Build Context Directory | `.` |

With Option 2, never write the folder name again in the Dockerfile Path or the context. Render already starts inside that folder, and repeating it makes it look for a second, nonexistent folder with the same name inside it. That was the cause of the earlier `lstat .../backend/backend` error. The earlier `failed to read dockerfile` error means there was no file at the configured path. In this layout `Dockerfile` (root) and `backend/Dockerfile` both exist.

After saving: Manual Deploy, then "Clear build cache & deploy". The Docker image installs FFmpeg and Deno (the JavaScript runtime yt-dlp needs for YouTube). The server listens on `0.0.0.0` and the `PORT` Render provides.

### Environment variables (Render, Environment tab)

| Variable | Value | Notes |
|---|---|---|
| FRONTEND_ORIGIN | `https://shiv-yogi19.github.io` | Origin only. No `/FluxVid` path, no trailing slash. Comma-separate more origins. `*` is ignored |
| TRUST_PROXY | `true` | Lets rate limits see the real visitor address |
| MAX_DOWNLOAD_SIZE | `262144000` | Bytes (250 MB). Raise only if your disk allows |
| DOWNLOAD_TIMEOUT | `600` | Seconds per download |
| JOB_TTL | `900` | Seconds a finished file stays available |
| MAX_ACTIVE_JOBS / MAX_JOBS_PER_IP | `2` / `1` | Keep low on the free plan |
| RATE_LIMIT_PER_MINUTE | `30` | |
| TEMP_DIRECTORY | `/tmp/fluxvid` | |
| ENABLE_DOCS | `true` | Serves `/docs` |

No secrets are needed. Never commit a `.env` file (it is git-ignored). `backend/.env.example` lists every variable.

### Check that it works

Open these in your phone browser (the first request can take a minute while the free server wakes):

- `https://fluxvid.onrender.com/` shows a small JSON status
- `https://fluxvid.onrender.com/api/health` shows `"status":"ok"` and `"ffmpeg":true`
- `https://fluxvid.onrender.com/docs` shows the interactive API docs

If `/docs` shows `{"detail":"Not Found"}`, Render is still running an old build. Redeploy and read the Logs.

### Free-plan limits (confirm current numbers on render.com/pricing)

- Free web services sleep after roughly 15 minutes without traffic and take up to about a minute to wake. FluxVid shows "Waking server" and retries for you.
- Memory and CPU are small. Merging video is fast (streams are copied), but MP3 conversion and long videos are slow.
- Disk is temporary: files vanish on restart or redeploy, and jobs are held in memory, so a restart cancels running jobs.
- Download size is capped by `MAX_DOWNLOAD_SIZE`. Nothing is stored permanently.
- Sites often block data-centre addresses. YouTube may answer "confirm you're not a bot", and Instagram and Facebook often need a login. Those links fail with a clear message. FluxVid does not log in or bypass anything.

## Deploy the frontend on GitHub Pages

1. Make sure `docs/config.js` has your backend address in `apiBase` (default `https://fluxvid.onrender.com`).
2. Repository, Settings, Pages, Source: "Deploy from a branch", Branch `main`, Folder `/docs`, Save.
3. Open `https://shiv-yogi19.github.io/FluxVid/`. The status pill should turn green.

## Replace the repository from an Android phone

### Option A: Termux (keeps the folder structure)

1. Install Termux from F-Droid, then in Termux: `pkg update && pkg install git unzip`, then `termux-setup-storage` and allow access.
2. Save `FluxVid.zip` to Downloads, then:

        cd ~ && unzip ~/storage/downloads/FluxVid.zip -d new
        git clone https://github.com/shiv-yogi19/FluxVid.git repo
        cd repo
        git rm -r -q . ; cp -a ../new/FluxVid/. .
        git config user.name "Shiv Yogi" ; git config user.email "you@example.com"
        git add -A && git commit -m "FluxVid v2" && git push

3. When `git push` asks for a password, paste a GitHub personal access token (GitHub, Settings, Developer settings, Fine-grained tokens, access to this repository only, Contents: read and write). Do not put the token in any file.

### Option B: browser only

GitHub's mobile upload cannot upload folders, so create each file with Add file, Create new file, typing the full path such as `backend/app/main.py`, then paste the content. It is about 45 files, most of them small; Termux is much easier. Binary files (the three PNG icons in `docs/assets`) cannot be pasted; upload those with Add file, Upload files after opening the `docs/assets` folder, or skip them (the app works without them, only Android install loses its icon).

## Run and test locally

    cd backend
    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements-dev.txt      # also install ffmpeg
    uvicorn app.main:app --reload --port 8000
    # second terminal
    cd docs && python -m http.server 8080    # open http://localhost:8080

Tests (from the repository root):

    cd backend && python -m unittest discover -s tests -t .
    node --test tests/frontend/frontend.test.mjs

The HTTP route tests need `pip install -r requirements-dev.txt`; without FastAPI they are skipped.

## API

Errors always look like `{"error": {"code": "...", "message": "..."}}`. Interactive docs: `/docs`.

| Method and path | Purpose |
|---|---|
| `GET /` | Service status |
| `GET /api/health` | `status`, `ffmpeg`, `yt_dlp` version, `active_jobs`, limits |
| `POST /api/info` `{"url"}` | Metadata and options (`video`, `audio` lists with `id`, `label`, `size`, `recommended`, `over_limit`) |
| `POST /api/jobs` `{"url","type","quality"}` | Start a download. `type` is `video` or `audio`. `quality` is `best`, a video height such as `720`, or an audio kbps such as `128`. Returns 202 and a job |
| `GET /api/jobs/{id}` | `state`, `stage`, `progress` (only when known), `downloaded_bytes`, `expected_bytes`, `filename`, `file_url`, `expires_in`, `error` |
| `GET /api/jobs/{id}/file` | The file, as an attachment with the FluxVid file name |
| `DELETE /api/jobs/{id}` | Cancel and delete (204, safe to repeat) |

## Troubleshooting

- "Could not reach the FluxVid server": the pill says Offline. Open `/api/health` in the browser; check `apiBase` in `docs/config.js` and that Render is running.
- Browser console shows a CORS error: `FRONTEND_ORIGIN` must be exactly `https://shiv-yogi19.github.io`.
- "Unexpected response (HTTP 404)": `apiBase` points at the wrong address.
- "Unable to process this URL": update yt-dlp by redeploying with a cleared build cache; the source may also be private or blocked.
- Build fails at the Deno line: delete the two `deno` lines in the Dockerfile you use. Everything works except some YouTube links.

## Security

Only http/https on ports 80 and 443; no credentials in URLs; the host must resolve to public addresses only (blocks localhost, private networks, cloud metadata). yt-dlp runs without a shell, with a timeout, size limit, private temp folder, and non-root user. Job ids are random 128-bit values. CORS allows only your configured origins. Rate limits and concurrency caps apply. Limitation: the address check covers the link you submit; yt-dlp may follow redirects or fetch pages the site references, so for stronger isolation keep the server off private networks.

## Legal

Download only content you own, that is in the public domain, or that you have permission to save, and follow each site's terms and your local laws. FluxVid does not bypass DRM, logins, private content or platform access controls.

## Verification status

Tested here: Python syntax, 41 Python tests (URL and SSRF validation, file naming, format detection, size estimates, job lifecycle, cancellation, timeouts, size limits, cleanup, concurrency, error classification, frontend/backend/Docker/Render consistency), 10 Node tests (API client, errors, timeouts, storage). The job tests ran real subprocesses and real FFmpeg against a stand-in for yt-dlp.

Not tested here, so confirm after deploying: the FastAPI HTTP layer (5 tests written, skipped because FastAPI could not be installed in the sandbox), the Docker build, Render settings, real yt-dlp against real sites (including its progress output format), real browsers and Android devices, and PWA install and Share.
