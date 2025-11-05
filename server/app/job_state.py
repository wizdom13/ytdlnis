from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

JOB_TTL_SECONDS = 60 * 60 * 24 * 7  # one week


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def job_key(job_id: str) -> str:
    return f"job:{job_id}"


def job_events_channel(job_id: str) -> str:
    return f"{job_key(job_id)}:events"


def download_token_key(token: str) -> str:
    return f"download-token:{token}"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class JobState:
    job_id: str
    status: JobStatus
    progress: float
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_redis(cls, job_id: str, payload: Dict[str, str]) -> "JobState | None":
        if not payload:
            return None
        result_raw = payload.get("result")
        result = json.loads(result_raw) if result_raw else None
        error = payload.get("error")
        progress = float(payload.get("progress", "0"))
        status = JobStatus(payload.get("status", JobStatus.QUEUED.value))
        return cls(
            job_id=job_id,
            status=status,
            progress=progress,
            result=result,
            error=error,
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.job_id,
            "status": self.status.value,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
        }


class BaseJobStore:
    def __init__(self, ttl_seconds: int = JOB_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _serialize_result(result: Optional[Dict[str, Any]]) -> Optional[str]:
        if result is None:
            return None
        return json.dumps(result)

    def _base_payload(
        self, status: JobStatus, progress: float = 0.0, *, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "status": status.value,
            "progress": f"{progress:.2f}",
            "updated_at": _now_iso(),
        }
        if result is not None:
            data["result"] = self._serialize_result(result)
        if error is not None:
            data["error"] = error
        return data


class JobStateStore(BaseJobStore):
    """Synchronous Redis helper for Celery workers."""

    def __init__(self, client: Redis, ttl_seconds: int = JOB_TTL_SECONDS):
        super().__init__(ttl_seconds)
        self.client = client

    def init_job(self, job_id: str, payload: Dict[str, Any]) -> None:
        data = {
            "status": JobStatus.QUEUED.value,
            "progress": "0",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "request": json.dumps(payload),
        }
        key = job_key(job_id)
        self.client.hset(key, mapping=data)
        self.client.expire(key, self.ttl_seconds)

    def set_status(self, job_id: str, status: JobStatus, progress: float = 0.0) -> None:
        key = job_key(job_id)
        data = self._base_payload(status, progress)
        self.client.hset(key, mapping=data)
        self.client.expire(key, self.ttl_seconds)

    def set_result(self, job_id: str, result: Dict[str, Any]) -> None:
        key = job_key(job_id)
        data = self._base_payload(JobStatus.SUCCEEDED, 100.0, result=result)
        self.client.hset(key, mapping=data)
        self.client.expire(key, self.ttl_seconds)

    def set_error(self, job_id: str, message: str) -> None:
        key = job_key(job_id)
        data = self._base_payload(JobStatus.FAILED, error=message)
        self.client.hset(key, mapping=data)
        self.client.expire(key, self.ttl_seconds)

    def publish_event(self, job_id: str, event: Dict[str, Any]) -> None:
        channel = job_events_channel(job_id)
        payload = {
            "timestamp": _now_iso(),
            **event,
        }
        self.client.publish(channel, json.dumps(payload))

    def store_download_token(
        self, job_id: str, file_path: str, ttl_seconds: int, *, file_name: str | None = None, mime: str | None = None
    ) -> str:
        token = uuid.uuid4().hex
        key = download_token_key(token)
        payload = json.dumps({"job_id": job_id, "file_path": file_path, "file_name": file_name, "mime": mime})
        self.client.setex(key, ttl_seconds, payload)
        return token


class AsyncJobStateStore(BaseJobStore):
    """Async Redis helper for FastAPI endpoints."""

    def __init__(self, client: AsyncRedis, ttl_seconds: int = JOB_TTL_SECONDS):
        super().__init__(ttl_seconds)
        self.client = client

    async def init_job(self, job_id: str, payload: Dict[str, Any]) -> None:
        data = {
            "status": JobStatus.QUEUED.value,
            "progress": "0",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "request": json.dumps(payload),
        }
        key = job_key(job_id)
        await self.client.hset(key, mapping=data)
        await self.client.expire(key, self.ttl_seconds)

    async def get_job(self, job_id: str) -> JobState | None:
        key = job_key(job_id)
        payload = await self.client.hgetall(key)
        return JobState.from_redis(job_id, payload)

    async def store_download_token(
        self, job_id: str, file_path: str, ttl_seconds: int, *, file_name: str | None = None, mime: str | None = None
    ) -> str:
        token = uuid.uuid4().hex
        key = download_token_key(token)
        payload = json.dumps({"job_id": job_id, "file_path": file_path, "file_name": file_name, "mime": mime})
        await self.client.setex(key, ttl_seconds, payload)
        return token

    async def pop_download_token(self, token: str) -> Optional[Dict[str, str]]:
        key = download_token_key(token)
        pipe = self.client.pipeline()
        pipe.get(key)
        pipe.delete(key)
        result = await pipe.execute()
        raw_payload = result[0]
        if raw_payload is None:
            return None
        return json.loads(raw_payload)

    async def list_events(self, job_id: str, min_id: int = 0) -> list[Dict[str, Any]]:
        # Placeholder for future list-based retrieval; events stream via pub/sub.
        return []
