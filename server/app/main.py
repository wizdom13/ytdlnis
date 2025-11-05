from __future__ import annotations

import asyncio
import json
import mimetypes
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
from redis.asyncio import Redis
from slowapi.errors import RateLimitExceeded

from .config import Settings, get_settings
from .dependencies import auth_dependency, build_limiter, get_job_store, rate_limit_handler
from .job_state import AsyncJobStateStore, JobStatus, job_events_channel
from .schemas import DownloadUrlResponse, JobCreateRequest, JobCreateResponse, JobResult, JobStatusResponse
from .tasks import download_media

settings = get_settings()
limiter = build_limiter(settings)
LIMIT_VALUE = f"{settings.rate_limit_per_minute}/minute"

app = FastAPI(title="YTDLnis Backend", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)



def _validate_url(url: str, settings: Settings) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only http(s) URLs are allowed")
    if settings.allowed_domains:
        host = (parsed.hostname or "").lower()
        if host not in settings.allowed_domains:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="URL domain is not allowed")


@app.post("/api/jobs", response_model=JobCreateResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(LIMIT_VALUE)
async def create_job(
    request_model: JobCreateRequest,
    job_store: AsyncJobStateStore = Depends(get_job_store),
    _: None = Depends(auth_dependency),
) -> JobCreateResponse:
    payload = request_model.model_dump(mode="json")
    payload["url"] = str(payload["url"])
    _validate_url(payload["url"], settings)

    job_id = uuid4().hex
    sanitized = dict(payload)
    if sanitized.get("cookie"):
        sanitized["cookie"] = "***"
    await job_store.init_job(job_id, sanitized)

    download_media.apply_async(args=(job_id, json.dumps(payload)), task_id=job_id)
    return JobCreateResponse(id=job_id, status=JobStatus.QUEUED)


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
@limiter.limit(LIMIT_VALUE)
async def get_job_status(
    job_id: str,
    job_store: AsyncJobStateStore = Depends(get_job_store),
    _: None = Depends(auth_dependency),
) -> JobStatusResponse:
    job = await job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    result_payload = None
    if job.result:
        result_payload = dict(job.result)
        result_payload.pop("storage_path", None)
        result_payload["download_url"] = f"{settings.base_public_url.rstrip('/')}/api/jobs/{job_id}/result"

    return JobStatusResponse(
        id=job.job_id,
        status=job.status,
        progress=job.progress,
        result=JobResult(**result_payload) if result_payload else None,
        error=job.error,
    )


@app.get("/api/jobs/{job_id}/result", response_model=DownloadUrlResponse)
@limiter.limit(LIMIT_VALUE)
async def get_job_result(
    job_id: str,
    job_store: AsyncJobStateStore = Depends(get_job_store),
    _: None = Depends(auth_dependency),
) -> DownloadUrlResponse:
    job = await job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status != JobStatus.SUCCEEDED or not job.result:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job has not finished successfully")

    storage_path = job.result.get("storage_path")
    if not storage_path:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Result is missing storage info")

    token = await job_store.store_download_token(
        job_id,
        storage_path,
        settings.signed_url_ttl_seconds,
        file_name=job.result.get("file_name"),
        mime=job.result.get("mime"),
    )
    download_url = f"{settings.base_public_url.rstrip('/')}/api/download/{token}"
    return DownloadUrlResponse(url=download_url, expires_in=settings.signed_url_ttl_seconds)


async def _event_stream(request: Request, redis: Redis, job_id: str) -> AsyncIterator[dict]:
    channel = job_events_channel(job_id)
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    store = AsyncJobStateStore(redis)

    job = await store.get_job(job_id)
    if job:
        snapshot = job.to_dict()
        yield {"event": "snapshot", "data": json.dumps(snapshot)}

    try:
        while True:
            if await request.is_disconnected():
                break
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                yield {"data": message["data"]}
            await asyncio.sleep(0.25)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()


@app.get("/api/jobs/{job_id}/events")
@limiter.limit(LIMIT_VALUE)
async def stream_job_events(
    job_id: str,
    request: Request,
    _: None = Depends(auth_dependency),
    settings: Settings = Depends(get_settings),
) -> EventSourceResponse:
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)

    async def generator() -> AsyncIterator[dict]:
        try:
            async for event in _event_stream(request, redis, job_id):
                yield event
        finally:
            await redis.close()

    return EventSourceResponse(generator())


@app.get("/api/download/{token}")
@limiter.limit(LIMIT_VALUE)
async def download_file(
    token: str,
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        store = AsyncJobStateStore(redis)
        payload = await store.pop_download_token(token)
    finally:
        await redis.close()
    if not payload:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Download link expired")

    path = Path(payload["file_path"])
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="File is no longer available")

    filename = payload.get("file_name") or path.name
    media_type = payload.get("mime") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(path, filename=filename, media_type=media_type)


@app.get("/api/health")
async def healthcheck() -> Response:
    return Response(content="ok", media_type="text/plain")
