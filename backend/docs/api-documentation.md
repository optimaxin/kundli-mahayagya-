# API documentation

* Interactive docs: `http://localhost:8000/docs` (Swagger UI) and `/redoc`.
* Machine-readable spec: [`docs/openapi.json`](openapi.json). To regenerate it:
  `python -c "import json; from app.main import app; json.dump(app.openapi(), open('docs/openapi.json','w'), indent=2)"`.
* Base path: `/api/v1`. All bodies are JSON (UTF-8). All timestamps are ISO-8601 UTC. Dates
  and times of sessions are in IST (Asia/Kolkata).

## Conventions

**Success envelope**

```json
{ "success": true, "data": { ... }, "meta": { "page": 1, "page_size": 25, "total": 120, "total_pages": 5 } }
```

`meta` appears only on paginated lists. Pagination uses `?page=1&page_size=25` (maximum
200). Sorting uses `?sort=<field>&order=asc|desc` where it is supported.

**Error envelope**

```json
{ "success": false,
  "error": { "code": "CAPACITY_UNAVAILABLE", "message": "No Kund has 4 free place(s) together in session 2",
             "details": { "unavailable_sessions": [2], "availability": [ ... ] } },
  "request_id": "6f1c…" }
```

Every response carries an `X-Request-ID` header. Quote it in support requests.

| HTTP | Typical codes |
|---|---|
| 400 | `IDEMPOTENCY_KEY_REQUIRED`, `IDEMPOTENCY_KEY_INVALID` |
| 401 | `UNAUTHORIZED`, `INVALID_TOKEN`, `INVALID_CREDENTIALS` |
| 403 | `FORBIDDEN` |
| 404 | `NOT_FOUND`, `INVALID_QR` |
| 409 | `CAPACITY_UNAVAILABLE`, `DUPLICATE_BOOKING`, `RESERVATION_HAS_CHECKINS`, `SESSION_COMPLETED`, `EMAIL_EXISTS`, `IDEMPOTENCY_IN_PROGRESS` |
| 422 | `VALIDATION_ERROR` (with per-field `details`), `INVALID_SESSION`, `SESSION_NOT_BOOKABLE`, `ONE_SESSION_PER_DAY`, `IDEMPOTENCY_KEY_REUSED`, `INVALID_BOOKING_NUMBER` |
| 429 | `RATE_LIMITED`, `ACCOUNT_LOCKED` (both send `Retry-After`) |
| 503 | `SERVICE_BUSY` (admission control or lock contention), `DATABASE_UNAVAILABLE` (both send `Retry-After`; safe to retry with the same `Idempotency-Key`) |

**Authentication:** `Authorization: Bearer <JWT>` from `POST /auth/login`. Staff tokens
last 30 min; scanner tokens last 8 h.

## Permission matrix

| Endpoint group | Public | SCANNER | SUPERVISOR | ADMIN |
|---|:-:|:-:|:-:|:-:|
| `GET /health`, `GET /health/ready` | ✓ | ✓ | ✓ | ✓ |
| `POST /registrations`, `GET /sessions` | ✓ | ✓ | ✓ | ✓ |
| `POST /qr/pass`, `/qr/pass/image`, `/qr/status` (token or booking number + mobile) | ✓ | ✓ | ✓ | ✓ |
| `GET /scanner/me`, `GET /scanner/recent`, `POST /scanner/scan`, `POST /scanner/checkin` | | ✓ (own session) | ✓ (`session_id` required) | ✓ (`session_id` required) |
| `POST /qr/validate` | | ✓ | ✓ | ✓ |
| `GET /bookings…`, `GET /family-members`, `POST /bookings/{bn}/cancel` | | | ✓ | ✓ |
| `GET /sessions/{id}`, `/sessions/{id}/kunds`, `/kunds/{n}`, `GET /checkins` | | | ✓ | ✓ |
| `POST /qr/{bn}/regenerate`, `POST /qr/{bn}/revoke` | | | ✓ | ✓ |
| `GET /admin/dashboard`, `GET /admin/analytics` | | | ✓ | ✓ |
| `/reports/*` (Excel exports, downloads, summary): personal data of every family | | | | ✓ |
| `GET /sessions/{id}/kund-map`, `POST /sessions/{id}/kunds/{n}/block`, `POST /bookings/{bn}/checkin` | | | ✓ | ✓ |
| `GET /offline/snapshot/{id}`, `POST /offline/sync/checkins` | | | ✓ | ✓ |
| `PATCH /sessions/{id}`, `/admin/users*`, `/admin/audit-logs`, `/admin/integrity`, `/admin/maintenance/*` | | | | ✓ |
| `POST /offline/local/*` (venue node only) | | ✓ | | |

