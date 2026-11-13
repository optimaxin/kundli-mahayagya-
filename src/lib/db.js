// API client for the Mahayagya backend (FastAPI, /api/v1). Replaces the former localStorage mock.
// Exported names follow the old mock where possible; anything that talks to the server is async.
import { useEffect, useState } from 'react'

export const EVENT = {
  nameHi: '2151 कुंडीय महायज्ञ',
  nameEn: '2151 Kundiya Mahayagya',
  venueHi: 'जेसीबी तिराहा, शास्त्रीपुरम, आगरा',
  venueEn: 'JCB Tiraha, Shastripuram, Agra',
  dates: ['2026-12-14', '2026-12-15', '2026-12-16', '2026-12-17', '2026-12-18', '2026-12-19', '2026-12-20', '2026-12-21'],
  // confirmed: 8-11 AM and 1-4 PM (the backend uses the same times)
  sessions: {
    morning: { start: '08:00', end: '11:00', hi: 'प्रातः सत्र', en: 'Morning' },
    afternoon: { start: '13:00', end: '16:00', hi: 'अपराह्न सत्र', en: 'Afternoon' },
  },
  kunds: 2151,
  seats: 8,
  zones: 11,
  graceMin: 15,
}

export const ZONES = [
  ['Brahma', 'ब्रह्म'], ['Vishnu', 'विष्णु'], ['Shiva', 'शिव'], ['Surya', 'सूर्य'], ['Ganesha', 'गणेश'], ['Durga', 'दुर्गा'],
  ['Lakshmi', 'लक्ष्मी'], ['Saraswati', 'सरस्वती'], ['Hanuman', 'हनुमान'], ['Indra', 'इन्द्र'], ['Agni', 'अग्नि'],
]
const PER_ZONE = Math.ceil(EVENT.kunds / EVENT.zones)
export const zoneOf = (k) => Math.min(EVENT.zones - 1, Math.floor((k - 1) / PER_ZONE))
export const zoneRange = (z) => [z * PER_ZONE + 1, Math.min(EVENT.kunds, (z + 1) * PER_ZONE)]
// 11 zones x 5 sectors: sectors 1-4 hold 39 kunds, sector 5 holds the rest of the zone (40; the last zone is 5 short of 2151).
export const sectorOf = (k) => { const o = (k - 1) % PER_ZONE; return o >= 156 ? 4 : Math.floor(o / 39) }
// ['Zone Brahma', 'Sector 2', 'Kund #45']: the parts of a Kund allocation (see KundTag in components/ui.jsx).
export const kundParts = (k, t) => { const z = ZONES[zoneOf(k)]; return [`${t('Zone', 'क्षेत्र')} ${t(z[0], z[1])}`, `${t('Sector', 'सेक्टर')} ${sectorOf(k) + 1}`, `${t('Kund', 'कुंड')} #${k}`] }
// "Zone Brahma · Sector 2 · Kund #45" as plain text (titles, CSV). `t` is the useLang translator.
export const kundLabel = (k, t) => kundParts(k, t).join(' · ')

