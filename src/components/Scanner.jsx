import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Html5Qrcode } from 'html5-qrcode'
import { Camera, CameraOff, Check, DoorOpen, ScanLine, X, Users } from 'lucide-react'
import { useLang } from '../lib/lang.jsx'
import { Btn } from './ui.jsx'
import { EVENT, checkIn, fmtDate, fmtTime, recentScans, reload } from '../lib/db.js'

// Shared by the admin console and the volunteer (staff) page. `by` = volunteer name stored with each entry.
export default function Scanner({ by = '' }) {
  const { t, lang } = useLang()
  const [on, setOn] = useState(false)
  const [res, setRes] = useState(null)
  const [manual, setManual] = useState('')
  const [fake, setFake] = useState('')
  const [err, setErr] = useState('')
  const [, force] = useState(0)
  const scanner = useRef(null)
  const last = useRef({ v: '', t: 0 })
  const fakeRef = useRef('')
  fakeRef.current = fake

  const handle = (code) => {
    const nowMs = Date.now()
    if (last.current.v === code && nowMs - last.current.t < 3000) return
    last.current = { v: code, t: nowMs }
    reload()
    setRes({ ...checkIn(code, fakeRef.current ? new Date(fakeRef.current).getTime() : Date.now(), by), at: nowMs })
    navigator.vibrate?.(60)
    force((x) => x + 1)
  }
  const stop = async () => { try { await scanner.current?.stop(); scanner.current?.clear() } catch {} setOn(false) }
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
  const tone = !R ? '' : R.ok ? 'from-emerald-500 to-emerald-700' : R.code === 'DUP' ? 'from-amber-500 to-orange-600' : 'from-red-500 to-red-700'
  const msg = !R ? '' : {
    undefined: t('ENTRY OK', 'प्रवेश मान्य'), DUP: t('ALREADY ENTERED', 'पहले ही प्रवेश हो चुका'),
    INVALID: t('INVALID TICKET', 'अमान्य टिकट'), EARLY: t('NOT VALID YET', 'अभी मान्य नहीं'), EXPIRED: t('SESSION OVER', 'सत्र समाप्त'),
  }[R.ok ? undefined : R.code]
  const recent = recentScans(by, 6)

  // Phones: result first (always visible), then camera, then history. Desktop: camera left, result + history right.
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-5">
      <div className="contents lg:block">
        <div className="order-2 rounded-3xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <div id="km-reader" className="mx-auto w-full max-w-sm overflow-hidden rounded-2xl bg-maroon-950 [&_video]:!w-full [&_video]:!object-cover" style={{ display: on ? 'block' : 'none' }} />
          {!on && <div className="mx-auto grid h-44 w-full max-w-sm place-items-center rounded-2xl bg-gradient-to-br from-maroon-900 to-maroon-950 text-maroon-200 sm:h-64"><div className="text-center"><ScanLine size={48} className="mx-auto text-gold-400" /><p className="mt-2 text-sm">{t('Camera is off', 'कैमरा बंद है')}</p></div></div>}
          {err && <p className="mt-3 text-sm font-semibold text-red-600">{err}</p>}
          <Btn onClick={on ? stop : start} variant={on ? 'ghost' : 'maroon'} className="mt-3 w-full">{on ? <><CameraOff size={18} />{t('Stop camera', 'कैमरा बंद करें')}</> : <><Camera size={18} />{t('Start scanning', 'स्कैन शुरू करें')}</>}</Btn>
          <form onSubmit={(e) => { e.preventDefault(); manual && handle(manual) }} className="mt-3 flex gap-2">
            <input value={manual} onChange={(e) => setManual(e.target.value.toUpperCase())} placeholder={t('Pass ID (KMXXXXXX)', 'पास आईडी (KMXXXXXX)')} className="min-h-12 min-w-0 flex-1 rounded-xl border border-slate-300 px-3 text-base outline-none focus:border-saffron-500" />
            <Btn type="submit" className="shrink-0 px-5">{t('Check', 'जाँचें')}</Btn>
          </form>
          <details className="mt-3 text-xs text-slate-500">
            <summary className="cursor-pointer font-bold">{t('Demo: test clock', 'डेमो: टेस्ट घड़ी')}</summary>
            <input type="datetime-local" value={fake} onChange={(e) => setFake(e.target.value)} className="mt-2 min-h-11 w-full rounded-xl border border-slate-300 px-3 text-sm font-medium" />
            <p className="mt-1">{t('Pretend it is this time to try the session-window rule.', 'सत्र-समय नियम जाँचने हेतु मान लें अभी यही समय है।')}</p>
          </details>
        </div>
      </div>

      <div className="contents lg:block lg:space-y-5">
        <div ref={resRef} className="order-1 scroll-mt-20">
          {!R ? (
            <div className="hidden min-h-60 place-items-center rounded-3xl border border-slate-200 bg-white p-5 text-center text-slate-400 shadow-sm lg:grid"><div><DoorOpen size={48} className="mx-auto" /><p className="mt-2 text-sm">{t('Scan result appears here', 'स्कैन परिणाम यहाँ दिखेगा')}</p></div></div>
          ) : (
            <motion.div key={R.at} initial={{ scale: .94, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className={`overflow-hidden rounded-3xl bg-gradient-to-br ${tone} text-white shadow-xl`}>
              <div className="flex items-center gap-4 p-4 sm:flex-col sm:p-6 sm:text-center">
                <div className="grid size-14 shrink-0 place-items-center rounded-full bg-white/20 sm:mx-auto sm:size-20">{R.ok ? <Check className="size-8 sm:size-12" /> : <X className="size-8 sm:size-12" />}</div>
                <div className="font-display text-2xl leading-tight sm:text-3xl">{msg}</div>
              </div>
              {R.booking && (
                <div className="space-y-1 bg-black/20 p-4 text-sm sm:p-5">
                  <div className="flex flex-wrap items-center gap-2 text-lg font-bold">{R.booking.coordinator.name} <span className="inline-flex items-center gap-1 rounded-full bg-white/20 px-2 py-0.5 text-sm"><Users size={13} />{R.booking.members.length}</span></div>
                  <div className="break-all">{R.booking.id} · +91 {R.booking.coordinator.mobile}</div>
                  {R.slot && <div className="font-semibold">{t('Kund', 'कुंड')} #{R.slot.kund} · {fmtDate(R.slot.date, lang)} · {t(EVENT.sessions[R.slot.session].en, EVENT.sessions[R.slot.session].hi)}</div>}
                  {R.code === 'DUP' && <div>{t('Entered at', 'प्रवेश समय')} {new Date(R.slot.attendedAt).toLocaleTimeString('en-IN')}</div>}
                  {R.next && <div>{t('Valid on', 'मान्य')} {fmtDate(R.next.date, lang)} · {t(EVENT.sessions[R.next.session].en, EVENT.sessions[R.next.session].hi)} ({fmtTime(EVENT.sessions[R.next.session].start)})</div>}
                </div>
              )}
            </motion.div>
          )}
        </div>
        <div className="order-3 rounded-3xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <h3 className="mb-3 text-sm font-bold text-slate-800">{by ? t('My recent entries', 'मेरी हाल की प्रविष्टियाँ') : t('Recent entries', 'हाल की प्रविष्टियाँ')}</h3>
          {!recent.length && <p className="text-sm text-slate-400">{t('No entries yet', 'अभी कोई प्रविष्टि नहीं')}</p>}
          <div className="divide-y divide-slate-100">
            {recent.map(({ b, s }) => (
              <div key={b.id + s.date + s.session} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="min-w-0"><b className="block truncate text-slate-800">{b.coordinator.name}</b><span className="block truncate text-xs text-slate-500">{b.id} · {t('Kund', 'कुंड')} #{s.kund}</span></span>
                <span className="shrink-0 text-right text-xs text-slate-500"><b className="block text-emerald-600">{b.members.length} ✔</b>{new Date(s.attendedAt).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
