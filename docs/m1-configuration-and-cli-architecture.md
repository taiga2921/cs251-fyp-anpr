# M1 — Configuration and CLI Architecture

## Milestone Summary

Milestone 1 (M1) extends the M0 project foundation with a **typed configuration loader**, **comprehensive validation rules**, and a **stable CLI interface** for all future runtime operations. M1 validates configuration and produces dry-run output; it does **not** implement real ANPR processing.

## Objective

Provide a stable public configuration and CLI contract so later milestones can add source reading, detection, OCR, tracking, evidence, and backend integration without redesigning the operator interface.

## Scope

### In Scope

- Typed `Config` dataclass loaded from `.env`, environment variables, defaults, and CLI overrides
- Standard-library `.env` parser (no `python-dotenv`)
- Source validation for `rtsp`, `video`, `image`, and `webcam`
- Model-path validation with **standard** and **strict** modes
- Backend configuration validation when backend is enabled
- Runtime and inference parameter validation
- CLI commands: `check-config`, `run --dry-run`, `flush-backend-queue`
- `--strict` flag on `check-config` and `run`
- M1 `worker_summary.json` contract (backward-compatible with M0)
- Updated `.env.example` and minimal `README.md`
- This document

### Out of Scope

- Real source reading (RTSP, video, image, webcam)
- Model loading or inference
- Vehicle or license plate detection
- OCR and plate voting
- Object tracking
- Event finalization
- Evidence image generation
- Backend login, token cache, API posting, or queue persistence
- Frontend integration
- Heavy dependencies (OpenCV, Ultralytics, PaddleOCR, PyTorch, NumPy, CUDA packages)

## Deliverables

| Deliverable | Description |
| ----------- | ----------- |
| Typed configuration | Full `Config` dataclass with parsing helpers |
| Validation engine | `validate_config()` with errors, warnings, and info messages |
| CLI | Extended `argparse` interface with `--strict` and source overrides |
| Dry-run output | M1 summary contract in `worker_summary.json` and `worker.log` |
| Documentation | Minimal README + this M1 document |
| Example config | Grouped `.env.example` with model placement notes |

## File-by-File Responsibilities

### main.py

- Thin CLI entry point using `argparse`
- Commands: `check-config`, `run`, `flush-backend-queue`
- Applies CLI overrides via `Config.apply_cli_overrides()`
- Delegates validation to `config.validate_config()`
- Delegates dry-run output to `ANPRProcessor.run_dry_run()`
- Prints clear success, warning, and error messages
- Returns non-zero exit codes for validation failure or unsupported non-dry-run execution

### config.py

- `Config` dataclass with all M1-supported settings
- `.env` file parser and environment merge logic
- Parsing helpers: `parse_str`, `parse_int`, `parse_float`, `parse_bool`, `parse_optional_str`, `parse_path`
- `ConfigValidationError` exception type
- `ValidationResult` with `errors`, `warnings`, and `info`
- `validate_config()` orchestrating foundation, source, model, inference, backend, and output checks
- `infer_source_from_path()` for `--source-path` type inference
- `check_foundation_config()` for directory and writable `runs/` checks

### anpr.py

- `ANPRProcessor.run_dry_run()` creates timestamped run directories
- Writes `worker.log`, `worker_summary.json`, and `events.jsonl`
- Embeds validation mode, warnings, and resolved source path in summary
- No model loading, media I/O, or backend calls

### backend.py

- `BackendClient.flush_queue()` placeholder
- No network calls in M1
- Reports queue flushing is not implemented

### Supporting Files

| File | Role |
| ---- | ---- |
| `.env.example` | Complete grouped example; models must be placed manually |
| `README.md` | Minimal setup, CLI examples, link to this document |
| `requirements.txt` | Unchanged; standard library only |

## Configuration Architecture

Configuration is loaded in this order:

1. **Safe defaults** defined on the `Config` dataclass
2. **`.env` file** values (if `.env` exists in the project root)
3. **Operating system environment variables** (override `.env`)
4. **CLI arguments** (override environment at runtime via `apply_cli_overrides()`)

Validation is performed separately via `validate_config(config, strict=...)`. Validation does not mutate configuration except for foundation directory creation.

## Environment Variables

