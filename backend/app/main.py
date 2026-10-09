"""FluxVid API. Run: uvicorn app.main:app --host 0.0.0.0 --port $PORT"""
import asyncio
import logging
import shutil
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import urls
from .config import Settings, load_settings
from .errors import AppError
from .info import InfoService
from .jobs import JobManager
from .schemas import ErrorResponse, HealthResponse, InfoRequest, InfoResponse, JobRequest, JobResponse

log = logging.getLogger("fluxvid")
JOB_ID = Path(pattern=r"^[A-Za-z0-9_-]{16,64}$", description="Job id returned by POST /api/jobs")
ERRORS = {"model": ErrorResponse}


class RateLimiter:
    def __init__(self, limit: int, window: int = 60):
        self.limit, self.window, self.hits = limit, window, defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        queue = self.hits[key]
        while queue and now - queue[0] > self.window:
            queue.popleft()
        if len(queue) >= self.limit:
            raise AppError("rate_limited", "Too many requests. Please wait a moment and try again.", 429)
        queue.append(now)
        if len(self.hits) > 5000:
            for k in [k for k, q in self.hits.items() if not q or now - q[-1] > self.window]:
                del self.hits[k]


def _yt_dlp_version() -> Optional[str]:
    try:
        from yt_dlp.version import __version__
        return __version__
    except Exception:
        return None


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or load_settings()
    info_service = InfoService(settings)
    jobs = JobManager(settings, info_service)
    limiter = RateLimiter(settings.rate_limit_per_minute)

    async def sweep_loop():
        while True:
            await asyncio.sleep(60)
            jobs.sweep()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.temp_directory.mkdir(parents=True, exist_ok=True)
        jobs.sweep()
        if not shutil.which("ffmpeg"):
            log.warning("FFmpeg not found on PATH: downloads will fail until it is installed.")
        if not settings.frontend_origins:
            log.warning("FRONTEND_ORIGIN is empty: browsers will block every cross-origin request.")
        task = asyncio.create_task(sweep_loop())
        yield
        task.cancel()
        await jobs.shutdown()

    app = FastAPI(
        title="FluxVid API",
        version="2.0.0",
        description="Analyze public media URLs and download them as MP4 or MP3. Created By Shiv Yogi.",
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
        lifespan=lifespan,
    )
    app.state.settings, app.state.jobs, app.state.info = settings, jobs, info_service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.frontend_origins),
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition", "Content-Length"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def client_ip(request: Request) -> str:
        if settings.trust_proxy:
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def error_response(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, __: RequestValidationError):
        return error_response(422, "invalid_request", "The request was not valid.")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        messages = {404: ("not_found", "That endpoint does not exist."), 405: ("method_not_allowed", "That method is not allowed here.")}
        code, message = messages.get(exc.status_code, ("http_error", "The request could not be completed."))
        return error_response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        log.exception("Unhandled error", exc_info=exc)
        return error_response(500, "server_error", "Something went wrong on the server. Please try again.")

    @app.get("/", include_in_schema=False)
    async def root():
        return {"name": "FluxVid API", "status": "ok", "health": "/api/health",
                "docs": "/docs" if settings.enable_docs else None}

    @app.get("/api/health", response_model=HealthResponse, tags=["system"])
    async def health():
        return {"status": "ok", "ffmpeg": shutil.which("ffmpeg") is not None, "yt_dlp": _yt_dlp_version(),
                "active_jobs": jobs.active_count(), "max_download_size": settings.max_download_size,
                "job_ttl": settings.job_ttl}

    @app.post("/api/info", response_model=InfoResponse, responses={400: ERRORS, 422: ERRORS, 429: ERRORS, 504: ERRORS}, tags=["media"])
    async def info(body: InfoRequest, request: Request):
        limiter.check(client_ip(request))
        url = await urls.validate_url(body.url)
        return await info_service.get(url)

    @app.post("/api/jobs", status_code=202, response_model=JobResponse, responses={400: ERRORS, 413: ERRORS, 429: ERRORS, 503: ERRORS}, tags=["jobs"])
    async def create_job(body: JobRequest, request: Request):
        ip = client_ip(request)
        limiter.check(ip)
        url = await urls.validate_url(body.url)
        if not shutil.which("ffmpeg"):
            raise AppError("server_misconfigured", "The server is missing a required component. Please try again later.", 503)
        return jobs.public(jobs.create(url, body.type, body.quality, ip))

    @app.get("/api/jobs/{job_id}", response_model=JobResponse, responses={404: ERRORS}, tags=["jobs"])
    async def job_status(job_id: str = JOB_ID):
        return jobs.public(jobs.get(job_id))

    @app.get("/api/jobs/{job_id}/file", responses={404: ERRORS, 409: ERRORS}, tags=["jobs"])
    async def job_file(job_id: str = JOB_ID):
        job = jobs.get(job_id)
        if job.state != "ready" or job.path is None or not job.path.exists():
            raise AppError("not_ready", "This file is not ready yet.", 409)
        return FileResponse(job.path, media_type=job.mime, filename=job.filename)

    @app.delete("/api/jobs/{job_id}", status_code=204, tags=["jobs"])
    async def cancel_job(job_id: str = JOB_ID):
        await jobs.remove(job_id)
        return Response(status_code=204)

    return app


app = create_app()
