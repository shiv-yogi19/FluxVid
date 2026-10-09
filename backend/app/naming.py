"""Download file names: <Sanitized Title>_FluxVid-created by shiv yogi.<ext>"""
import re
import unicodedata

BRAND_SUFFIX = "_FluxVid-created by shiv yogi"
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_BRAND_TAIL = re.compile(r"(_?FluxVid-created[ _]by[ _]shiv[ _]yogi)+$", re.IGNORECASE)


def sanitize_title(title: str, max_len: int = 100) -> str:
    text = unicodedata.normalize("NFC", title or "")
    text = _INVALID.sub(" ", text)
    text = re.sub(r"\s+", "_", text.strip()).strip("._")
    text = _BRAND_TAIL.sub("", text).strip("._")  # never duplicate the suffix
    return text[:max_len].rstrip("._") or "media"


def build_filename(title: str, extension: str) -> str:
    ext = re.sub(r"[^a-z0-9]", "", (extension or "").lower()) or "bin"
    return f"{sanitize_title(title)}{BRAND_SUFFIX}.{ext}"
