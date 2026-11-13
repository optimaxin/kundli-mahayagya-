import { useEffect, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useLang } from '../lib/lang.jsx'
import { kundParts } from '../lib/db.js'
import { Flame, Ticket, UserPlus, ShieldCheck } from 'lucide-react'

// "Zone Brahma · Sector 2 · Kund #45" that wraps only between its parts, never inside one
// (so "Kund" and "#45" stay together). The separator stays at the end of the earlier line.
export function KundTag({ k, className = '' }) {
  const { t } = useLang()
  const parts = kundParts(k, t)
  return (
    <span className={className}>
      {parts.map((p, i) => <span key={i}><span className="whitespace-nowrap">{p}{i < parts.length - 1 ? ' ·' : ''}</span>{i < parts.length - 1 ? ' ' : ''}</span>)}
    </span>
  )
}

// Procedural mandala: concentric petal rings, pure SVG, no assets
export function Mandala({ className = '', stroke = '#e5b94a', rings = 4 }) {
  const petals = (n, r, len, w) =>
    Array.from({ length: n }, (_, i) => (
      <ellipse key={i} cx="200" cy={200 - r} rx={w} ry={len} transform={`rotate(${(360 / n) * i} 200 200)`} />
    ))
  return (
    <svg viewBox="0 0 400 400" className={className} fill="none" stroke={stroke} strokeWidth="1.1" aria-hidden>
      <circle cx="200" cy="200" r="196" strokeDasharray="2 6" />
      <circle cx="200" cy="200" r="186" />
      {petals(24, 150, 36, 10)}
      {rings > 1 && petals(16, 112, 32, 14)}
      {rings > 2 && petals(12, 74, 26, 16)}
      {rings > 3 && petals(8, 40, 20, 12)}
      <circle cx="200" cy="200" r="150" strokeDasharray="1 5" />
      <circle cx="200" cy="200" r="22" fill={stroke} fillOpacity=".25" />
    </svg>
  )
}

export function Divider({ className = '' }) {
  return (
    <div className={`flex items-center justify-center gap-3 text-gold-500 ${className}`} aria-hidden>
      <span className="h-px w-16 bg-gradient-to-r from-transparent to-gold-400" />
      <Flame size={16} className="flicker" />
      <span className="h-px w-16 bg-gradient-to-l from-transparent to-gold-400" />
    </div>
  )
}

// Brand mark: Om on a maroon disc with a gold ring
export function Om({ size = 40, className = '' }) {
  return (
    <span className={`grid shrink-0 place-items-center rounded-full bg-gradient-to-br from-maroon-700 to-maroon-950 text-gold-300 shadow-md ring-2 ring-gold-400/70 ${className}`} style={{ width: size, height: size, aspectRatio: '1' }}>
      <span style={{ fontSize: size * 0.62, lineHeight: 1, fontFamily: 'Hind, "Noto Sans Devanagari", sans-serif', fontWeight: 600, marginTop: -size * 0.04 }}>ॐ</span>
    </span>
  )
}

export function Navbar() {
  const { lang, setLang, t } = useLang()
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const f = () => setScrolled(window.scrollY > 8)
    f(); window.addEventListener('scroll', f, { passive: true })
    return () => window.removeEventListener('scroll', f)
  }, [])
  const links = [['/', t('Home', 'मुख्य'), true], ['/register', t('Register', 'पंजीकरण')], ['/find', t('My pass', 'प्रवेश पत्र')]]
  return (
    <header className={`sticky top-0 z-40 transition-all ${scrolled ? 'glass border-b border-gold-300/60 shadow-[0_8px_30px_-12px_rgba(67,13,25,.25)]' : 'bg-cream/90 backdrop-blur border-b border-transparent'}`}>
      <div className="mx-auto flex min-h-16 max-w-6xl items-center justify-between gap-2 px-3 py-1.5 sm:px-4">
        <Link to="/" className="flex min-w-0 items-center gap-2.5">
          <Om size={42} />
          <span className="min-w-0 leading-tight">
            <span className="font-display line-clamp-2 block text-[15px] leading-tight text-maroon-900 sm:text-lg">{t('2151 Kundiya Mahayagya', '2151 कुंडीय महायज्ञ')}</span>
            <span className="block truncate text-[10px] font-bold uppercase tracking-wider text-saffron-600 sm:text-[11px]">{t('Agra · 14–21 Dec 2026', 'आगरा · 14–21 दिसंबर 2026')}</span>
          </span>
        </Link>

        <nav className="hidden items-center gap-1 rounded-full border border-maroon-100 bg-white/80 p-1 md:flex">
          {links.map(([to, label, end]) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `relative rounded-full px-4 py-2 text-sm font-semibold transition ${isActive ? 'text-gold-300' : 'text-maroon-800 hover:bg-maroon-50'}`}>
              {({ isActive }) => (<>{isActive && <motion.span layoutId="nav-pill" className="absolute inset-0 rounded-full bg-gradient-to-b from-maroon-700 to-maroon-900 shadow" transition={{ type: 'spring', duration: .4 }} />}<span className="relative">{label}</span></>)}
            </NavLink>
          ))}
        </nav>

        <div className="flex shrink-0 items-center gap-2">
          <div className="flex rounded-full border-2 border-maroon-800 bg-white p-0.5 text-sm font-bold shadow-sm" role="group" aria-label="Language">
            {[['hi', 'हिन्दी'], ['en', 'English']].map(([k, l]) => (
              <button key={k} onClick={() => setLang(k)} aria-pressed={lang === k} className={`min-h-10 rounded-full px-2.5 py-1.5 transition min-[380px]:px-3 sm:px-4 ${lang === k ? 'bg-maroon-800 text-gold-300 shadow' : 'text-maroon-800 hover:bg-maroon-50'}`}>{l}</button>
            ))}
          </div>
          <Link to="/register" className="hidden rounded-full bg-gradient-to-b from-saffron-500 to-saffron-600 px-5 py-2.5 text-sm font-bold text-white shadow-[0_6px_16px_-6px_rgba(217,95,12,.7)] transition hover:brightness-110 active:scale-95 sm:inline-flex">{t('Register now', 'पंजीकरण करें')}</Link>
        </div>
      </div>
    </header>
  )
}

