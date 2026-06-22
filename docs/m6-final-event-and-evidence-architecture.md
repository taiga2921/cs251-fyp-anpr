# M6 — Final Event and Evidence Architecture

## Milestone Summary

Milestone 6 (M6) converts M5 **FinalizedTrackCandidate** decisions into **persisted local ANPR events** and **saved evidence images**. Each dry-run produces valid `events.jsonl` records and an `evidence/` folder under the run directory. Backend posting remains out of scope.

## Objective

Provide dashboard-ready local event records and readable evidence images so M7 can later queue and post events without redesigning the runtime pipeline.

## Scope

### In Scope

- `FinalizedEvent` local event contract
- Evidence directories: `evidence/full/`, `evidence/plate/`, `evidence/annotated/`
- OpenCV image writes via `cv2.imwrite`
- JSONL append writer (`events.jsonl`, one JSON object per line)
- Plate-level duplicate cooldown (`ANPR_DUPLICATE_COOLDOWN_SECONDS`)
- M6 metrics in `worker_summary.json` and `worker.log`
- Preservation of all M4/M5 detection, OCR, tracking, and vote behavior

### Out of Scope

- Backend login, queue, posting, or image upload
- Laravel metadata creation
- New split runtime modules (`evidence.py`, `event_writer.py`)
- Model auto-download
- Internet dependency during runtime

## File-by-File Responsibilities

### main.py

- CLI success output includes M6 event/evidence counts
- RTSP `--source-path` rejection preserved

### config.py

- `ANPR_DUPLICATE_COOLDOWN_SECONDS` loading and validation (`>= 0`)

### anpr.py

- `FinalizedEvent`, evidence saving, JSONL writer, duplicate suppression
- Hooks persistence from `finalize_track()` after M5 candidate creation

### backend.py

- Unchanged placeholder; no network side effects in M6

## Architecture Flow

```text
M5 pipeline (unchanged)
        |
        v
finalize_track() → FinalizedTrackCandidate
        |
        v
_persist_finalized_event()
        |
        +--> duplicate cooldown check
        |
        +--> save evidence images (full, plate, annotated)
        |
        +--> append FinalizedEvent to events.jsonl
        |
        v
worker.log + worker_summary.json
```

## FinalizedEvent Contract

Each persisted event includes:

| Field | Purpose |
| ----- | ------- |
| `event_id` | Stable local ID, e.g. `local-run_YYYYMMDD_HHMMSS-track_1` |
| `run_id` | Run folder name |
| `track_id` | Vehicle track identifier |
| `plate_number` | Normalized winning plate text |
| `confidence` / `votes` | Vote-buffer decision metadata |
| `first_seen_at` / `last_seen_at` | Track timeline |
| `first_frame_index` / `last_frame_index` | Source frame indices |
| `finalization_reason` | `early_high_confidence`, `track_expired`, or `source_end` |
| `source_type` / `source_path` | Input source metadata |
| `vehicle_bbox` / `plate_bbox` | Detection geometry (lists in JSON) |
| `evidence` | Relative paths to saved images |
| `backend` | Placeholder with no M6 side effects |
| `dry_run` | `true` for current CLI dry-run |
| `created_at` | UTC ISO-8601 timestamp |

## Evidence Layout

```text
runs/run_YYYYMMDD_HHMMSS/
├── worker.log
├── worker_summary.json
├── events.jsonl
└── evidence/
    ├── full/
    ├── plate/
    └── annotated/
```

Filename pattern: `<event_id>_full.jpg`, `<event_id>_plate.jpg`, `<event_id>_annotated.jpg`.

## Evidence Saving Behavior

- Uses M5 `TrackState` best evidence: `best_full_frame`, `best_plate_crop`, `best_annotated_frame`.
- Directories are created at run start.
- Images are saved only for accepted persisted events (not rejected track finalizations).
- Missing images log warnings and increment `evidence_save_failures` without crashing.
- Annotated frame is regenerated at persist time with **final plate text and confidence** when possible.
- Controlled by `ANPR_SAVE_LOCAL_EVIDENCE` (default `true`).

