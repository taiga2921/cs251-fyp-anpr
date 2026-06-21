# AI ANPR Modules

## 1. Purpose

The goal is to design a clean, efficient, effective, practical ANPR system that can:

- Read from RTSP cameras.
- Read from sample video files.
- Read from single test images.
- Read from a webcam if needed.
- Detect vehicles.
- Detect license plates.
- OCR license plate text.
- Track vehicles across frames.
- Vote OCR results across multiple frames.
- Finalize one ANPR event per vehicle.
- Save evidence images.
- Send final ANPR event and evidence to a backend server.
- Run fast enough for demo and real-time monitoring.

The design follows a simple runtime philosophy:

```text
Load models once
Open source once
Process frames continuously
Keep temporary state in memory
Save only useful evidence
Send final results to backend asynchronously
```

---

## 2. Core Design Principles

### 2.1 Efficiency first

The system should not pass every frame through a long chain of folders and scripts. Most data should stay in memory while the vehicle is being tracked.

Only final evidence should be written to disk.

### 2.2 One runtime, multiple sources

The same pipeline should work for:

```text
RTSP camera
Video file
Single image
Webcam
```

This makes development and testing easier. Sample videos can be used when the physical camera is unavailable.

### 2.3 Backend owns final records

The AI module should detect, track, OCR, and prepare evidence. The backend should own final event records, image records, logs, and dashboard display.

The AI module may temporarily save evidence locally, but the final system should send the event and evidence to the backend.

### 2.4 Async backend communication

ANPR detection should not freeze just because the backend is slow.

The runtime should finalize an event, save evidence, enqueue a backend job, and continue processing frames.

### 2.5 Simple modules, clear responsibilities

Each module should do one job only.

Avoid huge files and avoid over-engineering.

### 2.6 GitHub reference approach

The new module may use the GitHub project `computervisioneng/automatic-number-plate-recognition-python-yolov8` as a **reference for simplicity**, not as code to copy blindly.

That project is useful because it demonstrates a compact ANPR flow:

```text
video frame
→ vehicle detection
→ vehicle tracking
→ license plate detection
→ OCR on plate crop
→ write simple output
```

The new module should learn from that style:

- Keep the runtime loop simple.
- Use one main processing file at first instead of many staged scripts.
- Support sample video testing from the beginning.
- Load models once.
- Process frames directly instead of writing every intermediate stage to folders.
- Save only final useful evidence.
- Keep output records compact and easy to inspect.

However, the new module should not copy the GitHub project exactly because this FYP system also needs:

- RTSP camera support.
- Backend API integration.
- Backend token caching.
- Async backend queue.
- Evidence upload or metadata creation.
- Configurable camera ID.
- Malaysian plate post-processing rules.
- Dashboard-ready event records.

So the GitHub project is a **runtime simplicity reference**, while this document remains the full design for the new module.

Reference repository:

```text
https://github.com/computervisioneng/automatic-number-plate-recognition-python-yolov8
```

---

## 3. High-Level Architecture

```text
Input Source
  RTSP / video / image / webcam
        |
        v
Source Reader
        |
        v
Frame Scheduler
  target FPS / frame skipping
        |
        v
Vehicle Detector
  YOLO vehicle detection
        |
        v
Vehicle Tracker
  track_id per vehicle
        |
        v
Plate Detector
  YOLO license plate detection
        |
        v
Plate Crop + Preprocessing
        |
        v
OCR Engine
        |
        v
Plate Text Normalizer
        |
        v
Per-Track Vote Buffer
        |
        v
Track Finalizer
        |
        v
Evidence Saver
        |
        v
Backend Queue
        |
        v
Backend API
  event + images + logs
```

---

## 4. Recommended Folder Structure

The first version should stay very small. Do not start with many `runtime/*.py` files. Keep the runtime logic in one clear `anpr.py` file, then split later only when the code becomes too large.

```text
new-ai-anpr/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── main.py
├── config.py
├── anpr.py
├── backend.py
│
├── models/
│   ├── vehicle/
│   │   └── .gitkeep
│   └── plate/
│       └── .gitkeep
│
├── samples/
│   ├── videos/
│   │   └── .gitkeep
│   └── images/
│       └── .gitkeep
│
├── runs/
│   └── .gitkeep
│
└── .cache/
    └── .gitkeep
```