| Variable | Type | Purpose |
| -------- | ---- | ------- |
| `ANPR_SOURCE` | str | Source mode: `rtsp`, `video`, `image`, `webcam` |
| `ANPR_RTSP_URL` | str | RTSP stream URL |
| `ANPR_VIDEO_PATH` | path | Video file path |
| `ANPR_IMAGE_PATH` | path | Image file path |
| `ANPR_CAMERA_INDEX` | int | Webcam device index |
| `ANPR_VEHICLE_MODEL` | path | Vehicle YOLO model path |
| `ANPR_PLATE_MODEL` | path | Plate YOLO model path |
| `ANPR_DEVICE` | str | `cpu` or `cuda` |
| `ANPR_TARGET_FPS` | float | Target processing FPS |
| `ANPR_VEHICLE_CONF` | float | Vehicle detection confidence |
| `ANPR_PLATE_CONF` | float | Plate detection confidence |
| `ANPR_TRACK_IOU_THRESHOLD` | float | Tracking IoU threshold |
| `ANPR_TRACK_EXPIRY_SECONDS` | float | Track expiry duration |
| `ANPR_EARLY_FINALIZE_MIN_VOTES` | int | Early finalize vote threshold |
| `ANPR_EARLY_FINALIZE_MIN_CONFIDENCE` | float | Early finalize confidence threshold |
| `ANPR_MIN_PLATE_VOTES` | int | Minimum plate votes |
| `ANPR_MIN_OCR_CONFIDENCE` | float | Minimum OCR confidence |
| `ANPR_BACKEND_ENABLED` | bool | Enable backend integration |
| `ANPR_BACKEND_BASE_URL` | str | Backend API base URL |
| `ANPR_BACKEND_EMAIL` | str | Backend login email |
| `ANPR_BACKEND_PASSWORD` | str | Backend login password |
| `ANPR_BACKEND_CAMERA_ID` | UUID str | Backend camera identifier |
| `ANPR_BACKEND_TOKEN_CACHE` | path | Token cache file path |
| `ANPR_BACKEND_QUEUE_FILE` | path | Backend queue file path |
| `ANPR_BACKEND_RETRY_LIMIT` | int | Backend retry limit |
| `ANPR_EVIDENCE_MODE` | str | `metadata` or `upload` |
| `ANPR_RUNS_DIR` | path | Runtime output directory |
| `ANPR_SAVE_LOCAL_EVIDENCE` | bool | Save local evidence flag |
| `ANPR_DELETE_LOCAL_AFTER_UPLOAD` | bool | Delete local evidence after upload |

## Validation Rules

### Source Validation

| Source | Requirement |
| ------ | ----------- |
| `rtsp` | Non-empty RTSP URL with plausible `rtsp://` or `rtsps://` shape; no connection attempted |
| `video` | Configured path must exist on disk |
| `image` | Configured path must exist on disk |
| `webcam` | Camera index must be integer `>= 0` |

**`--source-path` inference:**

| Input pattern | Inferred source |
| ------------- | --------------- |
| `rtsp://` or `rtsps://` | `rtsp` |
| `.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`, `.m4v` | `video` |
| `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp` | `image` |

`--source-path` overrides the specific source path fields. Local file paths are checked for existence; RTSP URLs are shape-validated only.

### Model Validation

- `ANPR_VEHICLE_MODEL` and `ANPR_PLATE_MODEL` must be configured (non-empty)
- **Standard mode:** missing model files produce **warnings**
- **Strict mode (`--strict`):** missing model files produce **errors** and fail validation
- `check-config` reports missing models; use `--strict` to fail on missing files

### Backend Validation

- When `ANPR_BACKEND_ENABLED=false`, backend credentials are optional
- When `ANPR_BACKEND_ENABLED=true`, require:
  - `ANPR_BACKEND_BASE_URL`
  - `ANPR_BACKEND_EMAIL`
  - `ANPR_BACKEND_PASSWORD`
  - `ANPR_BACKEND_CAMERA_ID` (UUID format)
  - `ANPR_BACKEND_TOKEN_CACHE`
  - `ANPR_BACKEND_QUEUE_FILE`
- `.cache/` must exist or be creatable
- No login, token cache I/O, or API calls in M1

### Runtime Parameter Validation

| Parameter | Rule |
| --------- | ---- |
| `ANPR_DEVICE` | `cpu` or `cuda` (CUDA availability not checked) |
| `ANPR_TARGET_FPS` | `> 0` |
| Confidence thresholds | `0.0` to `1.0` inclusive |
| `ANPR_TRACK_EXPIRY_SECONDS` | `> 0` |
| Vote minimums | `>= 1` |
| `ANPR_BACKEND_RETRY_LIMIT` | `>= 0` |
| `ANPR_EVIDENCE_MODE` | `metadata` or `upload` |
| `--max-seconds` | If set, must be `> 0` |

## CLI Behavior

### `python main.py check-config`

Loads configuration, runs full validation, and prints info, warnings, and errors.

```bash
python main.py check-config
python main.py check-config --strict
```

- **Standard:** missing model files are warnings; exit `0` if no errors
- **Strict:** missing model files are errors; exit `1` on failure

### `python main.py run --dry-run`

Validates configuration, then creates placeholder run output if validation passes.

