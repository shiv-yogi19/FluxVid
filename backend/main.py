"""FluxVid API: POST /api/info, POST /api/download, GET /api/health."""
import asyncio
import contextlib
import logging
import shutil
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

import downloader
from config import load_settings
from downloader import DownloadError

log = logging.getLogger("fluxvid")
settings = load_settings()


class RateLimiter:
    def __init__(self, limit: int, window: int = 60):
        self.limit, self.window = limit, window
        self.hits = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        queue = self.hits[key]
        while queue and now - queue[0] > self.window:
            queue.popleft()
        if len(queue) >= self.limit:
            raise DownloadError("rate_limited", "Too many requests. Please wait a moment and try again.", 429)
        queue.append(now)
        if len(self.hits) > 5000:
            for k in [k for k, q in self.hits.items() if not q or now - q[-1] > self.window]:
                del self.hits[k]


class Slots:
    """Fail fast instead of queueing when the server is at capacity."""

    def __init__(self, size: int):
        self.size, self.active = size, 0

    @contextlib.contextmanager
    def acquire(self):
        if self.active >= self.size:
            raise DownloadError("busy", "The server is busy right now. Please try again shortly.", 503)
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1


limiter = RateLimiter(settings.rate_limit_per_minute)
info_slots = Slots(settings.max_concurrent_downloads * 2)
download_slots = Slots(settings.max_concurrent_downloads)


async def _sweep_loop():
    while True:
        downloader.sweep_stale(settings.temp_directory)
        await asyncio.sleep(600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.temp_directory.mkdir(parents=True, exist_ok=True)
    if not shutil.which("ffmpeg"):
        log.warning("FFmpeg was not found on PATH; downloads will be rejected until it is installed.")
    task = asyncio.create_task(_sweep_loop())
    yield
    task.cancel()


app = FastAPI(title="FluxVid API", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.frontend_origins),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    expose_headers=["Content-Disposition", "Content-Length"],
)


class InfoRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class DownloadRequest(InfoRequest):
    type: Literal["video", "audio"]
    quality: str = Field(pattern=r"^(best|\d{2,4})$")


def _client_ip(request: Request) -> str:
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(DownloadError)
async def _download_error(_: Request, exc: DownloadError):
    return _error(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, __: RequestValidationError):
    return _error(422, "invalid_request", "The request was not valid.")


@app.exception_handler(Exception)
async def _unexpected_error(_: Request, exc: Exception):
    log.exception("Unhandled error", exc_info=exc)
    return _error(500, "server_error", "Something went wrong on the server. Please try again.")


@app.get("/api/health")
async def health():
    return {"status": "ok", "ffmpeg": shutil.which("ffmpeg") is not None}


@app.post("/api/info")
async def info(body: InfoRequest, request: Request):
    limiter.check(_client_ip(request))
    url = await downloader.validate_url(body.url)
    with info_slots.acquire():
        return await downloader.fetch_info(url, settings)


@app.post("/api/download")
async def download(body: DownloadRequest, request: Request):
    limiter.check(_client_ip(request))
    url = await downloader.validate_url(body.url)
    with download_slots.acquire():
        result = await downloader.download(url, body.type, body.quality, settings)
    return FileResponse(
        result.path,
        media_type=result.mime,
        filename=result.filename,
        background=BackgroundTask(shutil.rmtree, result.workdir, True),
    )
