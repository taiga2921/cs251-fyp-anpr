# M11 — Realtime RTSP Runtime Architecture

## Milestone Summary

Milestone 11 (M11) makes the **AI ANPR Python runtime** suitable for **live RTSP camera operation**. The runtime processes frames continuously, recovers from temporary stream failures, logs operational health, flushes the backend queue safely during long runs, and shuts down gracefully without losing finalized events.

## Objective

Enable a stable live path from RTSP camera to Laravel ANPR APIs and the existing M10 React monitoring UI, without changing frontend realtime behavior or Laravel API contracts.

**Pass condition:** RTSP runtime processes continuously until a controlled stop, survives transient read failures when the stream returns, and always writes `worker_summary.json` after shutdown.

## Scope

### In Scope

- **Continuous RTSP processing** until `--max-seconds`, stream end, user interrupt, or fatal startup failure
- **RTSP reconnection** with configurable delay, backoff, and attempt limits
- **Credential-safe logging** — RTSP URLs are masked in logs, summaries, warnings, and errors
- **Queue-safe runtime** — backend failures do not stop detection; periodic and shutdown queue flush
- **Runtime health logs** — periodic structured operational metrics in `worker.log`
- **Graceful shutdown** — Ctrl+C / SIGINT / SIGTERM finalize active tracks and write summary
- **M11 runtime summary fields** in `worker_summary.json`
- Minimal README update and this architecture document

### Out of Scope

- WebSocket server or push feed
- Frontend polling or realtime UI changes
- Cloud storage backends
- New database tables
- Model accuracy tuning or ONNX conversion
- Major module refactor or new runtime packages
- Backend or frontend code changes (unless required for compatibility)

## Architecture Overview

```text
RTSP Camera
→ OpenCV Capture
→ Frame Scheduler
→ ANPR Detection Pipeline
→ Track/Vote State
→ Finalized Event
→ Evidence Saver
→ Backend Queue
→ Periodic Safe Flush
→ Laravel ANPR APIs
→ React M10 Monitoring UI
```

M11 changes are confined to `ai-anpr-v1` (`config.py`, `anpr.py`, `backend.py`, `main.py`). Image, video, and webcam sources remain compatible.

## Runtime Flow

1. Validate configuration (`check-config` / run pre-check).
2. Create `runs/run_YYYYMMDD_HHMMSS/`.
3. Open RTSP capture once; load models and OCR once.
4. Read frames on the configured target FPS schedule.
5. Run vehicle/plate detection, OCR, tracking, and event finalization.
6. Save local evidence and enqueue backend jobs when enabled.
7. Periodically log health metrics and flush the backend queue (non-dry-run).
8. On controlled stop or stream failure policy, finalize remaining tracks.
9. Perform final queue flush, write `worker_summary.json`, and release capture.

## RTSP Reconnection Strategy

When `ANPR_RTSP_RECONNECT_ENABLED=true`:

1. Count **consecutive read failures** per open capture session.
2. Log `RTSP read failure count=N` (masked URL only in reconnect messages).
3. When failures reach `ANPR_RTSP_READ_FAILURE_LIMIT`, release capture and attempt reconnect.
4. Wait using exponential backoff from `ANPR_RTSP_RECONNECT_INITIAL_DELAY_SECONDS`, capped by `ANPR_RTSP_RECONNECT_MAX_DELAY_SECONDS`.
5. Reopen capture; on success log `RTSP reconnect succeeded` and resume processing.
6. On failure, increment reconnect attempts and retry until:
   - `ANPR_RTSP_RECONNECT_MAX_ATTEMPTS` is reached (`0` = unlimited), or
   - manual shutdown is requested, or
   - `--max-seconds` elapses.

Stop reason `rtsp_reconnect_exhausted` is recorded when reconnect attempts are exhausted.

## Queue-Safe Runtime Behavior

- Detection and event finalization continue when backend flush fails.
- `BackendClient.flush_queue_safe()` catches exceptions and returns a result object instead of raising into the frame loop.
- During live runs (`rtsp`, `webcam`), the runtime calls `flush_queue_safe()` every `ANPR_BACKEND_QUEUE_FLUSH_INTERVAL_SECONDS`.
- A final flush runs at shutdown for all backend-enabled sources.
- Existing queue checkpointing, per-job `evidence_mode`, upload/metadata behavior, and idempotency are unchanged.
- Dry-run never enqueues or posts to Laravel.

## Runtime Health Logs

Every `ANPR_RTSP_HEALTH_LOG_INTERVAL_SECONDS` during `rtsp` and `webcam` runs, one JSON line is appended to `worker.log`, for example:

```json
{"type":"health","uptime_seconds":30.1,"source_type":"rtsp","frames_read":90,"frames_processed":30,"active_tracks":1,"events_finalized":0,"backend_jobs_queued":0,"backend_jobs_succeeded":0,"backend_jobs_failed":0,"backend_jobs_exhausted":0,"rtsp_reconnect_attempts":0,"last_frame_at":"2026-06-22T12:00:00Z","stop_reason":null}
```

Health logs are operational only; they do not log per-frame detection detail.

## Graceful Shutdown

- **Ctrl+C** (`KeyboardInterrupt`) and **SIGINT/SIGTERM** set `stop_requested` and `stop_reason=manual_shutdown`.
- The frame loop exits naturally.
- Active tracks with valid vote-buffer candidates are finalized once with reason `manual_shutdown` or `runtime_shutdown`.
- Already finalized or decision-finalized tracks are not duplicated.
- Evidence is saved, `events.jsonl` is updated, backend jobs are enqueued when enabled, and `worker_summary.json` is written.

