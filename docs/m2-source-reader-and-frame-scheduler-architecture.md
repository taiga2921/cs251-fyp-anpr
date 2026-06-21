# M2 — Source Reader and Frame Scheduler Architecture

## Milestone Summary

Milestone 2 (M2) adds a **unified source reader** and **target-FPS frame scheduler** to the AI ANPR runtime. Dry runs open real sources, read frames into `FramePacket` objects, apply scheduling, and record accurate metrics. M2 does **not** implement model loading, detection, OCR, tracking, evidence, or backend integration.

## Objective

Provide a consistent frame input pipeline for RTSP, video, image, and webcam sources so later milestones can attach model inference without redesigning source handling.

## Scope

### In Scope

- `FramePacket` dataclass contract
- Source opening for `rtsp`, `video`, `image`, and `webcam`
- `open_source()`, `iter_frames()`, and `should_process_frame()` in `anpr.py`
- Target-FPS scheduling via `ANPR_TARGET_FPS`
- Accurate `frames_read`, `frames_processed`, `source_completed`, and `stop_reason` metrics
- RTSP URL configuration via `.env` / `ANPR_RTSP_URL` (not CLI)
- `--max-seconds` support for RTSP and webcam
- M2 extensions to `worker_summary.json` and `worker.log`
- Dependencies: `opencv-python`, `numpy`

### Out of Scope

- Model loading (begins in M3)
- Vehicle and license plate detection
- OCR and tracking
- Evidence image generation
- Backend posting, token cache, or queue persistence
- Frontend integration
- RTSP reconnect logic
- Heavy AI dependencies (Ultralytics, PyTorch, PaddleOCR, etc.)

## Deliverables

| Deliverable | Description |
| ----------- | ----------- |
| Source reader | OpenCV-based reading for all four source types |
| Frame scheduler | FPS-based skipping; assumed FPS for unknown video; wall-clock for RTSP/webcam |
| `FramePacket` | Unified frame contract |
| Dry-run runtime | `run --dry-run` reads real sources and writes metrics |
| Output contract | Extended `worker_summary.json` with M2 fields |
| Security | RTSP credentials configured in `.env`, not CLI |

## File-by-File Responsibilities

### main.py

- Thin CLI; rejects `--source-path rtsp://...` before validation
- Delegates runtime to `ANPRProcessor.run_dry_run()`

### config.py

- Typed configuration and validation (from M1)
- `ANPR_RTSP_URL` required for RTSP source
- `check_foundation_config()` always runs writability check before returning

### anpr.py

- Source reader, scheduler, metrics, and dry-run output
- No `source.py` module

### backend.py

- M2 placeholder; no networking

## Source Reader Architecture

```text
Config (validated)
        |
        v
  open_source()
        |
        +-- image  -> cv2.imread
        +-- video  -> cv2.VideoCapture(path)
        +-- rtsp   -> cv2.VideoCapture(ANPR_RTSP_URL)
        +-- webcam -> cv2.VideoCapture(index)
        |
        v
   iter_frames() -> FramePacket
        |
        v
 should_process_frame()
        |
        v
   worker_summary.json
```

## RTSP URL Configuration

Configure RTSP in `.env` or environment variables:

```env
ANPR_SOURCE=rtsp
ANPR_RTSP_URL=rtsp://user:password@camera-ip:554/stream1
```

Run:

```bash
python main.py run --source rtsp --dry-run
python main.py run --source rtsp --max-seconds 30 --dry-run
```

**Do not pass RTSP URLs on the CLI.** Credentials in shell history, process listings, and documentation are a security risk. `--source-path rtsp://...` is **rejected** with a clear error.

`--source-path` remains for **local video and image files** only.

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

## Frame Scheduler Behavior

| Metric | Definition |
| ------ | ---------- |
| `frames_read` | Every frame successfully read |
| `frames_processed` | Frames accepted by the scheduler |

- **Image:** always process the single frame
- **Video with known FPS:** `frame_skip_interval = max(1, round(source_fps / target_fps))`
- **Video with unknown FPS:** assume `30.0` FPS for deterministic skipping; record `assumed_source_fps` in summary
- **RTSP / webcam without FPS:** wall-clock fallback at `target_fps`

