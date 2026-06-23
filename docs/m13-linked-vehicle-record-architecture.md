# M13 — Linked Vehicle Record Architecture

## Milestone Summary

Milestone 13 (M13) ensures every ANPR event ingested by Laravel is linked to a vehicle record. The backend normalizes plate numbers, reuses existing vehicles, auto-creates unknown plates with `source = auto_detected`, and exposes linked vehicle data to the React monitoring UI. Admin users can manage vehicle metadata without changing plate number or source.

## Objective

Automate vehicle linking at ANPR event ingestion so operators see consistent vehicle context in ANPR monitoring, while admins maintain owner/type/status/notes through a dedicated management module.

**M13 Pass Condition:** When the AI runtime posts an ANPR event without `vehicle_id`, Laravel links or creates the vehicle, returns the vehicle relation in the event resource, and the React ANPR event detail displays linked vehicle information. Admins can manage vehicle records under Admin → Management → Vehicle with immutable plate number and source.

## Scope

### In Scope

- `AnprVehicleLinker` service for normalization, lookup, and safe auto-creation
- `AnprEventController@store` integration (backend-owned linking)
- Admin-only vehicle management API (`GET`, `PATCH`; optional `POST`)
- `AnprVehicleResource` responses for vehicle endpoints
- React `feature/management-vehicle` (list, detail, edit drawer)
- ANPR event detail linked vehicle section with admin navigation link
- Targeted backend tests and documentation updates

### Out of Scope

- AI runtime payload changes (`vehicle_id` not sent by AI)
- M14 broad testing architecture
- M15 model/runtime tuning
- Vehicle delete workflows (existing delete endpoint retained but not required for M13)
- Video livestreaming or M12 polling changes

## Existing System Review

| Component | Pre-M13 | M13 change |
| --------- | ------- | ---------- |
| `vehicles` table | Plate, owner, type, status, source, notes | Used as canonical link target |
| `anpr_events.vehicle_id` | Nullable, optional on store | Always set on create |
| `AnprEventController@store` | Accepted optional `vehicle_id` | Ignores client `vehicle_id`; links via service |
| `VehicleController` | Open to all authenticated users | Admin-only; hardened update rules |
| React ANPR detail | Partial vehicle display | Full linked vehicle card + admin link |
| `feature/management-vehicle` | Missing | New admin module |

## Architecture Overview

```text
AI runtime POST /api/anpr-events (plate_number, no vehicle_id)
→ Laravel validates payload
→ AnprVehicleLinker.normalizePlateNumber()
→ AnprVehicleLinker.linkOrCreate()
→ AnprEvent created with vehicle_id + normalized plate
→ is_flagged derived from vehicle.status === flagged
→ AnprEventResource returns vehicle relation
→ React ANPR detail + admin vehicle management
```

## Backend Vehicle Linking Service

`App\Services\Anpr\AnprVehicleLinker`:

| Method | Responsibility |
| ------ | -------------- |
| `normalizePlateNumber()` | Uppercase alphanumeric canonical plate |
| `linkOrCreate()` | Transactional lookup by normalized plate; create if missing |

**Auto-create defaults:**

| Field | Value |
| ----- | ----- |
| `plate_number` | Normalized plate |
| `source` | `auto_detected` |
| `status` | `normal` |
| `owner_name` | `null` |
| `vehicle_type` | `null` |
| `notes` | `null` |

Existing vehicle metadata is never overwritten on relink.

## ANPR Event Store Integration

`AnprEventController@store`:

1. Validates AI-compatible payload (no `vehicle_id` required)
2. Normalizes `plate_number`
3. Links or creates vehicle
4. Creates event with `vehicle_id`, normalized plate, `is_flagged` from vehicle status
5. Eager-loads `vehicle`, `camera`, `images`
6. Returns `AnprEventResource`

`AnprEventController@update`: when `plate_number` changes, vehicle is relinked consistently.

## Vehicle API and Admin Permissions

Vehicle routes moved under `auth:api` + `admin` middleware.

