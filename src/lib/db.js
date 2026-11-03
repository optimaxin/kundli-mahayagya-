// Mock backend (localStorage). Same function names/shapes the real API (Cloudflare Worker + D1) will expose,
// so the UI never changes when the backend is wired in.
// ponytail: client-side signature is NOT secure; real HMAC lives on the server.

export const EVENT = {
  nameHi: '2151 कुंडीय महायज्ञ',
  nameEn: '2151 Kundiya Mahayagya',
  venueHi: 'जेसीबी तिराहा, शास्त्रीपुरम, आगरा',
  venueEn: 'JCB Tiraha, Shastripuram, Agra',
  dates: ['2026-12-14', '2026-12-15', '2026-12-16', '2026-12-17', '2026-12-18', '2026-12-19', '2026-12-20', '2026-12-21'],
  // confirmed: 8-11 AM and 1-4 PM
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

const KEY = 'km_db_v1'
const DEFAULT_STAFF = { id: 's1', name: 'Volunteer 1', pin: '1234' }
let db = load()

function load() {
  try { const d = JSON.parse(localStorage.getItem(KEY)); if (d && !d.staff) d.staff = [DEFAULT_STAFF]; return d || { bookings: [], occ: {}, blocked: {}, staff: [DEFAULT_STAFF] } }
  catch { return { bookings: [], occ: {}, blocked: {}, staff: [DEFAULT_STAFF] } }
}
function save() { try { localStorage.setItem(KEY, JSON.stringify(db)) } catch {} }
export function reload() { db = load(); return db }

const sk = (date, session) => `${date}|${session}`
export const allSlots = () => EVENT.dates.flatMap((date) => Object.keys(EVENT.sessions).map((session) => ({ date, session })))

// ---- seat allocation: best fit (fill partly used kunds first, fewest leftover seats) ----
export function pickKund(date, session, n) {
  const k = sk(date, session)
  const occ = db.occ[k] || {}
  const bl = db.blocked[k] || {}
  let best = 0, bestLeft = 99
  for (const kd in occ) {
    const left = EVENT.seats - occ[kd]
    if (left >= n && left < bestLeft && !bl[kd]) { best = +kd; bestLeft = left; if (left === n) break }
  }
  if (best) return best
  for (let i = 1; i <= EVENT.kunds; i++) if (!occ[i] && !bl[i]) return i
  return 0
}

export function slotStats(date, session) {
  const k = sk(date, session)
  const occ = db.occ[k] || {}
  const blocked = Object.keys(db.blocked[k] || {}).length
  let used = 0, full = 0, partial = 0
  for (const kd in occ) { used += occ[kd]; occ[kd] >= EVENT.seats ? full++ : partial++ }
  const capacity = (EVENT.kunds - blocked) * EVENT.seats
  return { used, capacity, left: capacity - used, full, partial, blocked, empty: EVENT.kunds - blocked - full - partial }
}
export const canFit = (date, session, n) => pickKund(date, session, n) > 0

// ---- bookings ----
const rid = () => 'KM' + Array.from({ length: 6 }, () => '23456789ABCDEFGHJKMNPQRSTUVWXYZ'[Math.floor(Math.random() * 31)]).join('')
const sign = (id) => { let h = 2166136261; for (const c of id + 'km-secret') { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619) } return (h >>> 0).toString(36) }
export const qrPayload = (b) => `KM|${b.id}|${sign(b.id)}`

export function createBooking({ coordinator, members, slots }) {
  const n = members.length
  const picks = slots.map((s) => ({ ...s, kund: pickKund(s.date, s.session, n) }))
  const bad = picks.find((p) => !p.kund)
  if (bad) throw new Error(`FULL:${bad.date}|${bad.session}`)
  for (const p of picks) {
    const k = sk(p.date, p.session)
    db.occ[k] = db.occ[k] || {}
    db.occ[k][p.kund] = (db.occ[k][p.kund] || 0) + n
  }
  const b = {
    id: rid(), createdAt: Date.now(), coordinator, members,
    slots: picks.map((p) => ({ date: p.date, session: p.session, kund: p.kund, attended: false, attendedAt: null })),
  }
  db.bookings.unshift(b)
  save()
  return b
}
export const getBooking = (id) => db.bookings.find((b) => b.id === id)
export const allBookings = () => db.bookings
export const findByMobile = (m) =>
  db.bookings.filter((b) => b.coordinator.mobile === m || b.members.some((x) => x.mobile === m))

