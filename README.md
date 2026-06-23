# AI ANPR v1

**Current milestone:** M15 — Performance and Accuracy Tuning Architecture

M15 tunes runtime FPS, OCR efficiency, event latency metrics, backend list performance, and frontend polling backoff while preserving M12–M14 behavior.

Full M15 architecture: [docs/m15-performance-and-accuracy-tuning-architecture.md](docs/m15-performance-and-accuracy-tuning-architecture.md)

M14 adds regression coverage across the AI runtime, Laravel ANPR APIs, React ANPR UI, and manual end-to-end flows.

Full M14 architecture: [docs/m14-testing-architecture.md](docs/m14-testing-architecture.md)

M13 keeps the AI event payload unchanged. Laravel links each ANPR event to an existing vehicle record or auto-creates one when the plate is unknown.

Full M13 architecture: [docs/m13-linked-vehicle-record-architecture.md](docs/m13-linked-vehicle-record-architecture.md)

M12 connects the M11 RTSP runtime, Laravel ANPR APIs, and React ANPR monitoring page so new detections appear automatically in the frontend. This is live event monitoring, not video livestreaming.

Full M12 architecture: [docs/m12-live-anpr-monitoring-architecture.md](docs/m12-live-anpr-monitoring-architecture.md)

Python ANPR runtime for vehicle and license plate processing.

Frontend monitoring is implemented in the React frontend under `src/feature/anpr-monitoring/`.

Full M11 architecture: [docs/m11-realtime-rtsp-runtime-architecture.md](docs/m11-realtime-rtsp-runtime-architecture.md)

## Environment Setup

Recommended Python version:

```text
Python 3.11 or 3.12
```

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Setup

Place local YOLO `.pt` files before running detection. Configure models, OCR, tracking, events, backend, and RTSP in `.env`:

```env
ANPR_VEHICLE_MODEL=models/vehicle/yolo11s.pt
ANPR_PLATE_MODEL=models/plate/license-plate-finetune-v1s.pt
ANPR_BACKEND_ENABLED=false
ANPR_BACKEND_BASE_URL=http://localhost:8000/api
ANPR_BACKEND_CAMERA_ID=
ANPR_EVIDENCE_MODE=upload
ANPR_EVIDENCE_RETENTION_DAYS=0
ANPR_RTSP_URL=rtsp://user:password@camera-ip:554/stream1
```

**Upload mode** is the recommended backend/cloud evidence path. The AI runtime uploads evidence files to Laravel, and Laravel stores them under `storage/app/anpr`.

**Metadata mode** is retained for local development only and requires Laravel `ANPR_IMAGE_ROOTS` to resolve AI-local `runs/` paths.

## CLI

```bash
python main.py check-config

python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict
python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --strict
python main.py run --source image --image samples/images/photo_6177158287829176212_w.jpg --strict
python main.py run --source video --video samples/videos/document_6177158287369184218.mp4 --dry-run --strict
python main.py run --source video --video samples/videos/document_6177158287369184218.mp4 --strict
python main.py run --source rtsp --max-seconds 30 --dry-run --strict
python main.py run --source rtsp --max-seconds 30 --strict
python main.py flush-backend-queue
```

`--dry-run` has no backend side effects. Non-dry-run enqueues and flushes backend jobs. RTSP runs flush the queue periodically and again at shutdown.

## Output

Each run creates `runs/run_YYYYMMDD_HHMMSS/` with `worker.log`, `worker_summary.json`, `events.jsonl`, `evidence/`, and (after backend flush) `backend_results.json`. Queue state: `.cache/backend_queue.jsonl`.