### Why this structure is smaller

The goal is to avoid recreating a large staged architecture. The first clean version should have only four real Python files:

| File | Responsibility |
|---|---|
| `main.py` | CLI commands and entry point |
| `config.py` | Load and validate `.env` settings |
| `anpr.py` | Main ANPR runtime: source reading, detection, tracking, OCR, voting, evidence, metrics |
| `backend.py` | Backend token cache, API client, async queue, event posting, image metadata/upload |

### When to split later

Do not split early. Split only when a section becomes difficult to maintain.

| If this part becomes too large | Split later into |
|---|---|
| Source reading grows | `source.py` |
| Detector wrappers grow | `detector.py` |
| Tracker grows | `tracker.py` |
| OCR/preprocessing grows | `ocr.py` |
| Voting/finalization grows | `plate_vote.py` |
| Evidence handling grows | `evidence.py` |
| Backend queue grows | `backend_queue.py` |

Initial rule:

```text
Start simple: main.py + config.py + anpr.py + backend.py.
Refactor later only when needed.
```

---

## 5. Module-by-Module Design

## 5.1 `main.py` — CLI Entry Point

### Responsibility

`main.py` exposes the commands used by the developer/operator.

It should not contain the full ANPR logic. It should only:

- Parse command-line arguments.
- Load config.
- Create the ANPR processor.
- Start the selected run mode.
- Print final summary.

### Required commands

```bash
python main.py check-config
python main.py run --source rtsp --dry-run
python main.py run --source video --video samples/videos/test_vehicle.mp4 --dry-run
python main.py run --source image --image samples/images/frame.jpg --dry-run
python main.py run --source webcam --camera-index 0 --dry-run
python main.py run --source-path samples/videos/test_vehicle.mp4 --dry-run
python main.py flush-backend-queue
```

### Design rule

Keep `main.py` thin. If logic starts growing, move it into `anpr.py` or `backend.py`.

---

## 5.2 `config.py` — Configuration Loader

### Responsibility

Loads `.env` and exposes typed settings to the rest of the module.

### Main settings

```env
ANPR_SOURCE=rtsp
ANPR_RTSP_URL=rtsp://user:password@camera-ip:554/stream1
ANPR_VIDEO_PATH=samples/videos/test_vehicle.mp4
ANPR_IMAGE_PATH=samples/images/frame.jpg
ANPR_CAMERA_INDEX=0

ANPR_VEHICLE_MODEL=yolo11s.pt
ANPR_PLATE_MODEL=models/plate/license-plate-finetune-v1s.pt
ANPR_DEVICE=cpu

ANPR_TARGET_FPS=3
ANPR_VEHICLE_CONF=0.35
ANPR_PLATE_CONF=0.25
ANPR_TRACK_IOU_THRESHOLD=0.3
ANPR_TRACK_EXPIRY_SECONDS=2.0
ANPR_EARLY_FINALIZE_MIN_VOTES=3
ANPR_EARLY_FINALIZE_MIN_CONFIDENCE=0.90
ANPR_MIN_PLATE_VOTES=2
ANPR_MIN_OCR_CONFIDENCE=0.3

ANPR_BACKEND_ENABLED=false
ANPR_BACKEND_BASE_URL=http://localhost:8000/api
ANPR_BACKEND_EMAIL=
ANPR_BACKEND_PASSWORD=
ANPR_BACKEND_CAMERA_ID=
ANPR_BACKEND_TOKEN_CACHE=.cache/backend_token.json
ANPR_BACKEND_QUEUE_FILE=.cache/backend_queue.jsonl
ANPR_BACKEND_RETRY_LIMIT=3

ANPR_EVIDENCE_MODE=metadata
ANPR_RUNS_DIR=runs
ANPR_SAVE_LOCAL_EVIDENCE=true
ANPR_DELETE_LOCAL_AFTER_UPLOAD=false
```

### Validation rules

