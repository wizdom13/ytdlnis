from __future__ import annotations

import json
import mimetypes
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Optional

from celery import Celery
from celery.utils.log import get_task_logger
from redis import Redis
from yt_dlp import YoutubeDL

from .config import get_settings
from .job_state import JobStateStore, JobStatus
from .storage import StoredFile, get_storage_backend

logger = get_task_logger(__name__)

settings = get_settings()
celery_app = Celery(
    "ytdlnis",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_track_started=True,
    worker_hijack_root_logger=False,
    worker_prefetch_multiplier=1,
)


def _open_redis() -> Redis:
    return Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)


def _normalize_progress(value: Optional[str]) -> float:
    if not value:
        return 0.0
    try:
        cleaned = value.replace("%", "").strip()
        return max(0.0, min(100.0, float(cleaned)))
    except Exception:
        return 0.0


def _determine_mime(path: Path) -> Optional[str]:
    mime, _ = mimetypes.guess_type(path.name)
    return mime


def _write_temp_cookie(temp_dir: Path, cookie_content: str) -> Path:
    cookie_file = temp_dir / "cookies.txt"
    cookie_file.write_text(cookie_content, encoding="utf-8")
    return cookie_file


def _build_ydl_options(temp_dir: Path, payload: Dict[str, Optional[str | Dict[str, str] | bool]]) -> Dict[str, object]:
    outtmpl = payload.get("filename") or "%(title)s.%(ext)s"
    format_string = payload.get("format")
    prefer_audio = bool(payload.get("prefer_audio"))
    if not format_string:
        format_string = "bestaudio/best" if prefer_audio else "bestvideo+bestaudio/best"

    options: Dict[str, object] = {
        "format": format_string,
        "outtmpl": str(temp_dir / outtmpl),
        "noplaylist": False,
        "quiet": True,
        "progress_hooks": [],
        "concurrent_fragment_downloads": 3,
        "retries": 5,
        "continuedl": True,
    }

    headers = payload.get("headers")
    if isinstance(headers, dict):
        options["http_headers"] = headers

    proxy = payload.get("proxy")
    if isinstance(proxy, str) and proxy:
        options["proxy"] = proxy

    cookie = payload.get("cookie")
    if isinstance(cookie, str) and cookie:
        cookie_file = _write_temp_cookie(temp_dir, cookie)
        options["cookiefile"] = str(cookie_file)

    return options


@celery_app.task(name="app.tasks.download_media", bind=True)
def download_media(self, job_id: str, payload_json: str) -> Dict[str, object]:
    payload: Dict[str, object] = json.loads(payload_json)
    redis_client = _open_redis()
    store = JobStateStore(redis_client)
    storage = get_storage_backend(settings)
    temp_dir = Path(tempfile.mkdtemp(prefix=f"ytdlnis-{job_id}-"))
    result: Dict[str, object] | None = None

    def progress_hook(data: Dict[str, object]) -> None:
        status = data.get("status")
        if status == "downloading":
            progress = _normalize_progress(data.get("_percent_str"))
            store.set_status(job_id, JobStatus.RUNNING, progress)
            store.publish_event(
                job_id,
                {
                    "event": "progress",
                    "progress": progress,
                    "downloaded_bytes": data.get("downloaded_bytes"),
                    "total_bytes": data.get("total_bytes"),
                    "speed": data.get("speed"),
                    "eta": data.get("eta"),
                },
            )
        elif status == "finished":
            filename = data.get("filename")
            store.publish_event(job_id, {"event": "file_finished", "filename": filename})

    try:
        store.set_status(job_id, JobStatus.RUNNING, 0.0)
        store.publish_event(job_id, {"event": "started"})

        options = _build_ydl_options(temp_dir, payload)
        options["progress_hooks"].append(progress_hook)

        url = payload.get("url")
        if not isinstance(url, str):
            raise ValueError("Missing download URL")

        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

        filename = info.get("_filename")
        if not filename:
            raise RuntimeError("yt-dlp did not provide a filename")
        downloaded_path = Path(filename)
        if not downloaded_path.exists():
            raise FileNotFoundError(downloaded_path)

        mime = _determine_mime(downloaded_path)
        stored: StoredFile = storage.store(
            job_id=job_id,
            source_path=downloaded_path,
            preferred_name=payload.get("filename"),
            mime_type=mime,
        )

        result = {
            "mime": stored.mime_type,
            "file_name": stored.file_name,
            "size_bytes": stored.size_bytes,
            "storage_path": str(stored.absolute_path),
        }
        public_result = {k: v for k, v in result.items() if k != "storage_path"}
        store.set_result(job_id, result)
        store.publish_event(job_id, {"event": "completed", "result": public_result})
        return result
    except Exception as exc:  # pragma: no cover - defensive
        message = str(exc)
        store.set_error(job_id, message)
        store.publish_event(job_id, {"event": "error", "message": message})
        logger.exception("Job %s failed", job_id)
        raise
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        finally:
            redis_client.close()
