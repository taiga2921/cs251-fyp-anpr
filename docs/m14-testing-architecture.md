# M14 — Testing Architecture

## 1. Milestone Summary

**Milestone:** M14 — Testing Architecture  
**Status:** Implemented  
**Scope:** AI runtime, Laravel ANPR APIs, React ANPR UI, and reproducible manual end-to-end verification  
**Protects:** M11 realtime RTSP runtime, M12 live ANPR monitoring, M13 linked vehicle record architecture

M14 adds deterministic automated regression coverage across the ANPR stack without requiring real RTSP hardware, YOLO weights, PaddleOCR initialization, or live backend network access in CI.

## 2. Objective

Establish a reliable testing architecture that prevents regressions in the completed ANPR flow after M11–M13 delivery. Automated tests must run locally and in CI without production credentials, model files, or camera hardware.

## 3. Scope

| Layer | Coverage |
| ----- | -------- |
| **AI runtime (`ai-anpr-v1`)** | Config validation, source resolution, plate normalization, tracking/voting, finalization, duplicate cooldown, backend queue/token behavior, RTSP reconnect helpers, CLI integration with mocked processor |
| **Laravel backend** | ANPR event CRUD contracts, image upload/metadata, event logs, vehicle linking, authorization, list query validation, resource shape |
| **React frontend** | ANPR monitoring repository/controller/components, vehicle management repository/edit drawer, Vitest + Testing Library |
| **Manual E2E** | Reproducible matrix for full-stack verification with hardware/backend prerequisites documented |

## 4. Out of Scope

- M15 performance or accuracy tuning
- New product features (except minimal testability fixes)
- Browser automation frameworks (Playwright/Cypress) — manual matrix covers full E2E
- Real RTSP camera, real YOLO/PaddleOCR, or live production backend in unit/CI tests

## 5. Testing Architecture Overview

```text
┌─────────────────────────────────────────────────────────────────┐
│                     M14 Regression Layers                        │
├──────────────┬────────────────────┬────────────────────────────┤
│ AI pytest    │ Laravel PHPUnit    │ React Vitest                 │
│ (unit + CLI) │ (Feature tests)    │ (repository/controller/UI)   │
├──────────────┴────────────────────┴────────────────────────────┤
│ Manual E2E matrix (operator-run, evidence capture)              │
└─────────────────────────────────────────────────────────────────┘
```

**Design principles:**

- **Deterministic fixtures** — synthetic images/videos, temp directories, monkeypatched clients
- **No production mutation** — `--dry-run` verified; queue flush tested with fakes
- **Preserve M12/M13 behavior** — existing `AnprMonitoringTest` and `AnprVehicleLinkingTest` retained and extended

## 6. AI Runtime Test Strategy

### 6.1 Layout

```text
ai-anpr-v1/
  requirements-dev.txt
  pytest.ini
  tests/
    conftest.py
    test_config.py
    test_plate_normalization.py
    test_tracking_and_voting.py
    test_backend_queue.py
    test_runtime_rtsp_resilience.py
    test_integration.py
```

### 6.2 Unit coverage

| Area | Functions / behavior tested |
| ---- | --------------------------- |
| Config | `infer_source_from_path`, `is_rtsp_source_path`, `mask_rtsp_url`, `validate_config`, `validate_backend_config`, evidence mode, M11 interval validation |
| Plates | `normalize_plate_text`, `validate_plate_text` |
| Tracking | `calculate_iou`, `match_detection_to_track`, `create_track`, `select_best_plate_for_track`, early/source-end/expiry finalization, duplicate cooldown |
| Backend | `_is_retryable_job`, `BackendToken` cache validity, queue read/write, flush success/failure/exhausted/skipped, AI payload excludes `vehicle_id` |
| RTSP | `_attempt_rtsp_reconnect` with fake `VideoCapture`, shutdown finalization guard, credential masking in `_source_label` |

### 6.3 Integration coverage

CLI commands exercised via `main.main([...])` with mocked `ANPRProcessor` / `BackendClient`:

- `check-config`
- `run --source image --dry-run --strict`
- `run --source video --dry-run --strict`
- `flush-backend-queue` (disabled backend and fake client)

### 6.4 AI commands

```bash
cd ai-anpr-v1
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pytest
python main.py check-config
```

**Note:** Strict dry-run against repository sample media requires local YOLO `.pt` files. CI uses mocked processor tests instead. Manual strict dry-run:

```bash
python main.py run --source image --image samples/images/<sample>.jpg --dry-run --strict
python main.py run --source video --video samples/videos/<sample>.mp4 --dry-run --strict
```

## 7. Laravel Backend Test Strategy

### 7.1 Existing suites (preserved)

| File | Focus |
| ---- | ----- |
| `tests/Feature/AnprMonitoringTest.php` | M12 list queries, filters, camera credential hiding, image upload/file routes |
| `tests/Feature/AnprVehicleLinkingTest.php` | M13 vehicle auto-link/create, immutability, admin vehicle endpoints, legacy plate normalization |

### 7.2 M14 additions

| File | Focus |
| ---- | ----- |
| `tests/Feature/AnprM14RegressionTest.php` | AI-compatible payload (no `vehicle_id`), validation envelope, auth, resource relations, image metadata, event logs, legacy separator linking |

### 7.3 Backend commands

```bash
cd backend-laravel-v1
php artisan test --filter=Anpr
php artisan test
```

## 8. React Frontend Test Strategy

### 8.1 Stack

| Package | Role |
| ------- | ---- |
| `vitest` | Test runner (Vite-compatible) |
| `jsdom` | DOM environment |
| `@testing-library/react` | Component and hook rendering |
| `@testing-library/jest-dom` | DOM matchers |
| `@testing-library/user-event` | Interaction simulation |

### 8.2 Layout

```text
frontend-react-v1/
  vitest.config.mjs
  src/test/setupTests.js
  src/test/testUtils.jsx
  src/feature/anpr-monitoring/repositories/AnprMonitoringRepository.test.js
  src/feature/anpr-monitoring/controllers/useAnprMonitoringController.test.js
  src/feature/anpr-monitoring/components/AnprMonitoringComponents.test.jsx
  src/feature/management-vehicle/VehicleManagement.test.jsx
```

### 8.3 Coverage summary

- **AnprMonitoringRepository** — query params, filter mapping, pagination envelope, missing vehicle/images, image sort order, partial payloads
- **useAnprMonitoringController** — initial load, refresh, live polling start/stop, reconnecting state, highlight IDs, timer cleanup (fake timers)
- **UI components** — `AnprLiveIndicator`, `AnprEventTable`, `AnprEventSummaryCards`, `AnprEvidenceGallery`
- **Vehicle management** — `VehicleManagementRepository`, `VehicleEditDrawer` read-only plate/source

### 8.4 Frontend commands

```bash
cd frontend-react-v1
yarn install
yarn lint
yarn test
yarn build
```

## 9. Manual End-to-End Test Matrix

Execute in order when validating a release candidate. Record pass/fail and attach evidence paths.

| # | Manual Test Case | Preconditions | Steps | Expected Result | Evidence to Capture | Pass/Fail | Evidence Location |
| - | ---------------- | ------------- | ----- | --------------- | ------------------- | --------- | ----------------- |
| 1 | AI dry-run image | Python venv, `requirements.txt` installed; sample image in `samples/images/`; YOLO models in `models/` for strict mode | `python main.py run --source image --image samples/images/<sample>.jpg --dry-run --strict` | Run directory created under `runs/`; `events.jsonl`, `worker_summary.json`, evidence files or summary counts present | Terminal output; `runs/run_*/worker_summary.json` | | |
| 2 | AI dry-run video | Sample MP4 in `samples/videos/`; models available | `python main.py run --source video --video samples/videos/<sample>.mp4 --dry-run --strict` | Summary shows source-end finalization; events written | `worker_summary.json` `tracks_finalized_source_end` | | |
| 3 | AI RTSP short run | `ANPR_RTSP_URL` in `.env`; camera reachable on LAN | `python main.py run --source rtsp --max-seconds 30 --dry-run --strict` | Runtime opens stream, processes frames, shuts down cleanly (`stop_reason` logged) | `runs/run_*/worker.log` tail | | |
| 4 | AI RTSP live backend-enabled run | Backend running; `ANPR_BACKEND_ENABLED=true`; valid camera UUID; upload or metadata mode configured | `python main.py run --source rtsp --max-seconds 60 --strict` (no `--dry-run`) | Laravel receives ANPR event; evidence registered per mode | Backend `anpr_events` row; `anpr_images` rows or upload paths | | |
| 5 | Backend event creation | Admin JWT; Laravel migrated | `POST /api/anpr-events` with AI-compatible body (no `vehicle_id`) | Event stored; retrievable via `GET /api/anpr-events/{id}` | API response JSON | | |
| 6 | Evidence display | Event with resolvable images under `ANPR_IMAGE_ROOTS` or upload storage | Open `/admin/anpr-monitoring/{id}` as Admin/Security Operator | Detail page shows evidence gallery previews or safe unavailable state | Browser screenshot | | |
| 7 | Frontend live ANPR list | Backend seeding or live AI posting; operator logged in | Open `/admin/anpr-monitoring`; wait ≥10s without refresh | New rows appear; LIVE indicator active; new IDs highlighted briefly | Screen recording or two screenshots | | |
| 8 | Vehicle auto-link | Existing vehicle with plate `ABC1001` | Post ANPR event with plate `abc-1001` | Event `vehicle_id` matches existing record; no duplicate vehicle | API response `data.vehicle` | | |
| 9 | Vehicle admin edit | Admin user | `/admin/management-vehicle` → edit drawer | Owner/type/status/notes update; plate and source remain read-only | Before/after API or UI screenshot | | |
| 10 | Flagged vehicle detection | Vehicle `status=flagged` for test plate | Post ANPR event for that plate | `is_flagged=true` on event regardless of AI `is_flagged=false` | API response | | |
| 11 | Queue retry after backend downtime | `ANPR_BACKEND_ENABLED=true`; queued job in `.cache/backend_queue.jsonl` | Stop Laravel → run AI finalize → start Laravel → `python main.py flush-backend-queue` | Job retries and eventually `succeeded` or reaches `exhausted` with logged attempts | Queue file + flush terminal output | | |

## 10. Test Commands

| Component | Command |
| --------- | ------- |
| AI unit + integration | `cd ai-anpr-v1 && python -m pytest` |
| AI config check | `cd ai-anpr-v1 && python main.py check-config` |
| Backend ANPR only | `cd backend-laravel-v1 && php artisan test --filter=Anpr` |
| Backend full suite | `cd backend-laravel-v1 && php artisan test` |
| Frontend lint | `cd frontend-react-v1 && yarn lint` |
| Frontend tests | `cd frontend-react-v1 && yarn test` |
| Frontend build | `cd frontend-react-v1 && yarn build` |

## 11. Acceptance Criteria

- [x] AI pytest suite covers config, plates, tracking, backend queue, RTSP helpers, and CLI contracts without real models/camera
- [x] Laravel ANPR Feature tests cover monitoring, vehicle linking, and M14 regression gaps
- [x] React Vitest suite covers ANPR monitoring and vehicle management critical paths
- [x] Manual E2E matrix documented with preconditions, steps, and evidence placeholders
- [x] M12 live polling and M13 vehicle linking behavior not weakened
- [x] AI event payload does not include `vehicle_id`

## 12. Known Limitations

- **No real model inference in CI** — integration tests mock `ANPRProcessor`; strict dry-run with weights remains a manual step
- **No real RTSP in automated tests** — reconnect logic tested with fake `VideoCapture`
- **No browser E2E automation** — manual matrix required for full UI + camera + backend timing scenarios
- **Sample media** — repository may ship without committed sample images/videos; operators must supply local files for manual strict runs
- **Lint baseline** — `yarn lint` may report pre-existing issues outside ANPR modules; M14 does not mandate full-repo lint cleanup

## 13. M14 Pass Condition

AI, backend, frontend, and end-to-end tests cover the complete ANPR flow, including live frontend updates and linked vehicle records.
