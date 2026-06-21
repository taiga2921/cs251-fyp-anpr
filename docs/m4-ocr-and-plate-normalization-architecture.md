# M4 — OCR and Plate Normalization Architecture

## Milestone Summary

Milestone 4 (M4) adds **OCR and plate normalization** on detected plate crops. The runtime converts YOLO plate detections into normalized, validated Malaysian plate candidates and records OCR metrics. M4 does **not** create final ANPR events, tracking, evidence, or backend posts.

## Objective

Bridge detection (M3) and future event finalization (M5+) by producing validated `PlateCandidate` objects in memory with accurate OCR metrics in `worker_summary.json`.

## Scope

### In Scope

- Plate crop extraction from full-frame detections
- Basic plate preprocessing (`preprocess_plate`)
- PaddleOCR engine loaded once per run (`load_ocr_engine`)
- `read_plate_text()` wrapper
- `normalize_plate_text()` and `validate_plate_text()`
- `OCRReading` and `PlateCandidate` dataclasses
- OCR metrics in summary and `worker.log`
- Config fields: `ANPR_OCR_ENGINE`, `ANPR_OCR_LANG`, `ANPR_OCR_PREPROCESS`, `ANPR_OCR_SCALE`, `ANPR_MIN_OCR_CONFIDENCE`

### Out of Scope

- Vehicle tracking and track IDs
- Vote buffering
- Final ANPR events (`events.jsonl` remains empty)
- Evidence image saving
- Backend posting
- Plate text correction beyond normalization
- Full special-plate coverage

## Deliverables

| Deliverable | Description |
| ----------- | ----------- |
| OCR engine | PaddleOCR initialized once per run |
| Preprocessing | Grayscale, scale, light blur/sharpen |
| Normalization | Uppercase alphanumeric plate text |
| Validation | Conservative Malaysian private-vehicle pattern |
| Metrics | OCR calls, readings, candidates, timing |
| Documentation | Minimal README + this document |

## File-by-File Responsibilities

### main.py

- Thin CLI; prints OCR/candidate counts on success
- Preserves RTSP `--source-path` rejection

### config.py

- OCR configuration fields and validation
- Standard `check-config` uses lightweight `importlib.util.find_spec("paddleocr")` only
- Strict mode fails if the PaddleOCR package is not installed

### anpr.py

- All OCR, normalization, validation, and pipeline integration
- M4 uses **PaddleOCR 2.x legacy API** (`PaddleOCR(...).ocr(image, cls=False)`)
- Valid `PlateCandidate` objects are collected in `self._run_candidates` during each run
- No `ocr.py` module

### backend.py

- Unchanged placeholder

## Architecture Flow

```text
Config validation
        |
        v
  open_source()
        |
        v
  load_models()          ← YOLO once
        |
        v
  load_ocr_engine()      ← PaddleOCR once
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
 detect_plates() per vehicle
        |
        v
 extract_plate_crop()
        |
        v
 preprocess_plate()
        |
        v
 read_plate_text()
        |
        v
 normalize_plate_text()
        |
        v
 validate_plate_text()
        |
        v
 count PlateCandidate + metrics
        |
        v
 worker_summary.json
```

## OCR Engine Behavior

- Engine: **PaddleOCR 2.x legacy API** (`paddleocr<3` in `requirements.txt`)
- Initialization: `PaddleOCR(use_angle_cls=False, lang=..., show_log=False)`
- Inference: `ocr_engine.ocr(image, cls=False)`
- Loaded once via `load_ocr_engine()` after YOLO models
- Standard `check-config` uses lightweight package detection only (`importlib.util.find_spec`)
- Runtime `load_ocr_engine()` performs the full import and must fail clearly on error
- Initialization failure writes failed `worker_summary.json` with `ocr_engine_loaded: false`
- Runtime does not implement custom model downloads
- OCR inference failures raise `SourceRuntimeError` and write failed summary

## Plate Candidate Handoff

Valid `PlateCandidate` objects are returned from `_process_plate_detection()` and collected in memory:

- Per-frame: `frame_candidates` list during processed frames
- Per-run: `self._run_candidates` on `ANPRProcessor`