// ------------------------------------------------------------------ HTTP
export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(status, code, message, details, retryAfter) {
    super(message || code || 'Request failed')
    this.status = status
    this.code = code
    this.details = details
    this.retryAfter = retryAfter
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
// Spread retries over 1x-2x the wait so thousands of clients don't retry at the same instant.
const jitter = (ms) => ms * (1 + Math.random())

async function request(path, { method = 'GET', body, auth, headers = {}, retries = 0, raw = false } = {}) {
  const h = { Accept: 'application/json', ...headers }
  if (body !== undefined) h['Content-Type'] = 'application/json'
  const session = auth ? currentAuth(auth) : null
  if (auth && !session) throw new ApiError(401, 'UNAUTHORIZED', 'Please log in again')
  if (session) h.Authorization = `Bearer ${session.token}`
  for (let attempt = 0; ; attempt++) {
    let res
    try {
      res = await fetch(API_BASE + path, { method, headers: h, body: body === undefined ? undefined : JSON.stringify(body) })
    } catch {
      if (attempt < retries) { await sleep(jitter(800 * (attempt + 1))); continue }
      throw new ApiError(0, 'NETWORK', 'Network error. Please check your connection and try again.')
    }
    const retryAfter = Number(res.headers.get('Retry-After')) || 0
    if (res.status === 503 && attempt < retries) { await sleep(jitter(Math.min(8, retryAfter || 2) * 1000)); continue }
    if (raw && res.ok) return res
    let json = null
    try { json = await res.json() } catch { /* empty body */ }
    if (!res.ok) {
      const e = json?.error || {}
      if (res.status === 401 && auth) { clearAuth(auth); window.dispatchEvent(new CustomEvent('km-auth-expired', { detail: auth })) }
      throw new ApiError(res.status, e.code || `HTTP_${res.status}`, e.message || res.statusText, e.details, retryAfter)
    }
    return json
  }
}

// Turns any error into a short user-facing sentence.
export function describeError(err, t = (en) => en) {
  if (!(err instanceof ApiError)) return t('Something went wrong. Please try again.', 'कुछ गड़बड़ हुई। कृपया पुनः प्रयास करें।')
  if (err.code === 'NETWORK' && err.context === 'report') return t('Could not reach the server. Check your internet connection; the server may be waking up, so try again in a minute.', 'सर्वर से संपर्क नहीं हो पाया। इंटरनेट जाँचें; सर्वर चालू हो रहा हो सकता है, एक मिनट बाद पुनः प्रयास करें।')
  if (err.code === 'NETWORK') return t('No connection to the server. Please try again.', 'सर्वर से संपर्क नहीं हो पाया। कृपया पुनः प्रयास करें।')
  if (err.code === 'VALIDATION_ERROR' && Array.isArray(err.details) && err.details.length)
    return err.details.map((d) => d.message).join('. ')
  if (err.code === 'DUPLICATE_BOOKING') return t('This mobile number already has a booking for one of the selected sessions.', 'इस मोबाइल नंबर से चुने गए सत्र में पहले से पंजीकरण है।')
  // Staff login / account management (same text for unknown email and wrong password)
  if (err.code === 'INVALID_CREDENTIALS') return t('Wrong email or password', 'गलत ईमेल या पासवर्ड')
  if (err.code === 'WRONG_ROLE') return t('This account cannot open this console.', 'यह खाता इस कंसोल में प्रवेश नहीं कर सकता।')
  if (err.code === 'ACCOUNT_LOCKED') return t('Too many failed attempts. The account is locked for 15 minutes.', 'बहुत अधिक असफल प्रयास। खाता 15 मिनट के लिए बंद है।')
  if (err.code === 'INVALID_TOKEN' || err.code === 'UNAUTHORIZED') return t('Your session has expired. Please log in again.', 'सत्र समाप्त हो गया है। कृपया पुनः लॉगिन करें।')
  if (err.code === 'FORBIDDEN') return t('You do not have permission for this action.', 'आपको यह कार्य करने की अनुमति नहीं है।')
  if (err.code === 'EMAIL_EXISTS') return t('An account with this email already exists.', 'इस ईमेल से खाता पहले से मौजूद है।')
  if (err.code === 'INVALID_SESSION') return t('Please choose a valid session.', 'कृपया मान्य सत्र चुनें।')
  if (err.code === 'ADMIN_PASSWORD_RESET') return t('Admin passwords can only be changed by their owner.', 'एडमिन का पासवर्ड केवल वही स्वयं बदल सकते हैं।')
  if (err.code === 'REPORT_FAILED') return t('The report could not be prepared. Please try again.', 'रिपोर्ट तैयार नहीं हो सकी। कृपया पुनः प्रयास करें।')
  if (err.code === 'REPORT_TIMEOUT') return t('The report is taking too long. Please try again in a few minutes.', 'रिपोर्ट बनने में बहुत समय लग रहा है। कृपया कुछ मिनट बाद पुनः प्रयास करें।')
  if (err.code === 'REPORT_INVALID') return t('The downloaded file was incomplete. Please try again.', 'डाउनलोड की गई फ़ाइल अधूरी थी। कृपया पुनः प्रयास करें।')
  if (err.code === 'REPORT_BUSY') return t('Another report is being prepared. Please wait for it to finish.', 'दूसरी रिपोर्ट तैयार हो रही है। कृपया उसके पूरा होने तक प्रतीक्षा करें।')
  if (err.code === 'REPORT_EXPIRED') return t('The report file is no longer available. Please generate it again.', 'रिपोर्ट फ़ाइल अब उपलब्ध नहीं है। कृपया दोबारा बनाएँ।')
  if (err.status === 429) return t('Too many attempts. Please wait a minute and try again.', 'बहुत अधिक प्रयास। एक मिनट बाद पुनः प्रयास करें।')
  if (err.status === 503) return t('The system is busy. Please try again in a few seconds.', 'सिस्टम व्यस्त है। कुछ सेकंड बाद पुनः प्रयास करें।')
  return err.message
}

export function newKey() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID()
  const b = new Uint8Array(16)
  crypto.getRandomValues(b)
  return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
}

