import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import QRCode from 'qrcode'
import { CheckCircle2, Download, Flame, Clock, MapPin, Search, Sunrise, Sunset, Users, Printer, Share2 } from 'lucide-react'
import { useLang } from '../lib/lang.jsx'
import { Btn, KundTag, Mandala, Om } from '../components/ui.jsx'
import { EVENT, describeError, getBooking, qrPayload, slotWindow, fmtDate, fmtTime } from '../lib/db.js'

// "8:00 AM" with a no-break space, so a time never splits between the number and AM/PM.
const tm = (hhmm) => fmtTime(hhmm).replace(' ', ' ')

// html-to-image copies every computed style into its snapshot, including each box's on-screen pixel
// height and grid row sizes. If the phone then draws the snapshot with a different font (e.g. the web
// font could not be embedded), text re-wraps inside boxes frozen at the old height and overlaps the next
// line. Leaving those properties out lets every box and grid row grow with its text; widths are kept so
// the layout stays the same. (Fixed-size boxes such as the QR, date tile and Om use aspect-ratio.)
const HEIGHT_PROPS = new Set(['height', 'min-height', 'max-height', 'block-size', 'min-block-size', 'max-block-size', 'grid-template-rows', 'grid-auto-rows'])
const BG = [0xff, 0xf9, 0xee] // #fff9ee, the page colour the pass is drawn on

// Renders `el` to a canvas without fixed heights; the snapshot area gets extra room below in case the
// content grew, and the unused background strip is trimmed off again.
async function passCanvas(el) {
  const { toCanvas } = await import('html-to-image')
  const props = Array.from(getComputedStyle(document.documentElement)).filter((p) => !HEIGHT_PROPS.has(p))
  const ratio = 2
  const slack = Math.ceil(el.offsetHeight * 0.3)
  const full = await toCanvas(el, { pixelRatio: ratio, backgroundColor: '#fff9ee', cacheBust: true, includeStyleProperties: props, height: el.offsetHeight + slack })
  const ctx = full.getContext('2d')
  const W = full.width, from = Math.max(0, full.height - slack * ratio * 2)
  const px = ctx.getImageData(0, from, W, full.height - from).data
  let last = full.height - 1
  scan: for (; last > from; last--) {
    const row = (last - from) * W * 4
    for (let x = 0; x < W; x += 3) {
      const i = row + x * 4
      if (Math.abs(px[i] - BG[0]) > 6 || Math.abs(px[i + 1] - BG[1]) > 6 || Math.abs(px[i + 2] - BG[2]) > 6) break scan
    }
  }
  const h = Math.min(full.height, last + 1 + 12 * ratio)
  const out = document.createElement('canvas')
  out.width = W; out.height = h
  out.getContext('2d').drawImage(full, 0, 0)
  return out
}