Candidates are **not** written to `events.jsonl`. Summary exposes counts only (`plate_candidates`).

## Plate Crop Extraction

`extract_plate_crop(frame, plate_detection)`:

- Uses full-frame `Detection.bbox`
- Clips to image bounds
- Rejects zero-area crops
- Counts extracted vs rejected in metrics

## Plate Preprocessing

`preprocess_plate(crop, scale)` when `ANPR_OCR_PREPROCESS=true`:

1. Convert to grayscale
2. Resize by `ANPR_OCR_SCALE` (default `2.0`)
3. Light Gaussian blur
4. Conservative sharpening

## OCR Result Contract

```python
@dataclass
class OCRReading:
    raw_text: str
    confidence: float
```

Multiple OCR fragments are combined; confidence uses average of fragment confidences when combined.

## Plate Normalization Rules

`normalize_plate_text(raw_text)`:

- Uppercase
- Remove spaces and punctuation
- Keep only `A–Z` and `0–9`
- No character invention

Examples: `abc 1234` → `ABC1234`, `a-b c 1234` → `ABC1234`

## Plate Validation Rules

`validate_plate_text(normalized_text)` rejects:

- Empty strings
- Length &lt; 4 or &gt; 10
- No letters or no digits
- Pattern mismatch

Conservative Malaysian private-vehicle pattern:

```text
^[A-Z]{1,4}[0-9]{1,4}[A-Z]?$
```

Accepts: `ABC1234`, `WXY1234`, `WA1234A`, `B1234`

## Runtime Summary Contract

Preserves all M2/M3 fields and adds:

```json
{
  "milestone": "M4",
  "ocr_engine": "paddleocr",
  "ocr_engine_loaded": true,
  "plate_crops_extracted": 1,
  "plate_crops_rejected": 0,
  "ocr_calls": 1,
  "ocr_readings": 1,
  "plate_candidates": 1,
  "plate_candidates_rejected": 0,
  "average_ocr_ms": 85.3,
  "events_finalized": 0
}
```

`events.jsonl` remains **empty**.

## Logging Behavior

`worker.log` includes M4 startup, OCR engine status, crop/OCR/candidate counts, average OCR time, stop reason, and completion status. No per-frame spam.

## CLI Behavior

Preserves existing commands and RTSP credential safety. Successful dry-run prints OCR calls, readings, and plate candidate counts.

## Passing Criteria

1. OCR engine loads once per run
2. OCR runs only on scheduler-accepted frames and detected plate regions
3. Normalization and validation applied
4. Valid candidates counted; invalid rejected
5. OCR metrics in `worker_summary.json`
6. M2/M3 behavior preserved
7. `events.jsonl` empty
8. Failed OCR init/inference writes failed summary

## Verification Checklist

- [ ] `pip install -r requirements.txt`
- [ ] `python -m py_compile main.py config.py anpr.py backend.py`
- [ ] `python main.py check-config`
- [ ] `python main.py check-config --strict`
- [ ] `python main.py run --source image --image samples/images/photo_6177158287829176211_w.jpg --dry-run --strict`
- [ ] `python main.py run --source-path rtsp://... --dry-run` → rejected
- [ ] Confirm OCR metrics in summary
- [ ] Confirm `events.jsonl` is empty
- [ ] Confirm OCR/detection failures write failed summary

## Known Limitations

- No tracking or event finalization
- Malaysian pattern is conservative; special plates not covered
- PaddleOCR 2.x may require local model files on first use (outside runtime download logic)
- Use Python 3.11 or 3.12 in a clean virtual environment for reproducible installs
- Low-quality crops may yield zero valid candidates without crashing
- No evidence images saved

## Next Milestone Handoff Notes (M5)

M5 should add vote buffering and track-based candidate aggregation using `PlateCandidate`. Preserve:

- `PlateCandidate` contract
- OCR-once-per-crop pattern
- Scheduler-only processing
- Empty `events.jsonl` until event finalization is explicitly implemented

Do not reload OCR per frame. Associate candidates with track IDs before finalizing one event per vehicle.