// ----------------------------------------------------------- sessions/slots
const SLOT_API = { morning: 'MORNING', afternoon: 'AFTERNOON' }
const slotUi = (s) => String(s).toLowerCase()
const sk = (date, session) => `${date}|${session}`
export const allSlots = () => EVENT.dates.flatMap((date) => Object.keys(EVENT.sessions).map((session) => ({ date, session })))
export const slotId = (date, session) => slotCache[sk(date, session)]?.id ?? EVENT.dates.indexOf(date) * 2 + (session === 'morning' ? 1 : 2)
export const slotOf = (id) => ({ date: EVENT.dates[Math.floor((id - 1) / 2)], session: id % 2 ? 'morning' : 'afternoon' })

// Public availability is computed by the server for ONE family size: a session is AVAILABLE only if a
// single Kund can seat the whole family. The server returns no seat counts. The result is a hint for the
// picker; the Kund is chosen and locked by the server when the booking is confirmed.
//   AVAILABLE | NOT_FOR_THIS_FAMILY | FULL (no family of any size fits) | CLOSED (booking not open)
let slotCache = {}
let slotFamily = null // family size slotCache was computed for (null = nothing loaded yet)
let slotWanted = null // family size of the latest request; older responses are dropped
let slotVersion = 0
const slotListeners = new Set()
const notifySlots = () => { slotVersion++; slotListeners.forEach((fn) => fn(slotVersion)) }

let slotError = null
// The last error from loadSlots(), or null once availability has loaded successfully.
export const slotsError = () => slotError

const clampFamily = (n) => Math.min(EVENT.seats, Math.max(1, Math.floor(Number(n)) || 1))

export async function loadSlots(familySize = slotWanted ?? 1) {
  const n = clampFamily(familySize)
  slotWanted = n
  if (slotFamily !== n) { slotCache = {}; slotFamily = null; notifySlots() } // never show another size's result
  let data
  try {
    ({ data } = await request(`/sessions?family_size=${n}`, { retries: 1 }))
    if (!Array.isArray(data)) throw new ApiError(0, 'BAD_RESPONSE', 'Unexpected response from the server')
  } catch (err) {
    if (slotWanted === n) { slotError = err; notifySlots() }
    throw err
  }
  if (slotWanted !== n) return slotCache // the family size changed while this request was in flight
  slotError = null
  const next = {}
  for (const s of data) {
    if (s.family_size !== n) continue
    next[sk(s.event_date, slotUi(s.slot))] = { id: s.id, open: s.booking_open, status: s.availability, fits: s.fits_family }
  }
  slotCache = next
  slotFamily = n
  notifySlots()
  return slotCache
}