## Endpoints

### Health

* `GET /health`: liveness.
* `GET /health/ready`: 200 when the database is reachable, migrated and seeded; 503
  otherwise.

### Auth

* `POST /auth/login` `{email, password}` returns `{access_token, token_type, expires_at, role}`.
* `POST /auth/token`: OAuth2 password form, used by the Swagger "Authorize" button.
* `GET /auth/me`, `POST /auth/logout` (revokes all of the user's tokens),
  `POST /auth/change-password`.

### Registration

`POST /registrations` requires the header `Idempotency-Key: <uuid>`.

```json
{
  "coordinator": {
    "name": "Rahul Sharma", "primary_mobile": "9876543210", "secondary_mobile": "",
    "email": "rahul@example.com", "address": "12 Civil Lines", "city": "Agra",
    "state": "Uttar Pradesh", "pincode": "282001", "gotra": "Bharadwaj",
    "sankalp_purpose": "Family wellbeing"
  },
  "members": [
    {"full_name": "Rahul Sharma", "age": 38, "gender": "male", "relationship": "Self"},
    {"full_name": "Priya Sharma", "age": 35, "gender": "female", "relationship": "Spouse", "mobile": ""}
  ],
  "selected_sessions": [1, 2, 3]
}
```

`201` response (abridged):

```json
{ "success": true, "data": {
  "booking_number": "MY26-7K3QX9PD", "status": "CONFIRMED", "coordinator_name": "Rahul Sharma",
  "primary_mobile_masked": "98******10", "member_count": 2,
  "members": [{"member_number": 1, "full_name": "Rahul Sharma", "age": 38, "gender": "male", "relationship": "Self"}, ...],
  "reservations": [{"session_id": 1, "event_date": "2026-12-14", "slot": "MORNING", "start_time": "08:00:00",
                    "end_time": "11:00:00", "kund_number": 101, "member_count": 2, "status": "CONFIRMED"}],
  "qr_pass": {"token": "<43+ chars>", "qr_payload": "MY26.<token>", "expires_at": "2026-12-22T14:30:00Z",
              "image_endpoint": "/api/v1/qr/pass/image", "note": null},
  "created_at": "2026-11-10T04:30:00Z" } }
```

Validation rules:

* Coordinator: `name`, `primary_mobile`, `city` and `state` are required. `secondary_mobile`, `email`,
  `address`, `pincode`, `gotra` and `sankalp_purpose` are optional (blank strings are accepted as empty).
  `state` also accepts `"Other"`.
* Members: `full_name`, `age` (1–110) and `gender` (`male` / `female` / `other`) are required;
  `relationship` (for example Self, Spouse, Child) and `mobile` are optional.

* 1-8 members, with no duplicate names.
* Indian mobile numbers, normalised (`+91`, a leading `0` and spaces are accepted).
* 6-digit PIN code; a valid Indian state or UT.
* Names may contain letters of any script plus `. ' -`.
* Session ids must exist, be unique, and be open (status SCHEDULED, active, at least 60 min
  before the start).
* **One session per day:** a booking cannot include both the morning and the afternoon session of
  the same date (`422 ONE_SESSION_PER_DAY`, with the offending `dates` and `sessions`). A family
  may still pick one session on each of several days, in either slot. Switch off with
  `ONE_SESSION_PER_DAY=false`.
* Unknown fields are rejected.

Behaviour:

* Retrying with the same key and body returns the same booking and token, with the header
  `Idempotent-Replayed: true`.
* If any selected session cannot fit the whole family in one Kund, the response is
  `409 CAPACITY_UNAVAILABLE` and **nothing** is booked. `details.availability` lists
  `largest_family_bookable` per session.
* `409 DUPLICATE_BOOKING` means this primary mobile already holds a confirmed reservation in one
  of the selected sessions (`details.sessions`), or, with one-session-per-day on, in either slot of
  one of the selected days (`details.dates`). A cancelled reservation frees the day again.

### Sessions and Kunds

* `GET /sessions` (public): the 16 sessions with `total_capacity`, `reserved`, `remaining`,
  `kunds_empty`, `kunds_full`, `largest_family_bookable` and `booking_open`. Use this to
  render the session picker.
* `GET /sessions/{id}`: adds families, check-ins and, after the session ends, `no_shows`.
* `PATCH /sessions/{id}` `{status?, is_active?}` (ADMIN, audited). Capacity is not editable
  through the API.
* `GET /sessions/{id}/kunds?only_occupied=true&page=…`: Kund-wise allocation with the
  families in each Kund.
* `GET /kunds/{kund_number}`: one Kund across all 16 sessions.

### Bookings (staff)

* `GET /bookings?booking_number=&mobile=&status=&session_id=&city=&sort=created_at|booking_number|member_count|coordinator_name&order=`.
  Mobile numbers are masked in the results, and searching by mobile is audited.
* `GET /bookings/{bn}`: full details including contact data (audited).
* `GET /bookings/{bn}/members`, `GET /bookings/{bn}/sessions`,
  `GET /family-members?booking_number=`.
* `POST /bookings/{bn}/cancel` `{reason, session_ids?}`. Idempotent: a repeated call
  returns `already_cancelled: true` and `released_capacity: 0`. Reservations with check-ins
  or for completed sessions cannot be cancelled.

### QR passes

* `POST /qr/pass` `{token}`: the family pass (members, sessions, Kunds) for the token
  holder.
* `POST /qr/pass/image` `{token, format: "png"|"svg", scale}`: download the QR image.
* `POST /qr/status` `{booking_number, primary_mobile}`: public status with no names.
* `POST /qr/validate` `{token}` (staff/scanner): `{valid, booking_number, booking_status, pass_active, expired}`.
* `POST /qr/{bn}/regenerate`: returns a new token once and revokes the old one.
* `POST /qr/{bn}/revoke` `{reason}`.

### Scanner

* `GET /scanner/me`: the scanner's assigned session and whether its check-in window is open.
* `POST /scanner/scan` `{qr_payload}` returns `status` = `VALID | INVALID_QR |
  INVALID_SESSION | BOOKING_CANCELLED`. On `VALID` the response includes `kund_number`,
  `roster[] {member_number, full_name, checked_in, checked_in_at}` and `checked_in_count`.
* A pass can be given as `qr_payload` (camera) **or** `booking_number` (typed Pass ID when a camera
  fails; tighter rate limit; the volunteer checks names against photo ID). Exactly one is required.
* SCANNER accounts must not send `session_id` (422 `SESSION_NOT_ALLOWED`). ADMIN/SUPERVISOR may scan
  from the console and must send `session_id` (422 `SESSION_REQUIRED` otherwise).
* Results include a `reason`: `SCANNER_UNASSIGNED`, `SESSION_INACTIVE`, `UNKNOWN_PASS`, `PASS_REVOKED`,
  `BOOKING_CANCELLED`, `RESERVATION_CANCELLED`, `NO_RESERVATION` (with `booked_sessions`),
  `SESSION_NOT_OPEN`, `SESSION_OVER`, or `ALL_CHECKED_IN`. The check-in window is ±15 minutes around
  the session.
* `GET /scanner/recent?limit=`: the caller's own latest check-ins.
* `POST /scanner/checkin` `{qr_payload | booking_number, member_number, event_id?}` returns `status` =
  `CHECKIN_SUCCESS | ALREADY_CHECKED_IN | INVALID_QR | INVALID_SESSION | INVALID_MEMBER |
  BOOKING_CANCELLED`.

Scanner outcomes come back as HTTP 200 with a `status` field so that scanner apps can show
them uniformly. 401 and 403 are used only for authentication and permission failures.

### Check-ins, admin, reports

* `GET /checkins?session_id=&booking_number=`: paginated, newest first.
* `GET /admin/dashboard`: registrations, confirmed and cancelled bookings, unique members,
  attendee reservations, check-ins, capacity.
* `GET /admin/analytics`: the admin console's dashboard data (per-session used/capacity/attended,
  ages, gender, family sizes, cities, 14-day trend, entries by volunteer, relationships); cached ~10 s.
