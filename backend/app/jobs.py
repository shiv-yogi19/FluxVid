"""Download jobs: a real subprocess per job, real progress, real cancellation."""
import asyncio
import logging
import mimetypes
import secrets
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import runner
from .config import Settings
from .errors import AppError
from .info import InfoService
from .naming import build_filename

log = logging.getLogger("fluxvid.jobs")
ACTIVE = ("queued", "running")


@dataclass
class Job:
    id: str
    url: str
    media_type: str
    quality: str
    ip: str
    expected: Optional[int] = None
    state: str = "queued"          # queued | running | ready | failed
    stage: str = "queued"          # queued | starting | downloading | processing | ready | failed
    downloaded: int = 0
    error: Optional[AppError] = None
    workdir: Optional[Path] = None
    path: Optional[Path] = None
    filename: Optional[str] = None
    mime: Optional[str] = None
    size: Optional[int] = None
    created: float = field(default_factory=time.monotonic)
    finished: Optional[float] = None
    task: Optional[asyncio.Task] = None

    @property
    def progress(self) -> Optional[float]:
        if self.state == "ready":
            return 1.0
        if self.expected and self.stage == "downloading":
            return min(self.downloaded / self.expected, 0.99)
        return None


class JobManager:
    def __init__(self, settings: Settings, info: InfoService):
        self.settings, self.info = settings, info
        self.jobs = {}

    def active_count(self, ip: Optional[str] = None) -> int:
        return sum(1 for j in self.jobs.values() if j.state in ACTIVE and (ip is None or j.ip == ip))

    def create(self, url: str, media_type: str, quality: str, ip: str) -> Job:
        runner.build_format_args(media_type, quality)  # validates type and quality early
        if self.info.known_option(url, media_type, quality) is False:
            raise AppError("invalid_quality", "That quality is not available for this media.")
        if self.active_count(ip) >= self.settings.max_jobs_per_ip:
            raise AppError("too_many_jobs", "You already have a download in progress. Wait for it or cancel it first.", 429)
        if self.active_count() >= self.settings.max_active_jobs:
            raise AppError("busy", "The server is busy right now. Please try again shortly.", 503)
        expected = self.info.expected_size(url, media_type, quality)
        if expected and expected > self.settings.max_download_size:
            raise AppError("too_large", "This file is larger than the server limit.", 413)
        job = Job(secrets.token_urlsafe(16), url, media_type, quality, ip, expected)
        self.jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job))
        return job

    def get(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise AppError("job_not_found", "This download is no longer available. Start it again.", 404)
        return job

    async def _run(self, job: Job) -> None:
        s = self.settings
        job.state, job.stage = "running", "starting"
        s.temp_directory.mkdir(parents=True, exist_ok=True)
        job.workdir = Path(tempfile.mkdtemp(prefix="fv_", dir=s.temp_directory))

        def on_progress(total: int):
            job.downloaded = total

        def on_stage(stage: str):
            job.stage = stage

        try:
            title = await runner.run_download(
                job.url, job.media_type, job.quality, job.workdir,
                timeout=s.download_timeout, max_bytes=s.max_download_size,
                on_progress=on_progress, on_stage=on_stage,
            )
            files = [p for p in job.workdir.iterdir() if p.is_file() and p.suffix not in (".part", ".ytdl", ".json")]
            if not files:
                raise runner.classify_failure("")
            path = max(files, key=lambda p: p.stat().st_size)
            size = path.stat().st_size
            if size > s.max_download_size:
                raise AppError("too_large", "This file is larger than the server limit.", 413)
            ext = path.suffix.lstrip(".")
            job.path, job.size = path, size
            job.mime = mimetypes.types_map.get(f".{ext}") or "application/octet-stream"
            job.filename = build_filename(title or "media", ext)
            job.state, job.stage, job.finished = "ready", "ready", time.monotonic()
        except asyncio.CancelledError:
            self._discard_files(job)
            raise
        except AppError as exc:
            self._fail(job, exc)
        except Exception:
            log.exception("Job %s crashed", job.id)
            self._fail(job, AppError("server_error", "Something went wrong while downloading. Please try again.", 500))

    def _fail(self, job: Job, error: AppError) -> None:
        job.state, job.stage, job.error, job.finished = "failed", "failed", error, time.monotonic()
        self._discard_files(job)

    @staticmethod
    def _discard_files(job: Job) -> None:
        if job.workdir:
            shutil.rmtree(job.workdir, ignore_errors=True)
        job.path = None

    async def remove(self, job_id: str) -> None:
        """Cancel if running, delete files, forget the job. Safe to call twice."""
        job = self.jobs.pop(job_id, None)
        if job is None:
            return
        if job.task and not job.task.done():
            job.task.cancel()
            try:
                await job.task
            except BaseException:
                pass
        self._discard_files(job)

    def sweep(self) -> None:
        """Drop finished jobs past their TTL and any abandoned work directories."""
        now = time.monotonic()
        for job_id in [i for i, j in self.jobs.items() if j.finished and now - j.finished > self.settings.job_ttl]:
            job = self.jobs.pop(job_id)
            self._discard_files(job)
        tmp = self.settings.temp_directory
        if tmp.is_dir():
            known = {j.workdir for j in self.jobs.values() if j.workdir}
            cutoff = time.time() - max(self.settings.job_ttl, self.settings.download_timeout) - 300
            for child in tmp.iterdir():
                if child.is_dir() and child.name.startswith("fv_") and child not in known and child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)

    async def shutdown(self) -> None:
        for job_id in list(self.jobs):
            await self.remove(job_id)

    def public(self, job: Job) -> dict:
        ready = job.state == "ready"
        return {
            "id": job.id,
            "state": job.state,
            "stage": job.stage,
            "progress": job.progress,
            "downloaded_bytes": job.downloaded,
            "expected_bytes": job.expected,
            "filename": job.filename if ready else None,
            "size": job.size if ready else None,
            "file_url": f"/api/jobs/{job.id}/file" if ready else None,
            "expires_in": max(0, int(self.settings.job_ttl - (time.monotonic() - job.finished))) if ready and job.finished else None,
            "error": {"code": job.error.code, "message": job.error.message} if job.error else None,
        }
