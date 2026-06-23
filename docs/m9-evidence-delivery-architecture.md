# M9 — Evidence Delivery Architecture

## Milestone Summary

Milestone 9 (M9) completes **evidence delivery** for the AI ANPR runtime. Finalized detections register evidence with Laravel (metadata paths or uploaded files), record evidence delivery in event logs, and retain local evidence under a configurable policy. **Metadata mode** remains supported for local development. **Upload mode** is operational after the M10 backend-owned evidence patch and is the preferred cloud deployment path.

## Objective

Ensure backend event detail references all available evidence through backend-compatible metadata delivery, visible delivery status in logs and runtime summaries, and safe local retention configuration.

**Pass condition:** Backend event detail references all available evidence.

## Scope

### In Scope

- Metadata mode hardening (`full`, `plate`, `annotated`)
- Upload mode multipart delivery to Laravel `storage/app/anpr` (M10)
- Image path normalization and operator-facing image-root compatibility guidance
- Evidence delivery log stage (`ai_evidence_delivered`)
- Queue schema extensions for delivery/retention state
- Per-job `evidence_mode` durability (queue flush uses stored mode, not current `.env`)
- Local evidence retention for expired runs (not current run)
- M9 runtime summary and `backend_results.json` fields

### Out of Scope

- Cloud storage backends beyond Laravel local disk
- Frontend ANPR monitoring UI
- WebSocket/realtime features
- Detection, OCR, tracking, or voting changes

## File-by-File Responsibilities

### `backend.py`

- Metadata image posting and multipart upload delivery
- Event logs including `ai_evidence_delivered`
- Queue delivery fields, per-row checkpointing
- Per-job `evidence_mode` routing

### `anpr.py`

- Evidence path normalization relative to project root
- Expired-run evidence cleanup
- M9 metrics in `worker_summary.json`

### `config.py`

- `ANPR_EVIDENCE_RETENTION_DAYS`, metadata image-root warnings, upload mode info

### `main.py`

- M9 CLI labels

## Evidence Delivery Modes

| Mode | Status |
| ---- | ------ |
| `metadata` | **Supported** — posts `anpr_images` metadata rows (local development) |
| `upload` | **Operational (M10)** — uploads binary files to Laravel `storage/app/anpr` |

## Metadata Mode Behavior

For each available evidence file:

1. Build payload: `anpr_event_id`, `image_type`, `file_path`, `file_size`, `resolution`, `expires_at: null`
2. Post to `POST /api/anpr-images` after `backend_event_id` exists
3. Mark `image_statuses` per type (`succeeded`, `skipped`, `failed`, `validation_failed`)
4. Checkpoint queue after each successful row
5. Job succeeds only when images and logs are complete

Missing local paths → `skipped` (no crash).

## Image Root Compatibility

Evidence paths are stored relative to the AI ANPR project root (current working directory). Laravel must resolve these paths via configured allowed roots, for example:

```env
ANPR_IMAGE_ROOTS=D:/path/to/ai-anpr-v1
```

`check-config` emits a **warning** when metadata mode and backend are enabled. Upload mode does not require `ANPR_IMAGE_ROOTS` on the AI machine.

## Upload Mode (M10)

Upload mode posts binary evidence files to Laravel:

```text
POST /api/anpr-events/{event_id}/images/upload
multipart/form-data:
  image_type=full|plate|annotated
  image=@file.jpg
```

Laravel stores files under `storage/app/anpr/events/{event_id}/` and creates or updates `anpr_images` rows. The queue processes each job using its stored `evidence_mode`, so old metadata jobs are not broken by later `.env` changes.

Upload validation errors returned by Laravel are appended to AI `last_error` (for example `image: The image failed to upload.`). Transient upload `image` field 422 responses remain retryable as `failed` rather than terminal `validation_failed`.

Backend-owned files are the preferred cloud deployment path.

## Evidence Delivery Logs

| Stage | Purpose |
| ----- | ------- |
| `ai_event_created` | Backend event created |
| `ai_images_registered` | Image metadata complete |
| `ai_evidence_delivered` | Evidence delivery summary (mode, statuses, retention) |
| `ai_job_succeeded` | Job complete |

