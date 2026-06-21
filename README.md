# AI ANPR v1



**Current milestone:** M3 — Model Loading and Detector Architecture



Python ANPR runtime for vehicle and license plate processing.



## Setup



```bash

pip install -r requirements.txt

```



Place local YOLO `.pt` files before running detection. Model files are not committed to Git.



Configure models in `.env`:



```env

ANPR_VEHICLE_MODEL=models/vehicle/yolo11s.pt

ANPR_PLATE_MODEL=models/plate/license-plate-finetune-v1s.pt

ANPR_DEVICE=cpu

```



Place the plate model manually under `models/plate/`. Use `ANPR_DEVICE=cuda` only when CUDA is available.



Demo sample media is included in the repository under `samples/images/` and `samples/videos/`.



Configure RTSP streams in `.env` using `ANPR_RTSP_URL`. Do not put RTSP credentials directly in CLI commands.



## CLI



```bash

python main.py check-config



python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict

python main.py run --source image --image samples/images/photo_6177158287829176212_w.jpg --dry-run --strict

python main.py run --source video --video samples/videos/document_6177158287369184218.mp4 --dry-run --strict

python main.py run --source rtsp --dry-run --strict

python main.py run --source webcam --camera-index 0 --dry-run --max-seconds 2 --strict



python main.py flush-backend-queue

```



`run --dry-run` opens the source, schedules frames, loads local YOLO models once, and runs vehicle/plate detection. OCR, tracking, final events, evidence, and backend posting are not implemented yet.



## Output



Each run creates `runs/run_YYYYMMDD_HHMMSS/` with `worker.log`, `worker_summary.json`, and `events.jsonl`.



## Documentation



Full M3 architecture: [docs/m3-model-loading-and-detector-architecture.md](docs/m3-model-loading-and-detector-architecture.md)

