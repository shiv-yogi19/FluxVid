"""Metadata lookups with a small TTL cache (also supplies expected sizes to jobs)."""
import time
from typing import Optional

from . import formats, runner
from .config import Settings

CACHE_TTL = 600
CACHE_MAX = 64


class InfoService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache = {}

    async def get(self, url: str) -> dict:
        now = time.monotonic()
        hit = self._cache.get(url)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]
        data = await runner.run_info(url, min(self.settings.download_timeout, 90))
        summary = formats.summarize(data, self.settings.max_download_size)
        if len(self._cache) >= CACHE_MAX:
            self._cache.pop(min(self._cache, key=lambda k: self._cache[k][0]))
        self._cache[url] = (now, summary)
        return summary

    def expected_size(self, url: str, media_type: str, quality: str) -> Optional[int]:
        hit = self._cache.get(url)
        if not hit:
            return None
        for option in hit[1].get(media_type, []):
            if option["id"] == quality:
                return option["size"]
        return None

    def known_option(self, url: str, media_type: str, quality: str) -> Optional[bool]:
        """True/False if the URL was analyzed and the option does/doesn't exist; None if not analyzed."""
        hit = self._cache.get(url)
        if not hit:
            return None
        return any(o["id"] == quality for o in hit[1].get(media_type, []))
