# M15 — Performance and Accuracy Tuning Architecture

## 1. Overview

**Milestone:** M15 — Performance and Accuracy Tuning Architecture  
**Status:** Implemented  
**Scope:** AI runtime tuning, accuracy safeguards, backend list performance, frontend live polling efficiency  
**Builds on:** M11 RTSP runtime, M12 live monitoring, M13 vehicle linking, M14 testing architecture

M15 tunes runtime speed, detection reliability, OCR quality, backend responsiveness, and frontend live update efficiency **after correctness is stable**. It does not replace the existing architecture.

## 2. Scope

| Layer | M15 work |
| ----- | -------- |
| **AI (`ai-anpr-v1`)** | OCR throttle, runtime metrics in `worker_summary.json`, tuning profile, performance target results, plate normalization hardening |
| **Backend (`backend-laravel-v1`)** | Lighter ANPR list queries (`withCount('images')`), detail endpoint unchanged |
| **Frontend (`frontend-react-v1`)** | Polling backoff on repeated failures, `images_count` normalization for list evidence badges |

## 3. Out of Scope

- WebSocket/SSE live updates (documented as future upgrade only)
- Python WebSocket server, cloud uploads beyond existing evidence modes, Roboflow hosted API
- Multiple OCR engines, complex multi-stage pipelines, benchmark dashboards
- Rewriting `anpr.py` into many modules
- Exposing RTSP credentials, camera IPs, or secrets in logs, summaries, frontend, or docs

## 4. Architecture Context

```text
RTSP / video / image
        │
        ▼
   anpr.py (ANPRProcessor)
   ├── frame scheduler (ANPR_TARGET_FPS)
   ├── YOLO vehicle + plate (once at startup)
   ├── OCR throttle (ANPR_OCR_MIN_INTERVAL_SECONDS)
   ├── vote buffer + finalization
   ├── duplicate cooldown
   └── async backend queue enqueue (backend.py)
        │
        ▼
   Laravel ANPR APIs
        │
        ▼
   React ANPR monitoring (polling + backoff)
```

M12/M13/M14 behavior is preserved: live polling, blinking LIVE indicator, row highlights, vehicle linking, plate immutability, and existing event payloads.

## 5. AI Runtime Tuning

### Frame scheduling

- **`ANPR_TARGET_FPS`** (default `3.0`) controls processed frame rate via skip interval or wall-clock fallback.
- Demo target: **3–5 processed FPS** under typical RTSP demo hardware.

### Detection thresholds

| Variable | Default | Role |
| -------- | ------- | ---- |
| `ANPR_VEHICLE_CONF` | `0.35` | Vehicle YOLO confidence |
| `ANPR_PLATE_CONF` | `0.25` | Plate YOLO confidence |
| `ANPR_MIN_OCR_CONFIDENCE` | `0.30` | Minimum OCR reading confidence |

### OCR throttle (M15)

**`ANPR_OCR_MIN_INTERVAL_SECONDS`** (default `0.35`):

- Skips OCR for a track that already has vote data until the interval elapses.
- Never skips OCR when the track has **no** plate votes yet.
- Does not skip finalization or plate detection.
- Set to `0` to disable throttle.

### Tracking and finalization

| Variable | Default | Role |
| -------- | ------- | ---- |
| `ANPR_TRACK_EXPIRY_SECONDS` | `2.0` | Expire unseen tracks; drives event latency target |
| `ANPR_EARLY_FINALIZE_MIN_VOTES` | `3` | Early finalize vote count |
| `ANPR_EARLY_FINALIZE_MIN_CONFIDENCE` | `0.90` | Early finalize average confidence |
| `ANPR_MIN_PLATE_VOTES` | `2` | Minimum votes on source end / expiry |

### Backend posting

- Event enqueue remains **async and non-blocking** via JSONL queue.
- Periodic flush: **`ANPR_BACKEND_QUEUE_FLUSH_INTERVAL_SECONDS`** (default `10.0`).

### Model loading

- Vehicle model, plate model, and PaddleOCR load **once per run** at startup.

## 6. Runtime Metrics Added

`worker_summary.json` retains all prior fields and adds:

