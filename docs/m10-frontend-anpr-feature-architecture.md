# M10 — Frontend ANPR Feature Architecture

## Milestone Summary

**M10** delivers a React-based ANPR monitoring feature that consumes Laravel ANPR APIs and presents detections, evidence metadata, and lifecycle logs to **Admin** and **Security Operator** users. The Python AI runtime (M9) continues to deliver finalized events to Laravel; M10 does not change detection, OCR, tracking, queue, or evidence delivery behavior.

## Objective

Implement an end-to-end frontend monitoring flow:

```text
Laravel ANPR Event
→ Laravel ANPR Images
→ Laravel ANPR Logs
→ React Dashboard Display
```

The feature follows the existing frontend Clean Architecture pattern under `frontend-react-v1/src/feature/anpr-monitoring/`.

## Scope

### In Scope

- Datasource integration with Laravel ANPR REST endpoints via `src/api/api.js`
- Repository normalization for events, images, cameras, vehicles, and logs
- Controller hooks with isolated local state (no Redux/Zustand)
- ANPR event list and detail pages
- Evidence gallery with safe preview URL resolution
- Event log display with JSON/plain-text message handling
- Role-protected routes for Admin and Security Operator
- Sidebar navigation entry under Operator menu
- Manual Refresh action on list and detail pages
- Minimal README milestone update in `ai-anpr-v1`

### Out of Scope

- Realtime/WebSocket ANPR updates
- Binary image upload from the frontend
- New Laravel API endpoints (unless strictly required)
- Changes to Python detection, OCR, tracking, queue, or evidence delivery
- Cloud storage integration
- Polling automation (manual refresh only in M10)

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────────┐
│  Views (AnprEventList, AnprEventDetail)                       │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  Controllers (useAnprMonitoringController,                    │
│               useAnprEventDetailController)                   │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  AnprMonitoringRepository (normalize, filter, paginate)       │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  anprMonitoringService → api.js → Laravel /api/anpr-*        │
└─────────────────────────────────────────────────────────────┘
```

## Frontend Feature Structure

```text
src/feature/anpr-monitoring/
├── views/
│   ├── AnprEventList.jsx
│   └── AnprEventDetail.jsx
├── components/
│   ├── AnprEventTable.jsx
│   ├── AnprEventSummaryCards.jsx
│   ├── AnprEvidenceGallery.jsx
│   ├── AnprEventLogs.jsx
│   ├── AnprStatusChip.jsx
│   └── AnprEmptyState.jsx
├── controllers/
│   └── useAnprMonitoringController.js
├── repositories/
│   └── AnprMonitoringRepository.js
├── datasources/
│   └── anprMonitoringService.js
└── styles/
    (inline MUI sx; no dedicated styles module required for M10)
```

## File-by-File Responsibilities

| File | Responsibility |
|------|----------------|
| `datasources/anprMonitoringService.js` | HTTP calls to `/anpr-events`, `/anpr-images`, `/anpr-event-logs`; error shaping; paginator unwrap helper |
| `repositories/AnprMonitoringRepository.js` | Normalize API payloads; resolve preview URLs; filter/paginate events client-side |
| `controllers/useAnprMonitoringController.js` | List/detail state, loading, refresh, filters, pagination, navigation |
| `views/AnprEventList.jsx` | Monitoring dashboard shell with filters, table, pagination, refresh |
| `views/AnprEventDetail.jsx` | Event detail shell with summary, evidence, logs, raw metadata |
| `components/AnprEventTable.jsx` | Presentational detection table |
| `components/AnprEventSummaryCards.jsx` | Plate, confidence, camera, vehicle, coordinates |
| `components/AnprEvidenceGallery.jsx` | Ordered full/plate/annotated evidence cards |
| `components/AnprEventLogs.jsx` | Chronological lifecycle log list |
| `components/AnprStatusChip.jsx` | Validity, flagged, and evidence status chips |
| `components/AnprEmptyState.jsx` | Empty list placeholder |

## API Integration

| Endpoint | Usage |
|----------|-------|
| `GET /anpr-events` | Paginated event list (`page`, `per_page`) |
| `GET /anpr-events/{id}` | Primary detail source; eager-loads `camera`, `vehicle`, `images`, `logs` |
| `GET /anpr-images?anpr_event_id={id}&per_page=100` | Fallback when detail response has no images |
| `GET /anpr-event-logs?per_page=100` | Fallback when detail has no logs; filtered client-side by `anpr_event_id` |

All responses use the Laravel envelope:

```json
{ "success": true, "message": "...", "data": { ... } }
```

Paginated list endpoints return the Laravel paginator inside `data` with `data.data` as the row array.

## Repository Normalization

The repository converts backend snake_case models into stable frontend objects.

**Event shape:**

```js
{
  id, plateNumber, confidence, confidencePercent,
  detectionTime, formattedDetectionTime,
  isValid, isFlagged, latitude, longitude,
  camera, vehicle, images, imageMap, logs,
  evidenceCount, hasEvidence, raw
}
```

**Image shape:**

```js
{
  id, anprEventId, imageType, filePath, fileSize,
  resolution, expiresAt, previewUrl, raw
}
```

**Log shape:**

```js
{
  id, anprEventId, stage, message,
  createdAt, formattedCreatedAt, raw
}
```

Optional relationships (`camera`, `vehicle`, `images`, `logs`) are handled safely when absent.

## Controller State Management

State is isolated inside controller hooks — no global store.

**List state:** `events`, `pagination`, `filters`, `loading`, `refreshing`, `error`

**Filters:**

- Plate number search (client-side when active; fetches up to 100 rows)
- Valid / invalid / all (client-side)
- Flagged / not flagged / all (client-side)

When no filters are active, pagination is server-driven via `page` and `per_page`.

**Detail controller:** loads `GET /anpr-events/{id}` first. Images and logs endpoints are called only when the detail payload does not already include them, avoiding duplicate API work.

## Event List Page

Route: `/admin/anpr-monitoring`

Displays:

- Page title **ANPR Monitoring** with short description
- Refresh button
- Plate search and validity/flagged filters
- Detection table: plate, confidence, detection time, camera, valid, flagged, evidence, actions
- Loading, error, and empty states
- Pagination footer

## Event Detail Page

Route: `/admin/anpr-monitoring/:anprEventId`

Displays:

- Plate, confidence, detection time, valid/flagged chips
- Camera and vehicle panels when present
- Latitude/longitude when present
- Evidence gallery (full → plate → annotated)
- Event logs (stages such as `ai_event_created`, `ai_images_registered`, `ai_evidence_delivered`, `ai_job_succeeded`)
- Compact raw metadata JSON panel
- Back and Refresh actions

## Evidence Display Strategy

The backend stores **`file_path`** as metadata — not a guaranteed browser-loadable URL. The repository resolves previews in this order:

1. Explicit URL fields if present: `url`, `image_url`, `public_url`, `file_url`
2. Absolute `http://` or `https://` values in `file_path`
3. Paths starting with `/storage/` resolved against the backend origin (derived from `VITE_API_BASE_URL`)