* `GET /sessions/{id}/kund-map`: `{occ: {kund: reserved}, blocked: [...], inactive: [...]}` for all Kunds.
* `POST /sessions/{id}/kunds/{kund_number}/block` `{blocked}`: block or unblock an **empty** Kund for
  one session (409 `KUND_NOT_EMPTY` otherwise). Blocked Kunds are skipped by allocation. Audited.
* `POST /bookings/{bn}/checkin` `{session_id, member_numbers?}`: organiser marks members as entered
  (help desk). Allowed from 15 minutes before the session starts. Each member gets an individual,
  permanent check-in row. Audited.
* `GET /bookings?q=&event_date=&slot=MORNING|AFTERNOON&expand=true`: `q` matches a booking-number
  prefix, a mobile prefix, or a coordinator/member name. `expand=true` adds members, reservations
  (with check-in counts and who checked in) and the full mobile number. Audited.
* `GET /admin/integrity`: reconciliation report (`ok` should always be `true`).
* `GET /admin/audit-logs?action=&entity_type=&entity_id=&actor_id=`.
* `GET|POST /admin/users`, `PATCH /admin/users/{id}` (ADMIN): staff accounts and scanner session
  assignment. `PATCH` accepts `full_name`, `is_active` (activate/deactivate; deactivation revokes
  tokens), `assigned_session_id` (SCANNER only, 1-16) and `clear_assigned_session`. A role cannot be
  changed (422). You cannot deactivate yourself.
