# YTDLnis Architecture — Target Client–Server Design

## High-Level Topology
The refactored solution splits functionality between the Android client and a new Python
backend:

- **Android app** – Continues to own URL ingestion (share sheet, clipboard auto-paste),
  queue management UI, notifications, and media library operations. Instead of invoking
  `yt-dlp` locally, it issues authenticated REST calls to the backend and reacts to
  streamed progress events.
- **Backend service (`server/`)** – FastAPI application with Celery workers and Redis.
  The API exposes job submission, status polling, result retrieval, and live event feeds
  while Celery runs `yt-dlp` off-device using pluggable storage backends.【F:server/app/main.py†L1-L196】【F:server/app/tasks.py†L1-L170】

```
┌────────────┐    HTTPS (Bearer token + rate limit)     ┌───────────────┐
│ Android UI │ ───────────────────────────────────────▶ │  FastAPI API  │
└────────────┘ ◀───── progress SSE / polling ───────────┴───────┬───────┘
       │                                                      redis pub/sub
       │ share intents / queue UI                                │
       ▼                                                         ▼
┌────────────────────┐  Celery jobs (yt-dlp)  ┌──────────────────────────┐
│ Local Room DB      │ ─────────────────────▶ │ Celery workers + storage │
│ Notifications etc. │ ◀────────────────────  │ (filesystem now, S3 next) │
└────────────────────┘      metadata          └──────────────────────────┘
```

## Backend Components
- **Configuration** – `.env` variables drive authentication, Redis URL, public base URL,
  storage backend, signed URL TTL, rate limits, and optional domain allow-lists. The
  settings object normalizes `STORAGE_BACKEND` values (e.g. `loc_wisso`) and resolves the
  local storage root.【F:server/app/config.py†L1-L52】【F:server/.env.example†L1-L8】
- **Dependency wiring** – `dependencies.py` provisions a Redis connection per request,
  constructs the SlowAPI rate limiter (combining IP and API key), and exposes
  `AsyncJobStateStore` instances so endpoints can read/write job metadata.【F:server/app/dependencies.py†L1-L70】
- **Job metadata & tokens** – `job_state.py` centralizes Redis key naming, persists job
  state/result snapshots, emits pub/sub events, and issues signed download tokens that
  embed file metadata and expire after a configurable TTL.【F:server/app/job_state.py†L1-L190】
- **Storage abstraction** – `storage.py` provides a `StorageBackend` interface with a
  filesystem implementation that organizes results under
  `storage/YYYY/MM/DD/{jobId}` and a `S3Storage` stub so we can swap to object storage
  later without touching API logic.【F:server/app/storage.py†L1-L104】
- **Celery worker** – `tasks.py` initializes a Celery app bound to Redis and defines the
  `download_media` task. Workers create temporary sandboxes, map request fields into
  `yt-dlp` options, stream progress via Redis, move the finished file into the storage
  backend, and record result metadata (including the eventual download path).【F:server/app/tasks.py†L1-L170】

## API Surface & Data Flow
1. **Submit job** – Android posts to `POST /api/jobs` with URL, format, cookies, headers,
   proxy, and filename hints. The endpoint validates domain allow-lists, sanitizes stored
   metadata, persists a queued job record in Redis, and enqueues the Celery task using a
   deterministic job ID. Response: `{ id, status: "queued" }`.【F:server/app/main.py†L58-L90】
2. **Monitor progress** – Clients either poll `GET /api/jobs/{id}` or subscribe to
   `GET /api/jobs/{id}/events` (SSE). Status responses include latest progress and, when
   finished, a canonical result payload with a future download link. SSE streams a
   snapshot followed by progress/completion events published by the worker.【F:server/app/main.py†L92-L147】
3. **Retrieve artifact** – Once a job succeeds, `GET /api/jobs/{id}/result` returns a JSON
   object containing a time-limited download URL generated from a signed Redis token. The
   companion `GET /api/download/{token}` endpoint streams the file with correct
   `Content-Disposition` and MIME headers.【F:server/app/main.py†L115-L181】【F:server/app/job_state.py†L114-L180】
4. **Health** – `GET /api/health` provides a simple readiness probe for load balancers or
   the Android client before submitting work.【F:server/app/main.py†L183-L186】

All endpoints require `Authorization: Bearer <API_KEY>` except the one-time download URL,
which is protected by the signed token. SlowAPI enforces per-IP and per-key limits using
Redis so abusive clients cannot starve the worker pool.【F:server/app/dependencies.py†L18-L52】【F:server/app/main.py†L26-L30】

## Android Client Responsibilities After Migration
- **Queue orchestration** – Continue to store queue state in Room and display progress,
  but transition database updates to reflect server responses (e.g., map `JobStatus`
  strings to existing enums, surface download links when jobs succeed).
- **Network calls** – Replace direct `YoutubeDLRequest` execution with Retrofit/OkHttp
  calls to the new API. Share/clipboard handlers enqueue local records and immediately
  `POST /api/jobs` to get server-side job IDs.
- **Progress updates** – Use WorkManager (or a foreground service) to listen for SSE
  events and keep notifications in sync with server status. SSE fallback to polling
  ensures compatibility when background execution is restricted.
- **Downloads** – When the user opens or shares a completed item, resolve the latest
  signed URL, download/stream via OkHttp, and cache locally as needed.

## Operational Notes
- Dependencies are declared in `server/pyproject.toml` (FastAPI, Celery+Redis, yt-dlp,
  SlowAPI, SSE support) with optional dev extras for HTTPX-based integration tests.【F:server/pyproject.toml†L1-L29】
- `.gitignore` excludes environment files, virtualenvs, and persisted artifacts under
  `server/storage/` to keep repositories clean.【F:.gitignore†L12-L16】
- The design keeps yt-dlp update cadence on the server, enabling smaller Android APKs,
  simplified permissions (no `MANAGE_EXTERNAL_STORAGE`), and controlled network ingress
  (proxy/cookie handling centralized on the backend).

This architecture preserves all existing UX features while moving the heavy binaries and
network execution to managed infrastructure, making it easier to scale, patch, and reuse
across additional clients.
