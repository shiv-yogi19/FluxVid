"""Runs yt-dlp as a subprocess (argument list, never a shell) with timeouts."""
import asyncio
import json
import sys
from pathlib import Path
from typing import Callable, Optional

from .errors import AppError

BASE_ARGS = ["--ignore-config", "--no-playlist", "--no-warnings", "--socket-timeout", "20"]


def _command(args: list) -> list:
    return [sys.executable, "-m", "yt_dlp", *BASE_ARGS, *args]


def classify_failure(stderr: str) -> AppError:
    text = stderr.lower()
    if "max-filesize" in text:
        return AppError("too_large", "This file is larger than the server limit.", 413)
    if "drm" in text:
        return AppError("drm", "This media is DRM-protected and cannot be downloaded.", 422)
    if any(k in text for k in ("private", "sign in", "log in", "login", "cookies", "members-only", "age-restricted", "confirm you")):
        return AppError("restricted", "This media is private, login-only, or restricted.", 422)
    if any(k in text for k in ("geo", "not available in your country", "region")):
        return AppError("region", "This media is not available in the server's region.", 422)
    if "unsupported url" in text:
        return AppError("unsupported", "This source is not supported.", 422)
    return AppError(
        "extraction_failed",
        "Unable to process this URL. The source may be unsupported, private, DRM-protected, restricted, or temporarily unavailable.",
        422,
    )


async def _spawn(cmd: list):
    """Start a subprocess; if we are cancelled mid-spawn, still kill the child instead of leaking it."""
    spawning = asyncio.ensure_future(asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE))
    try:
        return await asyncio.shield(spawning)
    except asyncio.CancelledError:
        def reap(fut):
            if not fut.cancelled() and fut.exception() is None:
                try:
                    fut.result().kill()
                except ProcessLookupError:
                    pass
        if spawning.done():
            reap(spawning)
        else:
            spawning.add_done_callback(reap)
        raise


async def _kill(proc) -> None:
    try:
        proc.kill()
        await proc.wait()
    except (ProcessLookupError, BaseException):
        pass


async def run_info(url: str, timeout: int) -> dict:
    proc = await _spawn(_command(["-J", "--", url]))
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except BaseException as exc:
        await _kill(proc)
        if isinstance(exc, asyncio.TimeoutError):
            raise AppError("timeout", "The source took too long to respond. Try again later.", 504) from None
        raise
    if proc.returncode != 0 or not out.strip():
        raise classify_failure(err.decode("utf-8", "replace"))
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise classify_failure(err.decode("utf-8", "replace")) from None
    if data.get("_type") == "playlist":
        entries = [e for e in (data.get("entries") or []) if e]
        if not entries:
            raise AppError("no_formats", "No downloadable media was found at this link.", 422)
        data = entries[0]
    if data.get("is_live"):
        raise AppError("live", "Live streams are not supported.", 422)
    return data


def build_format_args(media_type: str, quality: str) -> list:
    if media_type == "video":
        if quality == "best":
            selector = "bv*+ba/b"
        else:
            height = int(quality)
            if not 144 <= height <= 4320:
                raise AppError("invalid_quality", "That quality is not available.")
            selector = f"bv*[height<={height}]+ba/b[height<={height}]"
        return ["-f", selector, "-S", "res,vcodec:h264,acodec:aac", "--merge-output-format", "mp4"]
    if media_type != "audio":
        raise AppError("invalid_type", "Choose video or audio.")
    if quality == "best":
        level = "0"
    else:
        kbps = int(quality)
        if not 32 <= kbps <= 320:
            raise AppError("invalid_quality", "That quality is not available.")
        level = f"{kbps}K"
    return ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", level]


def _number(value: str) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


async def run_download(url: str, media_type: str, quality: str, workdir: Path, *, timeout: int, max_bytes: int,
                       on_progress: Callable[[int], None], on_stage: Callable[[str], None]) -> Optional[str]:
    """Download into workdir. Returns the media title if yt-dlp reported one.

    Progress comes from yt-dlp's own progress lines: bytes of finished streams
    plus bytes of the stream in flight. Nothing is estimated or simulated."""
    args = [
        "--no-simulate", "--newline", "--progress",
        "--progress-template", "download:FVP|%(progress.status)s|%(progress.downloaded_bytes)s",
        "--progress-template", "postprocess:FVPP|%(progress.status)s",
        "--print", "after_move:FVT|%(title)s",
        "--max-filesize", str(max_bytes),
        "-o", str(workdir / "media.%(ext)s"),
        *build_format_args(media_type, quality), "--", url,
    ]
    proc = await _spawn(_command(args))
    state = {"base": 0, "current": 0, "title": None, "too_large": False}
    stderr_tail = []

    async def read_stdout():
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("FVP|"):
                _, status, downloaded = (line.split("|") + ["", ""])[:3]
                got = _number(downloaded)
                if got is not None:
                    state["current"] = got
                if status == "finished":
                    state["base"] += state["current"]
                    state["current"] = 0
                total = state["base"] + state["current"]
                if total > max_bytes:
                    state["too_large"] = True
                    proc.kill()
                    return
                on_stage("downloading")
                on_progress(total)
            elif line.startswith("FVPP|"):
                on_stage("processing")
            elif line.startswith("FVT|"):
                state["title"] = line[4:].strip() or None

    async def read_stderr():
        async for raw in proc.stderr:
            stderr_tail.append(raw.decode("utf-8", "replace"))
            del stderr_tail[:-40]

    try:
        await asyncio.wait_for(asyncio.gather(read_stdout(), read_stderr(), proc.wait()), timeout)
    except BaseException as exc:
        await _kill(proc)
        if isinstance(exc, asyncio.TimeoutError):
            raise AppError("timeout", "The download took too long and was stopped.", 504) from None
        raise
    if state["too_large"]:
        raise AppError("too_large", "This file is larger than the server limit.", 413)
    if proc.returncode != 0:
        raise classify_failure("".join(stderr_tail))
    return state["title"]