| Field | Description |
| ----- | ----------- |
| `processed_fps` | `frames_processed / duration_seconds` |
| `effective_read_fps` | `frames_read / duration_seconds` |
| `average_event_latency_seconds` | Mean `finalize_at - last_seen_at` for measurable finalizations |
| `max_event_latency_seconds` | Max latency in the run |
| `ocr_calls_per_processed_frame` | OCR calls ÷ processed frames |
| `ocr_calls_per_finalized_event` | OCR calls ÷ events finalized |
| `plate_candidates_per_processed_frame` | Valid candidates ÷ processed frames |
| `backend_flush_interval_seconds` | Configured flush interval |
| `ocr_calls_skipped_by_throttle` | Skipped OCR opportunities |
| `ocr_throttle_interval_seconds` | Configured throttle interval |
| `tuning_profile` | Snapshot of active tuning config |
| `performance_targets` | Documented target labels |
| `performance_target_results` | Objective pass/fail/`not_measured` per target |
| `milestone` | `"M15"` |

**Event latency note:** For `track_expired` finalization, latency approximates time from last vehicle sighting to finalization. For `source_end` or shutdown finalization, the metric reflects runtime-finalization latency rather than true disappearance latency.

## 7. Accuracy Tuning

### Plate normalization

`normalize_plate_text()`:

- Strips zero-width characters.
- Normalizes Unicode dash/separator variants before alphanumeric extraction.
- Preserves existing Malaysian private-vehicle validation (`^[A-Z]{1,4}[0-9]{1,4}[A-Z]?$`).

### Voting

- Majority vote with deterministic tie-break (unchanged from M5).
- OCR noise cannot dominate when more consistent votes exist for another plate string.
- Thresholds remain **config-driven**, not hardcoded.

## 8. Duplicate and Cooldown Behavior

**`ANPR_DUPLICATE_COOLDOWN_SECONDS`** (default `10.0`):

- Suppresses repeated events for the same normalized plate within the cooldown window.
- A genuinely new pass after cooldown can create a new event.
- Metric: `duplicate_events_suppressed` in `worker_summary.json`.

## 9. Backend Query Performance

### List (`GET /api/anpr-events`)

- Default sort: `detection_time` desc (M12).
- Supports `since`, `plate_number` / `search`, filters, pagination (max 100).
- **M15:** Eager-loads `vehicle` and `camera` only; uses `withCount('images')` instead of full image rows.
- Response adds **`images_count`** when counting; omits full `images` array on list.

### Detail (`GET /api/anpr-events/{id}`)

- Loads full `vehicle`, `camera`, and `images` (unchanged).

### Indexes

Existing indexes on `plate_number`, `detection_time`, `created_at`, flags, and FK columns support list filters.

## 10. Frontend Live Update Efficiency

| Constant | Value | Role |
| -------- | ----- | ---- |
| `POLL_INTERVAL_MS` | `5000` | Base live poll interval |
| `POLL_BACKOFF_MAX_MS` | `30000` | Max backoff cap |
| `HIGHLIGHT_DURATION_MS` | `4000` | New row highlight duration |

**M15 behavior:**

- In-flight request guard prevents overlapping polls.
- Repeated poll failures enter `reconnecting` state with exponential backoff (`interval × 2^failures`, capped).
- Successful poll resets backoff and restores `live` status.
- Polling stops on unmount; highlight timers are cleared.
- List evidence badges use `images_count` when image rows are omitted.

**Future upgrade:** Server-sent events or WebSocket broadcast (Laravel Reverb already exists for patrol) — not implemented in M15.

## 11. Recommended Demo `.env` Profile

```env
ANPR_SOURCE=rtsp
ANPR_TARGET_FPS=3
ANPR_DEVICE=cpu
ANPR_VEHICLE_CONF=0.35
ANPR_PLATE_CONF=0.25
ANPR_MIN_OCR_CONFIDENCE=0.30
ANPR_OCR_PREPROCESS=true
ANPR_OCR_SCALE=2.0
ANPR_OCR_MIN_INTERVAL_SECONDS=0.35
ANPR_TRACK_EXPIRY_SECONDS=2.0
ANPR_EARLY_FINALIZE_MIN_VOTES=3
ANPR_EARLY_FINALIZE_MIN_CONFIDENCE=0.90
ANPR_MIN_PLATE_VOTES=2
ANPR_DUPLICATE_COOLDOWN_SECONDS=10
ANPR_BACKEND_QUEUE_FLUSH_INTERVAL_SECONDS=10
ANPR_EVIDENCE_MODE=upload
```

## 12. Recommended Production-like `.env` Profile

