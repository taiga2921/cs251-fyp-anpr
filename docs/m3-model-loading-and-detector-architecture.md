# M3 — Model Loading and Detector Architecture

## Milestone Summary

Milestone 3 (M3) adds **YOLO model loading** and **normalized vehicle/plate detection** to the AI ANPR runtime. Models load once per run. Detection runs only on scheduler-accepted frames. M3 preserves all M2 source reader, scheduler, security, and summary behavior.

M3 does **not** implement OCR, tracking, final events, evidence saving, or backend posting.

## Objective

Load local YOLO vehicle and plate models once per runtime and expose normalized `detect_vehicles()` and `detect_plates()` wrappers for later OCR and tracking milestones.

## Scope

### In Scope

- Vehicle YOLO model loading via Ultralytics
- Plate YOLO model loading via Ultralytics
- `ANPR_DEVICE` support (`cpu` / `cuda`)
- `Detection` dataclass contract
- `detect_vehicles()` and `detect_plates()` in `anpr.py`
- Detection timing and counter metrics in `worker_summary.json`
- Detection integrated into `run --dry-run`
- Dependency: `ultralytics`

### Out of Scope

- OCR and plate text normalization (M4)
- Tracking and vote buffering
- Final ANPR event generation
- Evidence image saving
- Backend posting
- RTSP reconnect logic
- Model auto-download at runtime
- Internet dependency at runtime

## Deliverables

| Deliverable | Description |
| ----------- | ----------- |
| `load_models()` | Load vehicle and plate YOLO weights once per run |
| `Detection` | Normalized bbox/confidence/class contract |
| `detect_vehicles()` | COCO vehicle-class filtering when names available |
| `detect_plates()` | Full-frame or vehicle-crop detection with coordinate translation |
| Summary metrics | Detection calls, counts, average milliseconds |
| Documentation | Minimal README + this document |

## File-by-File Responsibilities

### main.py

- Thin CLI; M3 descriptions and detection metric output
- RTSP `--source-path` rejection preserved

### config.py

- Existing model/device/conf keys unchanged
- Strict validation requires model files on disk

### anpr.py

- Source reader, scheduler (M2), model loading, detection (M3)
- All logic in one file; no `detector.py`

### backend.py

- Placeholder; no networking

## Architecture Flow

```text
Config validation
        |
        v
  open_source()
        |
        v
  load_models()          ← once per run
        |
        v
   iter_frames()
        |
        v
 should_process_frame()
        |
        v
 detect_vehicles()
        |
        v
 detect_plates() per vehicle crop
        |
        v
 worker_summary.json
```

## Model Loading Behavior

- Models load **after** source open and **before** frame iteration
- Vehicle and plate models load **once**; never per frame
- Uses Ultralytics `YOLO(path)` with local `.pt` files only
- Missing files raise a clear `ModelLoadError`
- On failure, source is closed and `worker_summary.json` records `status: failed`
- No auto-download; no internet required at runtime

## Device Selection Behavior

| `ANPR_DEVICE` | Behavior |
| ------------- | -------- |
| `cpu` | Run inference on CPU |
| `cuda` | Require CUDA availability; fail clearly if unavailable |

## Detection Result Contract

```python
@dataclass
class Detection:
    bbox: tuple[int, int, int, int]   # (x1, y1, x2, y2) in full-frame pixels
    confidence: float
    class_id: int | None = None
    class_name: str | None = None
```

- Boxes clipped to image bounds
- Invalid zero-area boxes skipped

## Vehicle Detection Wrapper

- Model: `ANPR_VEHICLE_MODEL`
- Confidence: `ANPR_VEHICLE_CONF`
- Device: `ANPR_DEVICE`
- Filters COCO vehicle classes when names available: `car`, `motorcycle`, `bus`, `truck`
- If class names unavailable, returns detections conservatively
- Records call count, total detections, elapsed milliseconds

## Plate Detection Wrapper

- Model: `ANPR_PLATE_MODEL`
- Confidence: `ANPR_PLATE_CONF`
- With `vehicle_detection`: crops vehicle region, detects plates, translates boxes to full-frame coordinates
- Without vehicle: runs on full frame
- Records call count, total detections, elapsed milliseconds
- **No OCR** on plate crops in M3

## Runtime Summary Contract

Preserves all M2 fields and adds:

```json
{
  "milestone": "M3",
  "models_loaded": true,
  "vehicle_model": "yolo11s.pt",
  "plate_model": "models/plate/license-plate-finetune-v1s.pt",
  "device": "cpu",
  "vehicle_detection_calls": 1,
  "plate_detection_calls": 2,
  "vehicle_detections": 1,
  "plate_detections": 1,
  "average_vehicle_detect_ms": 120.5,
  "average_plate_detect_ms": 45.2,
  "events_finalized": 0
}
```

M2 fields preserved: `stop_reason`, `max_seconds` (always present), `source_fps`, `assumed_source_fps`, etc.

`events.jsonl` remains **empty** in M3.

## Logging Behavior

`worker.log` records M3 startup, masked source label, model loading, device, frame counts, detection calls/counts, average detection times, stop reason, and completion status. No per-frame spam.

## CLI Behavior

```bash
python main.py check-config
python main.py check-config --strict
python main.py run --source image --image samples/images/frame.jpg --dry-run --strict
python main.py run --source video --video samples/videos/test_vehicle.mp4 --dry-run --strict
python main.py run --source rtsp --max-seconds 2 --dry-run --strict
python main.py run --source webcam --camera-index 0 --dry-run --max-seconds 2 --strict
python main.py flush-backend-queue
```

RTSP via CLI `--source-path` remains **rejected**.

`run` without `--dry-run` remains unsupported.

## Model File Setup

1. Place vehicle weights at the path configured by `ANPR_VEHICLE_MODEL` (default `yolo11s.pt`).
2. Place plate weights at `models/plate/license-plate-finetune-v1s.pt` (or configured path).
3. `.pt` files are git-ignored; download manually before running.
4. Run `python main.py check-config --strict` to verify files exist.

## Passing Criteria

1. Models load once per run
2. Configured device used; CUDA fails clearly when unavailable
3. Normalized `Detection` results from both wrappers
4. Plate boxes translated from vehicle crops to full frame
5. Detection only on scheduler-accepted frames
6. Detection metrics in summary
7. M2 behavior preserved
8. `events.jsonl` empty
9. README minimal; M3 docs present

## Verification Checklist

- [ ] `pip install -r requirements.txt`
- [ ] `python -m py_compile main.py config.py anpr.py backend.py`
- [ ] `python main.py check-config`
- [ ] `python main.py check-config --strict` (requires both model files)
- [ ] `python main.py run --source image --image samples/images/frame.jpg --dry-run --strict`
- [ ] `python main.py run --source-path rtsp://... --dry-run` → rejected
- [ ] Confirm detection metrics in `worker_summary.json`
- [ ] Confirm `events.jsonl` is empty

## Known Limitations

- No OCR, tracking, events, evidence, or backend I/O
- No model auto-download
- Both model files must exist locally for `--strict` dry runs
- First Ultralytics import may be slow; not a benchmark subsystem
- Webcam/RTSP depend on local hardware/network

## Next Milestone Handoff Notes (M4)

M4 should add OCR on plate crops from `detect_plates()` results. Preserve:

- `FramePacket` and scheduler behavior
- `Detection` contract
- Model load-once pattern
- M2/M3 summary field compatibility

Do not reload models per frame. Run OCR only on scheduler-accepted frames and detected plate regions.