// React hook: keeps availability for `familySize` fresh (re-fetched at once when the size changes).
// Pass null to stop polling. Returns a version number to use as a memo dependency.
export function useSlots(intervalMs = 30000, familySize = 1) {
  const [v, setV] = useState(slotVersion)
  useEffect(() => {
    slotListeners.add(setV)
    if (familySize == null) return () => slotListeners.delete(setV)
    loadSlots(familySize).catch(() => {})
    const i = setInterval(() => loadSlots(familySize).catch(() => {}), intervalMs)
    return () => { slotListeners.delete(setV); clearInterval(i) }
  }, [intervalMs, familySize])
  return v
}

// Availability of one session for a family of n: { status, open }.
// status is 'loading' until the server has answered for exactly this family size, 'error' if it could not.
export function slotAvailability(date, session, n) {
  const c = slotFamily === clampFamily(n) ? slotCache[sk(date, session)] : null
  if (c) return c
  return { id: slotId(date, session), status: slotError ? 'error' : 'loading', open: false, fits: false }
}
export const canFit = (date, session, n) => slotAvailability(date, session, n).status === 'AVAILABLE'

// Staff only (ADMIN/SUPERVISOR): exact per-session capacity for the Kund map and dashboards.
export async function sessionCapacity(date, session) {
  const { data } = await request('/sessions/capacity', { auth: 'admin' })
  const s = data.find((x) => x.event_date === date && slotUi(x.slot) === session)
  if (!s) return null
  return {
    id: s.id, used: s.reserved, capacity: s.total_capacity, left: s.remaining, full: s.kunds_full,
    blocked: s.kunds_blocked || 0, empty: s.kunds_empty,
    partial: Math.max(0, EVENT.kunds - s.kunds_empty - s.kunds_full - (s.kunds_blocked || 0)),
    largest: s.largest_family_bookable, open: s.booking_open,
  }
}

// QR is valid only inside the session window (+-15 min), in India time.
export const slotWindow = (date, session) => {
  const s = EVENT.sessions[session]
  const g = EVENT.graceMin * 60000
  return [new Date(`${date}T${s.start}:00+05:30`).getTime() - g, new Date(`${date}T${s.end}:00+05:30`).getTime() + g]
}

// ------------------------------------------------------- passes on device
// Pass tokens are credentials: they are kept only on the family's own device (and inside the QR).
const PASS_KEY = 'km_passes_v2'
export function savedPasses() { try { return JSON.parse(localStorage.getItem(PASS_KEY)) || [] } catch { return [] } }
function rememberPass(b, mobile) {
  try {
    const list = savedPasses().filter((p) => p.token !== b.token)
    const prev = savedPasses().find((p) => p.token === b.token)
    list.unshift({ token: b.token, id: b.id, name: b.coordinator.name, mobile: mobile || prev?.mobile || '', mobileMasked: b.coordinator.mobileMasked, members: b.members.length, dates: b.slots.map((s) => s.date) })
    localStorage.setItem(PASS_KEY, JSON.stringify(list.slice(0, 20)))
  } catch { /* storage full or blocked */ }
}

function mapPass(d, token) {
  return {
    id: d.booking_number,
    token,
    qr: d.qr_payload,
    status: d.booking_status,
    createdAt: Date.parse(d.created_at),
    coordinator: { name: d.coordinator_name, mobileMasked: d.primary_mobile_masked, city: d.city },
    members: d.members.map((m) => ({ name: m.full_name, ...m })),
    slots: d.reservations.map((r) => ({
      date: r.event_date, session: slotUi(r.slot), kund: r.kund_number, status: r.status,
      checkedIn: r.checked_in_count, attended: r.checked_in_count > 0,
      attendedAt: r.first_checked_in_at ? Date.parse(r.first_checked_in_at) : null,
    })),
  }
}
export const qrPayload = (b) => b.qr