- If source type is `rtsp`, `ANPR_RTSP_URL` must exist.
- If source type is `video`, the video path must exist.
- If source type is `image`, the image path must exist.
- Vehicle model must be configured.
- Plate model should be configured for best performance.
- Backend credentials are required only when backend is enabled.
- If backend is enabled, `ANPR_BACKEND_CAMERA_ID` must be a real backend camera UUID.

---

## 5.3 `anpr.py` — Main ANPR Runtime

### Responsibility

`anpr.py` contains the complete first-version ANPR loop.

It handles:

- Source reading.
- Target FPS scheduling.
- YOLO vehicle detection.
- YOLO plate detection.
- Plate crop preprocessing.
- OCR.
- Plate text normalization.
- Simple in-memory tracking.
- Per-track OCR voting.
- Track finalization.
- Local evidence saving.
- Runtime metrics.
- Enqueuing backend jobs through `backend.py`.

This is intentionally one file at first so the new module stays easy to understand.

### Internal components inside `anpr.py`

Use classes or small functions inside one file:

```python
class FramePacket: ...
class Detection: ...
class TrackState: ...
class FinalizedEvent: ...
class ANPRProcessor: ...
```

Suggested functions/classes:

| Component | Role |
|---|---|
| `open_source()` | Open RTSP/video/image/webcam source |
| `iter_frames()` | Yield frames from selected source |
| `should_process_frame()` | Apply target FPS/frame skipping |
| `load_models()` | Load vehicle model, plate model, OCR once |
| `detect_vehicles()` | Run YOLO vehicle detection |
| `detect_plates()` | Run YOLO plate detection on vehicle crops |
| `preprocess_plate()` | Basic grayscale/resize/denoise/sharpen if needed |
| `read_plate_text()` | OCR plate crop |
| `normalize_plate_text()` | Uppercase, remove symbols, validate plate format |
| `update_tracks()` | IoU-based tracking |
| `add_plate_candidate()` | Add OCR candidate to a track |
| `should_finalize_track()` | Check expiry/early-vote/source-end conditions |
| `finalize_track()` | Choose final plate and prepare event |
| `save_evidence()` | Save full, plate, and annotated evidence |
| `write_event_record()` | Append to `events.jsonl` |
| `write_summary()` | Save `worker_summary.json` |

### Source support

`anpr.py` should support:

| Source | Behavior |
|---|---|
| RTSP | Open stream once and read until stopped/max seconds |
| Video | Read frames until video ends; flush active tracks at the end |
| Image | Process one frame; finalize any detected track immediately |
| Webcam | Open webcam index and read until stopped/max seconds |

### Frame packet

```python
@dataclass
class FramePacket:
    frame_index: int
    timestamp: float
    image: np.ndarray
    source_type: str
    source_path: str | None
    is_last: bool = False
```

### Detection flow

```text
Frame
→ vehicle YOLO
→ vehicle crops
→ plate YOLO on vehicle crop
→ plate crop
→ preprocessing
→ OCR
→ normalized plate candidate
→ track vote buffer
```

### Track state

```python
@dataclass
class TrackState:
    track_id: int
    bbox: tuple[int, int, int, int]
    first_seen_at: float
    last_seen_at: float
    plate_votes: list
    best_plate_crop: np.ndarray | None
    best_full_frame: np.ndarray | None
    best_annotated_frame: np.ndarray | None
    finalized: bool = False
```

### Track finalization

Finalize synchronously when:

1. Track disappears for `ANPR_TRACK_EXPIRY_SECONDS`.
2. Same high-confidence plate reaches `ANPR_EARLY_FINALIZE_MIN_VOTES` and `ANPR_EARLY_FINALIZE_MIN_CONFIDENCE`.
3. Source ends.

After finalization:

- Choose final plate by majority/weighted confidence.
- Save local evidence immediately.
- Append event to `events.jsonl`.
- Enqueue backend job if backend is enabled.
- Mark track finalized to prevent duplicate posting.

Backend posting/upload should be async and should not block frame processing.

### Evidence output

```text
runs/
└── run_YYYYMMDD_HHMMSS/
    ├── events.jsonl
    ├── worker_summary.json
    └── evidence/
        ├── full/
        ├── plate/
        └── annotated/
```

### Final event record

