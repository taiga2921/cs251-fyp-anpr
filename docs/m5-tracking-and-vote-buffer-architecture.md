# M5 — Tracking and Vote Buffer Architecture

## Milestone Summary

Milestone 5 (M5) adds **IoU vehicle tracking**, **per-track OCR vote buffering**, and **in-memory track finalization** on top of the M4 OCR pipeline. Valid `PlateCandidate` objects are associated with vehicle tracks, accumulated as votes, and resolved into `FinalizedTrackCandidate` decisions when finalization triggers fire.

M5 does **not** persist final ANPR events, save evidence images, or post to the backend.

## Objective

Bridge M4 plate candidates and future M6 event/evidence architecture by maintaining stable vehicle tracks, buffering OCR votes per track, selecting a deterministic winning plate, and finalizing track-level decisions in memory with full runtime metrics.

## Scope

### In Scope

- IoU-based vehicle tracking (no external tracker packages)
- `PlateVote`, `TrackState`, and `FinalizedTrackCandidate` dataclasses
- Per-track vote buffer with deterministic majority selection
- In-memory best evidence state (`best_full_frame`, `best_plate_crop`, `best_annotated_frame`)
- Finalization triggers: track expiry, source end, early high-confidence voting
- M5 metrics in `worker_summary.json` and `worker.log`
- Tracking configuration validation (`ANPR_TRACK_IOU_THRESHOLD`, `ANPR_TRACK_EXPIRY_SECONDS`, etc.)
- Preservation of all M4 detection and OCR behavior

### Out of Scope

- Persisted final event records (`events.jsonl` remains empty)
- Evidence image files on disk
- Backend posting or queue flushing with network activity
- Vehicle re-identification beyond IoU matching
- New runtime modules (`tracker.py`, `plate_vote.py`, `ocr.py`)

## File-by-File Responsibilities

### main.py

- Thin CLI; prints M5 tracking/vote/finalization counts on success
- Preserves RTSP `--source-path` rejection

### config.py

- Tracking configuration fields, loading, and validation
- Lightweight PaddleOCR package detection (unchanged from M4 cleanup)

### anpr.py

- All tracking, vote buffering, finalization, and pipeline integration
- M4 OCR, normalization, and validation preserved

### backend.py

- Unchanged placeholder; no network side effects in M5

## Architecture Flow

```text
Config validation
        |
        v
  open_source()
        |
        v
  load_models()              ← YOLO once
        |
        v
  load_ocr_engine()          ← PaddleOCR once
        |
        v
  For each scheduler-accepted frame:
        |
        +--> detect_vehicles()
        |
        +--> update_tracks() via IoU
        |
        +--> detect_plates() per matched track/vehicle
        |
        +--> OCR → PlateCandidate
        |
        +--> add_plate_candidate_to_track()
        |
        +--> update best evidence in memory
        |
        +--> early finalization check
        |
        +--> finalize expired tracks
        |
        +--> source-end flush on last frame
        |
        v
  worker.log + worker_summary.json + empty events.jsonl
```

## TrackState Contract

`TrackState` holds one vehicle track in memory:

| Field | Purpose |
| ----- | ------- |
| `track_id` | Stable integer identifier for the track |
| `bbox` | Latest vehicle bounding box |
| `first_seen_at` / `last_seen_at` | Wall-clock timestamps |
| `first_frame_index` / `last_frame_index` | Source frame indices |
| `plate_votes` | List of `PlateVote` entries |
| `best_plate_crop` | Highest-confidence plate crop (in memory) |
| `best_full_frame` | Full frame copy at best confidence |
| `best_annotated_frame` | Annotated frame copy with boxes and labels |
| `best_confidence` | Confidence of best evidence state |
| `finalized` | Whether the track has been finalized |
| `finalization_reason` | Reason string when finalized |

## PlateVote Contract

Each valid `PlateCandidate` added to a track becomes a `PlateVote`:

- `plate_text` — normalized plate string
- `raw_text` — raw OCR text
- `confidence` — OCR confidence
- `timestamp` — frame timestamp
- `frame_index` — source frame index
- `plate_bbox` / `vehicle_bbox` — detection geometry

## IoU Tracking Behavior

- Tracks are stored in `ANPRProcessor._tracks`.
- Each vehicle detection is matched to the best **non-finalized** track by IoU.
- If best IoU ≥ `ANPR_TRACK_IOU_THRESHOLD`, the existing `track_id` is retained.
- Otherwise a new track is created with an incrementing `track_id`.
- Matched tracks update `bbox`, `last_seen_at`, and `last_frame_index`.
- No external tracking libraries are used.

## Vote Buffer Behavior

