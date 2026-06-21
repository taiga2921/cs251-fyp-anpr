# M2 — Source Reader and Frame Scheduler Architecture

## Milestone Summary

Milestone 2 (M2) adds a **unified source reader** and **target-FPS frame scheduler** to the AI ANPR runtime. Dry runs now open real sources, read frames into `FramePacket` objects, apply scheduling, and record accurate metrics. M2 does **not** implement detection, OCR, tracking, evidence, or backend integration.

## Objective

Provide a consistent frame input pipeline for RTSP, video, image, and webcam sources so later milestones can attach model inference without redesigning source handling.

## Scope

### In Scope

- `FramePacket` dataclass contract
- Source opening for `rtsp`, `video`, `image`, and `webcam`
- `open_source()`, `iter_frames()`, and `should_process_frame()` in `anpr.py`
- Target-FPS scheduling via `ANPR_TARGET_FPS`
- Accurate `frames_read` and `frames_processed` metrics
- Source completion detection for video and bounded stream reads
- `--max-seconds` support for RTSP and webcam
- M2 extensions to `worker_summary.json` and `worker.log`
- Dependencies: `opencv-python`, `numpy`
- Minimal README update and this document

### Out of Scope

- Model loading
- Vehicle detection
- License plate detection
- OCR
- Tracking and event finalization
- Evidence image generation
- Backend posting, token cache, or queue persistence
- Frontend integration
- RTSP reconnect logic
- Video PTS-based timestamping
- Heavy AI dependencies (Ultralytics, PyTorch, PaddleOCR, etc.)

## Deliverables

| Deliverable | Description |
| ----------- | ----------- |
| Source reader | OpenCV-based reading for all four source types |
| Frame scheduler | FPS-based frame skipping with wall-clock fallback |
| `FramePacket` | Unified frame contract for downstream processing |
| Dry-run runtime | `run --dry-run` reads real sources and writes metrics |
| Output contract | Extended `worker_summary.json` with M2 fields |
| Documentation | Minimal README + this document |

## File-by-File Responsibilities

### main.py

- Thin CLI unchanged in structure
- Calls `ANPRProcessor.run_dry_run()` after M1 validation
- Prints frame metrics on success
- Returns non-zero exit code when runtime fails after run directory creation

### config.py

- Unchanged M1 validation and CLI override behavior
- `target_fps`, `max_seconds`, and source fields consumed by M2 runtime

### anpr.py

- `FramePacket`, `SourceRuntimeError`, `RuntimeMetrics`
- `ANPRProcessor.open_source()`, `close_source()`, `iter_frames()`, `should_process_frame()`
- `run_dry_run()` orchestrates source reading, scheduling, and output writing
- All source logic contained in this file (no `source.py`)

### backend.py

- Unchanged M1 placeholder; no networking in M2

### Supporting Files

| File | Change |
| ---- | ------ |
| `requirements.txt` | Added `opencv-python` and `numpy` |
| `README.md` | Minimal M2 milestone update |

## Source Reader Architecture

```text
Config (validated by M1)
        |
        v
  open_source()
        |
        +-- image  -> cv2.imread (in iter_frames)
        +-- video  -> cv2.VideoCapture(path)
        +-- rtsp   -> cv2.VideoCapture(url)
        +-- webcam -> cv2.VideoCapture(index)
        |
        v
   iter_frames() -> FramePacket stream
        |
        v
 should_process_frame()  (target FPS scheduler)
        |
        v
   metrics + worker_summary.json
```

Sources are opened once per run. `VideoCapture` resources are released in `close_source()`.

## FramePacket Contract

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

| Field | Description |
| ----- | ----------- |
| `frame_index` | Zero-based index of frames read from the source |
| `timestamp` | Wall-clock UNIX timestamp (`float`) |
| `image` | BGR `numpy` array from OpenCV |
| `source_type` | `rtsp`, `video`, `image`, or `webcam` |
| `source_path` | URL, file path, or camera index as string |
| `is_last` | `True` on the final frame when detectable |

## Frame Scheduler Behavior

Scheduling uses `ANPR_TARGET_FPS` from configuration.

| Metric | Definition |
| ------ | ---------- |
| `frames_read` | Every frame successfully read from the source |
| `frames_processed` | Frames accepted by the scheduler |

### Image source

The single frame is always processed (`frames_read = frames_processed = 1`).

### Video / RTSP / Webcam

When source FPS is available from `cv2.CAP_PROP_FPS`:

```text
frame_skip_interval = max(1, round(source_fps / target_fps))
process when frame_index % frame_skip_interval == 0
```

Example: 30 FPS source with `target_fps = 3` yields interval `10` (~every 10th frame).

When source FPS is unavailable or invalid, the scheduler falls back to **wall-clock** spacing using `1 / target_fps` seconds between processed frames.

