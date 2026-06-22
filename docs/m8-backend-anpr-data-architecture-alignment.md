# M8 — Backend ANPR Data Architecture Alignment

## Milestone Summary

Milestone 8 (M8) aligns the AI ANPR runtime with the Laravel backend data model so each finalized detection can be represented as an **ANPR Event**, **ANPR Images** (metadata), and **ANPR Event Logs**. M7 queue durability, token cache, and idempotent retry behavior are preserved.

## Objective

Ensure backend posting uses validated Laravel API contracts, verifies camera mapping at flush time, posts structured event logs, and supports unknown vehicles without blocking event creation.

## Scope

### In Scope

- Camera UUID verification via `GET /api/cameras/{id}` during queue flush
- ANPR event payload alignment with `AnprEventController@store`
- Image metadata alignment with `AnprImageController@store`
- Event log posting via `POST /api/anpr-event-logs`
- Queue schema extension: `log_statuses`, `logs_sent`
- Structured `BackendApiError` handling
- M8 runtime summary and `backend_results.json` fields

### Out of Scope

- Binary image upload (`ANPR_EVIDENCE_MODE=upload`)
- Evidence retention deletion
- Frontend ANPR monitoring UI
- WebSocket/realtime dashboard
- Backend schema changes
- New AI runtime modules
- Vehicle record creation or `vehicle_id` lookup
- Cloud storage

## File-by-File Responsibilities

### `backend.py`

- `BackendApiError`, `verify_camera_mapping()`, event/image/log posting
- Per-stage `log_statuses` idempotency
- Camera verification cache per flush session

### `anpr.py`

- M8 metrics in `worker_summary.json`
- `backend_results.json` with logs and statuses

### `config.py`

- Unchanged contract; backend-only validation path from M7 remains

### `main.py`

- CLI milestone label update only

## Backend API Contracts

| Endpoint | Method | Purpose |
| -------- | ------ | ------- |
| `/api/auth/login` | POST | JWT acquisition |
| `/api/cameras/{id}` | GET | Camera existence check |
| `/api/anpr-events` | POST | Create ANPR event |
| `/api/anpr-images` | POST | Register image metadata |
| `/api/anpr-event-logs` | POST | Create event log row |

Response envelope: `{ success, message, data }`.

## Camera Mapping Behavior

During `flush_queue()`, if at least one retryable/processable job exists:

1. Authenticate if needed.
2. Call `GET /api/cameras/{ANPR_BACKEND_CAMERA_ID}` once for that flush.
3. Confirm `data.id` matches configured camera UUID.
4. Cache success for the remainder of the flush.

If the queue is empty or contains only final/non-processable jobs, camera verification is skipped.

| Result | Behavior |
| ------ | -------- |
| Camera found | Jobs proceed |
| HTTP 404 | All retryable jobs marked `validation_failed` |
| HTTP 5xx / network | Flush fails; jobs remain retryable |
| Dry-run | No camera HTTP call |

`check-config` does not require backend availability.

## Unknown Vehicle Strategy

- **`vehicle_id` is omitted** from event payloads.
- Unknown plates (not in Laravel `vehicles` table) still create ANPR events.
- No vehicle lookup or invention in M8.
- Backend accepts nullable `vehicle_id` per `AnprEventController@store`.

## Event Payload Mapping

| Local source | Backend field |
| ------------ | ------------- |
| `ANPR_BACKEND_CAMERA_ID` | `camera_id` |
| `plate_number` (uppercase, max 20) | `plate_number` |
| `confidence` (0–1, 4 dp) | `confidence` |
| `created_at` / `last_seen_at` | `detection_time` |
| constant | `is_valid: true`, `is_flagged: false` |
| n/a | `latitude: null`, `longitude: null` |

`vehicle_id` is not sent.

## Image Metadata Mapping

| Evidence key | `image_type` |
| ------------ | ------------ |
| `full` | `full` |
| `plate` | `plate` |
| `annotated` | `annotated` |