// ------------------------------------------------------------ registration
// Throws Error('FULL:<date>|<session>,...') when sessions cannot fit the family (same contract as the mock).
export async function createBooking({ coordinator: c, members, slots }, idempotencyKey = newKey()) {
  const body = {
    coordinator: {
      name: c.name, primary_mobile: c.mobile, secondary_mobile: c.alt || '', email: c.email || '',
      address: c.address || '', city: c.city, state: c.state, pincode: c.pincode || '',
      gotra: c.gotra || '', sankalp_purpose: c.sankalp || '',
    },
    members: members.map((m, i) => ({
      full_name: m.name, age: Number(m.age), gender: m.gender,
      relationship: m.relationship || (i === 0 ? 'Self' : null), mobile: m.mobile || null,
    })),
    selected_sessions: slots.map((s) => slotId(s.date, s.session)),
  }
  try {
    const { data } = await request('/registrations', { method: 'POST', body, headers: { 'Idempotency-Key': idempotencyKey }, retries: 2 })
    const b = {
      id: data.booking_number, token: data.qr_pass.token, qr: data.qr_pass.qr_payload, status: data.status,
      createdAt: Date.parse(data.created_at),
      coordinator: { name: data.coordinator_name, mobileMasked: data.primary_mobile_masked, city: c.city },
      members: data.members.map((m) => ({ name: m.full_name, ...m })),
      slots: data.reservations.map((r) => ({ date: r.event_date, session: slotUi(r.slot), kund: r.kund_number, status: r.status, checkedIn: 0, attended: false, attendedAt: null })),
    }
    if (b.token) rememberPass(b, c.mobile)
    loadSlots(members.length).catch(() => {})
    return b
  } catch (err) {
    if (err instanceof ApiError && err.code === 'CAPACITY_UNAVAILABLE') {
      const ids = err.details?.unavailable_sessions || []
      const full = (err.details?.availability || []).filter((a) => !a.fits_this_family).map((a) => a.session_id)
      const keys = [...new Set([...ids, ...full])].map((id) => { const s = slotOf(id); return sk(s.date, s.session) })
      loadSlots(members.length).catch(() => {})
      const e = new Error(`FULL:${keys.join(',')}`)
      e.api = err
      throw e
    }
    throw err
  }
}

// Ticket page: the route id is the pass token.
export async function getBooking(token) {
  try {
    const { data } = await request('/qr/pass', { method: 'POST', body: { token } })
    const b = mapPass(data, token)
    rememberPass(b)
    return b
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 422)) return null
    throw err
  }
}

// "Find my pass": passes saved on THIS device for the mobile number (the server never lists bookings by mobile).
export async function findByMobile(m) {
  return savedPasses().filter((p) => p.mobile === m || (p.mobileMasked && p.mobileMasked.slice(0, 2) === m.slice(0, 2) && p.mobileMasked.slice(-2) === m.slice(-2) && !p.mobile))
    .map((p) => ({ id: p.id, token: p.token, coordinator: { name: p.name }, members: { length: p.members }, slots: p.dates.map((date) => ({ date })) }))
}
export async function passStatus(bookingNumber, mobile) {
  const { data } = await request('/qr/status', { method: 'POST', body: { booking_number: bookingNumber, primary_mobile: mobile } })
  return data
}

// ------------------------------------------------------------- staff auth
// kind: 'admin' (ADMIN/SUPERVISOR console) or 'staff' (gate volunteer = SCANNER account)
const AUTH_KEYS = { admin: 'km_admin_auth', staff: 'km_staff_auth' }
export function currentAuth(kind) {
  try {
    const a = JSON.parse(sessionStorage.getItem(AUTH_KEYS[kind]))
    return a && a.expiresAt > Date.now() ? a : null
  } catch { return null }
}
function clearAuth(kind) { try { sessionStorage.removeItem(AUTH_KEYS[kind]) } catch { /* ignore */ } }

