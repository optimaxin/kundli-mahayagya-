import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { LayoutDashboard, List, ScanLine, Grid3x3, Settings, LogOut, Users, Armchair, DoorOpen, Percent, Download, Search, Check, Lock, Trash2, ChevronDown, Ban, UserCog, UserPlus, TrendingUp, Home, FileSpreadsheet, Mail, KeyRound } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { useLang } from '../lib/lang.jsx'
import { Btn, Mandala, Om } from '../components/ui.jsx'
import Scanner from '../components/Scanner.jsx'
import { Area, Columns, Donut, HBars, Heat, PAL, StackedBars } from '../components/charts.jsx'
import {
  EVENT, ZONES, addStaff, analytics, currentAuth, describeError, exportBookings, fmtDate, kundFamilies,
  kundMap, signIn, logout, markEntered, removeStaff, activateStaff, resetStaffPassword, generateAndDownloadReport,
  searchBookings, slotOf,
  slotStats, slotWindow, staffList, toggleBlock, updateStaff, usePoll, useSlots, zoneRange,
} from '../lib/db.js'

const nf = (n) => (n ?? 0).toLocaleString('en-IN')
const SESSION_IDS = Array.from({ length: EVENT.dates.length * 2 }, (_, i) => i + 1)

export default function Admin() {
  const { t } = useLang()
  const navigate = useNavigate()
  const [auth, setAuth] = useState(() => currentAuth('admin'))
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState('overview')

  useEffect(() => {
    const onExpired = (e) => { if (e.detail === 'admin') setAuth(null) }
    window.addEventListener('km-auth-expired', onExpired)
    return () => window.removeEventListener('km-auth-expired', onExpired)
  }, [])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setErr('')
    try {
      const r = await signIn(email, pw)
      setPw('')
      if (r.kind === 'admin') setAuth(r); else navigate('/staff') // gate (scanner) accounts go to the gate page
    } catch (x) { setErr(x.status === 401 ? t('Wrong email or password', 'गलत ईमेल या पासवर्ड') : describeError(x, t)) } finally { setBusy(false) }
  }
  const signOut = async () => { await logout('admin'); setAuth(null) }

  if (!auth) return (
    <div className="relative grid min-h-[80vh] place-items-center overflow-hidden bg-gradient-to-br from-maroon-950 to-maroon-800 px-4">
      <Mandala className="spin-slow absolute w-[800px] opacity-15" />
      <motion.form initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} onSubmit={submit} className="relative w-full max-w-sm rounded-[2rem] bg-white p-8 shadow-2xl">
        <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-maroon-800 text-gold-300"><Lock /></span>
        <h1 className="font-display mt-4 text-center text-2xl text-maroon-900">{t('Organiser console', 'आयोजक कंसोल')}</h1>
        <input type="email" autoFocus autoComplete="username" value={email} onChange={(e) => { setEmail(e.target.value); setErr('') }} placeholder={t('Email', 'ईमेल')} className="mt-6 min-h-12 w-full rounded-xl border border-slate-300 px-4 outline-none focus:border-saffron-500 focus:ring-4 focus:ring-saffron-100" />
        <input type="password" autoComplete="current-password" value={pw} onChange={(e) => { setPw(e.target.value); setErr('') }} placeholder={t('Password', 'पासवर्ड')} className={`mt-3 min-h-12 w-full rounded-xl border px-4 outline-none focus:ring-4 ${err ? 'border-red-400 focus:ring-red-100' : 'border-slate-300 focus:border-saffron-500 focus:ring-saffron-100'}`} />
        {err && <p className="mt-1 text-xs font-semibold text-red-600">{err}</p>}
        <Btn type="submit" variant="maroon" className="mt-4 w-full" disabled={busy || !email || !pw}>{busy ? t('Checking…', 'जाँच हो रही है…') : t('Enter', 'प्रवेश')}</Btn>
      </motion.form>
    </div>
  )

  const isAdmin = auth.role === 'ADMIN'
  const tabs = [
    ['overview', t('Dashboard', 'डैशबोर्ड'), LayoutDashboard], ['bookings', t('Bookings', 'पंजीकरण'), List],
    ['scan', t('Scanner', 'स्कैनर'), ScanLine], ['map', t('Kund map', 'कुंड मानचित्र'), Grid3x3],
    ...(isAdmin ? [['staff', t('Volunteers', 'स्वयंसेवक'), UserCog], ['settings', t('Reports', 'रिपोर्ट'), Settings]] : []),
  ]
  return (
    <div className="min-h-[calc(100vh-4rem)] bg-slate-100 text-slate-800 md:grid md:grid-cols-[236px_1fr]">
      <aside className="fixed inset-x-0 bottom-0 z-40 flex border-t border-slate-200 bg-white md:sticky md:top-16 md:block md:h-[calc(100vh-4rem)] md:overflow-visible md:border-0 md:bg-slate-950 md:p-4 md:text-slate-300">
        <div className="mb-5 hidden items-center gap-2.5 px-2 py-2 md:flex"><Om size={36} /><div className="leading-tight"><div className="text-sm font-bold text-white">{t('Mahayagya', 'महायज्ञ')}</div><div className="text-[11px] text-slate-400">{auth.user?.name || auth.role}</div></div></div>
        {tabs.map(([k, l, Icon]) => (
          <button key={k} onClick={() => setTab(k)} className={`relative flex min-w-0 flex-1 flex-col items-center gap-0.5 px-0.5 py-2.5 text-[10px] font-semibold md:mb-1 md:w-full md:flex-none md:flex-row md:gap-3 md:rounded-xl md:px-3 md:py-2.5 md:text-sm ${tab === k ? 'text-maroon-800 md:bg-white/10 md:text-white' : 'text-slate-500 md:text-slate-400 md:hover:bg-white/5'}`}>
            {tab === k && <span className="absolute left-0 hidden h-6 w-1 rounded-r bg-saffron-500 md:block" />}
            <Icon size={19} />{l}
          </button>
        ))}
        <div className="hidden md:mt-6 md:block md:border-t md:border-white/10 md:pt-4">
          <Link to="/" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold text-slate-400 hover:bg-white/5"><Home size={19} />{t('Public site', 'मुख्य साइट')}</Link>
          <button onClick={signOut} className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold text-slate-400 hover:bg-white/5"><LogOut size={19} />{t('Logout', 'लॉगआउट')}</button>
        </div>
      </aside>
      <main className="min-w-0 p-4 pb-24 md:p-8">
        <div className="mb-3 flex items-center justify-between md:hidden">
          <Link to="/" className="flex items-center gap-1.5 text-xs font-bold text-slate-500"><Home size={15} />{t('Public site', 'मुख्य साइट')}</Link>
          <button onClick={signOut} className="flex items-center gap-1.5 rounded-full border border-red-200 bg-white px-4 py-2 text-sm font-bold text-red-600 active:scale-95"><LogOut size={16} />{t('Logout', 'लॉगआउट')}</button>
        </div>
        {tab === 'overview' && <Overview canExport={isAdmin} />}
        {tab === 'bookings' && <Bookings />}
        {tab === 'scan' && <AdminScanner />}
        {tab === 'map' && <KundMap />}
        {tab === 'staff' && isAdmin && <Volunteers />}
        {tab === 'settings' && isAdmin && <Reports />}
      </main>
    </div>
  )
}

