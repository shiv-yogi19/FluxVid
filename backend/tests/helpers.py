import os
import tempfile
from dataclasses import replace
from pathlib import Path

FAKE = str(Path(__file__).parent / "fake_ytdlp")
# Subprocesses started by the app import the stub instead of the real yt-dlp.
os.environ["PYTHONPATH"] = FAKE + os.pathsep + os.environ.get("PYTHONPATH", "")

from app.config import load_settings  # noqa: E402

PUBLIC = "https://8.8.8.8/watch?v=1"  # IP literal: public, resolves without DNS


def make_settings(tmp: Path, **overrides):
    base = load_settings({"TEMP_DIRECTORY": str(tmp), "FRONTEND_ORIGIN": "https://shiv-yogi19.github.io"})
    return replace(base, **overrides)


def tempdir():
    return Path(tempfile.mkdtemp(prefix="fvtest_"))
