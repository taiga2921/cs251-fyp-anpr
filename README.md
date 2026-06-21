# AI ANPR v1

**Current milestone:** M2 — Source Reader and Frame Scheduler Architecture

Python ANPR runtime for vehicle and license plate processing.

## Setup

```bash
pip install -r requirements.txt
```

Place your own test image/video under `samples/images/` or `samples/videos/` before running the sample image/video commands.

Configure RTSP streams in `.env` using `ANPR_RTSP_URL`. Do not put RTSP credentials directly in CLI commands.

## CLI

```bash
python main.py check-config

python main.py run --source image --image samples/images/frame.jpg --dry-run
python main.py run --source video --video samples/videos/test_vehicle.mp4 --dry-run
python main.py run --source rtsp --dry-run
python main.py run --source rtsp --max-seconds 30 --dry-run
python main.py run --source webcam --camera-index 0 --dry-run

python main.py flush-backend-queue
```

`run --dry-run` opens the configured source, reads frames, and applies target-FPS scheduling. Detection and OCR are not implemented yet.

## Output

Each run creates `runs/run_YYYYMMDD_HHMMSS/` with `worker.log`, `worker_summary.json`, and `events.jsonl`.

## Documentation

Full M2 architecture: [docs/m2-source-reader-and-frame-scheduler-architecture.md](docs/m2-source-reader-and-frame-scheduler-architecture.md)
