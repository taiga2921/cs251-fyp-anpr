# M10 — Frontend ANPR Feature Architecture

## Milestone Summary

**M10** delivers a React-based ANPR monitoring feature that consumes Laravel ANPR APIs and presents detections and evidence to **Admin** and **Security Operator** users. The Python AI runtime (M9) continues to deliver finalized events to Laravel; M10 does not change detection, OCR, tracking, queue, or evidence delivery behavior.

## Objective

Implement an end-to-end frontend monitoring flow:

```text
Laravel ANPR Event
→ Laravel ANPR Images
→ React Dashboard Display
```

The feature follows the existing frontend Clean Architecture pattern under `frontend-react-v1/src/feature/anpr-monitoring/`.

## Scope

### In Scope

- Datasource integration with Laravel ANPR REST endpoints via `src/api/api.js`
- Repository normalization for events, images, cameras, and vehicles
- Controller hooks with isolated local state (no Redux/Zustand)
- ANPR event list and detail pages
- Evidence gallery with backend-resolved preview URLs
- Backend-supported list filters (plate, validity, flagged)
- Protected evidence file endpoint with allowed-root path resolution
- Safe camera serialization in ANPR API responses
- Role-protected routes for Admin and Security Operator
- Sidebar navigation entry under Operator menu
- Manual Refresh action on list and detail pages
- Minimal README milestone update in `ai-anpr-v1`

### Out of Scope

- Realtime/WebSocket ANPR updates
- Frontend rendering of ANPR event lifecycle logs
- Binary image upload from the frontend
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
│  AnprMonitoringRepository (normalize, build query params)     │
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
| `datasources/anprMonitoringService.js` | HTTP calls to `/anpr-events` and `/anpr-images`; error shaping; paginator unwrap helper |
| `repositories/AnprMonitoringRepository.js` | Normalize API payloads; build backend filter query params; resolve preview URLs |
| `controllers/useAnprMonitoringController.js` | List/detail state, loading, refresh, filters, pagination, navigation |
| `views/AnprEventList.jsx` | Monitoring dashboard shell with filters, table, pagination, refresh |
| `views/AnprEventDetail.jsx` | Event detail shell with summary and evidence |
| `components/AnprEventTable.jsx` | Presentational detection table |
| `components/AnprEventSummaryCards.jsx` | Plate, confidence, camera, vehicle, coordinates |
| `components/AnprEvidenceGallery.jsx` | Ordered full/plate/annotated evidence cards with authenticated preview loading |
| `components/AnprStatusChip.jsx` | Validity, flagged, and evidence status chips |
| `components/AnprEmptyState.jsx` | Empty list placeholder |

## API Integration

| Endpoint | Usage |
|----------|-------|
| `GET /anpr-events` | Paginated event list with backend filters (`page`, `per_page`, `plate_number`, `search`, `is_valid`, `is_flagged`, `date_from`, `date_to`, `camera_id`) |
| `GET /anpr-events/{id}` | Primary detail source; eager-loads safe `camera`, `vehicle`, and `images` |
| `GET /anpr-images?anpr_event_id={id}&per_page=100` | Fallback when detail response has no images |
| `GET /anpr-images/{id}/file` | Protected evidence file proxy when the path resolves under configured ANPR image roots |

All responses use the Laravel envelope:

```json
{ "success": true, "message": "...", "data": { ... } }
```

Paginated list endpoints return the Laravel paginator inside `data` with `data.data` as the row array.

**Note:** Backend event logs remain available through `/anpr-event-logs` for audit and debugging, but M10 does not render them in the monitoring UI.

## Repository Normalization

The repository converts backend snake_case models into stable frontend objects.

**Event shape:**

```js
{
  id, plateNumber, confidence, confidencePercent,
  detectionTime, formattedDetectionTime,
  isValid, isFlagged, latitude, longitude,
  camera, vehicle, images, imageMap,
  evidenceCount, hasEvidence
}
```

**Image shape:**

```js
{
  id, anprEventId, imageType, filePath, fileSize,
  resolution, expiresAt, previewUrl
}
```

Optional relationships (`camera`, `vehicle`, `images`) are handled safely when absent.

## Controller State Management

State is isolated inside controller hooks — no global store.

**List state:** `events`, `pagination`, `filters`, `loading`, `refreshing`, `error`

**Filters (server-side):**

- Plate number search → `plate_number`
- Valid / invalid / all → `is_valid`
- Flagged / not flagged / all → `is_flagged`

Pagination is server-driven via `page` and `per_page`.

**Detail controller:** loads `GET /anpr-events/{id}` first. The images index endpoint is called only when the detail payload does not already include images.

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
- Back and Refresh actions

Raw backend event payloads are not rendered on the detail page to avoid exposing sensitive relationship fields such as camera credentials.

## Evidence Display Strategy

Normal operational flow is **upload mode** → Laravel stores files under `storage/app/anpr` → `AnprImageResource` exposes protected preview URLs.

The backend stores **`file_path`** relative to the ANPR image root. For uploaded evidence, Laravel resolves files under `storage/app/anpr` by default. For metadata mode (local development fallback), paths resolve when `ANPR_IMAGE_ROOTS` includes the AI `runs/` directory.

Laravel exposes:

- `url` and `image_url` pointing to `GET /api/anpr-images/{id}/file`
- A protected file response that rejects path traversal and unavailable files

The frontend evidence gallery:

1. Uses `url` / `image_url` from normalized image payloads
2. Fetches protected file URLs with the JWT `Authorization` header and renders a blob preview
3. Shows a **Preview unavailable** placeholder when no resolvable URL exists or loading fails (common in metadata-only setups without configured roots)

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
4. Test plate, validity, and flagged filters
5. Open an event detail page
6. Confirm evidence metadata appears
7. Confirm evidence previews load when Laravel can resolve files
8. Confirm missing evidence files show safe placeholders
9. Confirm no event logs or raw metadata are displayed
10. Confirm camera credentials are not visible in network responses
11. Confirm Security Operator can access the feature
12. Confirm Guard cannot access the feature
13. Run `yarn lint` and `yarn build` in `frontend-react-v1`
14. Run `php artisan test` in `backend-laravel-v1`

## Passing Criteria

M10 passes when:

- `src/feature/anpr-monitoring/` exists and follows the feature pattern
- Datasource calls Laravel APIs through `api.js`
- Repository normalizes events and images
- Controller isolates loading, error, pagination, and detail state
- List and detail pages display detections and evidence
- Routes are protected for Admin and Security Operator
- Sidebar exposes ANPR Monitoring
- README updated minimally
- This document exists and is complete
- `yarn lint` and `yarn build` pass (or failures are documented)
- Backend filters, safe camera serialization, and evidence file proxy are implemented

## Known Limitations

- No realtime ANPR feed; manual refresh only

## M11 Handoff Notes

Potential follow-ups for M11:

- Optional polling or WebSocket push for new detections
- Date-range filters in the frontend UI (`date_from`, `date_to` already supported by backend)
- Optional operator-facing lifecycle log viewer separate from the main monitoring UI
