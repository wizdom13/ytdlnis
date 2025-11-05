from __future__ import annotations


import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Settings, get_settings, get_storage_root


@dataclass
class StoredFile:
    job_id: str
    file_name: str
    absolute_path: Path
    size_bytes: int
    mime_type: Optional[str] = None


class StorageBackend(ABC):
    """Simple abstraction for persisting downloaded files."""

    @abstractmethod
    def store(self, *, job_id: str, source_path: Path, preferred_name: Optional[str] = None, mime_type: Optional[str] = None) -> StoredFile:
        raise NotImplementedError

    @abstractmethod
    def open(self, stored: StoredFile):
        raise NotImplementedError


class LocalStorageBackend(StorageBackend):
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _target_directory(self, job_id: str) -> Path:
        now = datetime.utcnow()
        subdir = Path(str(now.year), f"{now.month:02d}", f"{now.day:02d}", job_id)
        full_path = self.root / subdir
        full_path.mkdir(parents=True, exist_ok=True)
        return full_path

    def store(
        self,
        *,
        job_id: str,
        source_path: Path,
        preferred_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> StoredFile:
        target_dir = self._target_directory(job_id)
        file_name = preferred_name or source_path.name
        destination = target_dir / file_name
        # If destination exists, append numeric suffix
        if destination.exists():
            stem = destination.stem
            suffix = destination.suffix
            counter = 1
            while destination.exists():
                destination = target_dir / f"{stem}-{counter}{suffix}"
                counter += 1
        shutil.move(str(source_path), destination)
        return StoredFile(
            job_id=job_id,
            file_name=destination.name,
            absolute_path=destination,
            size_bytes=destination.stat().st_size,
            mime_type=mime_type,
        )

    def open(self, stored: StoredFile):
        return stored.absolute_path.open("rb")


class S3Storage(StorageBackend):
    """Placeholder for a future S3-compatible implementation."""

    def __init__(self, *_, **__):  # pragma: no cover - stub
        raise NotImplementedError("S3 storage backend is not implemented yet")


def get_storage_backend(settings: Settings | None = None) -> StorageBackend:
    settings = settings or get_settings()
    backend = settings.normalized_storage_backend
    if backend == "local":
        root = get_storage_root(settings)
        return LocalStorageBackend(root)
    if backend == "s3":
        return S3Storage()
    raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")