```json
{
  "track_id": 1,
  "plate_number": "ABC1234",
  "confidence": 0.92,
  "votes": 3,
  "first_seen_at": "2026-06-21T10:00:00Z",
  "last_seen_at": "2026-06-21T10:00:04Z",
  "finalization_reason": "track_expired",
  "evidence": {
    "full": "runs/run_YYYYMMDD_HHMMSS/evidence/full/track_1_full.jpg",
    "plate": "runs/run_YYYYMMDD_HHMMSS/evidence/plate/track_1_plate.jpg",
    "annotated": "runs/run_YYYYMMDD_HHMMSS/evidence/annotated/track_1_annotated.jpg"
  },
  "backend": {
    "queued": true,
    "posted": false,
    "event_id": null,
    "images_linked": 0,
    "error": null
  },
  "dry_run": true
}
```

### Runtime metrics

`anpr.py` should collect lightweight metrics only:

- frames read
- frames processed
- active tracks
- finalized events
- average vehicle detection time
- average plate detection time
- average OCR time
- average event latency
- backend jobs queued/succeeded/failed

Heavy benchmark dashboards should be backend/admin future work, not part of the first ANPR runtime.

---

## 5.4 `backend.py` — Backend Client and Async Queue

### Responsibility

`backend.py` contains all backend-related logic:

- Token caching.
- Login.
- Retry after token expiry.
- Posting ANPR event.
- Creating image metadata records.
- Future binary upload mode.
- Queueing backend jobs.
- Flushing failed/pending jobs.

Keeping this separate prevents network/backend code from cluttering the ANPR frame loop.

### Token cache

Use `.cache/backend_token.json`.

Behavior:

1. Load token from cache.
2. If token exists and is not expired, reuse it.
3. If missing/expired, login and save token.
4. If request returns 401, login again and retry once.
5. Do not login before every request.

Example cache:

```json
{
  "access_token": "...",
  "token_type": "bearer",
  "expires_at": "2026-06-21T10:00:00Z"
}
```

### Backend queue

Use `.cache/backend_queue.jsonl`.

A queued job should include:

```json
{
  "job_id": "uuid",
  "status": "pending",
  "attempts": 0,
  "event": {
    "plate_number": "ABC1234",
    "confidence": 0.92,
    "detection_time": "2026-06-21T10:00:00Z"
  },
  "evidence": {
    "full": "runs/.../full.jpg",
    "plate": "runs/.../plate.jpg",
    "annotated": "runs/.../annotated.jpg"
  }
}
```

### Backend event payload

Send only the fields the backend expects:

```json
{
  "camera_id": "<backend-camera-uuid>",
  "plate_number": "ABC1234",
  "confidence": 0.92,
  "detection_time": "2026-06-21T10:00:00Z",
  "is_valid": true,
  "latitude": null,
  "longitude": null
}
```

### Evidence modes

Support metadata mode first:

```env
ANPR_EVIDENCE_MODE=metadata
```

Metadata mode means:

- AI saves evidence locally under `runs/`.
- AI creates backend image metadata rows pointing to those paths.
- Backend can display images only if its allowed image roots include this new module folder.

Future upload mode:

```env
ANPR_EVIDENCE_MODE=upload
```

Upload mode means:

- AI uploads binary images to backend.
- Backend owns the final files.
- This requires a backend upload endpoint.

### Backend compatibility warning

If using metadata mode, the backend must be configured to read the new module evidence folder. For example:

```env
ANPR_IMAGE_ROOTS=D:/Degree CDCS251/ffyypp/Dev/new-ai-anpr
```

If this is not configured, backend image records may exist but image content endpoints can fail.

---

## 6. CLI Commands

## 6.1 Check config

```bash
python main.py check-config
```

Checks:

- `.env` loaded.
- Source config valid.
- Model files exist.
- Backend config valid if enabled.
- Runs directory writable.

---

## 6.2 Run RTSP camera

```bash
python main.py run --source rtsp --dry-run
python main.py run --source rtsp --max-seconds 30 --dry-run
python main.py run --source rtsp --max-seconds 30
```

---

## 6.3 Run sample video

```bash
python main.py run --source video --video samples/videos/test_vehicle.mp4 --dry-run
```