export function MobileDock() {
  const { t } = useLang()
  const item = ({ isActive }) =>
    `flex-1 flex flex-col items-center gap-0.5 py-2 text-[11px] font-bold ${isActive ? 'text-maroon-800' : 'text-stone-500'}`
  return (
    <nav className="md:hidden fixed bottom-0 inset-x-0 z-30 glass border-t border-gold-300/60 flex pb-[env(safe-area-inset-bottom)]">
      <NavLink to="/" end className={item}><span className="grid size-5 place-items-center text-[19px] leading-none" style={{ fontFamily: 'Hind, sans-serif', fontWeight: 600 }}>ॐ</span>{t('Home', 'मुख्य')}</NavLink>
      <NavLink to="/register" className={item}><UserPlus size={20} />{t('Register', 'पंजीकरण')}</NavLink>
      <NavLink to="/find" className={item}><Ticket size={20} />{t('My pass', 'प्रवेश पत्र')}</NavLink>
    </nav>
  )
}

export function Footer() {
  const { t } = useLang()
  return (
    <footer className="mt-16 bg-maroon-950 text-maroon-200 pb-24 md:pb-8">
      <div className="mx-auto max-w-6xl px-4 py-10 grid gap-6 md:grid-cols-3 text-sm">
        <div>
          <div className="font-display text-xl gold-text">{t('2151 Kundiya Mahayagya', '2151 कुंडीय महायज्ञ')}</div>
          <p className="mt-2 opacity-80">{t('JCB Tiraha, Shastripuram, Agra, Uttar Pradesh', 'जेसीबी तिराहा, शास्त्रीपुरम, आगरा, उत्तर प्रदेश')}</p>
        </div>
        <p className="opacity-80">{t('Registration is free. Your details are used only for seating and entry and are visible only to the organising team.', 'पंजीकरण निःशुल्क है। आपकी जानकारी केवल आसन-व्यवस्था व प्रवेश हेतु उपयोग होगी और केवल आयोजन समिति देख सकेगी।')}</p>
        <div className="md:text-right">
          <Link to="/admin" className="inline-flex items-center gap-1.5 opacity-70 hover:opacity-100"><ShieldCheck size={15} /> {t('Organiser login', 'आयोजक लॉगिन')}</Link>
        </div>
      </div>
    </footer>
  )
}

export function Btn({ as: As = 'button', variant = 'primary', className = '', ...p }) {
  const v = {
    primary: 'bg-gradient-to-b from-saffron-500 to-saffron-600 text-white shadow-[0_8px_20px_-6px_rgba(217,95,12,.6)] hover:brightness-110',
    maroon: 'bg-gradient-to-b from-maroon-700 to-maroon-900 text-gold-300 shadow-[0_8px_20px_-6px_rgba(67,13,25,.6)] hover:brightness-110',
    ghost: 'bg-white text-maroon-800 border border-maroon-200 hover:bg-maroon-50',
  }[variant]
  // In Tailwind the stylesheet order, not the class order, decides between two classes for the same
  // property (e.g. "px-6 px-4" renders px-6). So a default is only added when the caller did not set it.
  const has = (re) => re.test(className)
  const pad = has(/(^|\s)!?px-/) ? '' : 'px-6'
  const minH = has(/(^|\s)!?min-h-/) ? '' : 'min-h-12'
  const size = has(/(^|\s)!?text-(xs|sm|base|lg|[0-9]*xl|\[\d)/) ? '' : 'text-[15px]'
  return (
    <As
      {...p}
      className={`inline-flex items-center justify-center gap-2 rounded-2xl font-bold transition active:scale-[.97] disabled:opacity-50 disabled:pointer-events-none ${pad} ${minH} ${size} ${v} ${className}`}
    />
  )
}

export function Field({ label, hint, error, children, className = '' }) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1.5 block text-[13px] font-bold text-maroon-900">{label}</span>
      {children}
      {error ? <span className="mt-1 block text-xs font-semibold text-red-600">{error}</span> : hint ? <span className="mt-1 block text-xs text-stone-500">{hint}</span> : null}
    </label>
  )
}
export const inputCls = (err) =>
  `w-full min-h-12 rounded-xl border bg-white px-3.5 text-[15px] outline-none transition placeholder:text-stone-400 focus:ring-4 ${
    err ? 'border-red-400 focus:ring-red-100' : 'border-stone-300 focus:border-saffron-500 focus:ring-saffron-100'
  }`
