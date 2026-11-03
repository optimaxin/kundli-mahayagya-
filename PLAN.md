# 2151 Kundiya Mahayagya: Registration Platform — The Plan

> Read this first. `NEXT_STEPS.md` lists what is still to be built.

## 1. What we are building

A free, mobile-first registration + entry system for a Hindu yagya in **Agra, 14–21 Dec 2026**.

- **2–3 lakh devotees** register over ~1 month. Registration is free (no payment gateway).
- A **family of 1–8** registers once and gets **one QR pass**. The whole family sits together at **one kund** (fire-altar seat group).
- The pass is a **PDF generated in the browser** (zero server cost).
- Volunteers **scan the QR at the gate**; the QR works **only inside the booked session window**.
- Organisers get a **live dashboard**. The client will embed this into their existing website.
- Everything must run on **free tiers**, no SMS/email.

## 2. Event rules (source of truth)

| Rule | Value |
|---|---|
| Dates | 14–21 Dec 2026 (8 days) |
| Sessions | Morning **8:00–11:00**, Afternoon **1:00–4:00 PM** → 16 sessions |
| Kunds | **2151**, in 11 zones (~196 each) |
| Seats per kund | **8** |
| Capacity | 2151 × 8 × 16 = **275,328 seat-sessions** |
| Family size | 1–8. More than 8 → register a second group |
| Multi-day | One booking may include many sessions (one QR for all) |
| QR validity | Only inside the session window **± 15 min** (`EVENT.graceMin`) |
| Full session | Shown as “Full”, cannot be selected |
| Food | Everyone sattvik / vegetarian (declaration checkbox) |

### Seat allocation: best fit (important)
A family of N gets the **partly-used kund with the fewest free seats that still fits N**; otherwise a fresh kund. So a family of 5 leaves 3 seats, and the next family of 3 fills them exactly. Families are never split.
Implemented in `pickKund()` in `src/lib/db.js`. On the real backend this must be **one atomic SQL statement** (see NEXT_STEPS) so thousands of simultaneous bookings cannot double-book.

## 3. User flows

**Devotee** (`/#/register`, 4 steps): You (name, mobile, city/state; address, gotra, sankalp optional) → Family (name, age, gender, relation per member; kund graphic fills) → Day & session (live seats-left, multi-select) → Confirm (vegetarian + consent ticks) → Ticket page.
**Ticket** (`/#/ticket/:id`): QR + per-session kund & status, **Download PDF / Print / Share at the top**, free-Kundali gift popup after registration + banner (https://tredevaastro.com/), sponsor ad slot at the bottom (ads only here, never beside forms).
**Find pass** (`/#/find`): by mobile number.
**Volunteer** (`/#/staff`): PIN login → scan camera or type Pass ID → green/amber/red result. Nothing else visible.
**Admin** (`/#/admin`): Dashboard, Bookings (search/filter/CSV/manual entry toggle), Scanner, Kund map (block empty kunds), Volunteers (add/remove PINs), Settings (demo data).

## 4. Tech stack (all free)

| Layer | Choice | Why |
|---|---|---|
| Frontend | **React 19 + Vite + Tailwind v4 + Framer Motion + Lucide** | Fast, small, matches client’s existing stack |
| Hosting | **Cloudflare Pages** | Unlimited bandwidth |
| API | **Cloudflare Workers** | 100k req/day free (see §6) |
| DB | **Cloudflare D1 (SQLite)** | 5 GB, atomic transactions |
| Bot protection | **Cloudflare Turnstile** | Free |
| Staff auth | Cloudflare Access (admin) + PIN sessions (volunteers) | Free |
| QR / PDF | `qrcode`, `html-to-image` + `jspdf`, **client-side** | No server load |
| Scanner | `html5-qrcode` (phone camera) | No app install |

i18n: Hindi default + English via `t(english, hindi)` in `src/lib/lang.jsx`.
Fonts: Yatra One (Hindi headings) / Cinzel (English headings) / Outfit + Hind (body). Brand mark: **ॐ** on maroon disc (`<Om/>` in `ui.jsx`, `public/favicon.svg`).

## 5. Current state (what exists in this repo)

Complete **frontend + admin + volunteer UI**, running on a **mock backend** (`src/lib/db.js`, browser localStorage). Data lives only on one device. The function names/shapes in `db.js` are the **API contract**: the real backend replaces that file’s internals only; UI code does not change.

```
src/lib/db.js          mock backend + allocation + scan rules + analytics (REPLACE with API calls)
src/lib/lang.jsx       Hindi/English
src/components/ui.jsx  navbar, Om logo, footer, buttons, fields, AdSlot, Mandala
src/components/Scanner.jsx  shared admin/volunteer scanner
src/components/charts.jsx   dependency-free SVG charts
src/pages/Home|Register|Ticket|Find|Staff|Admin.jsx
public/person.png      hero photo   public/favicon.svg
```

Run: `npm install && npm run dev` → http://127.0.0.1:5173 · Build: `npm run build`.
Demo logins: admin `admin123`, volunteer PIN `1234` (**placeholders**). Admin → Settings → “Load demo data”.

## 6. Capacity & free-tier math

- ~3 lakh registrations over ~30 days ≈ **10k/day average**. A registration ≈ 3–4 requests ⇒ well under Workers’ 100k req/day, D1’s 100k writes/day.
- **Risks:** an opening-day spike or a social-media push can exceed 100k/day. Mitigations: cache slot availability at the edge (~15 s), keep dashboard reads on **counters** not table scans (D1 free = 5M rows read/day), and keep the **$5/month Workers plan** as a pressure valve for peak days.
- Data size: ~3 lakh families × ~1 KB ≈ 300 MB ≪ 5 GB.

## 7. Security & privacy (requirements)

- HTTPS only; D1 encrypted at rest; **no public endpoint lists personal data**.
- QR holds only `KM|<passId>|<HMAC signature>`: no personal data. Pass IDs random, unguessable.
- **Time check and signature check happen on the server** (a downloaded PDF can’t expire).
- Roles: **admin** (all) vs **volunteer** (scan only). Every entry stores who marked it.
- Turnstile + rate limits against bots; one booking per mobile per session is recommended.
- “Find my pass” by mobile alone leaks data without OTP: recover via mobile **+ name** (or pass ID).
- DPDP-style consent checkbox is already in the form. Collect only needed fields.
- Ads / sponsor scripts only on the ticket page, never on pages that show forms or personal data.

## 8. Assumptions to confirm with the client

1. Session times 8–11 / 1–4 and grace of ±15 min.
2. 2151 kunds × 8 seats for **every** session, 11 zones (zone names are placeholders).
3. Vegetarian: a single declaration for the family (not per person).
4. No OTP (SMS isn’t free): anyone can register any number.
5. Reference site (`2151-kundiya-mahayagya.vercel.app`) rule “3+ members need two distinct mobiles” was **dropped**: confirm.
6. Hero photo and the Tredeva Kundali gift link are approved for use.
