"""Runtime configuration, read once from environment variables."""
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ORIGINS = "http://localhost:8080,http://127.0.0.1:8080"


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from None
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class Settings:
    frontend_origins: tuple
    max_download_size: int
    download_timeout: int
    temp_directory: Path
    rate_limit_per_minute: int
    max_concurrent_downloads: int
    trust_proxy: bool


def load_settings() -> Settings:
    raw_origins = os.environ.get("FRONTEND_ORIGIN", DEFAULT_ORIGINS)
    origins = tuple(
        o.strip().rstrip("/") for o in raw_origins.split(",") if o.strip() and o.strip() != "*"
    )
    temp = Path(os.environ.get("TEMP_DIRECTORY") or Path(tempfile.gettempdir()) / "fluxvid")
    return Settings(
        frontend_origins=origins,
        max_download_size=_int("MAX_DOWNLOAD_SIZE", 524_288_000),
        download_timeout=_int("DOWNLOAD_TIMEOUT", 300),
        temp_directory=temp.resolve(),
        rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 20),
        max_concurrent_downloads=_int("MAX_CONCURRENT_DOWNLOADS", 2),
        trust_proxy=os.environ.get("TRUST_PROXY", "false").lower() == "true",
    )
