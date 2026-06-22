# M7 — Backend Client and Queue Architecture

## Milestone Summary

Milestone 7 (M7) adds a **Laravel backend client**, **JWT token cache**, and **JSONL job queue** so finalized local ANPR events can be posted asynchronously without blocking the frame processing loop. Dry-run behavior from M6 is preserved with zero backend side effects.

## Objective

Finalize ANPR events locally (M6), enqueue backend jobs safely, reuse cached tokens, post events to the Laravel API, and retry failed jobs through `flush-backend-queue` without blocking detection/OCR per frame.

## Scope

### In Scope

- `BackendClient` in `backend.py` with token cache and queue file
- `POST /api/auth/login` with JWT reuse and 401 refresh
- `POST /api/anpr-events` event posting
- `POST /api/anpr-images` metadata rows when `ANPR_EVIDENCE_MODE=metadata`
- Queue enqueue during non-dry-run processing
- End-of-run queue flush for finite image/video sources
- `flush-backend-queue` CLI command
- M7 metrics in `worker_summary.json`

### Out of Scope

- Binary image upload (`ANPR_EVIDENCE_MODE=upload` unsupported in M7)
- Backend posting during dry-run
- HTTP posting inside the per-frame loop
- New runtime modules (`api_client.py`, `backend_queue.py`)
- Frontend changes
- Laravel backend code changes

## File-by-File Responsibilities

### `backend.py`

- `BackendToken`, `BackendQueueJob`, result dataclasses
- Token cache at `.cache/backend_token.json`
- Queue at `.cache/backend_queue.jsonl`
- `enqueue_event()`, `flush_queue()`, HTTP via stdlib `urllib`

### `anpr.py`

- `_execute_run(dry_run=...)` shared pipeline
- Enqueue after local event persistence when backend enabled and not dry-run
- Post-run flush for image/video sources
- M7 backend metrics

### `config.py`

- `ANPR_BACKEND_TIMEOUT_SECONDS` validation
- Upload mode warning

### `main.py`

- Non-dry-run `run` when backend enabled
- Real `flush-backend-queue` implementation

## Architecture Flow

```text
Frame loop (M4/M5/M6 unchanged)
        |
        v
finalize_track() → FinalizedTrackCandidate
        |
        v
_persist_finalized_event()
        |
        +--> save evidence + events.jsonl
        |
        +--> if not dry-run and backend enabled:
        |         enqueue_event() → .cache/backend_queue.jsonl
        |
        v
(end of image/video run)
        |
        v
flush_queue() → login if needed → POST /anpr-events
        |
        +--> POST /anpr-images (metadata mode)
```

## Backend Configuration Contract

| Variable | Purpose |
| -------- | ------- |
| `ANPR_BACKEND_ENABLED` | Enable queue/posting |
| `ANPR_BACKEND_BASE_URL` | API base, e.g. `http://localhost:8000/api` |
| `ANPR_BACKEND_EMAIL` / `PASSWORD` | Login credentials |
| `ANPR_BACKEND_CAMERA_ID` | UUID camera FK for events |
| `ANPR_BACKEND_TOKEN_CACHE` | JWT cache path |
| `ANPR_BACKEND_QUEUE_FILE` | Queue JSONL path |
| `ANPR_BACKEND_RETRY_LIMIT` | Max retry attempts per job |
| `ANPR_BACKEND_TIMEOUT_SECONDS` | HTTP timeout |
| `ANPR_EVIDENCE_MODE` | `metadata` supported; `upload` unsupported |

## Token Cache Contract

Path: `.cache/backend_token.json`

```json
{
  "access_token": "...",
  "token_type": "bearer",
  "expires_at": "2026-06-21T11:00:00Z"
}
```

- Reused when `expires_at` is more than 60 seconds in the future
- Refreshed on login or HTTP 401 (one retry)
- Tokens are never logged

## Queue File Contract

Path: `.cache/backend_queue.jsonl`

- UTF-8, one JSON object per line
- Atomic rewrite on flush status updates
- Missing file treated as empty queue

## Queue Job Schema

