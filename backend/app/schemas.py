"""Request and response models (they also drive the /docs page)."""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class InfoRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048, description="Public http(s) media URL")


class JobRequest(InfoRequest):
    type: Literal["video", "audio"]
    quality: str = Field(pattern=r"^(best|\d{2,4})$", description="'best', a video height, or an audio bitrate in kbps")


class QualityOption(BaseModel):
    id: str
    label: str
    size: Optional[int] = Field(None, description="Estimated bytes, only when reliably known")
    recommended: bool
    over_limit: bool


class InfoResponse(BaseModel):
    title: str
    duration: Optional[int]
    thumbnail: Optional[str]
    platform: Optional[str]
    source_url: Optional[str]
    types: List[Literal["video", "audio"]]
    video: List[QualityOption]
    audio: List[QualityOption]
    video_format: str
    audio_format: str
    max_download_size: int


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class JobResponse(BaseModel):
    id: str
    state: Literal["queued", "running", "ready", "failed"]
    stage: Literal["queued", "starting", "downloading", "processing", "ready", "failed"]
    progress: Optional[float] = Field(None, description="0..1, only when the server knows the real total")
    downloaded_bytes: int
    expected_bytes: Optional[int]
    filename: Optional[str]
    size: Optional[int]
    file_url: Optional[str]
    expires_in: Optional[int]
    error: Optional[ErrorBody]


class HealthResponse(BaseModel):
    status: str
    ffmpeg: bool
    yt_dlp: Optional[str]
    active_jobs: int
    max_download_size: int
    job_ttl: int
