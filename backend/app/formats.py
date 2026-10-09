"""Turn raw yt-dlp metadata into the options shown in the UI. Nothing is invented:
only qualities present in the source are listed, and sizes appear only when the
source reports them (or can be derived from duration and bitrate)."""
from typing import Optional

from .errors import AppError

STANDARD_BITRATES = (64, 96, 128, 160, 192, 256, 320)
RECOMMENDED_MAX_HEIGHT = 1080


def _is_video(f: dict) -> bool:
    return f.get("vcodec") != "none" and f.get("ext") != "mhtml" and bool(f.get("vcodec") or f.get("height"))


def _is_audio(f: dict) -> bool:
    return f.get("acodec") != "none" and f.get("ext") != "mhtml" and bool(f.get("acodec") or f.get("abr") or _is_video(f))


def _is_audio_only(f: dict) -> bool:
    return f.get("vcodec") == "none" and f.get("acodec") not in (None, "none") and f.get("ext") != "mhtml"


def _size(f: dict) -> Optional[int]:
    value = f.get("filesize") or f.get("filesize_approx")
    return int(value) if isinstance(value, (int, float)) and value > 0 else None


def _https(value):
    return value if isinstance(value, str) and value.startswith(("http://", "https://")) else None


def _video_size(video: list, audio_only: list, height: int) -> Optional[int]:
    candidates = [f for f in video if f.get("height") == height]
    if not candidates:
        return None
    pick = max(candidates, key=lambda f: ((f.get("vcodec") or "").startswith(("avc", "h264")), f.get("tbr") or 0))
    size = _size(pick)
    if size is None or pick.get("acodec") not in (None, "none") or not audio_only:
        return size
    best_audio = max(audio_only, key=lambda f: ((f.get("acodec") or "").startswith("mp4a"), f.get("abr") or 0))
    audio_size = _size(best_audio)
    return size + audio_size if audio_size is not None else None


def summarize(data: dict, max_download_size: int) -> dict:
    formats = data.get("formats") or [data]
    video = [f for f in formats if _is_video(f)]
    audio = [f for f in formats if _is_audio(f)]
    audio_only = [f for f in formats if _is_audio_only(f)]
    duration = data.get("duration") if isinstance(data.get("duration"), (int, float)) else None

    heights = {}
    for f in video:
        if f.get("height"):
            h = int(f["height"])
            short = min(h, int(f["width"])) if f.get("width") else h
            heights[h] = f"{short}p"

    video_opts = []
    if heights:
        ordered = sorted(heights, reverse=True)
        within = [h for h in ordered if h <= RECOMMENDED_MAX_HEIGHT]
        recommended = within[0] if within else ordered[-1]
        for h in ordered:
            size = _video_size(video, audio_only, h)
            video_opts.append({"id": str(h), "label": heights[h], "size": size,
                               "recommended": h == recommended,
                               "over_limit": size is not None and size > max_download_size})
    elif video:
        video_opts.append({"id": "best", "label": "Best available", "size": None, "recommended": True, "over_limit": False})

    audio_opts = []
    if audio:
        buckets = set()
        for f in audio:
            abr = f.get("abr")
            if abr and abr > 0:
                fits = [b for b in STANDARD_BITRATES if b <= abr * 1.1]
                buckets.add(max(fits) if fits else int(round(abr)))
        audio_opts.append({"id": "best", "label": "Best audio", "size": None, "recommended": True, "over_limit": False})
        for kbps in sorted(buckets, reverse=True):
            size = int(duration * kbps * 125) if duration else None  # kbit/s * seconds / 8
            audio_opts.append({"id": str(kbps), "label": f"{kbps} kbps", "size": size, "recommended": False,
                               "over_limit": size is not None and size > max_download_size})

    if not video_opts and not audio_opts:
        raise AppError("no_formats", "No downloadable media was found at this link.", 422)

    thumbs = data.get("thumbnails") or []
    return {
        "title": data.get("title") or "Untitled",
        "duration": int(duration) if duration is not None else None,
        "thumbnail": _https(data.get("thumbnail")) or (_https(thumbs[-1].get("url")) if thumbs else None),
        "platform": data.get("extractor_key") or data.get("extractor"),
        "source_url": _https(data.get("webpage_url")),
        "types": (["video"] if video_opts else []) + (["audio"] if audio_opts else []),
        "video": video_opts,
        "audio": audio_opts,
        "video_format": "MP4",
        "audio_format": "MP3",
        "max_download_size": max_download_size,
    }