This is important for development and FYP demonstration because the system can be tested without a live camera.

---

## 6.4 Run single image

```bash
python main.py run --source image --image samples/images/frame.jpg --dry-run
```

---

## 6.5 Run webcam

```bash
python main.py run --source webcam --camera-index 0 --dry-run
```

---

## 6.6 Auto source path

```bash
python main.py run --source-path rtsp://user:pass@ip:554/stream1 --dry-run
python main.py run --source-path samples/videos/test_vehicle.mp4 --dry-run
python main.py run --source-path samples/images/frame.jpg --dry-run
```

---

## 6.7 Flush backend queue

```bash
python main.py flush-backend-queue
```

Sends pending backend jobs.

---

## 7. Backend Integration Design

## 7.1 Event payload

When a final plate is ready, send:

```json
{
  "camera_id": "camera-uuid",
  "plate_number": "ABC1234",
  "confidence": 0.92,
  "detection_time": "2026-06-21T10:00:00Z",
  "is_valid": true,
  "latitude": null,
  "longitude": null
}
```

## 7.2 Image evidence payload

### Metadata mode

The AI sends image metadata/path:

```json
{
  "anpr_event_id": "event-uuid",
  "image_type": "plate",
  "file_path": "runs/run_20260621_100000/evidence/plate/event_001_plate.jpg",
  "file_size": 12345,
  "resolution": "320x80"
}
```

### Upload mode

The AI uploads the binary file:

```text
POST /api/anpr-events/{event_id}/images/upload
image_type=plate
image=@event_001_plate.jpg
```

Upload mode is the cleaner final architecture because backend owns final evidence.

## 7.3 Recommended evidence strategy

Start with metadata mode if backend upload endpoint is not available.

Move to upload mode when backend supports image upload.

---

## 8. Hugging Face YOLOv11s Plate Model Plan

## 8.1 Recommended model

Use local plate detector weights:

```text
models/plate/license-plate-finetune-v1s.pt
```

Suggested source:

```text
Hugging Face: morsetechlab/yolov11-license-plate-detection
File: license-plate-finetune-v1s.pt
```

## 8.2 Setup steps

1. Download the `.pt` file manually.
2. Put it here:

```text
models/plate/license-plate-finetune-v1s.pt
```

3. Configure `.env`:

```env
ANPR_PLATE_MODEL=models/plate/license-plate-finetune-v1s.pt
ANPR_PLATE_CONFIDENCE=0.25
ANPR_PLATE_IMAGE_SIZE=640
```

4. Run:

```bash
python main.py check-config
python main.py run --source image --image samples/images/frame.jpg --dry-run
```

## 8.3 Rules

- Do not auto-download model during runtime.
- Do not require internet during runtime.
- Do not use hosted API for core detection.
- Keep `.pt` files ignored by Git.

---

## 9. Track Finalization Design

## 9.1 Why finalization is needed

A moving vehicle appears in multiple frames. OCR can produce different readings each time.

Instead of posting every OCR result, the system should collect candidates and post one final event.

## 9.2 Finalization triggers

```text
track disappeared
high-confidence early result
source ended
manual shutdown
```

## 9.3 Finalization process

```text
choose best plate by vote
freeze best evidence
save local evidence
append to events.jsonl
enqueue backend job
mark track finalized
```

## 9.4 Duplicate control

After a track finalizes, it should not post again.

Optional cooldown:

```env
ANPR_DUPLICATE_COOLDOWN_SECONDS=10
```

This prevents the same plate from being posted repeatedly if the same vehicle stays near the camera.

---

## 10. Evidence Design

## 10.1 Evidence saved per event

Each event should save:

```text
full frame
plate crop
annotated frame
```

## 10.2 Local evidence

Local evidence exists so the AI can upload or register images with backend.

It is not the final long-term storage unless metadata mode is used.

## 10.3 Backend evidence

Backend should be the final evidence source for dashboard display.

Recommended final flow:

```text
AI saves temp evidence
AI posts event
AI uploads evidence
Backend stores file
Backend creates image row
Frontend displays backend image URL
```

---

## 11. Runtime Flow Examples

