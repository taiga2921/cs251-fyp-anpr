# AI ANPR v1

**Current milestone:** M10 — Frontend ANPR Feature Architecture

Python ANPR runtime for vehicle and license plate processing.

Frontend monitoring is implemented in the React frontend under `src/feature/anpr-monitoring/`.

Full M10 architecture: [docs/m10-frontend-anpr-feature-architecture.md](docs/m10-frontend-anpr-feature-architecture.md)

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
```

## Setup

Place local YOLO `.pt` files before running detection. Configure models, OCR, tracking, events, and backend in `.env`:

```env
ANPR_VEHICLE_MODEL=models/vehicle/yolo11s.pt
ANPR_PLATE_MODEL=models/plate/license-plate-finetune-v1s.pt
ANPR_BACKEND_ENABLED=false
ANPR_BACKEND_BASE_URL=http://localhost:8000/api
ANPR_BACKEND_CAMERA_ID=
ANPR_EVIDENCE_MODE=metadata
ANPR_EVIDENCE_RETENTION_DAYS=0
```

**Metadata mode** is the supported M9 evidence path. **Upload mode** is design-only until Laravel adds a multipart upload endpoint. When using metadata mode, configure Laravel to resolve evidence paths (see `check-config` warning for `ANPR_IMAGE_ROOTS`).

## CLI

```bash
python main.py check-config

python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict
python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --strict
python main.py flush-backend-queue
```

`--dry-run` has no backend side effects. Non-dry-run enqueues and flushes backend jobs after finite image/video sources.

## Output

Each run creates `runs/run_YYYYMMDD_HHMMSS/` with `worker.log`, `worker_summary.json`, `events.jsonl`, `evidence/`, and (after backend flush) `backend_results.json`. Queue state: `.cache/backend_queue.jsonl`.

## Documentation

Full M10 architecture: [docs/m10-frontend-anpr-feature-architecture.md](docs/m10-frontend-anpr-feature-architecture.md)

M9 evidence delivery: [docs/m9-evidence-delivery-architecture.md](docs/m9-evidence-delivery-architecture.md)