const Card = ({ title, sub, right, className = '', children }) => (
  <section className={`rounded-2xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}>
    {(title || right) && <div className="mb-4 flex items-start justify-between gap-3"><div><h2 className="text-[15px] font-bold text-slate-900">{title}</h2>{sub && <p className="text-xs text-slate-500">{sub}</p>}</div>{right}</div>}
    {children}
  </section>
)
const H = ({ children, sub, right }) => (<div className="mb-6 flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-2xl font-bold tracking-tight text-slate-900 md:text-[28px]">{children}</h1>{sub && <p className="mt-0.5 text-sm text-slate-500">{sub}</p>}</div>{right}</div>)
const Sel = (p) => <select {...p} className="min-h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm font-medium outline-none focus:border-saffron-500" />
const Legend = ({ items }) => <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs font-medium text-slate-600">{items.map(([c, l]) => <span key={l} className="flex items-center gap-1.5"><i className="size-2.5 rounded-full" style={{ background: c }} />{l}</span>)}</div>
const Loading = () => <div className="grid min-h-40 place-items-center text-sm text-slate-400">…</div>
const ErrorNote = ({ error }) => { const { t } = useLang(); return error ? <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-700">{describeError(error, t)}</div> : null }

function SessionPicker({ value, onChange }) {
  const { t, lang } = useLang()
  return <Sel value={value} onChange={(e) => onChange(Number(e.target.value))}>{SESSION_IDS.map((id) => { const s = slotOf(id); return <option key={id} value={id}>{fmtDate(s.date, lang)} · {t(EVENT.sessions[s.session].en, EVENT.sessions[s.session].hi)}</option> })}</Sel>
}
// The session that is on now (or next), for sensible defaults on event days.
function currentSessionId() {
  const now = Date.now()
  const id = SESSION_IDS.find((i) => { const s = slotOf(i); return slotWindow(s.date, s.session)[1] >= now })
  return id || 1
}

function Kpi({ icon: Icon, label, value, sub, color, bar }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between"><span className="text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</span><span className="grid size-9 place-items-center rounded-xl text-white" style={{ background: color }}><Icon size={18} /></span></div>
      <div className="mt-3 text-3xl font-bold tracking-tight text-slate-900 tabular-nums">{value}</div>
      {bar != null ? <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full" style={{ width: `${Math.min(100, bar)}%`, background: color }} /></div> : null}
      {sub && <div className="mt-1.5 text-xs text-slate-500">{sub}</div>}
      <span className="absolute inset-x-0 bottom-0 h-0.5" style={{ background: color }} />
    </div>
  )
}

function Overview({ canExport = false }) {
  const { t, lang } = useLang()
  const [a, , error] = usePoll(analytics, 10000)
  if (!a) return <><H>{t('Dashboard', 'डैशबोर्ड')}</H><ErrorNote error={error} /><Loading /></>
  const pct = a.seatsTotal ? (a.seatsUsed / a.seatsTotal) * 100 : 0
  const entPct = a.seatsUsed ? (a.entered / a.seatsUsed) * 100 : 0
  const days = a.days.map((d) => ({ label: fmtDate(d.date, lang, { day: 'numeric', month: 'short' }), m: d.morning.used, a: d.afternoon.used }))
  const gSum = a.gender.male + a.gender.female + a.gender.other || 1
  return (
    <>
      <H sub={`${t('14–21 December 2026 · Agra', '14–21 दिसंबर 2026 · आगरा')}`} right={<div className="flex flex-wrap items-start gap-3"><span className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-700"><span className="size-2 animate-pulse rounded-full bg-emerald-500" />{t('Live · updates every 10s', 'लाइव · हर 10 सेकंड')}</span>{canExport && <ExcelReportButton variant="maroon" />}</div>}>{t('Dashboard', 'डैशबोर्ड')}</H>
      <ErrorNote error={error} />
      {a.families === 0 && <div className="mb-5 rounded-2xl border border-dashed border-slate-300 bg-white p-4 text-center text-sm text-slate-500">{t('No bookings yet.', 'अभी कोई पंजीकरण नहीं।')}</div>}

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Kpi icon={Users} label={t('Families', 'परिवार')} value={nf(a.uniqueFamilies ?? a.families)} sub={`${nf(a.families)} ${t('bookings', 'पंजीकरण')} · ${nf(a.familySessions ?? 0)} ${t('session bookings', 'सत्र बुकिंग')}`} color={PAL.maroon} />
        <Kpi icon={Armchair} label={t('Seats booked', 'बुक आसन')} value={nf(a.seatsUsed)} sub={`${t('of', 'में से')} ${nf(a.seatsTotal)}`} color={PAL.saffron} bar={pct} />
        <Kpi icon={DoorOpen} label={t('Entered', 'प्रवेश')} value={nf(a.entered)} sub={`${entPct.toFixed(0)}% ${t('of booked seats', 'बुक आसनों का')}`} color={PAL.emerald} bar={entPct} />
        <Kpi icon={Percent} label={t('Capacity used', 'क्षमता उपयोग')} value={`${pct.toFixed(1)}%`} sub={`${nf(a.seatsTotal - a.seatsUsed)} ${t('seats free', 'आसन खाली')}`} color={PAL.gold} bar={pct} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title={t('Registrations, last 14 days', 'पंजीकरण, पिछले 14 दिन')} sub={t('Families registered per day', 'प्रतिदिन पंजीकृत परिवार')} right={<TrendingUp size={18} className="text-slate-400" />}><Area data={a.trend} /></Card>
        <Card title={t('Seat capacity', 'आसन क्षमता')} sub={t('All 16 sessions', 'सभी 16 सत्र')}>
          <Donut size={170} parts={[{ v: a.entered, c: PAL.emerald, l: t('Entered', 'प्रवेश') }, { v: Math.max(0, a.seatsUsed - a.entered), c: PAL.saffron, l: t('Booked, not yet entered', 'बुक') }, { v: a.seatsTotal - a.seatsUsed, c: '#e2e8f0', l: t('Free', 'खाली') }]} center={`${pct.toFixed(0)}%`} sub={t('booked', 'बुक')} />
          <div className="mt-4"><Legend items={[[PAL.emerald, t('Entered', 'प्रवेश')], [PAL.saffron, t('Booked', 'बुक')], ['#e2e8f0', t('Free', 'खाली')]]} /></div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title={t('Day-wise devotees', 'दिन-वार श्रद्धालु')} sub={t('Seats booked per day, by session', 'प्रतिदिन बुक आसन, सत्र अनुसार')} right={<Legend items={[[PAL.saffron, t('Morning 8–11', 'प्रातः 8–11')], [PAL.maroon, t('Afternoon 1–4', 'अपराह्न 1–4')]]} />}>
          <StackedBars data={days} keys={['m', 'a']} colors={[PAL.saffron, PAL.maroon]} />
        </Card>
        <Card title={t('Fill heatmap', 'भराव हीटमैप')} sub={t('% of seats booked', 'बुक आसन का %')}>
          <Heat rows={a.days.map((d) => d.date.slice(8) + ' Dec')} cols={[t('Morning', 'प्रातः'), t('Afternoon', 'अपराह्न')]} get={(r, c) => { const d = a.days.find((x) => x.date.slice(8) + ' Dec' === r); const s = c === t('Morning', 'प्रातः') ? d.morning : d.afternoon; return s.capacity ? Math.round((s.used / s.capacity) * 100) : 0 }} />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card title={t('Age groups', 'आयु समूह')} sub={t('Devotees', 'श्रद्धालु')}><Columns rows={Object.entries(a.ages)} color={PAL.maroon} /></Card>
        <Card title={t('Gender', 'लिंग')}>
          <Donut size={130} thick={18} parts={[{ v: a.gender.male, c: PAL.sky, l: t('Male', 'पुरुष') }, { v: a.gender.female, c: PAL.rose, l: t('Female', 'महिला') }, { v: a.gender.other, c: PAL.slate, l: t('Other', 'अन्य') }]} center={nf(a.people)} sub={t('people', 'लोग')} />
          <div className="mt-3 flex justify-center"><Legend items={[[PAL.sky, `${t('Male', 'पुरुष')} ${Math.round((a.gender.male / gSum) * 100)}%`], [PAL.rose, `${t('Female', 'महिला')} ${Math.round((a.gender.female / gSum) * 100)}%`]]} /></div>
        </Card>
        <Card title={t('Family size', 'परिवार का आकार')} sub={t('Families by members', 'सदस्यों के अनुसार परिवार')}><Columns rows={a.sizes.slice(1).map((v, i) => [String(i + 1), v])} color={PAL.gold} /></Card>
        <Card title={t('Relationships', 'संबंध')}><HBars rows={a.rel} color={PAL.sky} /></Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card title={t('Top cities', 'शीर्ष शहर')} sub={t('Devotees', 'श्रद्धालु')}><HBars rows={a.cities} color={PAL.saffron} /></Card>
        <Card title={t('Entry by volunteer', 'स्वयंसेवक अनुसार प्रवेश')} sub={t('Members marked entered', 'प्रवेश दर्ज सदस्य')}><HBars rows={a.staff} color={PAL.emerald} /></Card>
        <Card title={t('Check-ins by session', 'सत्र-वार प्रवेश')}>
          <div className="space-y-2">
            {a.days.flatMap((d) => ['morning', 'afternoon'].map((s) => ({ d, s, x: d[s] }))).filter(({ x }) => x.attended).slice(0, 6).map(({ d, s, x }) => (
              <div key={d.date + s} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm"><span className="font-semibold">{fmtDate(d.date, lang, { day: 'numeric', month: 'short' })} · {t(EVENT.sessions[s].en, EVENT.sessions[s].hi)}</span><span className="font-bold text-emerald-600 tabular-nums">{x.attended}/{x.used}</span></div>
            ))}
            {!a.entered && <p className="py-6 text-center text-sm text-slate-400">{t('No entries yet', 'अभी कोई प्रवेश नहीं')}</p>}
          </div>
        </Card>
      </div>

      <Card className="mt-4 overflow-x-auto" title={t('Session-wise detail', 'सत्र-वार विवरण')}>
        <table className="w-full min-w-[640px] text-sm">
          <thead><tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wider text-slate-500"><th className="pb-2.5">{t('Date', 'तिथि')}</th><th>{t('Session', 'सत्र')}</th><th className="text-right">{t('Booked', 'बुक')}</th><th className="text-right">{t('Entered', 'प्रवेश')}</th><th className="text-right">{t('Kunds full', 'पूर्ण कुंड')}</th><th className="text-right">{t('Free seats', 'खाली')}</th><th className="w-40 pl-4">{t('Fill', 'भराव')}</th></tr></thead>
          <tbody>
            {a.days.flatMap((d) => ['morning', 'afternoon'].map((s) => {
              const x = d[s], p = x.capacity ? Math.round((x.used / x.capacity) * 100) : 0
              return (
                <tr key={d.date + s} className="border-b border-slate-100 last:border-0 hover:bg-slate-50"><td className="py-2.5 font-semibold">{fmtDate(d.date, lang)}</td><td>{t(EVENT.sessions[s].en, EVENT.sessions[s].hi)}</td><td className="text-right tabular-nums">{nf(x.used)}</td><td className="text-right font-semibold tabular-nums text-emerald-600">{nf(x.attended)}</td><td className="text-right tabular-nums">{x.full}</td><td className="text-right tabular-nums text-slate-500">{nf(x.left)}</td>
                  <td className="pl-4"><div className="flex items-center gap-2"><div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full" style={{ width: `${p}%`, background: p > 85 ? PAL.rose : p > 60 ? PAL.saffron : PAL.emerald }} /></div><span className="w-9 text-right text-xs tabular-nums text-slate-500">{p}%</span></div></td></tr>
              )
            }))}
          </tbody>
        </table>
      </Card>
    </>
  )
}

function Bookings() {
  const { t, lang } = useLang()
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  const [date, setDate] = useState('')
  const [sess, setSess] = useState('')
  const [open, setOpen] = useState(null)
  const [pages, setPages] = useState(1)
  const [note, setNote] = useState('')
  useEffect(() => { const x = setTimeout(() => { setDq(q); setPages(1) }, 400); return () => clearTimeout(x) }, [q])
  useEffect(() => setPages(1), [date, sess])
  const [res, reload, error] = usePoll(() => searchBookings({ q: dq, date, session: sess, page: 1, pageSize: 100 * pages }), 0, [dq, date, sess, pages])
  const rows = res?.rows || []

  const csv = async () => {
    setNote(t('Preparing CSV…', 'CSV तैयार हो रहा है…'))
    try {
      const all = await exportBookings({ q: dq, date, session: sess }, (n, total) => setNote(`${nf(n)} / ${nf(total)}`))
      const esc = (v) => `"${String(v ?? '').replace(/"/g, '""').replace(/^([=+\-@])/, "'$1")}"`
      const lines = [['PassID', 'Date', 'Session', 'Kund', 'Status', 'Entered', 'EnteredBy', 'Member', 'Age', 'Gender', 'Relation', 'Coordinator', 'Mobile', 'City', 'State']]
      for (const b of all) for (const s of b.slots) for (const m of b.members)
        lines.push([b.id, s.date, s.session, s.kund, s.status, `${s.checkedIn}/${b.members.length}`, s.by, m.name, m.age, m.gender, m.relationship, b.coordinator.name, b.coordinator.mobile, b.coordinator.city, b.coordinator.state])
      const el = document.createElement('a')
      el.href = URL.createObjectURL(new Blob(['﻿' + lines.map((l) => l.map(esc).join(',')).join('\n')], { type: 'text/csv' }))
      el.download = 'kundiya-bookings.csv'; el.click()
      setNote('')
    } catch (x) { setNote(describeError(x, t)) }
  }
  const enter = async (b, s) => {
    const left = b.members.length - s.checkedIn
    if (!confirm(t(`Mark ${left} member(s) of ${b.id} as entered? This cannot be undone.`, `${b.id} के ${left} सदस्यों का प्रवेश दर्ज करें? इसे वापस नहीं लिया जा सकता।`))) return
    try { await markEntered(b.id, s.date, s.session); reload() } catch (x) { alert(describeError(x, t)) }
  }
  return (
    <>
      <H sub={res ? `${nf(res.total)} ${t('families match', 'परिवार मिले')}` : ''} right={<div className="flex items-center gap-2">{note && <span className="text-xs text-slate-500">{note}</span>}<Btn variant="ghost" onClick={csv} className="min-h-10 px-4 text-sm"><Download size={16} />{t('Export CSV', 'CSV निकालें')}</Btn></div>}>{t('Bookings', 'पंजीकरण')}</H>
      <div className="mb-4 flex flex-wrap gap-2">
        <div className="relative min-w-52 flex-1"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('Search name, mobile, pass ID', 'नाम, मोबाइल, पास आईडी खोजें')} className="min-h-10 w-full rounded-lg border border-slate-300 bg-white pl-9 pr-3 text-sm outline-none focus:border-saffron-500" /></div>
        <Sel value={date} onChange={(e) => setDate(e.target.value)}><option value="">{t('All dates', 'सभी तिथियाँ')}</option>{EVENT.dates.map((d) => <option key={d} value={d}>{fmtDate(d, lang)}</option>)}</Sel>
        <Sel value={sess} onChange={(e) => setSess(e.target.value)}><option value="">{t('Both sessions', 'दोनों सत्र')}</option>{Object.keys(EVENT.sessions).map((s) => <option key={s} value={s}>{t(EVENT.sessions[s].en, EVENT.sessions[s].hi)}</option>)}</Sel>
      </div>
      <ErrorNote error={error} />
      {!res && !error && <Loading />}
      <div className="space-y-2">
        {rows.map((b) => (
          <div key={b.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <button onClick={() => setOpen(open === b.id ? null : b.id)} className="flex w-full items-center gap-3 p-4 text-left hover:bg-slate-50">
              <span className="font-mono text-sm font-bold text-maroon-800">{b.id}</span>
              <span className="min-w-0 flex-1"><span className="block truncate font-semibold">{b.coordinator.name}{b.status === 'CANCELLED' && <span className="ml-2 rounded bg-red-100 px-1.5 text-[10px] font-bold text-red-700">{t('CANCELLED', 'रद्द')}</span>}</span><span className="block truncate text-xs text-slate-500">+91 {b.coordinator.mobile} · {b.coordinator.city}</span></span>
              <span className="rounded-full bg-maroon-50 px-2.5 py-1 text-xs font-bold text-maroon-800"><Users size={11} className="mr-1 inline" />{b.members.length}</span>
              <span className={`hidden rounded-full px-2.5 py-1 text-xs font-bold sm:block ${b.slots.length && b.slots.every((s) => s.attended) ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>{b.slots.filter((s) => s.attended).length}/{b.slots.length} ✔</span>
              <ChevronDown size={18} className={`text-slate-400 transition ${open === b.id ? 'rotate-180' : ''}`} />
            </button>
            {open === b.id && (
              <div className="grid gap-5 border-t border-slate-100 bg-slate-50/60 p-4 md:grid-cols-2">
                <div>
                  <div className="mb-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">{t('Members', 'सदस्य')}</div>
                  {b.members.map((m, i) => <div key={i} className="flex justify-between border-b border-slate-100 py-1.5 text-sm"><span>{m.name}</span><span className="text-slate-500">{m.age ?? '–'} · {m.relationship || '–'}</span></div>)}
                </div>
                <div>
                  <div className="mb-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">{t('Sessions (tap to mark entry)', 'सत्र (प्रवेश दर्ज करने हेतु दबाएँ)')}</div>
                  {b.slots.map((s) => {
                    const complete = s.checkedIn >= b.members.length
                    const canMark = s.status === 'CONFIRMED' && !complete && Date.now() >= slotWindow(s.date, s.session)[0]
                    return (
                      <button key={s.date + s.session} disabled={!canMark} onClick={() => enter(b, s)} className={`mb-1.5 flex w-full items-center justify-between rounded-lg border px-3 py-2 text-sm font-medium transition ${s.status === 'CANCELLED' ? 'border-red-200 bg-red-50 text-red-700' : s.attended ? 'border-emerald-300 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-white enabled:hover:bg-slate-50'}`}>
                        <span>{fmtDate(s.date, lang)} · {t(EVENT.sessions[s.session].en, EVENT.sessions[s.session].hi)} · {t('Kund', 'कुंड')} #{s.kund}</span>
                        {s.status === 'CANCELLED' ? <span className="text-xs">{t('Cancelled', 'रद्द')}</span> : s.attended ? <span className="flex items-center gap-1 text-xs"><Check size={14} />{s.checkedIn}/{b.members.length} · {new Date(s.attendedAt).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}{s.by ? ` · ${s.by}` : ''}</span> : <span className="text-xs text-slate-400">{t('Not entered', 'प्रवेश नहीं')}</span>}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        ))}
        {res && rows.length < res.total && <Btn variant="ghost" className="w-full text-sm" onClick={() => setPages((p) => p + 1)}>{t(`Show more (${nf(res.total - rows.length)} more)`, `और दिखाएँ (${nf(res.total - rows.length)} और)`)}</Btn>}
        {res && !rows.length && <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">{t('Nothing found', 'कुछ नहीं मिला')}</div>}
      </div>
    </>
  )
}

function AdminScanner() {
  const { t } = useLang()
  const [sid, setSid] = useState(currentSessionId)
  return (
    <>
      <H sub={t('Scans count for the session selected here', 'यहाँ चुने गए सत्र हेतु स्कैन')} right={<SessionPicker value={sid} onChange={setSid} />}>{t('Gate scanner', 'द्वार स्कैनर')}</H>
      <Scanner kind="admin" sessionId={sid} />
    </>
  )
}

function KundMap() {
  const { t, lang } = useLang()
  useSlots(15000)
  const [date, setDate] = useState(EVENT.dates[0])
  const [sess, setSess] = useState('morning')
  const [zone, setZone] = useState(0)
  const [sel, setSel] = useState(null)
  const [fams, setFams] = useState([])
  const [msg, setMsg] = useState('')
  const [map, reload, error] = usePoll(() => kundMap(date, sess), 8000, [date, sess])
  useEffect(() => { setFams([]); if (sel) kundFamilies(date, sess, sel).then(setFams).catch(() => {}) }, [sel, date, sess])
  const occ = map?.occ || {}, blocked = map?.blocked || {}, inactive = map?.inactive || {}
  const st = slotStats(date, sess)
  const [a, z] = zoneRange(zone)
  const cells = Array.from({ length: z - a + 1 }, (_, i) => a + i)
  const color = (k) => blocked[k] || inactive[k] ? 'bg-slate-800 text-white' : !occ[k] ? 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100' : occ[k] >= EVENT.seats ? 'bg-maroon-700 text-white' : 'bg-saffron-400 text-maroon-950'
  const block = async () => {
    setMsg('')
    try { await toggleBlock(date, sess, sel, !blocked[sel]); reload() } catch (x) { setMsg(describeError(x, t)) }
  }
  return (
    <>
      <H sub={t('Tap a kund for families; block empty kunds', 'कुंड दबाकर परिवार देखें; खाली कुंड बंद करें')} right={<div className="flex gap-2"><Sel value={date} onChange={(e) => { setDate(e.target.value); setSel(null) }}>{EVENT.dates.map((d) => <option key={d} value={d}>{fmtDate(d, lang)}</option>)}</Sel><Sel value={sess} onChange={(e) => { setSess(e.target.value); setSel(null) }}>{Object.keys(EVENT.sessions).map((s) => <option key={s} value={s}>{t(EVENT.sessions[s].en, EVENT.sessions[s].hi)}</option>)}</Sel></div>}>{t('Kund map', 'कुंड मानचित्र')}</H>
      <ErrorNote error={error} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {[[PAL.emerald, t('Empty', 'खाली'), st.empty], [PAL.saffron, t('Partly filled', 'आंशिक'), st.partial], [PAL.maroon, t('Full', 'पूर्ण'), st.full], ['#1e293b', t('Blocked', 'बंद'), st.blocked]].map(([c, l, n]) => <div key={l} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-3"><i className="size-3 rounded-full" style={{ background: c }} /><div><div className="text-lg font-bold tabular-nums leading-none">{nf(n)}</div><div className="text-xs text-slate-500">{l}</div></div></div>)}
      </div>
      <div className="mb-4 flex gap-1.5 overflow-x-auto pb-1">
        {ZONES.map(([en, hi], i) => <button key={en} onClick={() => { setZone(i); setSel(null) }} className={`shrink-0 rounded-full px-3.5 py-2 text-xs font-bold transition ${zone === i ? 'bg-maroon-800 text-white' : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50'}`}>{t(en, hi)}</button>)}
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        <Card className="!p-3">
          {!map ? <Loading /> : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(40px,1fr))] gap-1.5">
              {cells.map((k) => <button key={k} onClick={() => setSel(k)} title={`${occ[k] || 0}/${EVENT.seats}`} className={`aspect-square rounded-lg text-[10px] font-bold transition active:scale-90 ${color(k)} ${sel === k ? 'ring-2 ring-maroon-900 ring-offset-1' : ''}`}>{k}</button>)}
            </div>
          )}
        </Card>
        <Card className="self-start">
          {!sel ? <p className="text-sm text-slate-500">{t('Select a kund.', 'कोई कुंड चुनें।')}</p> : (
            <>
              <div className="text-xl font-bold text-slate-900">{t('Kund', 'कुंड')} #{sel}</div>
              <div className="text-xs text-slate-500">{t(ZONES[Math.min(10, zone)][0], ZONES[Math.min(10, zone)][1])} · {occ[sel] || 0}/{EVENT.seats} {t('seats', 'आसन')}{inactive[sel] ? ` · ${t('inactive (all sessions)', 'निष्क्रिय (सभी सत्र)')}` : ''}</div>
              <div className="mt-2 flex gap-1">{Array.from({ length: EVENT.seats }, (_, i) => <span key={i} className={`size-5 rounded-full ${i < (occ[sel] || 0) ? 'bg-maroon-700' : 'bg-slate-200'}`} />)}</div>
              <div className="mt-3 space-y-2">{fams.map((b) => <div key={b.id} className="rounded-lg bg-slate-50 p-2.5 text-sm"><b>{b.name}</b> · {b.size}<div className="text-xs text-slate-500">{b.id}</div></div>)}</div>
              {!occ[sel] && !inactive[sel] && <Btn variant="ghost" className="mt-4 w-full text-sm" onClick={block}><Ban size={16} />{blocked[sel] ? t('Unblock', 'खोलें') : t('Block this kund', 'कुंड बंद करें')}</Btn>}
              {msg && <p className="mt-2 text-xs font-semibold text-red-600">{msg}</p>}
            </>
          )}
        </Card>
      </div>
    </>
  )
}

function Volunteers() {
  const { t, lang } = useLang()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')
  const [role, setRole] = useState('SCANNER')
  const [sid, setSid] = useState(currentSessionId)
  const [msg, setMsg] = useState('')
  const [note, setNote] = useState('')
  const [adding, setAdding] = useState(false)
  const [resetFor, setResetFor] = useState(null)
  const [resetPw, setResetPw] = useState('')
  const [list, reload, error] = usePoll(staffList, 0)
  const [a] = usePoll(analytics, 30000)
  const done = Object.fromEntries(a?.staff || [])
  const isStrong = (p) => p.length >= 12 && /[a-z]/.test(p) && /[A-Z]/.test(p) && /\d/.test(p)
  const add = async (e) => {
    e.preventDefault(); setMsg(''); setNote(''); setAdding(true)
    try {
      await addStaff({ name: name.trim(), email: email.trim(), password: pw, sessionId: sid, role })
      setName(''); setEmail(''); setPw('')
      setNote(t('Account created. Share the email and password with the volunteer privately.', 'खाता बन गया। ईमेल व पासवर्ड स्वयंसेवक को निजी रूप से बताएँ।'))
      reload()
    } catch (x) { setMsg(describeError(x, t)) } finally { setAdding(false) }
  }
  const act = async (fn, ok) => { setMsg(''); setNote(''); try { await fn(); if (ok) setNote(ok); reload() } catch (x) { setMsg(describeError(x, t)) } }
  const doReset = (s) => act(async () => { await resetStaffPassword(s.id, resetPw); setResetFor(null); setResetPw('') },
    t(`New password set for ${s.name}. They have been logged out everywhere.`, `${s.name} का नया पासवर्ड सेट हो गया। उन्हें सभी जगह से लॉगआउट कर दिया गया है।`))
  const sessName = (id) => {
    if (!id) return t('No session', 'कोई सत्र नहीं')
    const s = slotOf(id)
    return `${fmtDate(s.date, lang, { day: 'numeric', month: 'short' })} · ${t(EVENT.sessions[s.session].en, EVENT.sessions[s.session].hi)} (${EVENT.sessions[s.session].start}–${EVENT.sessions[s.session].end})`
  }
  const roleLabel = (r) => (r === 'SCANNER' ? t('Gate scanner', 'द्वार स्कैनर') : t('Supervisor', 'पर्यवेक्षक'))
  const input = 'min-h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-saffron-500'
  return (
    <>
      <H sub={t('Gate scanners log in at /staff and can only scan for the session assigned here. Supervisors use this console without volunteer or audit access.', 'द्वार स्कैनर /staff पर लॉगिन करते हैं और केवल यहाँ आवंटित सत्र हेतु स्कैन कर सकते हैं। पर्यवेक्षक इस कंसोल का उपयोग करते हैं (स्वयंसेवक व ऑडिट को छोड़कर)।')}>{t('Volunteers', 'स्वयंसेवक')}</H>
      <ErrorNote error={error} />
      {msg && <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-700">{msg}</div>}
      {note && <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm font-semibold text-emerald-700">{note}</div>}
      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <Card title={t('Add volunteer', 'स्वयंसेवक जोड़ें')}>
          <form onSubmit={add} className="space-y-3">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('Name', 'नाम')} className={input} />
            <div className="relative"><Mail size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder={t('Login email', 'लॉगिन ईमेल')} className={`${input} pl-9`} /></div>
            <input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder={t('Initial password (12+ chars, Aa1)', 'प्रारंभिक पासवर्ड (12+ अक्षर, Aa1)')} className={input} />
            {pw && !isStrong(pw) && <p className="text-xs text-slate-500">{t('At least 12 characters with upper-case, lower-case and a digit.', 'कम से कम 12 अक्षर, जिसमें बड़ा अक्षर, छोटा अक्षर व अंक हो।')}</p>}
            <Sel value={role} onChange={(e) => setRole(e.target.value)}><option value="SCANNER">{roleLabel('SCANNER')}</option><option value="SUPERVISOR">{roleLabel('SUPERVISOR')}</option></Sel>
            {role === 'SCANNER' && <SessionPicker value={sid} onChange={setSid} />}
            <Btn type="submit" className="w-full" disabled={adding || !name.trim() || !email.trim() || !isStrong(pw)}><UserPlus size={18} />{adding ? t('Creating…', 'बन रहा है…') : t('Add', 'जोड़ें')}</Btn>
          </form>
        </Card>
        <Card title={t('Volunteer accounts', 'स्वयंसेवक खाते')} sub={list ? `${list.filter((s) => s.active).length} ${t('active', 'सक्रिय')} · ${list.length} ${t('total', 'कुल')}` : ''}>
          {!list && !error && <Loading />}
          <div className="divide-y divide-slate-100">
            {(list || []).map((s) => (
              <div key={s.id} className="py-3">
                <div className={`flex flex-wrap items-center gap-3 ${s.active ? '' : 'opacity-60'}`}>
                  <span className="grid size-10 place-items-center rounded-full bg-maroon-50 font-bold text-maroon-800">{s.name[0]}</span>
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold">{s.name} <span className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold text-slate-600">{roleLabel(s.role)}</span>{!s.active && <span className="ml-1 rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-bold text-red-600">{t('Deactivated', 'निष्क्रिय')}</span>}</div>
                    <div className="truncate text-xs text-slate-500">{s.email}</div>
                  </div>
                  {s.role === 'SCANNER' && (s.active
                    ? <Sel value={s.sessionId || ''} onChange={(e) => act(() => updateStaff(s.id, { assigned_session_id: Number(e.target.value) }))}>{!s.sessionId && <option value="">{sessName(null)}</option>}{SESSION_IDS.map((id) => <option key={id} value={id}>{sessName(id)}</option>)}</Sel>
                    : <span className="text-xs text-slate-500">{sessName(s.sessionId)}</span>)}
                  <div className="text-right"><div className="text-lg font-bold tabular-nums text-emerald-600">{done[s.name] || 0}</div><div className="text-[11px] text-slate-500">{t('entered', 'प्रवेश')}</div></div>
                </div>
                <div className="mt-2 flex flex-wrap gap-2 pl-[52px]">
                  {s.active && <button onClick={() => { setResetFor(resetFor === s.id ? null : s.id); setResetPw('') }} className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"><KeyRound size={14} />{t('Reset password', 'पासवर्ड बदलें')}</button>}
                  {s.active
                    ? <button onClick={() => confirm(t(`Deactivate ${s.name}? Their login stops working immediately.`, `${s.name} को निष्क्रिय करें? उनका लॉगिन तुरंत बंद हो जाएगा।`)) && act(() => removeStaff(s.id))} className="flex items-center gap-1 rounded-lg border border-red-200 px-2.5 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-50"><Ban size={14} />{t('Deactivate', 'निष्क्रिय करें')}</button>
                    : <button onClick={() => act(() => activateStaff(s.id))} className="flex items-center gap-1 rounded-lg border border-emerald-200 px-2.5 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-50"><Check size={14} />{t('Activate', 'सक्रिय करें')}</button>}
                </div>
                {resetFor === s.id && (
                  <form onSubmit={(e) => { e.preventDefault(); doReset(s) }} className="mt-2 flex flex-wrap gap-2 pl-[52px]">
                    <input type="password" autoComplete="new-password" autoFocus value={resetPw} onChange={(e) => setResetPw(e.target.value)} placeholder={t('New password (12+ chars, Aa1)', 'नया पासवर्ड (12+ अक्षर, Aa1)')} className={`${input} max-w-xs`} />
                    <Btn type="submit" className="min-h-11 px-4 text-sm" disabled={!isStrong(resetPw)}>{t('Set password', 'पासवर्ड सेट करें')}</Btn>
                  </form>
                )}
              </div>
            ))}
            {list && !list.length && <p className="py-4 text-sm text-slate-400">{t('No volunteers yet', 'अभी कोई स्वयंसेवक नहीं')}</p>}
          </div>
        </Card>
      </div>
    </>
  )
}

// "Excel रिपोर्ट डाउनलोड करें": generates the 7-sheet workbook on the server and downloads it.
// Loading starts at the click, the button stays disabled until the request ends (success or failure), and
// a second click while a report is running is ignored (the API layer also refuses duplicate requests).
function ExcelReportButton({ type = 'FINAL', date = null, label, variant, className = '' }) {
  const { t } = useLang()
  const [state, setState] = useState('idle')
  const [err, setErr] = useState('')
  const [secs, setSecs] = useState(0)
  const running = useRef(false)
  const busy = state === 'generating' || state === 'downloading'
  useEffect(() => {
    if (!busy) return undefined
    const t0 = Date.now()
    setSecs(0)
    const id = setInterval(() => setSecs(Math.floor((Date.now() - t0) / 1000)), 1000)
    return () => clearInterval(id)
  }, [busy])
  const run = async () => {
    if (running.current) return
    running.current = true
    setErr('')
    setState('generating')
    try {
      await generateAndDownloadReport(type, date, setState)
      setState('done')
    } catch (x) {
      setErr(describeError(x, t))
      setState('idle')
    } finally {
      running.current = false
    }
  }
  const timer = secs >= 3 ? ` ${secs}s` : ''
  return (
    <div className={`flex flex-col items-start gap-1 ${className}`}>
      <Btn variant={variant} disabled={busy} onClick={run} className="min-h-11 px-4 text-sm" aria-busy={busy}>
        <FileSpreadsheet size={18} />
        {state === 'generating' ? t('Preparing report…', 'रिपोर्ट तैयार हो रही है…') + timer : state === 'downloading' ? t('Downloading…', 'डाउनलोड हो रही है…') : label || t('Download Excel report', 'Excel रिपोर्ट डाउनलोड करें')}
      </Btn>
      {state === 'generating' && secs >= 15 && <span className="max-w-xs text-xs text-slate-500" role="status">{t('The server is slow right now. Please keep this page open.', 'सर्वर अभी धीमा है। कृपया यह पेज खुला रखें।')}</span>}
      {state === 'done' && <span className="text-xs font-semibold text-emerald-700">{t('Report downloaded', 'रिपोर्ट डाउनलोड हो गई')}</span>}
      {err && <span className="text-xs font-semibold text-red-600" role="alert">{err}</span>}
    </div>
  )
}

function Reports() {
  const { t, lang } = useLang()
  const [date, setDate] = useState(EVENT.dates[0])
  return (
    <>
      <H>{t('Reports', 'रिपोर्ट')}</H>
      <Card className="max-w-2xl space-y-5">
        <div>
          <h2 className="font-bold">{t('Excel reports', 'एक्सेल रिपोर्ट')}</h2>
          <p className="text-sm text-slate-500">{t('7 sheets: Dashboard, Family Bookings, Family Members, Session Attendance, Kund Allocation, Cancellations, No Shows (no-shows only for finished sessions).', '7 शीट: डैशबोर्ड, परिवार, सदस्य, सत्र उपस्थिति, कुंड आवंटन, रद्दीकरण व अनुपस्थित (केवल समाप्त सत्रों हेतु)।')}</p>
          <div className="mt-4"><ExcelReportButton /></div>
        </div>
        <div className="border-t border-slate-100 pt-4">
          <h2 className="font-bold">{t('Daily report', 'दैनिक रिपोर्ट')}</h2>
          <div className="mt-3 flex flex-wrap items-start gap-2">
            <Sel value={date} onChange={(e) => setDate(e.target.value)}>{EVENT.dates.map((d) => <option key={d} value={d}>{fmtDate(d, lang)}</option>)}</Sel>
            <ExcelReportButton key={date} type="DAILY" date={date} variant="ghost" label={t('Download daily report', 'दैनिक रिपोर्ट डाउनलोड करें')} />
          </div>
        </div>
        <p className="border-t border-slate-100 pt-4 text-xs text-slate-500">{t('All data is stored on the server. Exports are not backups; the database is backed up separately.', 'सारा डेटा सर्वर पर सुरक्षित है। निर्यात बैकअप नहीं हैं; डेटाबेस का बैकअप अलग से होता है।')}</p>
      </Card>
    </>
  )
}
