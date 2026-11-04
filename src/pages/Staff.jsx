import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { KeyRound, LogOut, Mail, ScanLine } from 'lucide-react'
import { useLang } from '../lib/lang.jsx'
import { Btn, Mandala } from '../components/ui.jsx'
import Scanner from '../components/Scanner.jsx'
import { EVENT, currentAuth, describeError, fmtDate, logout, scannerMe, signIn } from '../lib/db.js'

// Volunteer gate page: log in with the gate (scanner) account given by the organisers. The account is
// assigned to one session by the admin; the server decides which session is being scanned.
export default function Staff() {
  const { t, lang } = useLang()
  const navigate = useNavigate()
  const [me, setMe] = useState(() => currentAuth('staff'))
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [info, setInfo] = useState(null)

  useEffect(() => {
    const onExpired = (e) => { if (e.detail === 'staff') setMe(null) }
    window.addEventListener('km-auth-expired', onExpired)
    return () => window.removeEventListener('km-auth-expired', onExpired)
  }, [])
  useEffect(() => { if (me) scannerMe('staff').then(setInfo).catch(() => {}) }, [me])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setErr('')
    try {
      const r = await signIn(email, pw)
      setPw('')
      if (r.kind === 'staff') setMe(r); else navigate('/admin') // admin / supervisor accounts go to the admin console
    } catch (x) { setErr(x.status === 401 ? t('Wrong email or password', 'गलत ईमेल या पासवर्ड') : describeError(x, t)) } finally { setBusy(false) }
  }

  if (!me) return (
    <div className="relative grid min-h-[80vh] place-items-center overflow-hidden bg-gradient-to-br from-maroon-950 to-maroon-800 px-4">
      <Mandala className="spin-slow absolute w-[800px] opacity-15" />
      <motion.form initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} onSubmit={submit} className="relative w-full max-w-sm rounded-[2rem] bg-white p-8 shadow-2xl">
        <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-saffron-500 text-white"><ScanLine /></span>
        <h1 className="font-display mt-4 text-center text-2xl text-maroon-900">{t('Staff & admin login', 'स्टाफ व एडमिन लॉगिन')}</h1>
        <p className="mt-1 text-center text-sm text-slate-500">{t('Use the account given by the organisers', 'आयोजकों द्वारा दिया गया खाता उपयोग करें')}</p>
        <div className="relative mt-5">
          <Mail size={18} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input type="email" autoFocus autoComplete="username" value={email} onChange={(e) => { setEmail(e.target.value); setErr('') }} placeholder={t('Email', 'ईमेल')} className="min-h-12 w-full rounded-xl border border-slate-300 pl-10 pr-4 outline-none focus:border-saffron-500 focus:ring-4 focus:ring-saffron-100" />
        </div>
        <div className="relative mt-3">
          <KeyRound size={18} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input type="password" autoComplete="current-password" value={pw} onChange={(e) => { setPw(e.target.value); setErr('') }} placeholder={t('Password', 'पासवर्ड')} className={`min-h-12 w-full rounded-xl border pl-10 pr-4 outline-none focus:ring-4 ${err ? 'border-red-400 focus:ring-red-100' : 'border-slate-300 focus:border-saffron-500 focus:ring-saffron-100'}`} />
        </div>
        {err && <p className="mt-1 text-xs font-semibold text-red-600">{err}</p>}
        <Btn type="submit" className="mt-4 w-full" disabled={busy || !email || !pw}>{t('Start duty', 'ड्यूटी शुरू करें')}</Btn>
      </motion.form>
    </div>
  )

  const s = info?.session
  const name = me.user?.name || info?.full_name || ''
  return (
    <div className="min-h-[calc(100vh-4rem)] bg-slate-100 pb-10">
      <div className="mx-auto max-w-5xl px-3 pt-3 sm:px-4 sm:pt-5">
        <div className="mb-4 flex items-center justify-between gap-3 rounded-2xl bg-gradient-to-r from-maroon-900 to-maroon-700 p-3 sm:p-4 text-white shadow-lg">
          <div className="flex min-w-0 items-center gap-3"><span className="grid size-11 shrink-0 place-items-center rounded-full bg-white/15 font-bold text-gold-300">{name[0] || '?'}</span>
            <div className="min-w-0"><div className="text-xs text-maroon-200">{t('Gate volunteer', 'द्वार स्वयंसेवक')}</div><div className="truncate font-bold">{name}</div>
              <div className="truncate text-xs text-gold-300">{s ? `${fmtDate(s.event_date, lang)} · ${t(EVENT.sessions[s.slot.toLowerCase()].en, EVENT.sessions[s.slot.toLowerCase()].hi)}` : t('No session assigned', 'कोई सत्र आवंटित नहीं')}</div></div></div>
          <button onClick={async () => { await logout('staff'); setMe(null); setInfo(null) }} className="flex shrink-0 items-center gap-1.5 rounded-full bg-white px-4 py-2.5 text-sm font-bold text-maroon-800 shadow active:scale-95"><LogOut size={16} />{t('Logout', 'लॉगआउट')}</button>
        </div>
        <Scanner kind="staff" />
      </div>
    </div>
  )
}