- Valid `PlateCandidate` objects are appended to the matched track’s `plate_votes`.
- Votes are grouped by normalized `plate_text`.
- `select_best_plate_for_track()` chooses the winner deterministically:

  1. Highest vote count
  2. Highest average confidence
  3. Highest best (peak) confidence in the group
  4. Most recent vote timestamp
  5. Lexicographic plate text

- Plate text is not corrected beyond M4 normalization and validation.

## Finalization Triggers

| Trigger | Reason | Minimum votes |
| ------- | ------ | ------------- |
| Track not seen for `ANPR_TRACK_EXPIRY_SECONDS` | `track_expired` | `ANPR_MIN_PLATE_VOTES` |
| Source end (last frame) | `source_end` | `1` for image; `ANPR_MIN_PLATE_VOTES` otherwise |
| Same plate reaches early vote/confidence thresholds | `early_high_confidence` | `ANPR_EARLY_FINALIZE_MIN_VOTES` with avg confidence ≥ `ANPR_EARLY_FINALIZE_MIN_CONFIDENCE` |

Rules:

- Tracks with **zero** valid votes are not finalized as candidates; they are marked finalized with `track_finalizations_rejected` incremented.
- A finalized track cannot finalize again.
- `FinalizedTrackCandidate` objects are stored in `self._finalized_track_candidates` only.

## Best Evidence State Behavior

When a new vote has higher confidence than the track’s `best_confidence`:

- `best_full_frame` — copy of the current frame
- `best_plate_crop` — crop extracted from the plate bbox
- `best_annotated_frame` — in-memory copy with vehicle bbox, plate bbox, track id, and plate text drawn via OpenCV

Evidence is **not** written to disk in M5. No `runs/.../evidence/` folders are created.

## Runtime Summary Contract

`worker_summary.json` includes M4 metrics plus M5 fields:

```json
{
  "milestone": "M5",
  "tracks_created": 0,
  "tracks_updated": 0,
  "active_tracks": 0,
  "tracks_finalized": 0,
  "tracks_finalized_early": 0,
  "tracks_finalized_expired": 0,
  "tracks_finalized_source_end": 0,
  "track_finalizations_rejected": 0,
  "plate_votes_added": 0,
  "finalized_track_candidates": [],
  "events_finalized": 0
}
```

`events_finalized` remains `0` because no persisted event records are written.

## Logging Behavior

`worker.log` includes:

- M5 startup line and tracking configuration values
- Aggregate counts: tracks created/updated, active tracks, plate votes added
- Finalization counts by reason and rejected finalizations
- All M4 detection and OCR metrics
- Stop reason and completion status

Per-frame logging is avoided.

## CLI Behavior

On successful dry-run, the CLI prints run paths plus concise M5 counts:

- Tracks created
- Plate votes added
- Tracks finalized
- Finalized track candidates (count only)

RTSP URLs via `--source-path` remain rejected.

## Passing Criteria

- IoU tracking persists `track_id` across frames when overlap threshold is met
- Valid `PlateCandidate` objects accumulate in per-track vote buffers
- Majority voting selects plates deterministically
- Best evidence state is stored in memory only
- Expiry, source-end, and early finalization triggers work as specified
- Finalized tracks do not finalize twice
- M4 single-load OCR/YOLO behavior is preserved
- `events.jsonl` remains empty
- No backend network calls occur

## Verification Checklist

```bash
python -m py_compile main.py config.py anpr.py backend.py
python main.py check-config
python main.py check-config --strict
python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict
python main.py run --source video --video samples/videos/document_6177158287369184218.mp4 --dry-run --strict
python main.py run --source-path rtsp://user:pass@camera-ip:554/stream1 --dry-run
```

Expected:

- Compile and config checks pass when dependencies and models are present
- Image/video runs include M5 tracking and vote metrics in summary and log
- `events.jsonl` is empty
- RTSP `--source-path` is rejected

## Known Limitations

- IoU-only tracking; no Kalman filter or appearance model
- Occlusion and crossing vehicles may swap or split tracks
- Best evidence exists only in memory until M6
- `ANPR_MIN_PLATE_VOTES` may block video finalization when only one vote is collected
- Image runs allow single-vote source-end finalization for testing convenience
- PaddleOCR and PyTorch environment constraints from M4 still apply

## Next Milestone Handoff Notes for M6

M6 should consume:

- `FinalizedTrackCandidate` records from `self._finalized_track_candidates`
- Per-track `best_full_frame`, `best_plate_crop`, and `best_annotated_frame` for evidence saving
- Existing `worker_summary.json` metrics as operational telemetry

M6 will:

- Write persisted final event records to `events.jsonl`
- Save evidence images under `runs/.../evidence/`
- Define the final event contract (distinct from `FinalizedTrackCandidate`)

M7+ will handle backend queue and posting.