Payload: `anpr_event_id`, `image_type`, `file_path` (normalized, max 255), `file_size`, `resolution`, `expires_at: null`.

Posted only after `backend_event_id` exists. Missing local paths → `skipped`.

## Event Log Mapping

| Stage | When posted |
| ----- | ----------- |
| `ai_event_created` | After event creation |
| `ai_images_registered` | After image metadata complete |
| `ai_job_succeeded` | Before job marked succeeded |

Payload: `anpr_event_id`, `stage` (max 50 chars), `message` (compact JSON string with job context).

## Queue Schema Changes

M8 extends M7 jobs:

```json
{
  "log_statuses": {
    "ai_event_created": "pending",
    "ai_images_registered": "pending",
    "ai_job_succeeded": "pending"
  },
  "logs_sent": 0
}
```

Older queue lines without these fields are normalized on read. M7 fields (`image_statuses`, `retry_limit`, `backend_event_id` checkpoint) are preserved.

## Retry and Idempotency Behavior

- **`backend_event_id` checkpoint** after successful event POST.
- **Image metadata checkpoint** after each successful image row (`image_statuses` + `images_sent` persisted immediately).
- **Event log checkpoint** after each successful log row (`log_statuses` + `logs_sent` persisted immediately).
- This protects retry behavior after partial flush crashes; already-succeeded images and logs are not resent.
- **`posting` + `backend_event_id`** jobs remain retryable (crash recovery).
- Retries skip `/api/anpr-events` when `backend_event_id` exists.
- Image and log rows retry only when `pending` or `failed`.
- Succeeded/skipped/validation_failed rows are not resent.

| Error | Job handling |
| ----- | ------------ |
| HTTP 401 | Token refresh, retry once |
| HTTP 404 / 422 | `validation_failed` |
| HTTP 5xx / network | `failed`, retry until limit |
| Upload mode | Rejected before posting |

## Dry-Run vs Non-Dry-Run

| Mode | Backend HTTP |
| ---- | ------------ |
| `--dry-run` | None |
| Non-dry-run | Enqueue + flush (finite sources) or `flush-backend-queue` |

## Runtime Summary Fields

```json
{
  "milestone": "M8",
  "backend_enabled": true,
  "backend_jobs_queued": 1,
  "backend_jobs_succeeded": 1,
  "backend_jobs_failed": 0,
  "backend_jobs_exhausted": 0,
  "backend_logs_sent": 3,
  "backend_camera_verified": true,
  "backend_queue_file": ".cache/backend_queue.jsonl"
}
```

`events.jsonl` `backend` object remains enqueue-time state. Final status: `backend_results.json` or queue file.

## CLI Behavior

```bash
python main.py check-config --strict
python main.py run --source image --image ... --dry-run --strict
python main.py run --source image --image ... --strict
python main.py flush-backend-queue
```

## Passing Criteria

- Camera mapping verified at flush
- Event, image, and log payloads match Laravel validation
- Unknown vehicles do not block events
- Idempotent retry for events, images, and logs
- M4–M7 behavior preserved
- Dry-run has no backend side effects
- Secrets never logged

## Verification Checklist

```bash
python -m py_compile main.py config.py anpr.py backend.py
python main.py check-config
python main.py check-config --strict
python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict
python main.py flush-backend-queue
```

With Laravel running and backend enabled:

```bash
python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --strict
python main.py flush-backend-queue
```

Verify in Laravel:

- One ANPR event per finalized detection
- Image metadata rows for available evidence
- Three event log stages per succeeded job
- No duplicate events or logs on re-flush

## Known Limitations

- `ANPR_EVIDENCE_MODE=upload` unsupported
- Metadata mode stores paths only; backend cannot fetch files from ANPR host
- No `vehicle_id` linkage in M8
- Camera verification requires backend reachable at flush time
- RTSP/live runs require manual `flush-backend-queue`

## M9 Handoff Notes

M9 — Evidence delivery architecture: binary upload, retention policy, `ANPR_DELETE_LOCAL_AFTER_UPLOAD`, and upload mode if backend adds multipart endpoints.
