import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { QrCode, Search, ChevronRight } from 'lucide-react'
import { useLang } from '../lib/lang.jsx'
import { Btn, Field, inputCls } from '../components/ui.jsx'
import { findByMobile, fmtDate } from '../lib/db.js'

export default function Find() {
  const { t, lang } = useLang()
  const [m, setM] = useState('')
  const [res, setRes] = useState(null)
  const go = (e) => { e.preventDefault(); if (m.length === 10) setRes(findByMobile(m)) }
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
          <Btn type="submit" className="w-full" disabled={m.length !== 10}><Search size={18} /> {t('Search', 'खोजें')}</Btn>
        </form>
        {res && (
          <div className="mt-6 space-y-3">
            {res.length === 0 && <p className="rounded-2xl bg-white p-5 text-center text-sm text-stone-600">{t('No booking found for this number.', 'इस नंबर पर कोई पंजीकरण नहीं मिला।')}</p>}
            {res.map((b, i) => (
              <motion.div key={b.id} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .06 }}>
                <Link to={`/ticket/${b.id}`} className="flex items-center gap-3 rounded-2xl border border-maroon-100 bg-white p-4 shadow-sm transition hover:border-saffron-400 hover:shadow-lg">
                  <div className="min-w-0 flex-1">
                    <div className="font-display text-xl text-maroon-800">{b.id}</div>
                    <div className="truncate text-sm font-semibold text-maroon-950">{b.coordinator.name} · {b.members.length} {t('members', 'सदस्य')}</div>
                    <div className="text-xs text-stone-500">{b.slots.map((s) => fmtDate(s.date, lang, { day: 'numeric', month: 'short' })).join(', ')}</div>
                  </div>
                  <ChevronRight className="text-saffron-600" />
                </Link>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
