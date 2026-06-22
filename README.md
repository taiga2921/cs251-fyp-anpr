# AI ANPR v1

**Current milestone:** M8 — Backend ANPR Data Architecture Alignment

Python ANPR runtime for vehicle and license plate processing.

## Environment Setup

Recommended Python version:

```text
Python 3.11 or 3.12
```

Create and activate a virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

Use a clean virtual environment and avoid unsupported Python/package combinations (for example Python 3.13 with incompatible wheels).

## Setup

Place local YOLO `.pt` files before running detection. Model files are not committed to Git.

Configure models, OCR, tracking, events, and backend in `.env`:

```env
ANPR_VEHICLE_MODEL=models/vehicle/yolo11s.pt
ANPR_PLATE_MODEL=models/plate/license-plate-finetune-v1s.pt
ANPR_BACKEND_ENABLED=false
ANPR_BACKEND_BASE_URL=http://localhost:8000/api
ANPR_BACKEND_CAMERA_ID=
ANPR_EVIDENCE_MODE=metadata
ANPR_DUPLICATE_COOLDOWN_SECONDS=10
```

Demo sample media is included under `samples/images/` and `samples/videos/`. Configure RTSP in `.env` via `ANPR_RTSP_URL` (not on the CLI).

## CLI

```bash
python main.py check-config

python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict
python main.py run --source video --video samples/videos/document_6177158287369184218.mp4 --dry-run --strict

python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --strict
python main.py flush-backend-queue
```

`--dry-run` performs local event/evidence output only (no backend side effects). Non-dry-run requires `ANPR_BACKEND_ENABLED=true`, enqueues backend jobs, and flushes the queue after finite image/video sources. M8 aligns posted ANPR events, image metadata, and event logs with the Laravel backend.

## Output

Each run creates `runs/run_YYYYMMDD_HHMMSS/` with `worker.log`, `worker_summary.json`, `events.jsonl`, `evidence/`, and (after backend flush) `backend_results.json`. Backend queue state is stored in `.cache/backend_queue.jsonl`.

## Documentation

Full M8 architecture: [docs/m8-backend-anpr-data-architecture-alignment.md](docs/m8-backend-anpr-data-architecture-alignment.md)