## 11.1 RTSP live camera flow

```text
open RTSP
vehicle enters frame
vehicle detected as track 1
plate detected
OCR reads ABC1234
next frame OCR reads ABC1234 again
track disappears
finalize ABC1234
evidence saved
backend job queued
runtime continues reading camera
backend job posts event/images
frontend shows event
```

## 11.2 Sample video flow

```text
open sample video
process video frames at target FPS
track vehicle
vote plate text
video ends
flush active tracks
save events/evidence
print summary
```

## 11.3 Single image flow

```text
read one image
detect vehicle
detect plate
OCR plate
finalize immediately if valid
save evidence
print dry-run event
```

---

## 12. Output Files

Each run creates:

```text
runs/run_YYYYMMDD_HHMMSS/
├── events.jsonl
├── worker_summary.json
├── worker.log
└── evidence/
    ├── full/
    ├── plate/
    └── annotated/
```

## 12.1 `events.jsonl`

One JSON record per finalized event.

Example:

```json
{
  "event_id": "local-001",
  "track_id": 1,
  "plate_number": "ABC1234",
  "confidence": 0.92,
  "votes": 3,
  "vehicle_class": "car",
  "first_seen_at": "2026-06-21T10:00:01Z",
  "last_seen_at": "2026-06-21T10:00:05Z",
  "finalization_reason": "track_expired",
  "evidence": {
    "full": "runs/run_20260621_100000/evidence/full/event_001_full.jpg",
    "plate": "runs/run_20260621_100000/evidence/plate/event_001_plate.jpg",
    "annotated": "runs/run_20260621_100000/evidence/annotated/event_001_annotated.jpg"
  },
  "backend": {
    "queued": true,
    "posted": false,
    "event_id": null,
    "images_sent": 0,
    "error": null
  }
}
```

## 12.2 `worker_summary.json`

Example:

```json
{
  "status": "completed",
  "source_type": "video",
  "frames_read": 300,
  "frames_processed": 45,
  "events_finalized": 2,
  "backend_jobs_queued": 2,
  "backend_jobs_succeeded": 2,
  "backend_jobs_failed": 0,
  "average_vehicle_detect_ms": 100,
  "average_plate_detect_ms": 40,
  "average_ocr_ms": 150
}
```

---

## 13. Minimal Implementation Phases

## Phase 1 — Local Dry-Run Runtime

Goal:

```text
source → vehicle detect → plate detect → OCR → print final plate → save evidence
```

Required:

- Config loader.
- Source reader.
- Vehicle detector.
- Plate detector.
- OCR engine.
- Simple tracker.
- Vote buffer.
- Evidence saver.
- Dry-run output.

Acceptance:

```bash
python main.py run --source video --video samples/videos/test_vehicle.mp4 --dry-run
```

Produces:

```text
events.jsonl
evidence images
summary
```

---

## Phase 2 — Backend Event Posting

Goal:

```text
finalized event → backend ANPR event
```

Required:

- Backend client.
- Token cache.
- Async backend queue.
- Event posting.
- Retry on failure.

Acceptance:

```bash
python main.py run --source video --video samples/videos/test_vehicle.mp4
```

Backend receives ANPR events.

---

## Phase 3 — Backend Evidence Sending

Goal:

```text
finalized evidence → backend images
```

Required:

- Metadata mode or upload mode.
- Image records.
- Backend logs.
- Queue retry.

Acceptance:

Backend event detail shows images.

---

## Phase 4 — Realtime RTSP Deployment

Goal:

```text
RTSP camera → continuous ANPR events
```

Required:

- Stable RTSP loop.
- Reconnect handling.
- Frame skipping.
- Queue failure handling.
- Runtime logs.

Acceptance:

The system can run for long periods and create events reliably.

---

## Phase 5 — Optimization and Accuracy Tuning

Goal:

Improve speed and correctness.

Tasks:

- Tune model confidence.
- Tune OCR confidence.
- Tune track expiry.
- Add duplicate cooldown.
- Compare CPU/GPU performance.
- Improve plate normalization.
- Add optional ONNX model support.

---

## 14. Testing Plan

## 14.1 Unit tests

Test:

