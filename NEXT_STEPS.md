# What to do next (handover to the team)

Context: see `PLAN.md`. The UI is finished; **the backend is the main remaining work.** Do the phases in order.

## Phase 1: Backend (Cloudflare Worker + D1) — MUST

Replace the internals of `src/lib/db.js` with `fetch()` calls. Keep exported names so no page changes. Everything async → pages need `await` (currently sync); convert call sites in `Register.jsx`, `Ticket.jsx`, `Find.jsx`, `Admin.jsx`, `Staff.jsx`, `Scanner.jsx`.

### D1 schema (suggested)
```sql
slots(id TEXT PK /* '2026-12-14|morning' */, date, session, capacity_seats INT, used_seats INT, attended_seats INT);
kund_slots(slot_id, kund INT, used INT DEFAULT 0, blocked INT DEFAULT 0, PRIMARY KEY(slot_id,kund));  -- 2151×16 = 34,416 rows, pre-seeded
bookings(id TEXT PK, created_at, c_name, c_mobile, c_city, c_state, c_extra JSON, size INT);
members(booking_id, idx, name, age, gender, relationship, mobile);
booking_slots(booking_id, slot_id, kund, attended INT DEFAULT 0, attended_at, attended_by);
staff(id, name, pin_hash, active);
CREATE INDEX ON bookings(c_mobile); CREATE INDEX ON kund_slots(slot_id, used);
```

### Endpoints
| Method | Path | Purpose | Mock fn |
|---|---|---|---|
| GET | `/api/slots` | seats left + “fits N?” per session (**cache 15 s**) | `slotStats`, `canFit` |
| POST | `/api/bookings` | create booking, allocate kund(s) atomically | `createBooking` |
| GET | `/api/bookings/:id` | ticket data | `getBooking` |
| POST | `/api/find` | pass lookup (mobile + name) | `findByMobile` |
| POST | `/api/checkin` | scan: verify sig + time window + duplicate | `checkIn` |
| GET | `/api/admin/overview` | counters + analytics | `analytics`, `overview` |
| GET | `/api/admin/bookings?…` | paged search / CSV | `allBookings` |
| GET/POST | `/api/admin/kunds` | map, block/unblock | `kundMap`, `toggleBlock` |
| POST | `/api/admin/attendance` | manual toggle | `toggleAttended` |
| CRUD | `/api/admin/staff` | volunteers | `addStaff`… |
| POST | `/api/staff/login` | PIN → short-lived token | `staffLogin` |

### Critical logic
1. **Atomic best-fit allocation** (per session) in one D1 batch/transaction:
   ```sql
   UPDATE kund_slots SET used = used + :n
   WHERE rowid = (SELECT rowid FROM kund_slots
                  WHERE slot_id=:s AND blocked=0 AND used + :n <= 8
                  ORDER BY used DESC, kund ASC LIMIT 1)   -- fullest kund that still fits
   RETURNING kund;
   ```
   If any session of a multi-session booking returns nothing → roll back all, return “FULL:<slot>”.
2. **Signature:** `HMAC-SHA256(secret, passId)` (Worker secret). Replace the toy `sign()` in `db.js`.
3. **Scan rule:** reject unless `now` is within `[start − 15 min, end + 15 min]` in **Asia/Kolkata**; reject duplicates; store `attended_by`. Never trust client clock. Remove the “test clock” field from `Scanner.jsx` in production.
4. **Counters:** maintain `slots.used_seats / attended_seats` on write; dashboard reads these, never scans bookings.
5. **Auth:** admin behind Cloudflare Access (or signed session cookie). Volunteers: PIN → JWT/cookie scoped to `/api/checkin`. **Delete the hard-coded `admin123` / `1234`.**
6. **Abuse:** Turnstile token on `POST /api/bookings`; rate limit per IP + per mobile.

## Phase 2: Integrate into the client’s website — MUST
- Decide: iframe/subpath (`/register`), or ship as a package. Router currently uses `HashRouter`: switch to `BrowserRouter` + SPA fallback (`_redirects`) once hosted under a path.
- Match client branding/domain; confirm hero photo, Kundali gift link, sponsor banner image/size.
- Replace `AdSlot` placeholder in `Ticket.jsx` with the real sponsor banner.

## Phase 3: Hardening — SHOULD
- **Offline gate scanning:** volunteer app downloads that session’s valid signed IDs (cached via service worker), checks locally, queues check-ins and syncs when online. Known gap: two offline phones can’t see each other’s scans (document it).
- **PWA** install for volunteers (manifest + service worker).
- Image: convert `public/banner.jpg` (≈330 KB) to **WebP/AVIF**; add `srcset`.
- Code-split big chunks (`jspdf`, `html5-qrcode` are already lazy; check bundle ≈ 890 KB main).
- Accessibility pass (focus rings, contrast on gold-on-maroon, `aria-live` on scan result).
- Error/empty/offline states on every API call; retry + idempotency key on `POST /api/bookings` (avoid double-submit on bad networks).
- Optional: web-push “your session starts soon” (free; iOS needs installed PWA).

## Phase 4: Test & launch — MUST
1. **Load test** (k6/autocannon): 3,000 concurrent bookings on one session → verify **no overbooking**, p95 < 1 s.
2. Concurrency test of the allocation SQL (fragmentation: many 5s, 3s, 1s).
3. Device matrix: Android Chrome (low-end), iOS Safari, 320–430 px widths; Hindi + English; PDF download on each (iOS may open instead of download).
4. Scan test with printed + on-screen QR, bright sun, cracked screens.
5. Time-window test: just before / during / after session; duplicate scan; wrong session.
6. Privacy review: confirm no endpoint returns personal data without auth.
7. Backup: scheduled D1 export (daily) + CSV export drill.
8. Go-live checklist: secrets set, demo credentials removed, Turnstile keys, domain + HTTPS, `$5` Workers plan decision for opening day, on-call contact.

## Known limitations of the current build
- All data is in **one browser’s localStorage**: tickets don’t exist on other devices.
- Auth + QR signature are **demo-grade**.
- Session times, zone names, kund counts are assumptions (see PLAN §8).
- Seeded demo data fills ~1% of capacity, so charts look sparse (honest, not a bug).
- Preview/dev server only; no CI.

## Repo quick facts
`npm run dev` · `npm run build` · no env vars yet (backend will need: `HMAC_SECRET`, `TURNSTILE_SECRET`, D1 binding `DB`). Hindi strings are inline: `t('English','हिन्दी')`: grep `t(` to review copy.