// ---- scanning: ticket is valid only inside its slot window (+grace) ----
export const slotWindow = (date, session) => {
  const s = EVENT.sessions[session]
  const g = EVENT.graceMin * 60000
  return [new Date(`${date}T${s.start}:00`).getTime() - g, new Date(`${date}T${s.end}:00`).getTime() + g]
}
export function checkIn(payload, now = Date.now(), by = '') {
  const [tag, id, sig] = String(payload).trim().split('|')
  const b = tag === 'KM' ? getBooking(id) : getBooking(String(payload).trim().toUpperCase())
  if (!b || (tag === 'KM' && sig !== sign(id))) return { ok: false, code: 'INVALID' }
  const live = b.slots.find((s) => { const [a, z] = slotWindow(s.date, s.session); return now >= a && now <= z })
  if (!live) {
    const next = b.slots.map((s) => ({ ...s, w: slotWindow(s.date, s.session) })).filter((s) => s.w[0] > now).sort((x, y) => x.w[0] - y.w[0])[0]
    return { ok: false, code: next ? 'EARLY' : 'EXPIRED', booking: b, next }
  }
  if (live.attended) return { ok: false, code: 'DUP', booking: b, slot: live }
  live.attended = true
  live.attendedAt = now
  live.by = by
  save()
  return { ok: true, booking: b, slot: live }
}
export function toggleAttended(id, date, session) {
  const s = getBooking(id)?.slots.find((x) => x.date === date && x.session === session)
  if (!s) return
  s.attended = !s.attended
  s.attendedAt = s.attended ? Date.now() : null
  save()
}

// ---- admin ----
export function toggleBlock(date, session, kund) {
  const k = sk(date, session)
  if ((db.occ[k] || {})[kund]) return false
  db.blocked[k] = db.blocked[k] || {}
  db.blocked[k][kund] ? delete db.blocked[k][kund] : (db.blocked[k][kund] = 1)
  save()
  return true
}
export const kundMap = (date, session) => ({ occ: db.occ[sk(date, session)] || {}, blocked: db.blocked[sk(date, session)] || {} })
export const kundFamilies = (date, session, kund) =>
  db.bookings.filter((b) => b.slots.some((s) => s.date === date && s.session === session && s.kund === kund))

export function overview() {
  const days = EVENT.dates.map((date) => {
    const row = { date }
    for (const session of Object.keys(EVENT.sessions)) {
      const st = slotStats(date, session)
      let att = 0
      for (const b of db.bookings) for (const s of b.slots) if (s.date === date && s.session === session && s.attended) att += b.members.length
      row[session] = { ...st, attended: att }
    }
    return row
  })
  const people = db.bookings.reduce((a, b) => a + b.members.length, 0)
  const entered = days.reduce((a, d) => a + d.morning.attended + d.afternoon.attended, 0)
  const seatsTotal = EVENT.dates.length * 2 * EVENT.kunds * EVENT.seats
  const seatsUsed = days.reduce((a, d) => a + d.morning.used + d.afternoon.used, 0)
  return { days, families: db.bookings.length, people, entered, seatsTotal, seatsUsed }
}

