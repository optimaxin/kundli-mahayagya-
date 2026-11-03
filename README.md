# 2151 Kundiya Mahayagya: registration and entry system

Registration, kund allocation, QR passes and gate check-in for the 2151 Kundiya Mahayagya
(Agra, 14-21 December 2026).

```
.
├── src/, public/, index.html ...   React 19 + Vite + Tailwind frontend (public site, volunteer scanner, admin console)
├── backend/                        FastAPI + PostgreSQL API (see backend/README.md)
├── PLAN.md, NEXT_STEPS.md          Original product plan. The backend described there (Cloudflare Workers + D1)
│                                   was replaced by backend/ (FastAPI + PostgreSQL / Supabase).
```

## Run locally

Prerequisites: Node 20+, Python 3.12+, Docker (for PostgreSQL).

```bash
# 1. Backend (details: backend/README.md)
cd backend
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                # dev defaults work as-is
docker compose up -d db
alembic upgrade head                                # migrations 0001-0003
python -m scripts.seed_all                          # 16 sessions, 2,151 kunds
python -m scripts.create_admin --email admin@example.org --name "Event Admin"        # prompts for a password
python -m scripts.create_admin --email gate1@example.org --name "Gate 1" --role SCANNER --session 1
uvicorn app.main:app --reload                       # http://localhost:8000/docs

# 2. Frontend (from the repo root, in a second terminal)
npm ci
npm run dev                                         # http://localhost:5173, proxies /api to http://127.0.0.1:8000
```

* Public site: `/#/register`, `/#/ticket/<pass token>`, `/#/find`
* Volunteers: `/#/staff`, with a SCANNER account (each account is assigned to one session by the admin)
* Organisers: `/#/admin`, with an ADMIN or SUPERVISOR account

Production: `npm run build`, then serve `dist/` and the API under one domain (reverse-proxy `/api` to the
backend), or set `VITE_API_BASE_URL` and add the site origin to the backend's `CORS_ALLOWED_ORIGINS`.
Copy `.env.example` to `.env.local` for frontend settings (only `VITE_*` values reach the browser).

Tests: `cd backend && pytest` (needs the Docker database; 185 tests against real PostgreSQL).

## How the frontend uses the API

`src/lib/db.js` is the API client (the old localStorage mock is gone).

| Area | Behaviour |
|---|---|
| Sessions | Morning 08:00-11:00 and Afternoon 13:00-16:00 IST. Live seat availability, refreshed every 30 s. |
| One session per day | A booking can hold **one session per day** (morning or afternoon, not both). Picking a slot replaces the other slot of that day. The server enforces it, also across bookings made with the same mobile number. |
| Registration | 4-step form. Gotra, sankalp, address, pincode and email are optional. One idempotency key per submit, so a network retry never double-books. |
| Ticket | Opened by the pass token (in the URL hash). QR, kunds and per-session entry status come from the server. PDF download as before. |
| Find my pass | Shows passes saved on this device for a mobile number. The server never lists passes by mobile number. A status check uses booking number + mobile. Lost passes are re-issued by the help desk. |
| Volunteers | Email + password scanner accounts. Scan a QR (or type the Pass ID), then tap each family member as they enter. The scan window is 15 minutes either side of the session, enforced by the server. |
| Admin | Dashboard analytics, booking search and CSV export, scanner tab, kund map with per-session block, volunteer accounts (ADMIN only), Excel reports. |

## Still to decide

1. **Zones:** the 11 zone names are placeholders in the frontend; the backend has no zones.
2. **Hosting:** the backend runs on FastAPI + PostgreSQL (or Supabase); see `backend/docs/deployment.md`.
3. **Pass recovery:** the help desk re-issues lost passes. A self-service flow would need SMS OTP.
4. **Typed Pass ID at the gate:** accepted as a camera fallback; volunteers must check names against a photo ID.
5. **Booking cut-off:** booking for a session closes 60 minutes before it starts (`BOOKING_CUTOFF_MINUTES`).
6. **Load testing at scale:** only laptop-level load tests were run (`backend/loadtest/README.md`). The target of
   100,000 simultaneous registrations is not proven.
