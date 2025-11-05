from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, Field, HttpUrl

from .job_state import JobStatus


class JobCreateRequest(BaseModel):
    url: HttpUrl | str = Field(..., description="Media URL to download")
    format: Optional[str] = Field(default=None, description="yt-dlp format selection string")
    cookie: Optional[str] = Field(default=None, description="Raw cookie string to pass to yt-dlp")
    headers: Optional[Dict[str, str]] = Field(default=None, description="Additional HTTP headers")
    proxy: Optional[str] = Field(default=None, description="Proxy URL for yt-dlp")
    prefer_audio: bool = Field(default=False, description="Prefer audio-only format when true")
    filename: Optional[str] = Field(default=None, description="Optional target filename override")


class JobCreateResponse(BaseModel):
    id: str
    status: JobStatus


class JobResult(BaseModel):
    mime: Optional[str] = None
    file_name: str
    size_bytes: int
    download_url: Optional[str] = None


class JobStatusResponse(BaseModel):
    id: str
    status: JobStatus
    progress: float = 0.0
    result: Optional[JobResult] = None
    error: Optional[str] = None


class DownloadUrlResponse(BaseModel):
    url: str
    expires_in: int