```env
ANPR_SOURCE=rtsp
ANPR_TARGET_FPS=4
ANPR_DEVICE=cuda
ANPR_VEHICLE_CONF=0.40
ANPR_PLATE_CONF=0.30
ANPR_MIN_OCR_CONFIDENCE=0.35
ANPR_OCR_MIN_INTERVAL_SECONDS=0.40
ANPR_TRACK_EXPIRY_SECONDS=2.5
ANPR_DUPLICATE_COOLDOWN_SECONDS=15
ANPR_BACKEND_ENABLED=true
ANPR_EVIDENCE_MODE=upload
ANPR_BACKEND_QUEUE_FLUSH_INTERVAL_SECONDS=10
ANPR_RTSP_RECONNECT_ENABLED=true
```

## 13. CPU Profile

- `ANPR_DEVICE=cpu`
- `ANPR_TARGET_FPS=3`
- `ANPR_OCR_MIN_INTERVAL_SECONDS=0.35` (or `0.40` if CPU-bound)
- Prefer `ANPR_OCR_PREPROCESS=true` with `ANPR_OCR_SCALE=2.0` for accuracy; reduce scale to `1.5` if FPS drops below target.

## 14. GPU Profile

- `ANPR_DEVICE=cuda` (requires CUDA-capable PyTorch)
- `ANPR_TARGET_FPS=4`–`5`
- Slightly higher detection confidences acceptable with faster inference.
- Keep OCR throttle enabled; GPU speeds YOLO more than OCR.

## 15. RTSP Camera Settings

- Configure stream URL only in `.env` (`ANPR_RTSP_URL`); never pass RTSP URLs on CLI.
- Use sub-stream / lower resolution where possible for stable 3–5 processed FPS.
- `ANPR_RTSP_RECONNECT_ENABLED=true` with sensible `ANPR_RTSP_READ_FAILURE_LIMIT`.
- `ANPR_MAX_SECONDS` useful for bounded demo runs.

## 16. Backend Queue Flush Interval

- Default: **10 seconds** during RTSP runs.
- Final flush at shutdown processes remaining jobs.
- Non-blocking: frame loop calls `flush_queue_safe()` only on interval.

## 17. Frontend Polling Interval

- Base: **5 seconds** on the ANPR monitoring list page.
- Backoff: doubles on consecutive failures up to **30 seconds**.
- Manual refresh bypasses backoff timer scheduling but still respects in-flight guard.

## 18. Evidence Mode and Retention Policy

| Mode | Use |
| ---- | --- |
| `upload` | Recommended for deployment; Laravel owns evidence files |
| `metadata` | Local dev only; requires `ANPR_IMAGE_ROOTS` on Laravel |

`ANPR_EVIDENCE_RETENTION_DAYS=0` keeps local evidence indefinitely (current run never deleted).

## 19. Known Accuracy Limitations

- OCR confuses similar characters (`O`/`0`, `I`/`1`) — normalization does not auto-correct these to avoid rejecting valid plates.
- Single-frame image runs may finalize with one vote.
- Short RTSP test runs may report `not_measured` for FPS/latency targets.
- List API no longer returns full image metadata; detail page and dedicated image API remain authoritative.

## 20. Testing and Verification

### AI

```bash
cd ai-anpr-v1
python -m pytest -q
python main.py check-config
python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict
python main.py run --source video --video samples/videos/document_6177158287369184218.mp4 --dry-run --strict
```

### Backend

```bash
cd backend-laravel-v1
php artisan test --filter=Anpr
```

### Frontend

```bash
cd frontend-react-v1
yarn test
yarn build
```

### Manual RTSP check

```bash
python main.py run --source rtsp --max-seconds 60 --dry-run --strict
```

Inspect `runs/run_*/worker_summary.json` for `processed_fps`, `tuning_profile`, and `performance_target_results`.

## 21. Milestone 15 Passing Criteria

| Area | Criteria |
| ---- | -------- |
| AI | Target 3–5 processed FPS measured or reported; summary includes tuning profile and latency metrics; OCR throttle active; duplicate suppression measured; async backend posting; models loaded once; tests pass |
| Backend | List remains responsive; plate lookup indexed; detail loads full evidence; linking intact |
| Frontend | Live updates within polling delay; backoff on failures; no duplicate rows; cleanup on unmount |
| Docs | This document, README link, module note |

## 22. Final Delivery Readiness Notes

- Tune `ANPR_TARGET_FPS` and `ANPR_OCR_MIN_INTERVAL_SECONDS` on target hardware using `worker_summary.json`.
- Compare `performance_target_results` across CPU vs GPU profiles before demo.
- For high event volume, keep list `per_page` modest (10–25) and rely on `since` for incremental polling if added later.
- Next recommendations: incremental `since` polling on frontend, composite DB index on `(detection_time, created_at)`, optional SSE channel for ANPR events.