// One login for everyone: the server's role decides the panel. SCANNER -> 'staff', ADMIN/SUPERVISOR -> 'admin'.
// Returns { kind, ...auth } so the caller can open the matching panel.
export async function signIn(email, password) {
  const { data } = await request('/auth/login', { method: 'POST', body: { email: email.trim(), password } })
  const kind = data.role === 'SCANNER' ? 'staff' : 'admin'
  const a = { token: data.access_token, role: data.role, expiresAt: Date.parse(data.expires_at) }
  sessionStorage.setItem(AUTH_KEYS[kind], JSON.stringify(a))
  try {
    const me = await request('/auth/me', { auth: kind })
    a.user = { id: me.data.id, name: me.data.full_name, email: me.data.email, sessionId: me.data.assigned_session_id }
    sessionStorage.setItem(AUTH_KEYS[kind], JSON.stringify(a))
  } catch { /* profile is optional */ }
  return { kind, ...a }
}
export async function logout(kind) {
  try { await request('/auth/logout', { method: 'POST', auth: kind }) } catch { /* token may already be invalid */ }
  clearAuth(kind)
}

// --------------------------------------------------------------- scanner
const passRef = (code) => {
  const c = String(code).trim()
  return /^MY26-[0-9A-Z]{8}$/i.test(c) ? { booking_number: c.toUpperCase() } : { qr_payload: c }
}
export async function scanPass(kind, code, sessionId) {
  const body = { ...passRef(code), ...(kind === 'admin' ? { session_id: sessionId } : {}) }
  return (await request('/scanner/scan', { method: 'POST', body, auth: kind })).data
}
export async function checkInMember(kind, code, memberNumber, sessionId, eventId = newKey()) {
  const body = { ...passRef(code), member_number: memberNumber, event_id: eventId, ...(kind === 'admin' ? { session_id: sessionId } : {}) }
  return (await request('/scanner/checkin', { method: 'POST', body, auth: kind, retries: 1 })).data
}
export async function recentScans(kind, n = 8) {
  return (await request(`/scanner/recent?limit=${n}`, { auth: kind })).data
}
export async function scannerMe(kind) { return (await request('/scanner/me', { auth: kind })).data }

// ------------------------------------------------------------------ admin
export async function analytics() { return (await request('/admin/analytics', { auth: 'admin' })).data }

function mapListBooking(b) {
  return {
    id: b.booking_number, status: b.status, createdAt: Date.parse(b.created_at),
    coordinator: { name: b.coordinator_name, mobile: b.primary_mobile, city: b.city, state: b.state },
    members: b.members.map((m) => ({ name: m.full_name, ...m })),
    slots: b.reservations.map((r) => ({
      date: r.event_date, session: slotUi(r.slot), sessionId: r.session_id, kund: r.kund_number, status: r.status,
      checkedIn: r.checked_in_count, attended: r.checked_in_count > 0,
      attendedAt: r.first_checked_in_at ? Date.parse(r.first_checked_in_at) : null, by: r.checked_in_by || '',
    })),
  }
}
export async function searchBookings({ q = '', date = '', session = '', page = 1, pageSize = 100 } = {}) {
  const p = new URLSearchParams({ page: String(page), page_size: String(pageSize), expand: 'true' })
  if (q.trim()) p.set('q', q.trim())
  if (date) p.set('event_date', date)
  if (session) p.set('slot', SLOT_API[session])
  const res = await request(`/bookings?${p}`, { auth: 'admin' })
  return { rows: res.data.map(mapListBooking), total: res.meta.total }
}
// All matching bookings for CSV export (paged; capped -- use the Excel report for everything).
export async function exportBookings(filters, onProgress, cap = 20000) {
  const out = []
  for (let page = 1; out.length < cap; page++) {
    const { rows, total } = await searchBookings({ ...filters, page, pageSize: 200 })
    out.push(...rows)
    onProgress?.(out.length, total)
    if (!rows.length || out.length >= total) break
  }
  return out
}
// Mark every not-yet-entered member of a reservation as entered (organiser action, audited, cannot be undone).
export async function markEntered(bookingId, date, session, memberNumbers) {
  return (await request(`/bookings/${encodeURIComponent(bookingId)}/checkin`, { method: 'POST', auth: 'admin', body: { session_id: slotId(date, session), member_numbers: memberNumbers || null } })).data
}

