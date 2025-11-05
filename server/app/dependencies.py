from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import Settings, get_settings
from .job_state import AsyncJobStateStore, JOB_TTL_SECONDS


@asynccontextmanager
async def redis_client(settings: Settings) -> AsyncIterator[Redis]:
    client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        yield client
    finally:
        await client.close()


def rate_limit_key_func(request: Request) -> str:
    client_host = get_remote_address(request)
    auth_header = request.headers.get("authorization", "")
    token = "anonymous"
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    return f"{client_host}:{token}"


def build_limiter(settings: Settings) -> Limiter:
    default_limit = f"{settings.rate_limit_per_minute}/minute"
    limiter = Limiter(key_func=rate_limit_key_func, default_limits=[default_limit], storage_uri=settings.redis_url)
    return limiter


async def get_limiter(settings: Settings = Depends(get_settings)) -> Limiter:
    return build_limiter(settings)


def auth_dependency(request: Request, settings: Settings = Depends(get_settings)) -> None:
    header = request.headers.get("Authorization")
    if not header or not header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = header.split(" ", 1)[1].strip()
    if token != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    request.state.authenticated_key = token


async def get_async_redis(settings: Settings = Depends(get_settings)) -> AsyncIterator[Redis]:
    async with redis_client(settings) as client:
        yield client


def get_job_store(redis: Redis = Depends(get_async_redis), settings: Settings = Depends(get_settings)) -> AsyncJobStateStore:
    ttl = max(JOB_TTL_SECONDS, settings.signed_url_ttl_seconds * 8)
    return AsyncJobStateStore(redis, ttl_seconds=ttl)


def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Rate limit exceeded: {exc.detail}",
    )