If no usable URL exists, the gallery shows a professional **Preview unavailable** card with path, type, file size, and resolution. The UI never fabricates URLs pointing at local `runs/` filesystem paths.

**M10 depends on the backend exposing or resolving evidence paths for actual image previews.**

## Routing and Permissions

Registered in `src/routes/MainRoutes.jsx`:

| Route | Roles |
|-------|-------|
| `/admin/anpr-monitoring` | Admin, Security Operator |
| `/admin/anpr-monitoring/:anprEventId` | Admin, Security Operator |

Uses `RoleProtectedRoute` via the existing `adminOrOperator` helper. Guard users are redirected to `/forbidden`.

## Sidebar Navigation

Added to `src/menu-items/operator.js`:

- **ANPR Monitoring** → `/admin/anpr-monitoring` (Tabler `IconCar`)

Security Operator menu filtering in `getMenuItemsForRole.js` includes `operator-anpr-monitoring` alongside patrol monitoring.

## Error, Loading, and Empty States

- **Loading:** centered `CircularProgress` on initial fetch
- **Refreshing:** disables refresh button label; list remains visible
- **Error:** MUI `Alert` with API message; detail page offers back navigation
- **Empty:** `AnprEmptyState` when no detections match filters

## README Update

`ai-anpr-v1/README.md` milestone line updated to M10 with a short pointer to this document. Essential setup and CLI content preserved.

## Verification Checklist

1. Login as Admin
2. Open `/admin/anpr-monitoring`
3. Confirm ANPR events load
4. Open an event detail page
5. Confirm evidence metadata appears
6. Confirm preview images appear only when a valid browser-loadable URL exists
7. Confirm event logs appear when available
8. Confirm Security Operator can access the feature
9. Confirm Guard cannot access the feature
10. Confirm direct refresh of routes works with Vite/React Router
11. Run `yarn lint` and `yarn build` in `frontend-react-v1`

## Passing Criteria

M10 passes when:

- `src/feature/anpr-monitoring/` exists and follows the feature pattern
- Datasource calls Laravel APIs through `api.js`
- Repository normalizes events, images, and logs
- Controller isolates loading, error, pagination, and detail state
- List and detail pages display detections, evidence, and logs
- Routes are protected for Admin and Security Operator
- Sidebar exposes ANPR Monitoring
- README updated minimally
- This document exists and is complete
- `yarn lint` and `yarn build` pass (or failures are documented)

## Known Limitations

- No realtime ANPR feed; manual refresh only
- Backend list endpoint does not support plate/validity/flagged query filters — applied client-side on the current fetch window
- `GET /anpr-event-logs` has no `anpr_event_id` filter; log fallback fetches 100 global logs and filters in the browser
- Image previews require backend URL resolution; local AI `runs/` paths are not directly viewable in the browser
- Camera `password` may appear in raw API payloads (backend serialization); not displayed in the UI

## M11 Handoff Notes

Potential follow-ups for M11:

- Backend filtering for plate number, validity, flagged status, and date range
- Dedicated `anpr_event_id` filter on event logs index
- Signed or public evidence URL generation in Laravel for reliable previews
- Optional polling or WebSocket push for new detections
- Binary evidence upload endpoint if upload mode is activated
- Hide sensitive camera credentials at the API layer