// Cancels every session of the booking and frees its seats (server is idempotent).
export async function cancelBooking(bookingId, reason = 'Cancelled by organiser') {
  return (await request(`/bookings/${encodeURIComponent(bookingId)}/cancel`, { method: 'POST', auth: 'admin', body: { reason } })).data
}

export async function kundMap(date, session) {
  const { data } = await request(`/sessions/${slotId(date, session)}/kund-map`, { auth: 'admin' })
  return { occ: data.occ, blocked: Object.fromEntries(data.blocked.map((k) => [k, 1])), inactive: Object.fromEntries(data.inactive.map((k) => [k, 1])) }
}
export async function kundFamilies(date, session, kund) {
  const { data } = await request(`/sessions/${slotId(date, session)}/kunds?kund_number=${kund}`, { auth: 'admin' })
  return (data[0]?.families || []).map((f) => ({ id: f.booking_number, name: f.coordinator_name, size: f.member_count }))
}
export async function toggleBlock(date, session, kund, blocked) {
  const r = await request(`/sessions/${slotId(date, session)}/kunds/${kund}/block`, { method: 'POST', auth: 'admin', body: { blocked } })
  return r.data
}

// Volunteers = SCANNER accounts (ADMIN only).
// Volunteers = SCANNER (gate) and SUPERVISOR accounts. ADMIN accounts are not managed here.
export async function staffList() {
  const [scanners, supervisors] = await Promise.all(['SCANNER', 'SUPERVISOR'].map((role) =>
    request(`/admin/users?role=${role}&page_size=200`, { auth: 'admin' })))
  return [...scanners.data, ...supervisors.data].map((u) => ({
    id: u.id, name: u.full_name, email: u.email, role: u.role, sessionId: u.assigned_session_id,
    active: u.is_active, lastLogin: u.last_login_at,
  }))
}
export async function addStaff({ name, email, password, sessionId, role = 'SCANNER' }) {
  const body = { full_name: name, email, password, role, assigned_session_id: role === 'SCANNER' ? sessionId || null : null }
  return (await request('/admin/users', { method: 'POST', auth: 'admin', body })).data
}
export async function updateStaff(id, patch) {
  return (await request(`/admin/users/${id}`, { method: 'PATCH', auth: 'admin', body: patch })).data
}
export const removeStaff = (id) => updateStaff(id, { is_active: false })
export const activateStaff = (id) => updateStaff(id, { is_active: true })
// ADMIN sets a new password for a volunteer (logs them out everywhere; clears lockout).
export async function resetStaffPassword(id, newPassword) {
  return (await request(`/admin/users/${id}/reset-password`, { method: 'POST', auth: 'admin', body: { new_password: newPassword } })).data
}

// Create the Excel report on the server, wait for it, then download it.
// onStatus receives 'generating' / 'downloading'. Throws ApiError on failure.
//
// - Single flight: only one report runs at a time. Clicking the same report again returns the request
//   that is already running (no duplicate job on the server); a different report is refused until it ends.
// - Polling starts fast and backs off; it is bounded by time, not by a number of polls, and rides out a
//   few transient poll failures (the free server may be waking up or busy generating the workbook).
// - The downloaded file is checked to really be an .xlsx before it is handed to the browser.
const REPORT_MAX_WAIT_MS = 10 * 60 * 1000
const REPORT_POLL_FAILURES = 4
const XLSX_TYPE = 'spreadsheetml'
let reportFlight = null // { key, promise }