export default function Ticket() {
  const { id } = useParams() // the pass token (kept in the URL hash, never sent to the server in a URL)
  const [sp] = useSearchParams()
  const { t, lang } = useLang()
  const [b, setB] = useState(undefined) // undefined = loading, null = not found
  const [loadErr, setLoadErr] = useState('')
  useEffect(() => {
    let alive = true
    setB(undefined); setLoadErr('')
    getBooking(id).then((x) => alive && setB(x)).catch((e) => { if (alive) { setB(null); setLoadErr(describeError(e, t)) } })
    return () => { alive = false }
  }, [id])
  const [qr, setQr] = useState('')
  const [busy, setBusy] = useState(false)
  const ref = useRef(null)
  const pdfRef = useRef(null)
  const auto = useRef(false)
  // auto-download the pass once, right after registration (button stays available if the browser blocks it)
  useEffect(() => {
    if (!qr || !sp.get('new') || auto.current) return
    auto.current = true
    setTimeout(async () => { await document.fonts?.ready; pdfRef.current?.() }, 900)
  }, [qr])
  useEffect(() => { if (b) QRCode.toDataURL(qrPayload(b), { width: 560, margin: 1, color: { dark: '#430d19', light: '#ffffff' }, errorCorrectionLevel: 'M' }).then(setQr) }, [b?.qr])

  if (b === undefined) return (
    <div className="mx-auto max-w-md px-4 py-24 text-center text-maroon-800">
      <Flame className="mx-auto flicker text-saffron-500" size={48} />
      <p className="mt-3 font-semibold">{t('Loading your pass…', 'प्रवेश पत्र लोड हो रहा है…')}</p>
    </div>
  )
  if (!b) return (
    <div className="mx-auto max-w-md px-4 py-24 text-center">
      <Search className="mx-auto text-maroon-200" size={56} />
      <h1 className="font-display mt-4 text-3xl text-maroon-900">{t('Pass not found', 'प्रवेश पत्र नहीं मिला')}</h1>
      <p className="mt-2 text-stone-600">{loadErr || t('This pass link is not valid, or the pass was re-issued by the help desk. Look for passes saved on this device, or bring your booking number and photo ID to the help desk.', 'यह लिंक मान्य नहीं है, या हेल्प डेस्क ने नया प्रवेश पत्र जारी किया है। इस डिवाइस पर सहेजे प्रवेश पत्र देखें, या बुकिंग नंबर व फोटो पहचान पत्र के साथ हेल्प डेस्क पर आएँ।')}</p>
      <Btn as={Link} to="/find" className="mt-6">{t('Find my pass', 'प्रवेश पत्र खोजें')}</Btn>
    </div>
  )

  const now = Date.now()
  const status = (s) => {
    const [a, z] = slotWindow(s.date, s.session)
    if (s.status === 'CANCELLED') return ['cancelled', t('Cancelled', 'रद्द'), 'bg-red-100 text-red-700']
    if (s.attended) return ['done', `${t('Entered', 'प्रवेश')} ${s.checkedIn}/${b.members.length} ✔`, 'bg-emerald-100 text-emerald-700']
    if (now > z) return ['past', t('Expired', 'समाप्त'), 'bg-stone-200 text-stone-600']
    if (now >= a) return ['live', t('Valid now', 'अभी मान्य'), 'bg-emerald-500 text-white animate-pulse']
    return ['soon', t('Opens at session time', 'सत्र समय पर मान्य'), 'bg-saffron-100 text-saffron-600']
  }

  const pdf = async () => {
    setBusy(true)
    try {
      const [canvas, { jsPDF }] = await Promise.all([passCanvas(ref.current), import('jspdf')])
      const url = canvas.toDataURL('image/jpeg', 0.9)
      const w = 190, h = (canvas.height / canvas.width) * w
      const doc = new jsPDF({ unit: 'mm', format: [210, Math.max(297, h + 20)] })
      doc.addImage(url, 'JPEG', 10, 10, w, h, undefined, 'FAST')
      doc.save(`Kundiya-Mahayagya-${b.id}.pdf`)
    } finally { setBusy(false) }
  }
  pdfRef.current = pdf
  const share = () => navigator.share?.({ title: EVENT.nameEn, text: `Pass ${b.id}`, url: location.href }).catch(() => {})

  return (
    <div className="paper pb-28 md:pb-16">
      <div className="mx-auto max-w-xl px-4 pt-8">
        {sp.get('new') && (
          <motion.div initial={{ scale: .8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className="mb-6 text-center">
            <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: 'spring', delay: .15 }} className="mx-auto grid size-16 place-items-center rounded-full bg-emerald-500 text-white shadow-xl"><CheckCircle2 size={36} /></motion.div>
            <h1 className="font-display mt-3 text-3xl text-maroon-900">{t('Registration confirmed!', 'पंजीकरण सफल!')}</h1>
            <p className="mt-1 text-sm text-stone-600">{t('Download your pass now. It is also saved on this device (Find pass → your mobile number).', 'अभी डाउनलोड करें। यह इस डिवाइस पर भी सहेजा है (प्रवेश पत्र खोजें → मोबाइल नंबर)।')}</p>
          </motion.div>
        )}

        {/* one compact row on phones (icon-only Print/Share) so the sticky bar does not hide the pass */}
        <div className="sticky top-[4.5rem] z-30 mb-5 grid grid-cols-[minmax(0,1fr)_auto_auto] gap-2 rounded-2xl border border-gold-300/70 bg-white/90 p-2 shadow-lg backdrop-blur sm:grid-cols-[1.6fr_1fr_1fr] sm:gap-2.5 sm:p-2.5">
          <Btn onClick={pdf} disabled={busy} className="min-h-12 px-3 text-center leading-tight sm:min-h-14 sm:px-6 sm:text-base"><Download size={20} className="shrink-0" />
            {busy ? t('Preparing…', 'तैयार हो रहा है…') : <><span className="sm:hidden">{t('Download PDF', 'PDF डाउनलोड')}</span><span className="hidden sm:inline">{t('Download pass (PDF)', 'प्रवेश पत्र डाउनलोड (PDF)')}</span></>}
          </Btn>
          <Btn variant="ghost" onClick={() => window.print()} aria-label={t('Print', 'प्रिंट')} className="min-h-12 px-3.5 sm:min-h-14 sm:px-6"><Printer size={18} className="shrink-0" /><span className="sr-only sm:not-sr-only">{t('Print', 'प्रिंट')}</span></Btn>
          <Btn variant="ghost" onClick={share} aria-label={t('Share', 'साझा करें')} className="min-h-12 px-3.5 sm:min-h-14 sm:px-6"><Share2 size={18} className="shrink-0" /><span className="sr-only sm:not-sr-only">{t('Share', 'साझा करें')}</span></Btn>
        </div>

        {/* the pass — this exact node becomes the PDF (the wrapper gives the snapshot room to grow) */}
        <div ref={ref}>
        <div className="overflow-hidden rounded-[2rem] bg-cream shadow-[0_30px_60px_-25px_rgba(67,13,25,.55)] ring-1 ring-gold-400/60">
          <div className="relative overflow-hidden bg-gradient-to-br from-maroon-800 via-maroon-900 to-maroon-950 px-6 pt-7 pb-6 text-center text-white">
            <Mandala className="absolute -right-16 -top-16 w-64 opacity-25" rings={3} />
            <Om size={52} className="mx-auto" />
            <div className="font-display mt-1 text-3xl gold-text">{t(EVENT.nameEn, EVENT.nameHi)}</div>
            <div className="mt-1 text-xs font-bold uppercase tracking-[.25em] text-maroon-200">{t('Devotional E-Pass', 'प्रवेश पत्र')}</div>
          </div>

          {/* @container: the pass is laid out by its own width (same on screen and in the PDF), not the viewport */}
          <div className="@container relative px-4 pb-6 pt-6 sm:px-6">
            {/* narrow pass: QR centred above the details; from 20rem: QR beside them */}
            <div className="flex flex-col items-center gap-4 text-center @xs:flex-row @xs:text-left">
              <div className="shrink-0 rounded-2xl bg-white p-2 shadow-inner ring-1 ring-gold-300">
                {qr ? <img src={qr} alt="QR" className="block size-44 @xs:size-36 @md:size-44" /> : <div className="size-44 animate-pulse rounded-xl bg-stone-200 @xs:size-36 @md:size-44" />}
              </div>
              <div className="w-full min-w-0 @xs:flex-1">
                <div className="text-[11px] font-bold uppercase tracking-wider text-stone-500">{t('Pass ID', 'पास आईडी')}</div>
                <div className="font-display text-2xl tracking-wider text-maroon-800 [overflow-wrap:anywhere] @md:text-3xl">{b.id}</div>
                <div className="mt-3 text-[11px] font-bold uppercase tracking-wider text-stone-500">{t('Yagyakarta', 'यज्ञकर्ता')}</div>
                <div className="font-bold leading-snug text-maroon-950 [overflow-wrap:anywhere]">{b.coordinator.name}</div>
                <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-maroon-800 px-3 py-1 text-xs font-bold text-gold-300"><Users size={13} className="shrink-0" /> {b.members.length} {t('members', 'सदस्य')}</div>
              </div>
            </div>

            {/* tear line; the notch cut-outs sit on it at the pass edges */}
            <div className="ticket-notch relative -mx-4 my-5 py-px sm:-mx-6"><div className="mx-4 border-t-2 border-dashed border-maroon-200 sm:mx-6" /></div>

            <div className="space-y-2.5">
              {b.slots.map((s) => {
                const [, label, cls] = status(s)
                const S = EVENT.sessions[s.session]
                return (
                  // Narrow pass: [date | details] with the status on its own row under the details.
                  // From 28rem: [date | details | status] in one row. Every box grows with its text.
                  <div key={s.date + s.session} className="grid grid-cols-[3.75rem_minmax(0,1fr)] items-center gap-x-3 gap-y-2 rounded-2xl bg-white p-3 ring-1 ring-maroon-100 @md:grid-cols-[3.75rem_minmax(0,1fr)_auto] @md:gap-x-4">
                    <div className="row-span-2 grid aspect-square w-15 place-items-center self-center rounded-xl bg-gradient-to-br from-saffron-400 to-maroon-700 py-1 text-center text-white @md:row-span-1">
                      <div>
                        <div className="text-[10px] font-bold uppercase leading-tight opacity-90">{fmtDate(s.date, lang, { month: 'short' })}</div>
                        <div className="font-display text-xl leading-none">{s.date.slice(8)}</div>
                        <div className="text-[10px] font-semibold leading-tight opacity-90">{fmtDate(s.date, lang, { weekday: 'short' })}</div>
                      </div>
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
                        <span className="inline-flex items-center gap-1.5 text-[15px] font-bold leading-snug text-maroon-900">{s.session === 'morning' ? <Sunrise size={16} className="shrink-0" /> : <Sunset size={16} className="shrink-0" />}{t(S.en, S.hi)}</span>
                        <span className="inline-flex items-center gap-1 text-[13px] font-medium leading-snug text-stone-600 tabular-nums"><Clock size={13} className="shrink-0" aria-hidden />{tm(S.start)} – {tm(S.end)}</span>
                      </div>
                      <KundTag k={s.kund} className="mt-1 block text-[13px] font-bold leading-snug text-maroon-800" />
                    </div>
                    <span className={`col-start-2 max-w-full justify-self-start rounded-full px-3 py-1 text-center text-[11px] font-bold leading-tight ${cls} @md:col-start-3 @md:max-w-[10rem] @md:justify-self-end`}>{label}</span>
                  </div>
                )
              })}
            </div>

            <div className="mt-5 rounded-2xl bg-white p-4 ring-1 ring-maroon-100">
              <div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-stone-500">{t('Family seated together', 'साथ बैठने वाले सदस्य')}</div>
              <ol className="grid gap-x-4 gap-y-1 @md:grid-cols-2">
                {b.members.map((m, i) => <li key={i} className="min-w-0 text-sm leading-snug text-maroon-950 [overflow-wrap:anywhere]">{i + 1}. {m.name}</li>)}
              </ol>
            </div>

            <div className="mt-4 flex gap-2 text-xs leading-relaxed text-stone-600"><Clock size={15} className="mt-0.5 shrink-0 text-saffron-600" /><span className="min-w-0">{t('QR works only during your session time (±15 min). Carry a photo ID.', 'QR केवल आपके सत्र के समय (±15 मिनट) मान्य है। पहचान पत्र साथ रखें।')}</span></div>
            <div className="mt-1.5 flex gap-2 text-xs leading-relaxed text-stone-600"><MapPin size={15} className="mt-0.5 shrink-0 text-saffron-600" /><span className="min-w-0">{t(EVENT.venueEn, EVENT.venueHi)}</span></div>
          </div>
        </div>
        </div>

      </div>
    </div>
  )
}
