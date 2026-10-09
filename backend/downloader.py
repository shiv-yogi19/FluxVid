"""Extraction and download logic. yt-dlp runs as a subprocess with an argument
list (never a shell), a hard timeout, and a private temporary directory."""
import asyncio
import ipaddress
import json
import mimetypes
import re
import shutil
import socket
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from config import Settings

BRAND_SUFFIX = "_FluxVid-created by shiv yogi"
MAX_URL_LENGTH = 2048
STANDARD_BITRATES = (64, 96, 128, 160, 192, 256, 320)
_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


class DownloadError(Exception):
    """An error that is safe to show to end users."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    workdir: Path
    filename: str
    mime: str


# --- filenames -------------------------------------------------------------

def sanitize_title(title: str, max_len: int = 100) -> str:
    text = unicodedata.normalize("NFC", title or "")
    text = _INVALID_NAME_CHARS.sub(" ", text)
    text = re.sub(r"\s+", "_", text.strip()).strip("._")
    return text[:max_len].rstrip("._") or "media"


def build_filename(title: str, extension: str) -> str:
    ext = re.sub(r"[^a-z0-9]", "", (extension or "").lower()) or "bin"
    return f"{sanitize_title(title)}{BRAND_SUFFIX}.{ext}"


# --- URL validation --------------------------------------------------------

def _invalid_url() -> DownloadError:
    return DownloadError("invalid_url", "Enter a valid http or https link.")


async def validate_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url or len(url) > MAX_URL_LENGTH or any(c.isspace() or ord(c) < 32 for c in url):
        raise _invalid_url()
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise _invalid_url()
    try:
        port = parts.port
    except ValueError:
        raise _invalid_url() from None
    if port not in (None, 80, 443):
        raise _invalid_url()
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            parts.hostname, port or 443, type=socket.SOCK_STREAM
        )
    except socket.gaierror:
        raise DownloadError("unresolvable", "That address could not be found.") from None
    for info in infos:
        if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
            raise DownloadError("blocked_address", "That address is not allowed.")
    return url


# --- yt-dlp subprocess -----------------------------------------------------

async def _run_ytdlp(args: list, timeout: int):
    cmd = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
           "--no-warnings", "--socket-timeout", "20", *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except BaseException as exc:
        proc.kill()
        try:
            await proc.wait()
        except BaseException:
            pass
        if isinstance(exc, asyncio.TimeoutError):
            raise DownloadError("timeout", "The source took too long to respond. Try again later.", 504) from None
        raise
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _classify_failure(stderr: str) -> DownloadError:
    text = stderr.lower()
    if "larger than max-filesize" in text or "max-filesize" in text:
        return DownloadError("too_large", "This file is larger than the server limit.", 413)
    if "drm" in text:
        return DownloadError("drm", "This media is DRM-protected and cannot be downloaded.", 422)
    if any(k in text for k in ("private", "sign in", "log in", "login", "cookies", "members-only", "age-restricted", "confirm you")):
        return DownloadError("restricted", "This media is private, login-only, or restricted.", 422)
    if any(k in text for k in ("geo", "not available in your country", "region")):
        return DownloadError("region", "This media is not available in the server's region.", 422)
    if "unsupported url" in text:
        return DownloadError("unsupported", "This source is not supported.", 422)
    return DownloadError(
        "extraction_failed",
        "Unable to process this URL. The source may be unsupported, private, DRM-protected, restricted, or temporarily unavailable.",
        422,
    )


# --- info ------------------------------------------------------------------

def _is_video(f: dict) -> bool:
    return f.get("vcodec") != "none" and f.get("ext") != "mhtml" and bool(f.get("vcodec") or f.get("height"))


def _is_audio(f: dict) -> bool:
    return f.get("acodec") != "none" and f.get("ext") != "mhtml" and bool(f.get("acodec") or f.get("abr") or _is_video(f))


def _https(value):
    return value if isinstance(value, str) and value.startswith(("http://", "https://")) else None


def summarize(data: dict) -> dict:
    formats = data.get("formats") or [data]
    video = [f for f in formats if _is_video(f)]
    audio = [f for f in formats if _is_audio(f)]

    heights = {}
    for f in video:
        if f.get("height"):
            h = int(f["height"])
            short = min(h, int(f["width"])) if f.get("width") else h
            heights[h] = f"{short}p"
    if heights:
        video_opts = [{"id": str(h), "label": heights[h]} for h in sorted(heights, reverse=True)]
    elif video:
        video_opts = [{"id": "best", "label": "Best available"}]
    else:
        video_opts = []

    audio_opts = []
    if audio:
        buckets = set()
        for f in audio:
            abr = f.get("abr")
            if abr and abr > 0:
                fits = [b for b in STANDARD_BITRATES if b <= abr * 1.1]
                buckets.add(max(fits) if fits else int(round(abr)))
        audio_opts = [{"id": "best", "label": "Best audio"}] + [
            {"id": str(b), "label": f"{b} kbps"} for b in sorted(buckets, reverse=True)
        ]

    if not video_opts and not audio_opts:
        raise DownloadError("no_formats", "No downloadable media was found at this link.", 422)

    thumbs = data.get("thumbnails") or []
    duration = data.get("duration")
    return {
        "title": data.get("title") or "Untitled",
        "duration": int(duration) if isinstance(duration, (int, float)) else None,
        "thumbnail": _https(data.get("thumbnail")) or (_https(thumbs[-1].get("url")) if thumbs else None),
        "platform": data.get("extractor_key") or data.get("extractor"),
        "source_url": _https(data.get("webpage_url")),
        "types": (["video"] if video_opts else []) + (["audio"] if audio_opts else []),
        "video": video_opts,
        "audio": audio_opts,
        "video_format": "MP4",
        "audio_format": "MP3",
    }


async def fetch_info(url: str, settings: Settings) -> dict:
    code, out, err = await _run_ytdlp(["-J", "--", url], min(settings.download_timeout, 90))
    if code != 0 or not out.strip():
        raise _classify_failure(err)
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise _classify_failure(err) from None
    if data.get("_type") == "playlist":
        entries = [e for e in (data.get("entries") or []) if e]
        if not entries:
            raise DownloadError("no_formats", "No downloadable media was found at this link.", 422)
        data = entries[0]
    if data.get("is_live"):
        raise DownloadError("live", "Live streams are not supported.", 422)
    return summarize(data)


# --- download --------------------------------------------------------------

def build_format_args(media_type: str, quality: str) -> list:
    if media_type == "video":
        if quality == "best":
            selector = "bv*+ba/b"
        else:
            height = int(quality)
            if not 144 <= height <= 4320:
                raise DownloadError("invalid_quality", "That quality is not available.")
            selector = f"bv*[height<={height}]+ba/b[height<={height}]"
        return ["-f", selector, "-S", "res,vcodec:h264,acodec:aac", "--merge-output-format", "mp4"]
    if quality == "best":
        level = "0"
    else:
        kbps = int(quality)
        if not 32 <= kbps <= 320:
            raise DownloadError("invalid_quality", "That quality is not available.")
        level = f"{kbps}K"
    return ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", level]


async def download(url: str, media_type: str, quality: str, settings: Settings) -> DownloadResult:
    if not shutil.which("ffmpeg"):
        raise DownloadError("server_misconfigured", "The server is missing a required component. Please try again later.", 503)
    format_args = build_format_args(media_type, quality)
    settings.temp_directory.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="fv_", dir=settings.temp_directory))
    try:
        code, out, err = await _run_ytdlp(
            ["-J", "--no-simulate", "--no-progress",
             "--max-filesize", str(settings.max_download_size),
             "-o", str(workdir / "media.%(ext)s"), *format_args, "--", url],
            settings.download_timeout,
        )
        files = [p for p in workdir.iterdir() if p.is_file() and p.suffix not in (".part", ".ytdl", ".json")]
        if code != 0 or not files:
            raise _classify_failure(err)
        path = max(files, key=lambda p: p.stat().st_size)
        if path.stat().st_size > settings.max_download_size:
            raise DownloadError("too_large", "This file is larger than the server limit.", 413)
        try:
            title = json.loads(out).get("title") or "media"
        except (json.JSONDecodeError, AttributeError):
            title = "media"
        ext = path.suffix.lstrip(".")
        mime = mimetypes.types_map.get(f".{ext}") or "application/octet-stream"
        return DownloadResult(path, workdir, build_filename(title, ext), mime)
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise


def sweep_stale(temp_directory: Path, max_age_seconds: int = 3600) -> int:
    """Remove leftover work directories (e.g. after a dropped connection)."""
    removed = 0
    if not temp_directory.is_dir():
        return removed
    cutoff = time.time() - max_age_seconds
    for child in temp_directory.iterdir():
        if child.is_dir() and child.name.startswith("fv_") and child.stat().st_mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed
