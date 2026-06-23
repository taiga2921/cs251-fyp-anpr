# M12 — Live ANPR Monitoring Architecture

## Milestone Summary

Milestone 12 (M12) connects the M11 RTSP AI runtime, Laravel ANPR APIs, and the React ANPR monitoring page so **new ANPR detections appear in the frontend automatically** without manual browser refresh. This milestone delivers **live ANPR event monitoring**, not video livestreaming.

## Objective

Provide safe, efficient live monitoring of ANPR detection rows, evidence availability, and operational status feedback while preserving existing filters, pagination, manual refresh, and backend security boundaries.

**Pass condition:**

Live ANPR monitoring works end-to-end: while the AI RTSP runtime is running, new ANPR detections appear in the React ANPR monitoring table automatically, with a blinking red LIVE indicator beside the table title and tooltip text **Live update**.

## Scope

### In Scope

- Laravel `GET /api/anpr-events` enhancements for live polling (`sort`, `direction`, `since`, existing filters)
- React ANPR monitoring live polling (5-second interval) inside `useAnprMonitoringController`
- Blinking red **LIVE** indicator beside the ANPR table title with tooltip **Live update**
- Temporary highlight for newly appeared detection rows (3–5 seconds)
- Degraded **RECONNECTING** state on polling failure without clearing existing rows
- Manual refresh preserved
- Targeted documentation updates in `ai-anpr-v1`, `backend-laravel-v1`, and `frontend-react-v1`

### Out of Scope

- Video livestreaming or RTSP preview in the browser
- WebSocket/Reverb ANPR event push (polling is preferred for M12)
- M13 linked vehicle auto-creation/management
- AI detection logic changes (M11 owns RTSP runtime)
- New database tables or AI POST payload changes

## Existing Skeleton Review

| Layer | Existing (pre-M12) | M12 extension |
| ----- | ------------------ | ------------- |
| AI runtime (M11) | RTSP processing, backend queue, evidence upload | No runtime changes required |
| Laravel API (M10) | `GET /api/anpr-events` with filters, pagination, safe camera resource | Add `sort`, `direction`, `since` for live polling |
| React UI (M10) | List, detail, filters, manual refresh | Live polling, LIVE indicator, row highlighting |

## Architecture Overview

```text
RTSP Camera
→ AI ANPR Runtime (M11)
→ Backend Queue Flush
→ Laravel POST /api/anpr-events (+ evidence upload)
→ Laravel GET /api/anpr-events (latest-first, since/sort filters)
→ React ANPR Monitoring (5s polling)
→ LIVE indicator + new-row highlight
```

M11 handles RTSP runtime stability. M12 handles frontend/backend live **event** monitoring. Live ANPR monitoring means event auto-refresh, not video streaming.

## Backend Latest Event Query Support

`AnprEventController@index` supports:

| Parameter | Purpose |
| --------- | ------- |
| `page`, `per_page` | Pagination |
| `plate_number`, `search` | Plate filter |
| `is_valid`, `is_flagged` | Status filters |
| `date_from`, `date_to`, `camera_id` | Existing filters |
| `sort` | `detection_time` (default), `created_at`, `plate_number`, `confidence` |
| `direction` | `desc` (default) or `asc` |
| `since` | ISO date — returns rows where `created_at > since` **or** `detection_time > since` |

The `since` OR clause accommodates queue-delivered events that may have an older `detection_time` but a recent `created_at`.

Default ordering: `detection_time` descending (newest first). Response envelope: `{ success, message, data }` with Laravel pagination metadata. Eager loads: `vehicle`, `camera`, `images`. Camera credentials remain hidden via `AnprCameraResource`.

## Frontend Live Polling Controller Design

`useAnprMonitoringController` manages:

- `liveEnabled` (default `true`)
- `liveStatus`: `live` | `reconnecting` | `paused`
- `lastUpdatedAt`, `liveError`, `highlightedEventIds`
- Refs: `isMountedRef`, `pollTimerRef`, `inFlightRef`, `lastSeenEventIdsRef`

**Polling rules:**

1. Initial load on mount.
2. Poll every 5 seconds via `setTimeout` chain (cleanup on unmount).
3. Prevent overlapping requests with `inFlightRef`.
4. Compare event IDs; highlight newly appeared rows for ~4 seconds.
5. On poll failure: set `reconnecting`, keep existing rows, retry on next interval.
6. Manual refresh and filter/pagination changes remain functional.
7. Reset `lastSeenEventIdsRef` when filters or page change to avoid false highlights.

## LIVE Indicator Design

`AnprLiveIndicator.jsx`:

- Red blinking dot + `LIVE` chip beside **ANPR Monitoring** title
- Tooltip: **Live update** (includes last updated time when available)
- `RECONNECTING` warning state when polling fails
- Material UI `sx` + keyframes; responsive on mobile

## New Event Highlighting Behavior

`AnprEventTable` accepts `highlightedEventIds`. New rows receive a subtle `action.selected` background for 3–5 seconds, then the controller removes the ID from state. Existing rows are not reordered beyond API latest-first ordering.

## End-to-End Live ANPR Flow

1. AI runtime (M11) detects plate on RTSP stream and finalizes event.
2. Backend queue posts event + evidence to Laravel.
3. Laravel persists `anpr_events` and `anpr_images` rows.
4. React ANPR Monitoring page polls `GET /api/anpr-events?sort=detection_time&direction=desc&per_page=10`.
5. Controller detects new event ID not in `lastSeenEventIdsRef`.
6. Table row appears with temporary highlight; LIVE indicator shows active state.
7. Operator may open detail page for evidence (unchanged M10 behavior).

## File-by-File Responsibilities

### Backend (`backend-laravel-v1`)

| File | Role |
| ---- | ---- |
| `AnprEventController.php` | `sort`, `direction`, `since` validation and query |
| `AnprMonitoringTest.php` | Live polling query coverage |
| `documentation.md` | API parameter documentation |

### Frontend (`frontend-react-v1`)

| File | Role |
| ---- | ---- |
| `useAnprMonitoringController.js` | Live polling, highlight timers, degraded state |
| `AnprMonitoringRepository.js` | `sort`/`direction` query params |
| `AnprLiveIndicator.jsx` | LIVE / RECONNECTING UI |
| `AnprEventList.jsx` | Title + indicator + last updated line |
| `AnprEventTable.jsx` | Row highlighting |
| `documentation.md` | M12 behavior notes |

### AI (`ai-anpr-v1`)

| File | Role |
| ---- | ---- |
| `README.md` | Current milestone M12, link to this doc |
| `ai-anpr-modules.md` | M12 flow note |
| `docs/m12-live-anpr-monitoring-architecture.md` | This document |

## Backend/Frontend/AI Compatibility

- AI POST payload unchanged; no new fields required.
- JWT `auth:api` protects list endpoint.
- `AnprCameraResource` continues to omit IP, port, RTSP URL, username, password.
- Frontend repository architecture unchanged (view → controller → repository → service).
- Vehicle resource fields preserved; M13 auto-linking not implemented.

## Verification Checklist

- [ ] `php artisan test --filter=AnprMonitoringTest` passes
- [ ] `yarn lint` and `yarn build` pass in frontend
- [ ] Backend running; frontend on ANPR Monitoring page
- [ ] AI RTSP runtime with `ANPR_BACKEND_ENABLED=true` delivers events
- [ ] New detection appears without browser refresh
- [ ] Blinking red LIVE indicator beside table title
- [ ] Tooltip shows **Live update**
- [ ] New row highlight appears then fades
- [ ] Manual refresh still works
- [ ] Polling failure shows RECONNECTING without clearing rows
- [ ] Detail page evidence still loads
- [ ] Camera IP/RTSP credentials not exposed

## Passing Criteria

- Latest ANPR events fetch reliably from Laravel with correct default ordering
- React auto-refreshes every 5 seconds while page is open
- Polling stops on unmount (navigate away)
- No duplicate rows; filters and pagination stable
- LIVE indicator and tooltip per specification
- Backend tests and frontend lint/build pass
- Documentation updated minimally and accurately

## Known Limitations

- Polling interval is fixed at 5 seconds (not configurable in UI).
- First-page polling only; deep pagination does not auto-merge new events from other pages.
- No WebSocket push; slight delay (up to poll interval) before new events appear.
- Highlighting applies to IDs newly seen on the current page after initial load.
- Video preview/streaming remains out of scope.