```bash
python main.py run --dry-run
python main.py run --source rtsp --dry-run
python main.py run --source rtsp --max-seconds 30 --dry-run
python main.py run --source video --video samples/videos/test_vehicle.mp4 --dry-run
python main.py run --source image --image samples/images/frame.jpg --dry-run
python main.py run --source webcam --camera-index 0 --dry-run
python main.py run --source-path rtsp://user:pass@camera-ip:554/stream1 --dry-run
python main.py run --dry-run --strict
```

- Validation failure **before** run directory creation → exit `1`
- Validation with warnings in standard mode → still creates output; warnings in summary
- `run` without `--dry-run` → not implemented message, exit `2`

### `python main.py flush-backend-queue`

Safe placeholder. No network activity. Reports M1 queue flushing is not implemented.

## Source Override Behavior

CLI overrides apply after environment loading:

| Flag | Effect |
| ---- | ------ |
| `--source` | Sets source mode directly |
| `--source-path` | Infers source type and sets the matching path field |
| `--video` | Sets `source=video` and `video_path` |
| `--image` | Sets `source=image` and `image_path` |
| `--camera-index` | Sets `source=webcam` and `camera_index` |
| `--max-seconds` | Sets optional max duration (stored in summary when dry-running) |

## Runtime Summary Contract

Every successful `run --dry-run` writes:

```text
runs/run_YYYYMMDD_HHMMSS/
├── worker.log
├── worker_summary.json
└── events.jsonl
```

### `worker_summary.json` (M1 minimum)

```json
{
  "status": "completed",
  "milestone": "M1",
  "source_type": "video",
  "source_path": "samples/videos/test_vehicle.mp4",
  "frames_read": 0,
  "frames_processed": 0,
  "events_finalized": 0,
  "backend_enabled": false,
  "validation_mode": "standard",
  "warnings": [],
  "errors": [],
  "run_dir": "runs/run_YYYYMMDD_HHMMSS"
}
```

M0 keys are preserved. New M1 keys: `source_path`, `validation_mode`, `warnings`, `errors`. Optional: `max_seconds` when `--max-seconds` is provided.

### `worker.log`

Includes startup message, selected source, validation mode, warning count, and completion message.

### `events.jsonl`

Empty in M1 (valid JSONL container for later milestones).

## Output Structure

Same directory contract as M0:

```text
runs/
└── run_YYYYMMDD_HHMMSS/
    ├── worker.log
    ├── worker_summary.json
    └── events.jsonl
```

## Passing Criteria

1. All four Python runtime modules compile
2. No unnecessary runtime modules created
3. `check-config` prints clear validation results
4. Invalid configuration fails with readable messages
5. `run --dry-run` creates M1 output files
6. `worker_summary.json` is valid JSON with M1 contract fields
7. All CLI flags parse correctly (`--source`, `--video`, `--image`, `--camera-index`, `--source-path`, `--max-seconds`, `--strict`)
8. Backend credentials required only when backend is enabled
9. README is minimal and links to this document
10. No heavy dependencies added
11. No real ANPR processing before M2

## Verification Checklist

- [ ] `python -m py_compile main.py config.py anpr.py backend.py`
- [ ] `python main.py check-config`
- [ ] `python main.py check-config --strict` (expect failure if models missing)
- [ ] `python main.py run --dry-run`
- [ ] `python main.py run --source webcam --camera-index 0 --dry-run`
- [ ] `python main.py run --source-path rtsp://user:pass@camera-ip:554/stream1 --dry-run`
- [ ] `python main.py flush-backend-queue`
- [ ] `python main.py run --source video --video samples/videos/missing.mp4 --dry-run` (expect failure)
- [ ] Confirm `worker_summary.json` includes M1 fields
- [ ] Confirm only four runtime Python modules exist

## Known Limitations

- **No real processing** — dry-run only creates placeholder files
- **No media I/O** — sources are validated but not opened
- **No model loading** — model paths are checked, not loaded
- **No CUDA probe** — `cuda` device is accepted without hardware check
- **No backend I/O** — queue flush is a placeholder
- **No RTSP connection test** — URL shape validation only
- **Argparse source guard** — invalid `--source` values are rejected by argparse before custom validation

## Next Milestone Handoff Notes

M2 should build on this configuration and CLI contract:

1. Implement real source opening in `anpr.py` using validated `Config` fields
2. Add model loading after strict validation passes
3. Introduce detection, OCR, and tracking (new modules only when the milestone spec allows)
4. Populate `events.jsonl` with finalized events
5. Extend `worker_summary.json` with runtime metrics (frames processed, events finalized, timing)
6. Keep `validate_config()` as the pre-run gate; extend with any M2-specific rules
7. Wire `BackendClient` when backend milestones begin

Preserve backward compatibility for `worker_summary.json` keys introduced in M0 and M1.