| Field | Description |
| ----- | ----------- |
| `job_id` | UUID |
| `local_event_id` | Local event ID from M6 |
| `status` | `pending`, `posting`, `succeeded`, `failed`, `exhausted`, `validation_failed` |
| `attempts` | Posting attempts |
| `max_attempts` | From `ANPR_BACKEND_RETRY_LIMIT` |
| `event` | Backend POST payload |
| `evidence` | Relative evidence paths |
| `backend_event_id` | Laravel UUID after success |
| `images_sent` | Metadata rows created |
| `last_error` | Last failure message |

## Event Payload Mapping

| Local source | Backend field |
| ------------ | ------------- |
| `ANPR_BACKEND_CAMERA_ID` | `camera_id` |
| `plate_number` | `plate_number` |
| `confidence` | `confidence` (0–1) |
| `created_at` or wall-clock `last_seen_at` | `detection_time` |
| constant | `is_valid: true`, `is_flagged: false` |
| n/a | `latitude: null`, `longitude: null` |

Validated against `AnprEventController@store` in the Laravel backend.

## Evidence Metadata Behavior

When `ANPR_EVIDENCE_MODE=metadata` and event posting succeeds:

| Evidence key | `image_type` |
| ------------ | ------------ |
| `full` | `full` |
| `plate` | `plate` |
| `annotated` | `annotated` |

Posts to `POST /api/anpr-images` with `file_path`, `file_size`, `resolution`, `expires_at: null`. Missing paths are skipped with warnings.

## Dry-Run vs Non-Dry-Run

| Mode | Local events | Enqueue | HTTP post |
| ---- | ------------ | ------- | --------- |
| `--dry-run` | Yes | No | No |
| `run` (no flag) | Yes | Yes (if enabled) | Via flush after finite sources or `flush-backend-queue` |

## Retry and Failure Handling

| Condition | Behavior |
| --------- | -------- |
| Valid token cache | Reuse |
| Expired/missing token | Login |
| HTTP 401 | Refresh token, retry once |
| HTTP 422 | `validation_failed`, no endless retry |
| HTTP 5xx / network | `failed`, retry until limit |
| Limit reached | `exhausted` |
| Empty queue | Success, processed `0` |

## Runtime Summary Fields

```json
{
  "milestone": "M7",
  "backend_enabled": true,
  "backend_jobs_queued": 0,
  "backend_jobs_succeeded": 0,
  "backend_jobs_failed": 0,
  "backend_jobs_exhausted": 0,
  "backend_queue_file": ".cache/backend_queue.jsonl"
}
```

M6 event/evidence metrics are preserved.

## Logging Behavior

- Backend enabled/disabled, queue path, dry-run flag at startup
- Enqueue success/failure by local event ID
- Flush summary counts
- No passwords, tokens, or Authorization headers

## CLI Behavior

```bash
python main.py run --source image --image ... --dry-run --strict
python main.py run --source image --image ... --strict
python main.py flush-backend-queue
```

Non-dry-run requires `ANPR_BACKEND_ENABLED=true`.

## Passing Criteria

- Token cache and queue implemented
- Dry-run has no backend side effects
- Non-dry-run enqueues without blocking frame loop
- `flush-backend-queue` posts pending jobs
- Retry limit honored
- Secrets never logged
- M4/M5/M6 behavior intact

## Verification Checklist

```bash
python -m py_compile main.py config.py anpr.py backend.py
python main.py check-config
python main.py check-config --strict
python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict
python main.py flush-backend-queue
```

With backend enabled and Laravel running:

```bash
python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --strict
python main.py flush-backend-queue
```

## Known Limitations

- `ANPR_EVIDENCE_MODE=upload` is not implemented (no upload endpoint in backend)
- RTSP/live runs do not auto-flush; use `flush-backend-queue`
- Metadata mode stores paths only; backend must resolve files locally
- Duplicate cooldown is local-runtime only (M6); queue does not deduplicate across runs
- Requires valid `camera_id` UUID existing in Laravel `cameras` table

## Next Milestone Handoff Notes for M8/M9

**M8** — Backend data alignment: verify camera IDs, field mapping, and dashboard display against posted records.

**M9** — Evidence delivery: binary upload, retention policy, `ANPR_DELETE_LOCAL_AFTER_UPLOAD`, and full upload mode if backend adds multipart endpoints.

M7 primary pass condition: **reliable non-blocking backend event posting** via queue + flush.