## Annotated Evidence Behavior

Annotated images include:

- Vehicle bounding box (green)
- Plate bounding box (red)
- Track ID label
- Plate text and confidence label

Only **final event** evidence is written to disk (no per-frame dumps).

## JSONL Event Writer Contract

- Helper: `write_event_record(events_file, event)`
- UTF-8 append mode
- One compact JSON object per line (`json.dumps(..., separators=(",", ":"))`)
- Tuples converted to lists
- Every line must parse with `json.loads`

## Duplicate Prevention Behavior

M5 prevents duplicate candidates per track via `decision_finalized`.

M6 adds **plate-level cooldown**:

- Config: `ANPR_DUPLICATE_COOLDOWN_SECONDS` (default `10`, `0` disables)
- In-memory map: last persisted event time per normalized plate
- Suppressed duplicates increment `duplicate_events_suppressed`
- No JSONL line and no evidence files for suppressed duplicates

## Dry-Run Behavior

M6 dry-run:

- Saves local evidence (when enabled)
- Writes `events.jsonl`
- Writes `worker_summary.json` and `worker.log`
- Does **not** post to backend or enqueue backend jobs

Each event `backend` object:

```json
{
  "queued": false,
  "posted": false,
  "event_id": null,
  "images_sent": 0,
  "error": null
}
```

## Runtime Summary Contract

`worker_summary.json` includes M6 fields plus all M5 metrics:

```json
{
  "milestone": "M6",
  "events_finalized": 0,
  "events_written": 0,
  "evidence_files_saved": 0,
  "evidence_save_failures": 0,
  "duplicate_events_suppressed": 0,
  "finalized_events": []
}
```

`tracks_finalized` remains the M5 track-decision count; `events_finalized` counts persisted events after duplicate suppression.

## Logging Behavior

`worker.log` includes M6 startup config (duplicate cooldown, save evidence), per-event persist lines, suppression lines, evidence warnings, and aggregate M6 counts at completion.

## CLI Behavior

On success, prints concise M6 counts:

- Events finalized
- Events written
- Evidence files saved
- Duplicate events suppressed

Existing M5 counts are preserved. Full event JSON is not printed by default.

## Passing Criteria

- Finalized M5 track → one `FinalizedEvent` (unless duplicate suppressed)
- Valid JSONL in `events.jsonl`
- Evidence images under `evidence/full`, `evidence/plate`, `evidence/annotated`
- Annotated images show boxes, track ID, plate text, and confidence
- Duplicate cooldown suppresses repeated same-plate events within window
- No backend network or queue side effects
- M4/M5 pipeline behavior intact

## Verification Checklist

```bash
python -m py_compile main.py config.py anpr.py backend.py
python main.py check-config
python main.py check-config --strict
python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict
python main.py run --source video --video samples/videos/document_6177158287369184218.mp4 --dry-run --strict
python main.py run --source-path rtsp://user:pass@camera-ip:554/stream1 --dry-run
python -c "import json, pathlib; p=next(pathlib.Path('runs').glob('run_*/events.jsonl')); [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip()]; print('events.jsonl valid')"
```

## Known Limitations

- Duplicate cooldown is runtime-local only (no database)
- Evidence paths are relative to project working directory
- Failed OCR/model runs may produce empty `events.jsonl`
- Backend integration deferred to M7
- IoU tracking limitations from M5 remain

## Next Milestone Handoff Notes for M7

M7 should consume:

- `events.jsonl` `FinalizedEvent` records
- Saved evidence paths under `evidence/`
- `backend` placeholder fields for queue/post state updates

M7 will implement:

- Backend token cache and login
- Backend queue file processing
- Event posting to Laravel API
- Evidence image upload and metadata delivery

M6 intentionally leaves all `backend` fields at no-op values.
