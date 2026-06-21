# AI ANPR v1

**Current milestone:** M4 — OCR and Plate Normalization Architecture

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
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Verify PyTorch and Ultralytics:

```powershell
python -c "import torch; print(torch.__version__); print(torch.rand(1))"
python -c "from ultralytics import YOLO; print('ultralytics ok')"
```

If CPU-only PyTorch on Windows fails during normal install, use the official CPU wheel first, then install the remaining dependencies:

```powershell
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

Use a clean virtual environment and avoid unsupported Python/package combinations (for example Python 3.13 with incompatible wheels).

## Setup

Place local YOLO `.pt` files before running detection. Model files are not committed to Git.

M4 uses **PaddleOCR 2.x legacy API** (`paddleocr<3` in `requirements.txt`).

Configure models and OCR in `.env`:

```env
ANPR_VEHICLE_MODEL=models/vehicle/yolo11s.pt
ANPR_PLATE_MODEL=models/plate/license-plate-finetune-v1s.pt
ANPR_DEVICE=cpu
ANPR_OCR_ENGINE=paddleocr
ANPR_MIN_OCR_CONFIDENCE=0.30
```

Demo sample media is included under `samples/images/` and `samples/videos/`. Configure RTSP in `.env` via `ANPR_RTSP_URL` (not on the CLI).

## CLI

```bash
python main.py check-config

python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict
python main.py run --source video --video samples/videos/document_6177158287369184218.mp4 --dry-run --strict
python main.py run --source rtsp --dry-run --strict

python main.py flush-backend-queue
```

`run --dry-run` opens the source, schedules frames, loads YOLO models once, runs vehicle/plate detection, and performs OCR with normalization and validation on plate crops. Valid `PlateCandidate` objects are kept in memory for M5 handoff. Tracking, final events, evidence saving, and backend posting are not implemented yet. `events.jsonl` remains empty in M4.

## Output

Each run creates `runs/run_YYYYMMDD_HHMMSS/` with `worker.log`, `worker_summary.json`, and an empty `events.jsonl`.

## Documentation

Full M4 architecture: [docs/m4-ocr-and-plate-normalization-architecture.md](docs/m4-ocr-and-plate-normalization-architecture.md)
