import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { QrCode, Search, ChevronRight, ShieldCheck } from 'lucide-react'
import { useLang } from '../lib/lang.jsx'
import { Btn, Field, inputCls } from '../components/ui.jsx'
import { describeError, findByMobile, fmtDate, passStatus } from '../lib/db.js'

// Passes (QR tokens) are never listed by the server for a mobile number -- that would let anyone who knows a
// number download someone else's pass. This page shows passes saved on THIS device, and can confirm a
// booking's status from the server with booking number + mobile. Lost passes are re-issued at the help desk.
export default function Find() {
  const { t, lang } = useLang()
  const [m, setM] = useState('')
  const [res, setRes] = useState(null)
  const [bn, setBn] = useState('')
  const [st, setSt] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const go = async (e) => { e.preventDefault(); if (m.length === 10) { setRes(await findByMobile(m)); setSt(null); setErr('') } }
  const check = async (e) => {
    e.preventDefault()
    setBusy(true); setErr(''); setSt(null)
    try { setSt(await passStatus(bn.trim().toUpperCase(), m)) } catch (x) { setErr(x.status === 404 ? t('No booking matches these details.', 'इन विवरणों से कोई पंजीकरण नहीं मिला।') : describeError(x, t)) } finally { setBusy(false) }
  }
  return (
    <div className="paper min-h-[70vh] pb-28">
      <div className="mx-auto max-w-md px-4 pt-12">
        <div className="text-center">
          <span className="mx-auto grid size-16 place-items-center rounded-2xl bg-gradient-to-br from-saffron-400 to-maroon-700 text-white shadow-xl"><QrCode size={30} /></span>
          <h1 className="font-display mt-4 text-3xl text-maroon-900">{t('Find your pass', 'अपना प्रवेश पत्र खोजें')}</h1>
          <p className="mt-1 text-sm text-stone-600">{t('Enter the mobile number used at registration.', 'पंजीकरण में दिया गया मोबाइल नंबर लिखें।')}</p>
        </div>
        <form onSubmit={go} className="mt-8 space-y-4 rounded-[2rem] border border-gold-300/70 bg-white p-6 shadow-xl">
          <Field label={t('Mobile number', 'मोबाइल नंबर')}>
            <div className="flex gap-2"><span className="grid min-h-12 place-items-center rounded-xl bg-maroon-50 px-3.5 font-bold text-maroon-800">+91</span>
              <input className={inputCls()} inputMode="numeric" value={m} onChange={(e) => setM(e.target.value.replace(/\D/g, '').slice(0, 10))} placeholder="98XXXXXXXX" /></div>
          </Field>
          <Btn type="submit" className="w-full" disabled={m.length !== 10}><Search size={18} /> {t('Search this device', 'इस डिवाइस पर खोजें')}</Btn>
        </form>
        {res && (
          <div className="mt-6 space-y-3">
            {res.map((b, i) => (
              <motion.div key={b.token} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .06 }}>
                <Link to={`/ticket/${encodeURIComponent(b.token)}`} className="flex items-center gap-3 rounded-2xl border border-maroon-100 bg-white p-4 shadow-sm transition hover:border-saffron-400 hover:shadow-lg">
                  <div className="min-w-0 flex-1">
                    <div className="font-display text-xl text-maroon-800">{b.id}</div>
                    <div className="truncate text-sm font-semibold text-maroon-950">{b.coordinator.name} · {b.members.length} {t('members', 'सदस्य')}</div>
                    <div className="text-xs text-stone-500">{b.slots.map((s) => fmtDate(s.date, lang, { day: 'numeric', month: 'short' })).join(', ')}</div>
                  </div>
                  <ChevronRight className="text-saffron-600" />
                </Link>
              </motion.div>
            ))}
            {res.length === 0 && (
              <div className="rounded-2xl bg-white p-5 text-sm text-stone-600 shadow-sm">
                <p>{t('No pass for this number is saved on this device. Use the PDF you downloaded, or check your booking below.', 'इस नंबर का कोई प्रवेश पत्र इस डिवाइस पर सहेजा नहीं है। डाउनलोड किया PDF उपयोग करें, या नीचे अपना पंजीकरण जाँचें।')}</p>
                <form onSubmit={check} className="mt-4 space-y-3">
                  <Field label={t('Booking number (on your pass)', 'बुकिंग नंबर (प्रवेश पत्र पर)')}>
                    <input className={inputCls()} value={bn} onChange={(e) => setBn(e.target.value.toUpperCase().slice(0, 13))} placeholder="MY26-XXXXXXXX" />
                  </Field>
                  <Btn type="submit" variant="ghost" className="w-full" disabled={busy || bn.trim().length < 13}><ShieldCheck size={18} /> {t('Check booking status', 'पंजीकरण स्थिति जाँचें')}</Btn>
                </form>
                {err && <p className="mt-3 text-sm font-semibold text-red-600">{err}</p>}
                {st && (
                  <div className="mt-4 rounded-xl bg-emerald-50 p-4 text-emerald-800">
                    <div className="font-bold">{st.booking_number} · {st.booking_status === 'CONFIRMED' ? t('Confirmed', 'पुष्ट') : t('Cancelled', 'रद्द')}</div>
                    <div className="text-sm">{st.member_count} {t('members', 'सदस्य')} · {st.confirmed_sessions} {t('session(s)', 'सत्र')}</div>
                    <p className="mt-2 text-xs">{t('Lost your pass? Bring this booking number and a photo ID to the help desk to get a new QR.', 'प्रवेश पत्र खो गया? नया QR पाने हेतु यह बुकिंग नंबर व फोटो पहचान पत्र लेकर हेल्प डेस्क पर आएँ।')}</p>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