## Runtime Summary Contract

`worker_summary.json` includes M11 fields:

| Field | Description |
| ----- | ----------- |
| `milestone` | `"M11"` |
| `source_type` | `rtsp`, `video`, `image`, or `webcam` |
| `status` | `completed` or `failed` |
| `stop_reason` | e.g. `max_seconds_reached`, `manual_shutdown`, `rtsp_reconnect_exhausted` |
| `started_at` / `ended_at` | UTC ISO timestamps |
| `uptime_seconds` | Wall-clock runtime duration |
| `frames_read` / `frames_processed` | Frame counters |
| `events_finalized` | Persisted local events |
| `active_tracks_finalized_on_shutdown` | Tracks finalized during shutdown |
| `rtsp_reconnect_attempts` / `rtsp_reconnect_successes` | Reconnect counters |
| `rtsp_consecutive_read_failures` | Last streak before reconnect |
| `last_frame_at` | UTC ISO timestamp of last successful frame |
| Backend metrics | Existing `backend_jobs_*`, `backend_images_sent`, etc. |

Previous milestone summary fields are preserved where applicable.

## Configuration

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `ANPR_RTSP_RECONNECT_ENABLED` | `true` | Enable RTSP reconnect behavior |
| `ANPR_RTSP_RECONNECT_MAX_ATTEMPTS` | `0` | Max reconnect cycles (`0` = unlimited) |
| `ANPR_RTSP_RECONNECT_INITIAL_DELAY_SECONDS` | `2.0` | First reconnect wait |
| `ANPR_RTSP_RECONNECT_MAX_DELAY_SECONDS` | `30.0` | Backoff cap |
| `ANPR_RTSP_READ_FAILURE_LIMIT` | `10` | Consecutive read failures before reopen |
| `ANPR_RTSP_HEALTH_LOG_INTERVAL_SECONDS` | `15.0` | Health log interval |
| `ANPR_BACKEND_QUEUE_FLUSH_INTERVAL_SECONDS` | `10.0` | Periodic queue flush interval |

RTSP credentials remain in `.env` only (`ANPR_RTSP_URL`). They are masked in runtime output via `mask_rtsp_url()`.

## CLI Usage

```bash
python main.py check-config --strict

python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict
python main.py run --source video --video samples/videos/document_6177158287369184218.mp4 --dry-run --strict

python main.py run --source rtsp --max-seconds 30 --dry-run --strict
python main.py run --source rtsp --max-seconds 30 --strict

python main.py flush-backend-queue
```

Use `--max-seconds` for bounded RTSP validation when no long-running deployment is desired.

## File-by-File Responsibilities

| File | M11 responsibility |
| ---- | ------------------ |
| `config.py` | M11 env fields, validation, `mask_rtsp_url()` |
| `anpr.py` | RTSP reconnect loop, health logs, periodic flush, shutdown finalization, M11 summary |
| `backend.py` | `flush_queue_safe()` for frame-loop-safe flushing |
| `main.py` | M11 CLI labels and unchanged command compatibility |
| `README.md` | Minimal milestone pointer and RTSP examples |
| `docs/m11-realtime-rtsp-runtime-architecture.md` | This document |

## Backend and Frontend Compatibility

- **Laravel** — No API contract changes. Upload/metadata queue behavior from M9/M10 is preserved.
- **React M10** — Manual refresh only. M11 does not add realtime UI; operators refresh `/admin/anpr-monitoring` to view new RTSP events after backend flush.

## Verification Checklist

```bash
python -m compileall .
python main.py check-config --strict
python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict
python main.py run --source video --video samples/videos/document_6177158287369184218.mp4 --dry-run --strict
python main.py run --source rtsp --max-seconds 30 --dry-run --strict
python main.py flush-backend-queue
```

Manual checks when a live RTSP camera and backend credentials are available:

1. Run `python main.py run --source rtsp --max-seconds 60 --strict`.
2. Confirm health JSON lines in `worker.log`.
3. Confirm `worker_summary.json` has `milestone: M11` and reconnect counters.
4. Confirm backend events and evidence appear in M10 monitoring after refresh.
5. Confirm Ctrl+C produces `stop_reason: manual_shutdown` and a written summary.

## Passing Criteria

- RTSP runtime processes continuously until a controlled stop.
- Temporary RTSP read failures trigger reconnect instead of immediate fatal exit (when enabled).
- Backend flush failures are logged but do not stop frame processing.
- Health metrics are logged periodically during long RTSP/webcam runs.
- Ctrl+C or SIGTERM causes graceful shutdown with summary written.
- Active tracks are finalized on shutdown when valid candidates exist.
- `worker_summary.json` is always written after shutdown.
- README updated minimally; M11 documentation exists.
- Image/video dry-run commands still work.
- `flush-backend-queue` still works.

## Known Limitations

- No frontend realtime feed; manual refresh only.
- RTSP verification requires a reachable camera and valid `ANPR_RTSP_URL`.
- OpenCV RTSP behavior varies by camera firmware and network conditions.
- Periodic queue flush is synchronous but bounded by `ANPR_BACKEND_TIMEOUT_SECONDS`; very slow backend responses may delay a frame iteration briefly.
- Windows signal handling supports SIGINT; SIGTERM when available.

## M12 Handoff Notes

Potential follow-ups for M12:

- Unit tests for reconnect state machine and backoff.
- Unit tests for shutdown track finalization (no duplicate events).
- Integration test with simulated RTSP read failures.
- Queue retry regression tests under periodic flush.
- Manual long-running RTSP soak test and operator runbook.