export function generateAndDownloadReport(type = 'FINAL', date = null, onStatus = () => {}) {
  const key = `${type}|${date || ''}`
  if (reportFlight) {
    if (reportFlight.key === key) return reportFlight.promise
    return Promise.reject(new ApiError(409, 'REPORT_BUSY', 'Another report is already being prepared'))
  }
  const promise = runReport(type, date, onStatus)
    .catch((e) => { if (e instanceof ApiError && e.code === 'NETWORK') e.context = 'report'; throw e })
    .finally(() => { reportFlight = null })
  reportFlight = { key, promise }
  return promise
}

const pollDelay = (elapsedMs) => (elapsedMs < 10_000 ? 1000 : elapsedMs < 60_000 ? 2000 : 4000)
const isTransient = (e) => e instanceof ApiError && (e.code === 'NETWORK' || e.status >= 500 || e.status === 429)

async function runReport(type, date, onStatus) {
  onStatus('generating')
  const started = Date.now()
  let job = await requestReport(type, date) // never retried: a retry could create a second job
  let failures = 0
  while (job.status === 'PENDING' || job.status === 'RUNNING') {
    const elapsed = Date.now() - started
    if (elapsed > REPORT_MAX_WAIT_MS) throw new ApiError(504, 'REPORT_TIMEOUT', 'Report is taking too long')
    await sleep(pollDelay(elapsed))
    try {
      job = await reportStatus(job.id)
      failures = 0
    } catch (e) {
      if (!isTransient(e) || ++failures >= REPORT_POLL_FAILURES) throw e
    }
  }
  if (job.status !== 'COMPLETED') throw new ApiError(500, 'REPORT_FAILED', 'Report generation failed')
  onStatus('downloading')
  await downloadReport(job.id, job.file_name)
  return job
}

// Excel reports (generated asynchronously on the server).
export async function requestReport(type, date) {
  return (await request('/reports/exports', { method: 'POST', auth: 'admin', body: { report_type: type, report_date: date || null } })).data
}
export async function reportStatus(id) { return (await request(`/reports/exports/${id}`, { auth: 'admin' })).data }
export async function downloadReport(id, fileName) {
  const res = await request(`/reports/exports/${id}/download`, { auth: 'admin', raw: true, retries: 2 })
  let blob
  try { blob = await res.blob() } catch { throw new ApiError(0, 'NETWORK', 'Download was interrupted') }
  const type = res.headers.get('Content-Type') || ''
  const expected = Number(res.headers.get('Content-Length')) || 0
  if (!type.includes(XLSX_TYPE) || blob.size < 1000 || (expected && blob.size !== expected))
    throw new ApiError(502, 'REPORT_INVALID', 'The downloaded file is not a valid report')
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = fileName || 'mahayagya-report.xlsx'; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}

// ------------------------------------------------------------ UI helpers
export const fmtDate = (d, lang = 'en', opts = { weekday: 'short', day: 'numeric', month: 'short' }) =>
  new Date(d + 'T12:00:00').toLocaleDateString(lang === 'hi' ? 'hi-IN' : 'en-IN', opts)
export const fmtTime = (hhmm) => {
  const [h, m] = hhmm.split(':').map(Number)
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`
}

// Poll an async loader; returns [data, reload, error]. Re-runs when deps change.
export function usePoll(fn, ms, deps = []) {
  const [state, setState] = useState({ data: null, error: null })
  const [n, setN] = useState(0)
  useEffect(() => {
    let alive = true
    const run = () => fn().then((data) => alive && setState({ data, error: null })).catch((error) => alive && setState((s) => ({ data: s.data, error })))
    run()
    const i = ms ? setInterval(run, ms) : null
    return () => { alive = false; if (i) clearInterval(i) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n, ms])
  return [state.data, () => setN((x) => x + 1), state.error]
}
