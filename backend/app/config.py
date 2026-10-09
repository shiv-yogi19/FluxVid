"""Runtime configuration, read from environment variables."""
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

# Origins are scheme + host (+ port) only. A path such as /FluxVid is never part of an origin.
DEFAULT_ORIGINS = "https://shiv-yogi19.github.io,http://localhost:8080,http://127.0.0.1:8080"


def _int(env: Mapping, name: str, default: int) -> int:
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from None
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


def _flag(env: Mapping, name: str, default: bool) -> bool:
    return str(env.get(name, str(default))).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    frontend_origins: tuple
    max_download_size: int
    download_timeout: int
    temp_directory: Path
    rate_limit_per_minute: int
    max_active_jobs: int
    max_jobs_per_ip: int
    job_ttl: int
    trust_proxy: bool
    enable_docs: bool


def load_settings(env: Optional[Mapping] = None) -> Settings:
    env = os.environ if env is None else env
    origins = tuple(
        o.strip().rstrip("/")
        for o in env.get("FRONTEND_ORIGIN", DEFAULT_ORIGINS).split(",")
        if o.strip() and o.strip() != "*"
    )
    temp = Path(env.get("TEMP_DIRECTORY") or Path(tempfile.gettempdir()) / "fluxvid")
    return Settings(
        frontend_origins=origins,
        max_download_size=_int(env, "MAX_DOWNLOAD_SIZE", 262_144_000),
        download_timeout=_int(env, "DOWNLOAD_TIMEOUT", 600),
        temp_directory=temp.resolve(),
        rate_limit_per_minute=_int(env, "RATE_LIMIT_PER_MINUTE", 30),
        max_active_jobs=_int(env, "MAX_ACTIVE_JOBS", 2),
        max_jobs_per_ip=_int(env, "MAX_JOBS_PER_IP", 1),
        job_ttl=_int(env, "JOB_TTL", 900),
        trust_proxy=_flag(env, "TRUST_PROXY", False),
        enable_docs=_flag(env, "ENABLE_DOCS", True),
    )