- Source detection.
- Plate text normalization.
- Vote selection.
- Track expiry.
- Backend queue retry.
- Token cache refresh.

## 14.2 Integration tests

Test:

- Image file to final event.
- Video file to final event.
- Dry-run evidence saving.
- Backend event posting with fake server.
- Backend queue retry.

## 14.3 Manual tests

Test:

```bash
python main.py check-config
python main.py run --source image --image samples/images/frame.jpg --dry-run
python main.py run --source video --video samples/videos/test_vehicle.mp4 --dry-run
python main.py run --source rtsp --max-seconds 30 --dry-run
python main.py flush-backend-queue
```

---

## 15. Performance Targets

Initial acceptable targets:

| Metric | Target |
|---|---:|
| Target FPS | 3–5 FPS |
| Event latency after vehicle disappears | 2–5 seconds |
| OCR calls per vehicle per second | As low as possible |
| Plate candidates per vehicle per frame | 1 |
| Backend posting | Async, should not block runtime |
| Model loading | Once at startup |

---

## 16. What Not To Build Initially

Do not build these in the first phase:

- Complex benchmark report generator.
- Full dashboard.
- WebSocket server in Python.
- Cloud upload.
- Roboflow hosted API runtime.
- Huge multi-stage folder pipeline.
- Too many preprocessing variants.
- Multiple OCR engines at once.
- Complicated tracker unless simple tracker fails.

---

## 17. Final New AI ANPR Module List

The clean new AI ANPR system should start with only these main modules:

| Module | File | Main role |
|---|---|---|
| CLI | `main.py` | User commands and entry point |
| Config | `config.py` | Load and validate `.env` settings |
| ANPR Runtime | `anpr.py` | Source reading, detection, tracking, OCR, voting, finalization, evidence, metrics |
| Backend Client/Queue | `backend.py` | Token cache, backend posting, image metadata/upload, async queue |

Supporting folders:

| Folder | Purpose |
|---|---|
| `models/vehicle/` | Vehicle YOLO model files or placeholders |
| `models/plate/` | Local plate YOLO `.pt` model, for example Hugging Face YOLOv11s |
| `samples/videos/` | Test videos like GitHub-style ANPR demos |
| `samples/images/` | Test images for single-frame validation |
| `runs/` | Local event/evidence outputs |
| `.cache/` | Token cache and backend queue files |

Potential future split only if needed:

| Future file | Split from | Reason |
|---|---|---|
| `source.py` | `anpr.py` | Source handling becomes too large |
| `detector.py` | `anpr.py` | YOLO wrappers become complex |
| `tracker.py` | `anpr.py` | Tracking logic becomes complex |
| `ocr.py` | `anpr.py` | OCR/preprocessing options grow |
| `plate_vote.py` | `anpr.py` | Voting/finalization grows |
| `evidence.py` | `anpr.py` | Evidence handling needs more modes |
| `backend_queue.py` | `backend.py` | Queue/retry logic grows |

Initial rule:

```text
Do not split early. Keep the first version understandable.
```

---

## 18. Summary

This AI ANPR module should be simple, fast, and practical.

The most important design choices are:

```text
Use sample video support from day one
Use RTSP continuous reading for real camera
Load models once
Keep track state in memory
OCR only selected plate crops
Finalize one event per vehicle
Save useful evidence only
Send backend work asynchronously
Cache backend token
Keep benchmark/reporting outside the runtime
```

---

## 24. References

The module can refer to these public resources while keeping the implementation independent:

- GitHub ANPR reference: `computervisioneng/automatic-number-plate-recognition-python-yolov8`
  - Useful for simple video-loop structure, YOLO vehicle detection, plate detection, tracking, OCR-on-crop, and compact output flow.
- Hugging Face plate model reference: `morsetechlab/yolov11-license-plate-detection`
  - Useful for local YOLOv11 license plate `.pt` model planning.
- Ultralytics YOLO documentation
  - Useful for loading local `.pt` model files and running prediction from Python.
- PaddleOCR documentation
  - Useful for OCR engine setup and plate crop text recognition.

Do not make runtime depend on internet access. Any model file should be downloaded manually and stored locally under `models/`.