| Endpoint | Access | Notes |
| -------- | ------ | ----- |
| `GET /api/vehicles` | Admin | Paginated list + plate search |
| `GET /api/vehicles/{id}` | Admin | `AnprVehicleResource` |
| `PATCH /api/vehicles/{id}` | Admin | Owner/type/status/notes only |
| `POST /api/vehicles` | Admin | Manual create (`source = manual`) |

**Immutable on update:** `plate_number`, `source` (422 if provided).

ANPR ingestion auto-linking uses the service directly and does not require `/api/vehicles` access from the AI runtime user.

## Frontend Vehicle Management

`src/feature/management-vehicle/`:

- List at `/admin/management-vehicle`
- Detail at `/admin/management-vehicle/view/:vehicleId`
- Sidebar: Admin → Management → Vehicle
- Edit drawer: owner, type, status, notes editable; plate and source read-only

## ANPR Event Detail Vehicle Link

`AnprEventSummaryCards` shows linked vehicle plate, status, source, owner, type, notes. Auto-detected unknown vehicles display “Auto-detected vehicle record”. Admins see **Open vehicle record** link; Security Operators see read-only vehicle context without admin management link.

## AI Runtime Impact

**No AI code changes required.**

`backend.py` continues posting:

```text
camera_id, plate_number, confidence, detection_time, is_valid, latitude, longitude
```

The AI must not send or decide `vehicle_id`. Laravel owns linking after ingestion.

## Data Integrity and Duplicate Prevention

- Unique `vehicles.plate_number` constraint
- Normalized lookup prevents duplicate rows for `ABC-1001` vs `ABC1001`
- `lockForUpdate()` inside transaction reduces race duplicates
- Existing metadata preserved on repeated detections

## Security and Privacy

- Vehicle management admin-only (403 for non-admin)
- M12 camera credential hiding unchanged
- Plate/source immutability enforced server-side

## Testing Strategy

`tests/Feature/AnprVehicleLinkingTest.php` covers:

- Reuse, auto-create, no duplicates, metadata preservation
- Flagged/whitelist vehicle behavior
- Event resource includes vehicle
- Admin-only vehicle endpoints
- Update allow/reject rules

Existing `AnprMonitoringTest` (M12) must continue passing.

## Files Changed

| Repo | Key files |
| ---- | --------- |
| `backend-laravel-v1` | `AnprVehicleLinker.php`, `AnprEventController.php`, `VehicleController.php`, `routes/api.php`, `AnprVehicleLinkingTest.php` |
| `frontend-react-v1` | `feature/management-vehicle/*`, `AnprEventSummaryCards.jsx`, routes, menu |
| `ai-anpr-v1` | `README.md`, `docs/m13-linked-vehicle-record-architecture.md`, `ai-anpr-modules.md` |

## Acceptance Criteria

- Every new ANPR event has `vehicle_id`
- Existing vehicles reused; unknown plates auto-created
- No duplicate vehicles for same normalized plate
- Existing metadata not overwritten
- Flagged vehicle → event `is_flagged = true`
- Event response includes vehicle
- Vehicle APIs admin-only; plate/source immutable on update
- Admin vehicle management UI functional
- ANPR detail shows linked vehicle context

## M13 Hardening (Post-Acceptance)

- Backend rejects empty-after-normalization plate values with 422 on `plate_number` (`POST /api/anpr-events`, `PATCH /api/anpr-events/{id}`, `POST /api/vehicles`).
- Manual vehicle create normalizes plates and rejects normalized duplicates through shared `AnprVehicleLinker` lookup (including legacy separators `-`, space, `.`, `_`, `/`, `\`).
- `PATCH /api/anpr-events/{id}` prohibits `vehicle_id` and `is_flagged`; plate changes relink via `AnprVehicleLinker` and re-derive `is_flagged` from linked vehicle status.
- The backend normalized lookup uses MySQL-safe `CHAR(92)` for backslash removal; the AI payload remains unchanged.
- AI event payload remains unchanged (no `vehicle_id`).

## M13 Pass Condition

When the AI runtime posts an ANPR event without `vehicle_id`, Laravel links or creates the vehicle, returns the vehicle relation in the event resource, and the React ANPR event detail displays linked vehicle information. Admins can manage vehicle records under Admin → Management → Vehicle with immutable plate number and source.