## Source Completion and `stop_reason`

`source_completed` is set after the frame iterator ends normally. Zero-frame sources still complete with an explicit warning.

| `stop_reason` | When used |
| ------------- | --------- |
| `image_complete` | Single image processed |
| `video_end` | Video file reached natural end |
| `max_seconds_reached` | RTSP/webcam stopped by `--max-seconds` |
| `stream_read_failed` | RTSP/webcam stream ended after at least one frame |
| `zero_frames` | Source opened but returned no frames |
| `runtime_error` | Open/read failure; `status` is `failed` |
| `unknown` | Fallback |

Zero-frame example summary fields:

```json
{
  "source_opened": true,
  "source_completed": true,
  "frames_read": 0,
  "frames_processed": 0,
  "stop_reason": "zero_frames",
  "warnings": ["Source opened but returned zero frames"]
}
```

## Metrics and Summary Contract

`worker_summary.json` preserves M0/M1 fields and adds M2 metrics. **`max_seconds` is always present** (`null` when unset).

```json
{
  "status": "completed",
  "milestone": "M2",
  "source_type": "video",
  "source_path": "samples/videos/test_vehicle.mp4",
  "frames_read": 90,
  "frames_processed": 9,
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
  "stop_reason": "video_end",
  "max_seconds": null,
  "duration_seconds": 0.012
}
```

Unknown-FPS video may include:

```json
"source_fps": null,
"assumed_source_fps": 30.0,
"frame_skip_interval": 10
```

## CLI Behavior

```bash
python main.py check-config
python main.py run --source image --image samples/images/frame.jpg --dry-run
python main.py run --source video --video samples/videos/test_vehicle.mp4 --dry-run
python main.py run --source-path samples/videos/test_vehicle.mp4 --dry-run
python main.py run --source rtsp --dry-run
python main.py run --source rtsp --max-seconds 30 --dry-run
python main.py run --source webcam --camera-index 0 --dry-run --max-seconds 2
python main.py flush-backend-queue
```

Rejected:

```bash
python main.py run --source-path rtsp://user:pass@camera-ip:554/stream1 --dry-run
```

## Output Files

```text
runs/run_YYYYMMDD_HHMMSS/
├── worker.log
├── worker_summary.json
└── events.jsonl
```

`events.jsonl` remains empty in M2.

## Passing Criteria

1. RTSP URLs configured via `ANPR_RTSP_URL`, not CLI
2. `--source-path` works for local video/image only
3. `source_completed` reliable for zero-frame sources
4. `stop_reason` present in every summary
5. Unknown-FPS video uses assumed FPS, not wall-clock under-processing
6. `max_seconds` always in summary
7. Foundation writability check always runs
8. No M3 features implemented prematurely

## Verification Checklist

- [ ] `python -m py_compile main.py config.py anpr.py backend.py`
- [ ] `python main.py check-config`
- [ ] `python main.py run --source image --image samples/images/frame.jpg --dry-run`
- [ ] `python main.py run --source video --video samples/videos/test_vehicle.mp4 --dry-run`
- [ ] `python main.py run --source rtsp --max-seconds 2 --dry-run` (requires valid `ANPR_RTSP_URL`)
- [ ] `python main.py run --source webcam --camera-index 0 --dry-run --max-seconds 2` (requires webcam)
- [ ] `python main.py run --source-path rtsp://... --dry-run` → rejected with clear error
- [ ] `python main.py flush-backend-queue`
- [ ] Confirm `stop_reason` and `max_seconds` in summary

## Known Limitations

- No inference, evidence, or backend I/O
- No RTSP reconnect
- Webcam/RTSP depend on local hardware/network
- Sample media may be git-ignored; place test files locally before running sample commands
- OpenCV may emit internal warnings to stderr for unavailable devices

## Next Milestone Handoff Notes

M3 should load models after successful source open and run detection on scheduler-accepted `FramePacket` frames. Preserve M2 summary fields and the RTSP config-first security rule.
