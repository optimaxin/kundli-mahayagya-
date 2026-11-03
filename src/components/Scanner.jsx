import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Html5Qrcode } from 'html5-qrcode'
import { Camera, CameraOff, Check, DoorOpen, ScanLine, X, Users, UserCheck } from 'lucide-react'
import { useLang } from '../lib/lang.jsx'
import { Btn } from './ui.jsx'
import { EVENT, checkInMember, describeError, fmtDate, fmtTime, recentScans, scanPass } from '../lib/db.js'

// Shared by the admin console (kind="admin", explicit sessionId) and the volunteer page (kind="staff":
// the session comes from the scanner account on the server). Scan a family pass, then mark EACH member
// as they walk in -- one member's entry never marks the rest of the family.
export default function Scanner({ kind = 'staff', sessionId }) {
  const { t, lang } = useLang()
  const [on, setOn] = useState(false)
  const [res, setRes] = useState(null)
  const [manual, setManual] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [recent, setRecent] = useState([])
  const scanner = useRef(null)
  const last = useRef({ v: '', t: 0 })
  // The camera callback is registered once, so read the (admin-selectable) session through a ref.
  const sessRef = useRef(sessionId)
  sessRef.current = sessionId

  const loadRecent = () => recentScans(kind, 30).then(setRecent).catch(() => {})
  useEffect(() => { loadRecent() }, [kind])

  const handle = async (code) => {
    const nowMs = Date.now()
    if (last.current.v === code && nowMs - last.current.t < 3000) return
    last.current = { v: code, t: nowMs }
    setErr('')
    try {
      const r = await scanPass(kind, code, sessRef.current)
      setRes({ ...r, code, at: nowMs })
      navigator.vibrate?.(r.status === 'VALID' ? 60 : [60, 80, 60])
    } catch (x) { setRes(null); setErr(describeError(x, t)) }
  }

  const mark = async (numbers) => {
    if (!res) return
    setBusy(true); setErr('')
    try {
      let roster = res.roster
      for (const n of numbers) {
        const r = await checkInMember(kind, res.code, n, sessRef.current)
        if (r.status === 'CHECKIN_SUCCESS' || r.status === 'ALREADY_CHECKED_IN') {
          roster = roster.map((m) => (m.member_number === n ? { ...m, checked_in: true, checked_in_at: r.checked_in_at } : m))
        } else { setErr(r.message); break }
      }
      const done = roster.filter((m) => m.checked_in).length
      setRes((p) => ({ ...p, roster, checked_in_count: done, reason: done === roster.length ? 'ALL_CHECKED_IN' : null, at: p.at }))
      navigator.vibrate?.(40)
      loadRecent()
    } catch (x) { setErr(describeError(x, t)) } finally { setBusy(false) }
  }

  const stop = async () => { try { await scanner.current?.stop(); scanner.current?.clear() } catch { /* not running */ } setOn(false) }
  const start = async () => {
    setErr('')
    try {
      scanner.current = new Html5Qrcode('km-reader')
      await scanner.current.start({ facingMode: 'environment' }, { fps: 10, qrbox: (w, h) => { const m = Math.floor(Math.min(w, h) * 0.72); return { width: m, height: m } } }, handle, () => {})
      setOn(true)
    } catch { setErr(t('Camera unavailable. Use manual entry below.', 'कैमरा उपलब्ध नहीं। नीचे मैन्युअल एंट्री करें।')) }
  }
  useEffect(() => () => { scanner.current?.isScanning && scanner.current.stop().catch(() => {}) }, [])

  const R = res
  const resRef = useRef(null)
  useEffect(() => { R && resRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [R?.at])
  const valid = R?.status === 'VALID'
  const allIn = valid && R.reason === 'ALL_CHECKED_IN'
  const tone = !R ? '' : valid && !allIn ? 'from-emerald-500 to-emerald-700' : allIn ? 'from-amber-500 to-orange-600' : 'from-red-500 to-red-700'
  const msg = !R ? '' : allIn ? t('ALREADY ENTERED', 'पहले ही प्रवेश हो चुका') : valid ? t('PASS VALID', 'प्रवेश पत्र मान्य') : ({
    UNKNOWN_PASS: t('INVALID TICKET', 'अमान्य टिकट'), PASS_REVOKED: t('PASS REVOKED', 'प्रवेश पत्र निरस्त'),
    SESSION_NOT_OPEN: t('NOT VALID YET', 'अभी मान्य नहीं'), SESSION_OVER: t('SESSION OVER', 'सत्र समाप्त'),
    NO_RESERVATION: t('NOT BOOKED FOR THIS SESSION', 'इस सत्र हेतु पंजीकृत नहीं'),
    BOOKING_CANCELLED: t('BOOKING CANCELLED', 'पंजीकरण रद्द'), RESERVATION_CANCELLED: t('BOOKING CANCELLED', 'पंजीकरण रद्द'),
    SCANNER_UNASSIGNED: t('NO SESSION ASSIGNED', 'कोई सत्र आवंटित नहीं'), SESSION_INACTIVE: t('SESSION NOT ACTIVE', 'सत्र सक्रिय नहीं'),
  }[R.reason] || t('INVALID TICKET', 'अमान्य टिकट'))
  const sessLabel = (s) => `${fmtDate(s.event_date, lang)} · ${t(EVENT.sessions[s.slot.toLowerCase()].en, EVENT.sessions[s.slot.toLowerCase()].hi)}`
  const upcoming = (R?.booked_sessions || []).filter((s) => s.status === 'CONFIRMED')
  const pending = valid ? R.roster.filter((m) => !m.checked_in) : []

  // Group recent per-member entries by family + session.
  const groups = []
  for (const r of recent) {
    const k = r.booking_number + '|' + r.session_id
    const g = groups.find((x) => x.k === k)
    if (g) g.n++
    else groups.push({ k, ...r, n: 1 })
  }

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-5">
      <div className="contents lg:block">
        <div className="order-2 rounded-3xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <div id="km-reader" className="mx-auto w-full max-w-sm overflow-hidden rounded-2xl bg-maroon-950 [&_video]:!w-full [&_video]:!object-cover" style={{ display: on ? 'block' : 'none' }} />
          {!on && <div className="mx-auto grid h-44 w-full max-w-sm place-items-center rounded-2xl bg-gradient-to-br from-maroon-900 to-maroon-950 text-maroon-200 sm:h-64"><div className="text-center"><ScanLine size={48} className="mx-auto text-gold-400" /><p className="mt-2 text-sm">{t('Camera is off', 'कैमरा बंद है')}</p></div></div>}
          {err && <p className="mt-3 text-sm font-semibold text-red-600">{err}</p>}
          <Btn onClick={on ? stop : start} variant={on ? 'ghost' : 'maroon'} className="mt-3 w-full">{on ? <><CameraOff size={18} />{t('Stop camera', 'कैमरा बंद करें')}</> : <><Camera size={18} />{t('Start scanning', 'स्कैन शुरू करें')}</>}</Btn>
          <form onSubmit={(e) => { e.preventDefault(); manual && handle(manual) }} className="mt-3 flex gap-2">
            <input value={manual} onChange={(e) => setManual(e.target.value.toUpperCase().slice(0, 13))} placeholder={t('Pass ID (MY26-XXXXXXXX)', 'पास आईडी (MY26-XXXXXXXX)')} className="min-h-12 min-w-0 flex-1 rounded-xl border border-slate-300 px-3 text-base outline-none focus:border-saffron-500" />
            <Btn type="submit" className="shrink-0 px-5" disabled={manual.length < 13}>{t('Check', 'जाँचें')}</Btn>
          </form>
          <p className="mt-2 text-xs text-slate-500">{t('With a typed Pass ID, check the names against a photo ID.', 'पास आईडी टाइप करने पर नाम फोटो पहचान पत्र से मिलाएँ।')}</p>
        </div>
      </div>

      <div className="contents lg:block lg:space-y-5">
        <div ref={resRef} className="order-1 scroll-mt-20">
          {!R ? (
            <div className="hidden min-h-60 place-items-center rounded-3xl border border-slate-200 bg-white p-5 text-center text-slate-400 shadow-sm lg:grid"><div><DoorOpen size={48} className="mx-auto" /><p className="mt-2 text-sm">{t('Scan result appears here', 'स्कैन परिणाम यहाँ दिखेगा')}</p></div></div>
          ) : (
            <motion.div key={R.at} initial={{ scale: .94, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className={`overflow-hidden rounded-3xl bg-gradient-to-br ${tone} text-white shadow-xl`}>
              <div className="flex items-center gap-4 p-4 sm:flex-col sm:p-6 sm:text-center">
                <div className="grid size-14 shrink-0 place-items-center rounded-full bg-white/20 sm:mx-auto sm:size-20">{valid ? <Check className="size-8 sm:size-12" /> : <X className="size-8 sm:size-12" />}</div>
                <div className="font-display text-2xl leading-tight sm:text-3xl">{msg}</div>
              </div>
              {R.booking_number && (
                <div className="space-y-1 bg-black/20 p-4 text-sm sm:p-5">
                  <div className="flex flex-wrap items-center gap-2 text-lg font-bold">{R.coordinator_name} <span className="inline-flex items-center gap-1 rounded-full bg-white/20 px-2 py-0.5 text-sm"><Users size={13} />{R.member_count}</span></div>
                  <div className="break-all">{R.booking_number}{R.primary_mobile_masked ? ` · +91 ${R.primary_mobile_masked}` : ''}</div>
                  {valid && <div className="text-base font-bold">{t('Kund', 'कुंड')} #{R.kund_number} · {sessLabel(R.session)}</div>}
                  {!valid && upcoming.length > 0 && <div>{t('Booked for', 'पंजीकृत')}: {upcoming.map((s) => `${sessLabel(s)} (${fmtTime(EVENT.sessions[s.slot.toLowerCase()].start)})`).join(', ')}</div>}
                </div>
              )}
              {valid && (
                <div className="space-y-2 bg-white p-3 text-slate-800 sm:p-4">
                  <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider text-slate-500"><span>{t('Tap each member as they enter', 'प्रत्येक सदस्य के प्रवेश पर दबाएँ')}</span><span>{R.checked_in_count}/{R.member_count}</span></div>
                  {R.roster.map((m) => (
                    <button key={m.member_number} disabled={busy || m.checked_in} onClick={() => mark([m.member_number])} className={`flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left text-sm font-semibold transition ${m.checked_in ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-slate-200 hover:border-saffron-400 active:scale-[.98]'}`}>
                      <span className="min-w-0 truncate">{m.member_number}. {m.full_name}{m.age ? <span className="font-normal text-slate-500"> · {m.age}</span> : null}</span>
                      {m.checked_in ? <span className="flex shrink-0 items-center gap-1 text-xs"><Check size={14} />{new Date(m.checked_in_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</span> : <span className="shrink-0 rounded-full bg-saffron-500 px-3 py-1 text-xs text-white">{t('Enter', 'प्रवेश')}</span>}
                    </button>
                  ))}
                  {pending.length > 1 && <Btn variant="maroon" className="w-full" disabled={busy} onClick={() => mark(pending.map((m) => m.member_number))}><UserCheck size={18} />{t(`All ${pending.length} present`, `सभी ${pending.length} उपस्थित`)}</Btn>}
                </div>
              )}
            </motion.div>
          )}
        </div>
        <div className="order-3 rounded-3xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <h3 className="mb-3 text-sm font-bold text-slate-800">{t('My recent entries', 'मेरी हाल की प्रविष्टियाँ')}</h3>
          {!groups.length && <p className="text-sm text-slate-400">{t('No entries yet', 'अभी कोई प्रविष्टि नहीं')}</p>}
          <div className="divide-y divide-slate-100">
            {groups.slice(0, 6).map((g) => (
              <div key={g.k} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="min-w-0"><b className="block truncate text-slate-800">{g.coordinator_name}</b><span className="block truncate text-xs text-slate-500">{g.booking_number} · {t('Kund', 'कुंड')} #{g.kund_number}</span></span>
                <span className="shrink-0 text-right text-xs text-slate-500"><b className="block text-emerald-600">{g.n}/{g.member_count} ✔</b>{new Date(g.checked_in_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