* `POST /admin/users/{id}/reset-password` `{new_password}` (ADMIN): sets a new password for a
  SCANNER/SUPERVISOR account (12+ chars, upper, lower, digit). Revokes all of that user's tokens and
  clears any login lockout; audited as `STAFF_PASSWORD_RESET` (password never logged). Refused for
  ADMIN accounts (`403 ADMIN_PASSWORD_RESET`) and for your own account (`422 OWN_ACCOUNT`).
* **ADMIN only** (SUPERVISOR and SCANNER get 403): `POST /reports/exports` `{report_type: "DAILY"|"FINAL", report_date?}` returns 202 with a
  job. Then call `GET /reports/exports/{id}`, and `GET /reports/exports/{id}/download` once
  it is `COMPLETED`. The download is `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
  named `Mahayagya_Registration_Report_YYYYMMDD.xlsx` (FINAL; generation date in IST) or
  `Mahayagya_Daily_Report_YYYYMMDD.xlsx` (DAILY; the event date). The `.xlsx` has the sheets
  Dashboard, Family Bookings, Family Members, Session Attendance, Kund Allocation, Cancellations and
  No Shows. Report files live on the server's local disk: after a Render restart, `download` returns
  `410 REPORT_EXPIRED`. Generate again.

Staff accounts are created only by an ADMIN through this API, or with the
`python -m scripts.create_admin` CLI for the very first ADMIN. There is no public registration
endpoint for staff.
* `GET /reports/summary?report_date=`: the same session-wise numbers as JSON.

### Offline sync

* `GET /offline/snapshot/{session_id}` (SUPERVISOR+): roster with token hashes.
* `POST /offline/sync/checkins` `{node_id, events[≤500]: {event_id, session_id, booking_number, member_number, checked_in_at}}`
  returns a per-event `result` of `ACCEPTED | DUPLICATE_EVENT | ALREADY_CHECKED_IN | REJECTED`
  plus `replayed`.
* Venue node only (`OFFLINE_NODE_MODE=true`): `POST /offline/local/scan`,
  `POST /offline/local/checkin`, `GET /offline/local/status`.

## Frontend integration notes (React + Vite, a separate phase)

1. Set `CORS_ALLOWED_ORIGINS` to the site origin(s). The API uses bearer tokens, not
   cookies.
2. **Registration form:** fetch `GET /sessions` and disable sessions where
   `largest_family_bookable < members.length` or `booking_open` is false. Generate **one**
   `crypto.randomUUID()` per submit attempt and reuse it on network retries. Show
   `error.details[]` next to the matching fields (`field` is a dotted path such as
   `coordinator.primary_mobile`).
3. **Confirmation page:** keep `qr_pass.token` only in memory. Immediately call
   `POST /qr/pass/image` to render or download the PNG. Never put the token in a URL.
4. On 409 `CAPACITY_UNAVAILABLE`, show `details.availability` and let the family change
   their sessions. On 429 or 503, honour `Retry-After`.
5. The admin dashboard and the scanner PWA authenticate with `/auth/login` and store the
   JWT in memory (or sessionStorage). Expect 401 and send the user back to log in.