Log messages are compact JSON. Each successful log row is checkpointed immediately. Re-flush does not duplicate succeeded logs.

## Queue Schema Changes

M9 extends M8 jobs (backward compatible):

```json
{
  "evidence_mode": "metadata",
  "evidence_delivery_status": "pending",
  "retention_status": "kept",
  "local_evidence_deleted": 0
}
```

Older queue lines normalize missing fields on read.

## Retry and Idempotency Behavior

- `backend_event_id` checkpointed after event creation
- Each successful image/log row checkpointed immediately
- Retries skip succeeded rows
- `posting` + `backend_event_id` jobs remain recoverable (M7/M8 durability)
- Terminal validation failures (`validation_failed`) for invalid `image_type`, unknown `evidence_mode`, and non-retryable 404/422 payloads
- Retryable upload validation errors on `/images/upload` (for example transient `image` upload failures) remain `failed` and retry until the limit
- Network/5xx retry until limit
- `last_error` includes Laravel field-level validation detail when available

## Local Evidence Retention Policy

| Setting | Behavior |
| ------- | -------- |
| `ANPR_EVIDENCE_RETENTION_DAYS=0` | Keep local evidence indefinitely |
| `ANPR_EVIDENCE_RETENTION_DAYS>0` | Delete evidence files in **old** runs past retention age |
| Current run | Never deleted by retention cleanup |
| Metadata mode | Does not delete evidence after metadata registration |
| `ANPR_DELETE_LOCAL_AFTER_UPLOAD=true` (upload mode) | Deletes local run evidence files after all uploads succeed |

Deletion is limited to files under `runs/*/evidence/` within the configured runs directory.

## Dry-Run vs Non-Dry-Run

| Mode | Backend | Retention cleanup |
| ---- | ------- | ----------------- |
| `--dry-run` | No HTTP, no enqueue | No |
| Non-dry-run | Enqueue + flush | Yes (if retention days > 0) |

## Runtime Summary Fields

```json
{
  "milestone": "M9",
  "evidence_mode": "metadata",
  "evidence_retention_days": 0,
  "backend_jobs_queued": 1,
  "backend_jobs_succeeded": 1,
  "backend_images_sent": 3,
  "backend_images_uploaded": 3,
  "backend_logs_sent": 4,
  "local_evidence_deleted": 0,
  "backend_queue_file": ".cache/backend_queue.jsonl"
}
```

`backend_results.json` includes per-event delivery status, image/log statuses, evidence mode, and retention status.

## CLI Behavior

```bash
python main.py check-config --strict
python main.py run --source image --image ... --dry-run --strict
python main.py run --source image --image ... --strict
python main.py flush-backend-queue
```

## Passing Criteria

- Backend event detail includes all available evidence (metadata or uploaded files)
- Metadata mode registers `full`, `plate`, `annotated` when paths exist
- Upload mode stores files under Laravel `storage/app/anpr`
- `ai_evidence_delivered` log visible in Laravel
- Re-flush does not duplicate events, images, or logs
- Queue jobs use stored `evidence_mode` even if `.env` changes later
- Dry-run has no backend side effects
- M4–M8 behavior preserved

## Verification Checklist

```bash
python -m py_compile main.py config.py anpr.py backend.py
python main.py check-config
python main.py check-config --strict
python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict
python main.py flush-backend-queue
```

With Laravel running:

```bash
python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --strict
python main.py flush-backend-queue
python main.py flush-backend-queue
```

Verify: one event, image rows, evidence delivery log, no duplicates on second flush.

## Known Limitations

- Metadata paths require Laravel `ANPR_IMAGE_ROOTS` configuration on the AI machine
- Retention deletes old run evidence only; metadata may reference deleted files if retention is aggressive
- No `vehicle_id` linkage

## M10 Backend-Owned Evidence Upload Patch

Upload mode now posts binary evidence files to Laravel:

```text
POST /api/anpr-events/{event_id}/images/upload
```

The queue processes each job using its stored `evidence_mode`, so old metadata jobs are not broken by later `.env` changes.

## M10 Handoff Notes

M10 — Frontend ANPR monitoring UI displays events and evidence from Laravel. Upload mode is the normal operational path for cloud backends; metadata mode remains a local-development fallback.