// ---- demo data ----
const FIRST = ['Ramesh', 'Sunita', 'Mahesh', 'Geeta', 'Suresh', 'Kavita', 'Anil', 'Meena', 'Rajesh', 'Pooja', 'Vikas', 'Anita', 'Deepak', 'Rekha', 'Manoj', 'Sarita']
const LAST = ['Sharma', 'Verma', 'Gupta', 'Agarwal', 'Yadav', 'Singh', 'Mishra', 'Jain', 'Chauhan', 'Pandey']
const REL = ['Spouse', 'Parent', 'Child', 'Sibling', 'Relative']
const pick = (a) => a[Math.floor(Math.random() * a.length)]
export function seedDemo(count = 500) {
  const slots = allSlots()
  for (let i = 0; i < count; i++) {
    const size = Math.min(8, 1 + Math.floor(Math.random() ** 1.6 * 8))
    const mob = () => '9' + String(Math.floor(Math.random() * 1e9)).padStart(9, '0')
    const nm = () => `${pick(FIRST)} ${pick(LAST)}`
    const members = Array.from({ length: size }, (_, j) => ({
      name: j ? nm() : '', age: String(8 + Math.floor(Math.random() * 70)), gender: pick(['male', 'female']),
      relationship: j ? pick(REL) : 'Self', mobile: '', self: !j,
    }))
    const coordinator = { name: nm(), mobile: mob(), city: pick(['Agra', 'Mathura', 'Firozabad', 'Aligarh', 'Gwalior']), state: 'Uttar Pradesh' }
    members[0].name = coordinator.name
    const chosen = [pick(slots)]
    if (Math.random() < 0.25) chosen.push(pick(slots))
    const uniq = [...new Map(chosen.map((s) => [sk(s.date, s.session), s])).values()]
    try {
      const b = createBooking({ coordinator, members, slots: uniq })
      b.createdAt = Date.now() - Math.floor(Math.random() ** 1.5 * 13 * 864e5)
      for (const sl of b.slots) if (Math.random() < .3) { sl.attended = true; sl.attendedAt = Date.now() - Math.floor(Math.random() * 36e5 * 5); sl.by = pick(['Volunteer 1', 'Ramesh (Gate A)', 'Sunita (Gate B)']) }
    } catch {}
  }
  save()
}
export function resetAll() { db = { bookings: [], occ: {}, blocked: {}, staff: db.staff }; save() }

// ---- helpers shared by UI ----
export const fmtDate = (d, lang = 'en', opts = { weekday: 'short', day: 'numeric', month: 'short' }) =>
  new Date(d + 'T12:00:00').toLocaleDateString(lang === 'hi' ? 'hi-IN' : 'en-IN', opts)
export const fmtTime = (hhmm) => {
  const [h, m] = hhmm.split(':').map(Number)
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`
}

// ---- volunteers / staff ----
export const staffList = () => db.staff
export function staffLogin(pin) { return db.staff.find((x) => x.pin === String(pin).trim()) || null }
export function addStaff(name, pin) { db.staff.push({ id: 's' + Date.now(), name, pin }); save() }
export function removeStaff(id) { db.staff = db.staff.filter((x) => x.id !== id); save() }
export const recentScans = (by, n = 8) =>
  db.bookings.flatMap((b) => b.slots.filter((s) => s.attended && (!by || s.by === by)).map((s) => ({ b, s })))
    .sort((x, y) => y.s.attendedAt - x.s.attendedAt).slice(0, n)

// ---- analytics for the dashboard ----
export function analytics() {
  const ov = overview()
  const ages = { '0-12': 0, '13-30': 0, '31-50': 0, '51-70': 0, '70+': 0 }
  const gender = { male: 0, female: 0, other: 0 }
  const sizes = Array(9).fill(0)
  const cities = {}
  const perDay = {}
  const staff = {}
  const rel = {}
  for (const b of db.bookings) {
    sizes[b.members.length]++
    cities[b.coordinator.city] = (cities[b.coordinator.city] || 0) + b.members.length
    const d = new Date(b.createdAt).toISOString().slice(0, 10)
    perDay[d] = (perDay[d] || 0) + 1
    for (const m of b.members) {
      const a = +m.age
      ages[a <= 12 ? '0-12' : a <= 30 ? '13-30' : a <= 50 ? '31-50' : a <= 70 ? '51-70' : '70+']++
      gender[m.gender] = (gender[m.gender] || 0) + 1
      rel[m.relationship] = (rel[m.relationship] || 0) + 1
    }
    for (const s of b.slots) if (s.attended) staff[s.by || 'Manual'] = (staff[s.by || 'Manual'] || 0) + b.members.length
  }
  const trend = Array.from({ length: 14 }, (_, i) => {
    const dt = new Date(Date.now() - (13 - i) * 864e5), k = dt.toISOString().slice(0, 10)
    return { date: k, n: perDay[k] || 0 }
  })
  const top = (o, n = 6) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n)
  return { ...ov, ages, gender, sizes, cities: top(cities), trend, staff: top(staff, 10), rel: top(rel), avgFamily: ov.families ? ov.people / ov.families : 0 }
}
