# M0 — Project Foundation Architecture

## Milestone Summary

Milestone 0 (M0) establishes the AI ANPR project foundation: directory layout, minimal runtime skeleton, CLI baseline, output directory contract, and documentation. M0 intentionally excludes detection, OCR, tracking, and backend integration.

## Objective

Create a small, runnable project shell that operators and developers can install, validate, and dry-run without models, media libraries, or backend services.

## Scope

### In Scope

- Exact folder structure for models, samples, runs, and cache
- Four Python modules: `main.py`, `config.py`, `anpr.py`, `backend.py`
- CLI commands: `check-config`, `run --dry-run`, `flush-backend-queue`
- Dry-run output under `runs/run_YYYYMMDD_HHMMSS/`
- `.env.example`, `.gitignore`, `requirements.txt`, `README.md`
- Foundation configuration validation (directories and writable `runs/`)

### Out of Scope

- Vehicle and license plate detection
- OCR and plate voting
- Object tracking
- Backend HTTP calls, token login, or queue persistence
- RTSP, webcam, video, and image processing
- Heavy dependencies (OpenCV, Ultralytics, PaddleOCR, PyTorch, NumPy)

## Deliverables

| Deliverable | Description |
| ----------- | ----------- |
| Project structure | `models/`, `samples/`, `runs/`, `.cache/` with `.gitkeep` files |
| Runtime skeleton | Compilable Python modules with clear responsibilities |
| CLI | `argparse`-based command routing with future-ready `run` arguments |
| Output contract | Dry-run creates `worker.log`, `worker_summary.json`, `events.jsonl` |
| Documentation | `README.md` and this document |

## File-by-File Responsibilities

### `main.py`

- CLI entry point and command routing
- Subcommands: `check-config`, `run`, `flush-backend-queue`
- Parses future-ready `run` arguments (`--source`, `--source-path`, `--video`, `--image`, `--camera-index`, `--max-seconds`, `--dry-run`)
- Returns exit code `0` on success; non-zero on validation failure or unsupported non-dry-run execution

### `config.py`

- `Config` dataclass loaded from environment variables
- Fields include `runs_dir`, `backend_enabled`, `source`, `video_path`, `image_path`, `rtsp_url`, `camera_index`
- `check_foundation_config()` ensures required directories exist and `runs_dir` is writable
- Does not require model files to exist in M0

### `anpr.py`

- `ANPRProcessor` class with `run_dry_run()` method
- Creates `runs/run_YYYYMMDD_HHMMSS/` and placeholder output files
- No image processing, model loading, or backend side effects

### `backend.py`

- `BackendClient` placeholder with `flush_queue()` method
- No network calls in M0; reports queue flushing is not implemented

### Supporting Files

- **`requirements.txt`** — minimal; M0 uses standard library only
- **`.env.example`** — complete example for future milestones; not required for M0
- **`.gitignore`** — ignores Python cache, `.env`, `*.pt`, generated `runs/` and `.cache/` content while keeping `.gitkeep` files tracked

## CLI Behavior

### `python main.py check-config`

Loads configuration from the environment (with defaults), validates foundation requirements, and prints clear success or failure messages.

### `python main.py run --dry-run`

1. Optionally applies CLI overrides to config (source-related flags are parsed but not executed in M0)
2. Re-validates foundation config
3. Creates a timestamped run directory and writes:
   - `worker.log` — startup/completion text
   - `worker_summary.json` — JSON summary with M0 contract fields
   - `events.jsonl` — empty file

### `python main.py run` (without `--dry-run`)

Prints that non-dry-run ANPR execution is not implemented until later milestones. Exits with a non-zero code.

### `python main.py flush-backend-queue`

Invokes `BackendClient.flush_queue()` and prints a safe placeholder message. No queue items are processed.

### Future-Ready `run` Arguments (parsed, not executed in M0)

```bash
python main.py run --source rtsp --dry-run
python main.py run --source video --video samples/videos/test_vehicle.mp4 --dry-run
python main.py run --source image --image samples/images/frame.jpg --dry-run
python main.py run --source webcam --camera-index 0 --dry-run
python main.py run --source-path samples/videos/test_vehicle.mp4 --dry-run
```

## Output Structure

```text
runs/
└── run_YYYYMMDD_HHMMSS/
    ├── worker.log
    ├── worker_summary.json
    └── events.jsonl
```

### `worker_summary.json` Minimum Contract

```json
{
  "status": "completed",
  "milestone": "M0",
  "source_type": "dry-run",
  "frames_read": 0,
  "frames_processed": 0,
  "events_finalized": 0,
  "backend_enabled": false,
  "run_dir": "runs/run_YYYYMMDD_HHMMSS"
}
```

## Passing Criteria

1. Folder structure matches the specified architecture
2. `.gitignore` ignores `*.pt`, `runs/*` (except `.gitkeep`), `.cache/*` (except `.gitkeep`)
3. All four Python modules compile successfully
4. `python main.py check-config` exits `0` with clear output
5. `python main.py run --dry-run` creates the three output files with valid JSON in `worker_summary.json`
6. `python main.py flush-backend-queue` runs without error
7. No extra runtime modules beyond the four specified files
8. No heavy dependencies in `requirements.txt`

## Verification Checklist

- [ ] `pip install -r requirements.txt`
- [ ] `python main.py check-config`
- [ ] `python main.py run --dry-run`
- [ ] Confirm `runs/run_*/worker.log`, `worker_summary.json`, `events.jsonl` exist
- [ ] Validate `worker_summary.json` parses as JSON
- [ ] `python main.py flush-backend-queue`
- [ ] `python main.py run` (no `--dry-run`) prints not-implemented message and non-zero exit
- [ ] Confirm only `main.py`, `config.py`, `anpr.py`, `backend.py` exist as runtime modules

## Known Limitations

- **No real ANPR processing** — dry-run only creates placeholder files
- **No media I/O** — cameras, RTSP, video, and images are not read
- **No backend** — `flush-backend-queue` is a no-op placeholder
- **Minimal validation** — full typed config validation deferred to M1
- **Empty events** — `events.jsonl` is intentionally empty in M0

## Next Milestone Handoff Notes

M1 and later milestones should build on this foundation without restructuring the output contract:

1. Add configuration validation for models, sources, and inference parameters
2. Introduce detection, OCR, and tracking logic incrementally inside the existing runtime structure first, then split into new files only when later milestones require it or the code becomes difficult to maintain.
3. Implement real `run` execution paths per `--source` type
4. Wire `BackendClient` to the Laravel API with token cache and queue file under `.cache/`
5. Populate `events.jsonl` with finalized plate events
6. Add heavy dependencies to `requirements.txt` incrementally as features land

Preserve the `runs/run_YYYYMMDD_HHMMSS/` layout and `worker_summary.json` schema extensions should remain backward-compatible where possible.