Frame skipping is preferred over sleeping for file-based video processing.

## Source-End Behavior

| Source | Completion behavior |
| ------ | ------------------- |
| **Image** | One frame yielded with `is_last=True` |
| **Video** | Reads until `capture.read()` fails; last frame marked `is_last=True` |
| **RTSP** | Reads until stream stops, `--max-seconds` elapses, or read fails |
| **Webcam** | Reads until `--max-seconds` elapses or read fails |

RTSP reconnect is **not** implemented in M2.

## Metrics and Summary Contract

`worker_summary.json` preserves all M1 fields and adds M2 metrics:

```json
{
  "status": "completed",
  "milestone": "M2",
  "source_type": "video",
  "source_path": "samples/videos/test_vehicle.mp4",
  "frames_read": 300,
  "frames_processed": 30,
  "events_finalized": 0,
  "backend_enabled": false,
  "validation_mode": "standard",
  "warnings": [],
  "errors": [],
  "run_dir": "runs/run_YYYYMMDD_HHMMSS",
  "target_fps": 3.0,
  "source_fps": 30.0,
  "frame_skip_interval": 10,
  "source_opened": true,
  "source_completed": true,
  "max_seconds": null,
  "duration_seconds": 0.5
}
```

On runtime failure after run directory creation, `status` is `"failed"` and `errors` contains the operator-facing message.

## CLI Behavior

### `python main.py run --dry-run`

1. Validates configuration (M1 rules)
2. Creates run directory
3. Opens configured source
4. Reads frames and applies scheduler
5. Writes `worker.log`, `worker_summary.json`, and empty `events.jsonl`

Supported examples:

```bash
python main.py run --source image --image samples/images/frame.jpg --dry-run
python main.py run --source video --video samples/videos/test_vehicle.mp4 --dry-run
python main.py run --source webcam --camera-index 0 --dry-run
python main.py run --source-path samples/videos/test_vehicle.mp4 --dry-run
python main.py run --source-path rtsp://user:pass@camera-ip:554/stream1 --dry-run
python main.py run --source rtsp --max-seconds 30 --dry-run
```

`run` without `--dry-run` remains unsupported (exit code `2`).

### Other commands

`check-config`, `check-config --strict`, and `flush-backend-queue` behave as in M1.

## Output Files

```text
runs/run_YYYYMMDD_HHMMSS/
├── worker.log
├── worker_summary.json
└── events.jsonl
```

- `events.jsonl` remains **empty** in M2 (no finalized events)
- No `evidence/` folder in M2

## Passing Criteria

1. All four Python runtime modules compile
2. No unnecessary runtime modules created
3. `run --dry-run` opens real sources
4. RTSP, video, image, and webcam source types supported
5. All read frames use `FramePacket`
6. `ANPR_TARGET_FPS` scheduling applied
7. `frames_read` and `frames_processed` are accurate
8. Image yields exactly one last frame
9. Video detects completion
10. Stream/webcam stop handled gracefully
11. `worker_summary.json` includes M1 + M2 fields
12. `events.jsonl` remains empty
13. README minimal; M2 docs present
14. No premature detection/OCR/tracking/backend work

## Verification Checklist

- [ ] `pip install -r requirements.txt`
- [ ] `python -m py_compile main.py config.py anpr.py backend.py`
- [ ] `python main.py check-config`
- [ ] `python main.py run --source image --image samples/images/frame.jpg --dry-run`
- [ ] `python main.py run --source video --video samples/videos/test_vehicle.mp4 --dry-run`
- [ ] `python main.py run --source webcam --camera-index 0 --dry-run` (requires webcam)
- [ ] `python main.py run --source-path rtsp://... --dry-run` (requires reachable RTSP)
- [ ] `python main.py flush-backend-queue`
- [ ] Confirm `frames_read` / `frames_processed` in summary
- [ ] Confirm `events.jsonl` is empty

## Known Limitations

- **No inference** — frames are read and counted only
- **No RTSP reconnect** — stream failure ends the run
- **Wall-clock timestamps** — video PTS not used
- **Invalid/empty video files** — may open but yield zero frames
- **Webcam/RTSP tests** — depend on local hardware/network; failures are expected when unavailable
- **Placeholder sample video** — may not decode frames if not a valid video container

## Next Milestone Handoff Notes

M3+ should build on `FramePacket` and `should_process_frame()` without changing the CLI contract:

1. Load models after successful source open (when that milestone begins)
2. Run vehicle/plate detection only on scheduler-accepted frames
3. Populate `events.jsonl` when event finalization is implemented
4. Extend `worker_summary.json` with detection/OCR timing metrics
5. Consider extracting `source.py` only if `anpr.py` grows too large

Preserve backward compatibility for M0/M1/M2 summary fields.
