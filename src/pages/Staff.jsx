import { useState } from 'react'
import { motion } from 'framer-motion'
import { KeyRound, LogOut, ScanLine } from 'lucide-react'
import { useLang } from '../lib/lang.jsx'
import { Btn, Mandala } from '../components/ui.jsx'
import Scanner from '../components/Scanner.jsx'
import { staffLogin } from '../lib/db.js'

// Volunteer gate page: login with a PIN given by the admin, scan and mark entry. Nothing else is visible.
export default function Staff() {
  const { t } = useLang()
  const [me, setMe] = useState(() => { try { return JSON.parse(sessionStorage.getItem('km_staff')) } catch { return null } })
  const [pin, setPin] = useState('')
  const [bad, setBad] = useState(false)

  if (!me) return (
    <div className="relative grid min-h-[80vh] place-items-center overflow-hidden bg-gradient-to-br from-maroon-950 to-maroon-800 px-4">
      <Mandala className="spin-slow absolute w-[800px] opacity-15" />
      <motion.form initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} onSubmit={(e) => { e.preventDefault(); const s = staffLogin(pin); if (s) { sessionStorage.setItem('km_staff', JSON.stringify(s)); setMe(s) } else setBad(true) }} className="relative w-full max-w-sm rounded-[2rem] bg-white p-8 shadow-2xl">
        <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-saffron-500 text-white"><ScanLine /></span>
        <h1 className="font-display mt-4 text-center text-2xl text-maroon-900">{t('Volunteer login', 'स्वयंसेवक लॉगिन')}</h1>
        <p className="mt-1 text-center text-sm text-slate-500">{t('Enter the PIN given by the organisers', 'आयोजकों द्वारा दिया गया पिन लिखें')}</p>
        <div className="relative mt-5">
          <KeyRound size={18} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input type="password" inputMode="numeric" autoFocus value={pin} onChange={(e) => { setPin(e.target.value); setBad(false) }} placeholder="PIN" className={`min-h-12 w-full rounded-xl border pl-10 pr-4 text-center text-lg tracking-[.4em] outline-none focus:ring-4 ${bad ? 'border-red-400 focus:ring-red-100' : 'border-slate-300 focus:border-saffron-500 focus:ring-saffron-100'}`} />
        </div>
        {bad && <p className="mt-1 text-xs font-semibold text-red-600">{t('Wrong PIN', 'गलत पिन')}</p>}
        <Btn type="submit" className="mt-4 w-full">{t('Start duty', 'ड्यूटी शुरू करें')}</Btn>
        <p className="mt-4 text-center text-[11px] text-slate-400">Demo PIN: 1234</p>
      </motion.form>
    </div>
  )

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-slate-100 pb-10">
      <div className="mx-auto max-w-5xl px-4 pt-5">
        <div className="mb-5 flex items-center justify-between gap-3 rounded-2xl bg-gradient-to-r from-maroon-900 to-maroon-700 p-4 text-white shadow-lg">
          <div className="flex items-center gap-3"><span className="grid size-11 place-items-center rounded-full bg-white/15 font-bold text-gold-300">{me.name[0]}</span>
            <div><div className="text-xs text-maroon-200">{t('Gate volunteer', 'द्वार स्वयंसेवक')}</div><div className="font-bold">{me.name}</div></div></div>
          <button onClick={() => { sessionStorage.removeItem('km_staff'); setMe(null); setPin('') }} className="flex items-center gap-1.5 rounded-full bg-white/10 px-3.5 py-2 text-xs font-bold hover:bg-white/20"><LogOut size={15} />{t('Logout', 'लॉगआउट')}</button>
        </div>
        <Scanner by={me.name} />
      </div>
    </div>
  )
}
