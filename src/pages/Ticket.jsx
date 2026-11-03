import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import QRCode from 'qrcode'
import { CheckCircle2, Download, Flame, Clock, MapPin, Search, Sunrise, Sunset, Users, Printer, Share2, Gift, Sparkles, X } from 'lucide-react'
import { useLang } from '../lib/lang.jsx'
import { Btn, Mandala, Om } from '../components/ui.jsx'
import { EVENT, getBooking, qrPayload, slotWindow, fmtDate, fmtTime } from '../lib/db.js'

export default function Ticket() {
  const { id } = useParams()
  const [sp] = useSearchParams()
  const { t, lang } = useLang()
  const b = getBooking(id)
  const [qr, setQr] = useState('')
  const [busy, setBusy] = useState(false)
  const ref = useRef(null)
  const [gift, setGift] = useState(false)
  useEffect(() => { if (!b || !sp.get('new')) return; const x = setTimeout(() => setGift(true), 2200); return () => clearTimeout(x) }, [id])

  useEffect(() => { if (b) QRCode.toDataURL(qrPayload(b), { width: 560, margin: 1, color: { dark: '#430d19', light: '#ffffff' }, errorCorrectionLevel: 'M' }).then(setQr) }, [id])

  if (!b) return (
    <div className="mx-auto max-w-md px-4 py-24 text-center">
      <Search className="mx-auto text-maroon-200" size={56} />
      <h1 className="font-display mt-4 text-3xl text-maroon-900">{t('Pass not found', 'प्रवेश पत्र नहीं मिला')}</h1>
      <p className="mt-2 text-stone-600">{t('It is saved on the device it was created on. Try searching with your mobile number.', 'यह उसी डिवाइस पर सहेजा है जहाँ बना था। मोबाइल नंबर से खोजें।')}</p>
      <Btn as={Link} to="/find" className="mt-6">{t('Find my pass', 'प्रवेश पत्र खोजें')}</Btn>
    </div>
  )

  const now = Date.now()
  const status = (s) => {
    const [a, z] = slotWindow(s.date, s.session)
    if (s.attended) return ['done', t('Entered ✔', 'प्रवेश हो चुका ✔'), 'bg-emerald-100 text-emerald-700']
    if (now > z) return ['past', t('Expired', 'समाप्त'), 'bg-stone-200 text-stone-600']
    if (now >= a) return ['live', t('Valid now', 'अभी मान्य'), 'bg-emerald-500 text-white animate-pulse']
    return ['soon', t('Opens at session time', 'सत्र समय पर मान्य'), 'bg-saffron-100 text-saffron-600']
  }

  const pdf = async () => {
    setBusy(true)
    try {
      const [{ toPng }, { jsPDF }] = await Promise.all([import('html-to-image'), import('jspdf')])
      const url = await toPng(ref.current, { pixelRatio: 2.5, backgroundColor: '#fff9ee', cacheBust: true })
      const el = ref.current
      const w = 190, h = (el.offsetHeight / el.offsetWidth) * w
      const doc = new jsPDF({ unit: 'mm', format: [210, Math.max(297, h + 20)] })
      doc.addImage(url, 'PNG', 10, 10, w, h)
      doc.save(`Kundiya-Mahayagya-${b.id}.pdf`)
    } finally { setBusy(false) }
  }
  const share = () => navigator.share?.({ title: EVENT.nameEn, text: `Pass ${b.id}`, url: location.href }).catch(() => {})

  return (
    <div className="paper pb-28 md:pb-16">
      <div className="mx-auto max-w-xl px-4 pt-8">
        {sp.get('new') && (
          <motion.div initial={{ scale: .8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className="mb-6 text-center">
            <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: 'spring', delay: .15 }} className="mx-auto grid size-16 place-items-center rounded-full bg-emerald-500 text-white shadow-xl"><CheckCircle2 size={36} /></motion.div>
            <h1 className="font-display mt-3 text-3xl text-maroon-900">{t('Registration confirmed!', 'पंजीकरण सफल!')}</h1>
            <p className="mt-1 text-sm text-stone-600">{t('Download your pass now, or find it later using your mobile number.', 'अभी डाउनलोड करें, या बाद में मोबाइल नंबर से खोजें।')}</p>
          </motion.div>
        )}

        <div className="sticky top-[4.5rem] z-30 mb-5 grid grid-cols-2 gap-2 rounded-2xl border border-gold-300/70 bg-white/90 p-2 shadow-lg backdrop-blur sm:grid-cols-[1.6fr_1fr_1fr] sm:gap-2.5 sm:p-2.5">
          <Btn onClick={pdf} disabled={busy} className="col-span-2 min-h-14 text-base sm:col-span-1"><Download size={20} /> {busy ? t('Preparing…', 'तैयार हो रहा है…') : t('Download pass (PDF)', 'प्रवेश पत्र डाउनलोड (PDF)')}</Btn>
          <Btn variant="ghost" onClick={() => window.print()} className="min-h-14"><Printer size={18} /> {t('Print', 'प्रिंट')}</Btn>
          <Btn variant="ghost" onClick={share} className="min-h-14"><Share2 size={18} /> {t('Share', 'साझा करें')}</Btn>
        </div>

        {/* the pass — this exact node becomes the PDF */}
        <div ref={ref} className="overflow-hidden rounded-[2rem] bg-cream shadow-[0_30px_60px_-25px_rgba(67,13,25,.55)] ring-1 ring-gold-400/60">
          <div className="relative overflow-hidden bg-gradient-to-br from-maroon-800 via-maroon-900 to-maroon-950 px-6 pt-7 pb-6 text-center text-white">
            <Mandala className="absolute -right-16 -top-16 w-64 opacity-25" rings={3} />
            <Om size={52} className="mx-auto" />
            <div className="font-display mt-1 text-3xl gold-text">{t(EVENT.nameEn, EVENT.nameHi)}</div>
            <div className="mt-1 text-xs font-bold uppercase tracking-[.25em] text-maroon-200">{t('Devotional E-Pass', 'प्रवेश पत्र')}</div>
          </div>

          <div className="ticket-notch relative px-6 pb-6 pt-6">
            <div className="flex items-center gap-4">
              <div className="rounded-2xl bg-white p-2 shadow-inner ring-1 ring-gold-300">
                {qr ? <img src={qr} alt="QR" className="size-36 sm:size-44" /> : <div className="size-36 animate-pulse rounded-xl bg-stone-200 sm:size-44" />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-[11px] font-bold uppercase tracking-wider text-stone-500">{t('Pass ID', 'पास आईडी')}</div>
                <div className="font-display text-2xl tracking-wider text-maroon-800 sm:text-3xl">{b.id}</div>
                <div className="mt-3 text-[11px] font-bold uppercase tracking-wider text-stone-500">{t('Yagyakarta', 'यज्ञकर्ता')}</div>
                <div className="truncate font-bold text-maroon-950">{b.coordinator.name}</div>
                <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-maroon-800 px-3 py-1 text-xs font-bold text-gold-300"><Users size={13} /> {b.members.length} {t('members', 'सदस्य')}</div>
              </div>
            </div>

            <div className="my-5 border-t-2 border-dashed border-maroon-200" />

            <div className="space-y-2.5">
              {b.slots.map((s) => {
                const [, label, cls] = status(s)
                return (
                  <div key={s.date + s.session} className="flex items-center gap-3 rounded-2xl bg-white p-3 ring-1 ring-maroon-100">
                    <div className="grid size-14 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-saffron-400 to-maroon-700 text-white">
                      <div className="text-center leading-none"><div className="font-display text-xl">{s.date.slice(8)}</div><div className="text-[9px] font-bold uppercase">{fmtDate(s.date, lang, { month: 'short' })}</div></div>
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 text-sm font-bold text-maroon-900">{s.session === 'morning' ? <Sunrise size={15} /> : <Sunset size={15} />}{t(EVENT.sessions[s.session].en, EVENT.sessions[s.session].hi)}<span className="font-medium text-stone-500">· {fmtTime(EVENT.sessions[s.session].start)}–{fmtTime(EVENT.sessions[s.session].end)}</span></div>
                      <div className="mt-0.5 text-xs text-stone-600">{t('Kund', 'कुंड')} <b className="text-maroon-800">#{s.kund}</b></div>
                    </div>
                    <span className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] font-bold ${cls}`}>{label}</span>
                  </div>
                )
              })}
            </div>

            <div className="mt-5 rounded-2xl bg-white p-4 ring-1 ring-maroon-100">
              <div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-stone-500">{t('Family seated together', 'साथ बैठने वाले सदस्य')}</div>
              <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
                {b.members.map((m, i) => <div key={i} className="truncate text-sm text-maroon-950">{i + 1}. {m.name}</div>)}
              </div>
            </div>

            <div className="mt-4 flex gap-2 text-xs text-stone-600"><Clock size={15} className="shrink-0 text-saffron-600" />{t('QR works only during your session time (±15 min). Carry a photo ID.', 'QR केवल आपके सत्र के समय (±15 मिनट) मान्य है। पहचान पत्र साथ रखें।')}</div>
            <div className="mt-1.5 flex gap-2 text-xs text-stone-600"><MapPin size={15} className="shrink-0 text-saffron-600" />{t(EVENT.venueEn, EVENT.venueHi)}</div>
          </div>
        </div>

        <GiftBanner className="mt-6" />
      </div>
      <AnimatePresence>{gift && <GiftPopup onClose={() => setGift(false)} />}</AnimatePresence>
    </div>
  )
}

const KUNDALI_URL = 'https://tredevaastro.com/'

function GiftBanner({ className = '' }) {
  const { t } = useLang()
  return (
    <a href={KUNDALI_URL} target="_blank" rel="noopener noreferrer" className={`group flex items-center gap-4 overflow-hidden rounded-2xl bg-gradient-to-r from-maroon-800 to-maroon-950 p-4 text-white shadow-lg ${className}`}>
      <span className="grid size-14 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-gold-300 to-saffron-500 text-maroon-950"><Gift size={28} /></span>
      <span className="min-w-0 flex-1"><span className="block font-bold text-gold-300">{t('A gift for you: Free Kundali', 'आपके लिए उपहार: निःशुल्क कुंडली')}</span><span className="block text-sm text-maroon-200">{t('Generate your Kundali free at Tredeva Astro', 'त्रिदेव एस्ट्रो पर अपनी कुंडली निःशुल्क बनाएँ')}</span></span>
      <span className="rounded-full bg-saffron-500 px-4 py-2 text-sm font-bold transition group-hover:brightness-110">{t('Open', 'खोलें')}</span>
    </a>
  )
}

function GiftPopup({ onClose }) {
  const { t } = useLang()
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 grid place-items-center bg-maroon-950/70 p-4 backdrop-blur-sm" onClick={onClose}>
      <motion.div initial={{ scale: .8, y: 30, opacity: 0 }} animate={{ scale: 1, y: 0, opacity: 1 }} exit={{ scale: .9, opacity: 0 }} transition={{ type: 'spring', damping: 18 }} onClick={(e) => e.stopPropagation()} className="relative w-full max-w-sm overflow-hidden rounded-[2rem] bg-cream text-center shadow-2xl ring-1 ring-gold-400">
        <div className="relative bg-gradient-to-br from-maroon-800 to-maroon-950 px-6 pb-8 pt-9">
          <Mandala className="spin-slow absolute -right-16 -top-16 w-60 opacity-25" rings={3} />
          <button onClick={onClose} aria-label="close" className="absolute right-3 top-3 grid size-9 place-items-center rounded-full bg-white/10 text-white hover:bg-white/20"><X size={18} /></button>
          <motion.div animate={{ rotate: [0, -8, 8, -4, 0] }} transition={{ repeat: Infinity, duration: 2.4 }} className="relative mx-auto grid size-20 place-items-center rounded-3xl bg-gradient-to-br from-gold-300 to-saffron-500 text-maroon-950 shadow-xl"><Gift size={42} /></motion.div>
          <div className="font-display relative mt-4 text-2xl gold-text">{t('A gift for you!', 'आपके लिए उपहार!')}</div>
        </div>
        <div className="p-6">
          <p className="flex items-center justify-center gap-1.5 text-lg font-bold text-maroon-900"><Sparkles size={18} className="text-saffron-500" />{t('Generate your Kundali FREE', 'अपनी कुंडली बनाएँ निःशुल्क')}</p>
          <p className="mt-1.5 text-sm text-stone-600">{t('Thank you for registering. Enjoy a complimentary Kundali from Tredeva Astro, our blessing to your family.', 'पंजीकरण के लिए धन्यवाद। त्रिदेव एस्ट्रो की ओर से निःशुल्क कुंडली, आपके परिवार को हमारा आशीर्वाद।')}</p>
          <Btn as="a" href={KUNDALI_URL} target="_blank" rel="noopener noreferrer" onClick={onClose} className="mt-5 w-full min-h-14 text-base"><Gift size={19} />{t('Get my free Kundali', 'मेरी निःशुल्क कुंडली पाएँ')}</Btn>
          <button onClick={onClose} className="mt-3 text-sm font-semibold text-stone-500 hover:text-stone-700">{t('Maybe later', 'बाद में')}</button>
        </div>
      </motion.div>
    </motion.div>
  )
}
