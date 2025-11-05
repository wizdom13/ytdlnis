# YTDLnis Server

This FastAPI application provides the backend API for the refactored YTDLnis
client–server architecture. Media downloads are executed asynchronously through Celery
workers that call `yt-dlp`, while Redis handles task queuing, metadata storage, rate
limiting, and live progress events.

## Key Features
- Authenticated REST endpoints for job submission, status polling, and result retrieval
- Celery worker that runs `yt-dlp` with support for custom headers, cookies, proxies, and
  output templates
- Pluggable storage backends with a local filesystem implementation and an S3-compatible
  stub
- Live progress/event streaming over Server-Sent Events
- Simple rate limiting that combines client IP and API key identity

## Getting Started
1. Install dependencies (Python 3.11):
   ```bash
   cd server
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```
2. Copy `.env.example` to `.env` and edit values (API key, Redis URL, storage paths).
3. Start Redis and a Celery worker:
   ```bash
   redis-server --port 6379
   CELERY_BROKER_URL=redis://localhost:6379/0 \
   celery -A app.tasks.celery_app worker --loglevel=info
   ```
4. Launch the API:
   ```bash
   uvicorn app.main:app --reload
   ```

Use the `Authorization: Bearer <API_KEY>` header on every request.

## Project Layout
```
server/
  app/
    config.py           # Settings and environment loading
    dependencies.py     # Authentication and rate limiting helpers
    job_state.py        # Redis-backed job metadata helpers
    main.py             # FastAPI application entry point
    schemas.py          # Pydantic request/response models
    storage.py          # Storage abstraction + Local/S3 implementations
    tasks.py            # Celery app and yt-dlp execution logic
```
