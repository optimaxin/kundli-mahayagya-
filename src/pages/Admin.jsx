import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { LayoutDashboard, List, ScanLine, Grid3x3, Settings, LogOut, Users, Armchair, DoorOpen, Percent, Download, Search, Check, Flame, Lock, Database, Trash2, ChevronDown, Ban, UserCog, UserPlus, TrendingUp, Home } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useLang } from '../lib/lang.jsx'
import { Btn, Mandala, Om } from '../components/ui.jsx'
import Scanner from '../components/Scanner.jsx'
import { Area, Columns, Donut, HBars, Heat, PAL, StackedBars } from '../components/charts.jsx'
import { EVENT, ZONES, addStaff, allBookings, analytics, fmtDate, kundFamilies, kundMap, removeStaff, reload, resetAll, seedDemo, slotStats, staffList, toggleAttended, toggleBlock, zoneRange } from '../lib/db.js'

// DEMO login only. Real build: Cloudflare Access / server session.
const DEMO_PASS = 'admin123'
const nf = (n) => n.toLocaleString('en-IN')

function useTick(ms = 4000) {
  const [n, setN] = useState(0)
  useEffect(() => { const i = setInterval(() => { reload(); setN((x) => x + 1) }, ms); return () => clearInterval(i) }, [ms])
  return [n, () => setN((x) => x + 1)]
}

export default function Admin() {
  const { t } = useLang()
  const [authed, setAuthed] = useState(() => sessionStorage.getItem('km_admin') === '1')
  const [pw, setPw] = useState('')
  const [bad, setBad] = useState(false)
  const [tab, setTab] = useState('overview')

  if (!authed) return (
    <div className="relative grid min-h-[80vh] place-items-center overflow-hidden bg-gradient-to-br from-maroon-950 to-maroon-800 px-4">
      <Mandala className="spin-slow absolute w-[800px] opacity-15" />
      <motion.form initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} onSubmit={(e) => { e.preventDefault(); if (pw === DEMO_PASS) { sessionStorage.setItem('km_admin', '1'); setAuthed(true) } else setBad(true) }} className="relative w-full max-w-sm rounded-[2rem] bg-white p-8 shadow-2xl">
        <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-maroon-800 text-gold-300"><Lock /></span>
        <h1 className="font-display mt-4 text-center text-2xl text-maroon-900">{t('Organiser console', 'आयोजक कंसोल')}</h1>
        <input type="password" autoFocus value={pw} onChange={(e) => { setPw(e.target.value); setBad(false) }} placeholder={t('Password', 'पासवर्ड')} className={`mt-6 min-h-12 w-full rounded-xl border px-4 outline-none focus:ring-4 ${bad ? 'border-red-400 focus:ring-red-100' : 'border-slate-300 focus:border-saffron-500 focus:ring-saffron-100'}`} />
        {bad && <p className="mt-1 text-xs font-semibold text-red-600">{t('Wrong password', 'गलत पासवर्ड')}</p>}
        <Btn type="submit" variant="maroon" className="mt-4 w-full">{t('Enter', 'प्रवेश')}</Btn>
        <p className="mt-4 text-center text-[11px] text-slate-400">Demo password: admin123 · {t('Volunteers use', 'स्वयंसेवक यहाँ जाएँ')} <Link to="/staff" className="font-bold text-saffron-600">/staff</Link></p>
      </motion.form>
    </div>
  )

  const tabs = [
    ['overview', t('Dashboard', 'डैशबोर्ड'), LayoutDashboard], ['bookings', t('Bookings', 'पंजीकरण'), List],
    ['scan', t('Scanner', 'स्कैनर'), ScanLine], ['map', t('Kund map', 'कुंड मानचित्र'), Grid3x3],
    ['staff', t('Volunteers', 'स्वयंसेवक'), UserCog], ['settings', t('Settings', 'सेटिंग'), Settings],
  ]
  return (
    <div className="min-h-[calc(100vh-4rem)] bg-slate-100 text-slate-800 md:grid md:grid-cols-[236px_1fr]">
      <aside className="fixed inset-x-0 bottom-0 z-40 flex border-t border-slate-200 bg-white md:sticky md:top-16 md:block md:h-[calc(100vh-4rem)] md:overflow-visible md:border-0 md:bg-slate-950 md:p-4 md:text-slate-300">
        <div className="mb-5 hidden items-center gap-2.5 px-2 py-2 md:flex"><Om size={36} /><div className="leading-tight"><div className="text-sm font-bold text-white">{t('Mahayagya', 'महायज्ञ')}</div><div className="text-[11px] text-slate-400">{t('Admin console', 'एडमिन कंसोल')}</div></div></div>
        {tabs.map(([k, l, Icon]) => (
          <button key={k} onClick={() => setTab(k)} className={`relative flex min-w-0 flex-1 flex-col items-center gap-0.5 px-0.5 py-2.5 text-[10px] font-semibold md:mb-1 md:w-full md:flex-none md:flex-row md:gap-3 md:rounded-xl md:px-3 md:py-2.5 md:text-sm ${tab === k ? 'text-maroon-800 md:bg-white/10 md:text-white' : 'text-slate-500 md:text-slate-400 md:hover:bg-white/5'}`}>
            {tab === k && <span className="absolute left-0 hidden h-6 w-1 rounded-r bg-saffron-500 md:block" />}
            <Icon size={19} />{l}
          </button>
        ))}
        <div className="hidden md:mt-6 md:block md:border-t md:border-white/10 md:pt-4">
          <Link to="/" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold text-slate-400 hover:bg-white/5"><Home size={19} />{t('Public site', 'मुख्य साइट')}</Link>
          <button onClick={() => { sessionStorage.removeItem('km_admin'); setAuthed(false) }} className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold text-slate-400 hover:bg-white/5"><LogOut size={19} />{t('Logout', 'लॉगआउट')}</button>
        </div>
      </aside>
      <main className="min-w-0 p-4 pb-24 md:p-8">
        {tab === 'overview' && <Overview />}
        {tab === 'bookings' && <Bookings />}
        {tab === 'scan' && (<><H>{t('Gate scanner', 'द्वार स्कैनर')}</H><Scanner by="Admin" /></>)}
        {tab === 'map' && <KundMap />}
        {tab === 'staff' && <Volunteers />}
        {tab === 'settings' && <Sett />}
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

function Overview() {
  const { t, lang } = useLang()
  useTick()
  const a = analytics()
  const pct = a.seatsTotal ? (a.seatsUsed / a.seatsTotal) * 100 : 0
  const entPct = a.seatsUsed ? (a.entered / a.seatsUsed) * 100 : 0
  const days = a.days.map((d) => ({ label: fmtDate(d.date, lang, { day: 'numeric', month: 'short' }), m: d.morning.used, a: d.afternoon.used }))
  const gSum = a.gender.male + a.gender.female + a.gender.other || 1
  return (
    <>
      <H sub={`${t('14–21 December 2026 · Agra', '14–21 दिसंबर 2026 · आगरा')}`} right={<span className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-700"><span className="size-2 animate-pulse rounded-full bg-emerald-500" />{t('Live · updates every 4s', 'लाइव · हर 4 सेकंड')}</span>}>{t('Dashboard', 'डैशबोर्ड')}</H>
      {a.families === 0 && <div className="mb-5 rounded-2xl border border-dashed border-slate-300 bg-white p-4 text-center text-sm text-slate-500">{t('No bookings yet. Load demo data from Settings to preview every chart.', 'अभी कोई पंजीकरण नहीं। सभी चार्ट देखने हेतु सेटिंग से डेमो डेटा लोड करें।')}</div>}

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Kpi icon={Users} label={t('Families', 'परिवार')} value={nf(a.families)} sub={`${t('Avg size', 'औसत सदस्य')} ${a.avgFamily.toFixed(1)}`} color={PAL.maroon} />
        <Kpi icon={Armchair} label={t('Seats booked', 'बुक आसन')} value={nf(a.seatsUsed)} sub={`${t('of', 'में से')} ${nf(a.seatsTotal)}`} color={PAL.saffron} bar={pct} />
        <Kpi icon={DoorOpen} label={t('Entered', 'प्रवेश')} value={nf(a.entered)} sub={`${entPct.toFixed(0)}% ${t('of booked seats', 'बुक आसनों का')}`} color={PAL.emerald} bar={entPct} />
        <Kpi icon={Percent} label={t('Capacity used', 'क्षमता उपयोग')} value={`${pct.toFixed(1)}%`} sub={`${nf(a.seatsTotal - a.seatsUsed)} ${t('seats free', 'आसन खाली')}`} color={PAL.gold} bar={pct} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title={t('Registrations, last 14 days', 'पंजीकरण, पिछले 14 दिन')} sub={t('Families registered per day', 'प्रतिदिन पंजीकृत परिवार')} right={<TrendingUp size={18} className="text-slate-400" />}><Area data={a.trend} /></Card>
        <Card title={t('Seat capacity', 'आसन क्षमता')} sub={t('All 16 sessions', 'सभी 16 सत्र')}>
          <Donut size={170} parts={[{ v: a.entered, c: PAL.emerald, l: t('Entered', 'प्रवेश') }, { v: a.seatsUsed - a.entered, c: PAL.saffron, l: t('Booked, not yet entered', 'बुक') }, { v: a.seatsTotal - a.seatsUsed, c: '#e2e8f0', l: t('Free', 'खाली') }]} center={`${pct.toFixed(0)}%`} sub={t('booked', 'बुक')} />
          <div className="mt-4"><Legend items={[[PAL.emerald, t('Entered', 'प्रवेश')], [PAL.saffron, t('Booked', 'बुक')], ['#e2e8f0', t('Free', 'खाली')]]} /></div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title={t('Day-wise devotees', 'दिन-वार श्रद्धालु')} sub={t('Seats booked per day, by session', 'प्रतिदिन बुक आसन, सत्र अनुसार')} right={<Legend items={[[PAL.saffron, t('Morning 8–11', 'प्रातः 8–11')], [PAL.maroon, t('Afternoon 1–4', 'अपराह्न 1–4')]]} />}>
          <StackedBars data={days} keys={['m', 'a']} colors={[PAL.saffron, PAL.maroon]} />
        </Card>
        <Card title={t('Fill heatmap', 'भराव हीटमैप')} sub={t('% of seats booked', 'बुक आसन का %')}>
          <Heat rows={a.days.map((d) => d.date.slice(8) + ' Dec')} cols={[t('Morning', 'प्रातः'), t('Afternoon', 'अपराह्न')]} get={(r, c) => { const d = a.days.find((x) => x.date.slice(8) + ' Dec' === r); const s = c === t('Morning', 'प्रातः') ? d.morning : d.afternoon; return Math.round((s.used / s.capacity) * 100) }} />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card title={t('Age groups', 'आयु समूह')} sub={t('Devotees', 'श्रद्धालु')}><Columns rows={Object.entries(a.ages)} color={PAL.maroon} /></Card>
        <Card title={t('Gender', 'लिंग')}>
          <Donut size={130} thick={18} parts={[{ v: a.gender.male, c: PAL.sky, l: t('Male', 'पुरुष') }, { v: a.gender.female, c: PAL.rose, l: t('Female', 'महिला') }, { v: a.gender.other, c: PAL.slate, l: t('Other', 'अन्य') }]} center={nf(gSum - (a.people ? 0 : 1))} sub={t('people', 'लोग')} />
          <div className="mt-3 flex justify-center"><Legend items={[[PAL.sky, `${t('Male', 'पुरुष')} ${Math.round((a.gender.male / gSum) * 100)}%`], [PAL.rose, `${t('Female', 'महिला')} ${Math.round((a.gender.female / gSum) * 100)}%`]]} /></div>
        </Card>
        <Card title={t('Family size', 'परिवार का आकार')} sub={t('Families by members', 'सदस्यों के अनुसार परिवार')}><Columns rows={a.sizes.slice(1).map((v, i) => [String(i + 1), v])} color={PAL.gold} /></Card>
        <Card title={t('Relationships', 'संबंध')}><HBars rows={a.rel} color={PAL.sky} /></Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card title={t('Top cities', 'शीर्ष शहर')} sub={t('Devotees', 'श्रद्धालु')}><HBars rows={a.cities} color={PAL.saffron} /></Card>
        <Card title={t('Entry by volunteer', 'स्वयंसेवक अनुसार प्रवेश')} sub={t('Devotees marked entered', 'प्रवेश दर्ज श्रद्धालु')}><HBars rows={a.staff} color={PAL.emerald} /></Card>
        <Card title={t('Today’s check-ins', 'आज के प्रवेश')}>
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
              const x = d[s], p = Math.round((x.used / x.capacity) * 100)
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
  const [tick, bump] = useTick()
  const [q, setQ] = useState('')
  const [date, setDate] = useState('')
  const [sess, setSess] = useState('')
  const [open, setOpen] = useState(null)
  const all = allBookings()
  const rows = useMemo(() => all.filter((b) => {
    if (date && !b.slots.some((s) => s.date === date && (!sess || s.session === sess))) return false
    if (!date && sess && !b.slots.some((s) => s.session === sess)) return false
    const n = q.trim().toLowerCase()
    return !n || b.id.toLowerCase().includes(n) || b.coordinator.name.toLowerCase().includes(n) || b.coordinator.mobile.includes(n) || b.members.some((m) => m.name.toLowerCase().includes(n))
  }), [all, q, date, sess, tick])

  const csv = () => {
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
    const lines = [['PassID', 'Date', 'Session', 'Kund', 'Entered', 'EnteredBy', 'Member', 'Age', 'Gender', 'Relation', 'Coordinator', 'Mobile', 'City', 'State']]
    for (const b of rows) for (const s of b.slots) for (const m of b.members)
      lines.push([b.id, s.date, s.session, s.kund, s.attended ? 'Yes' : 'No', s.by || '', m.name, m.age, m.gender, m.relationship, b.coordinator.name, b.coordinator.mobile, b.coordinator.city, b.coordinator.state])
    const el = document.createElement('a')
    el.href = URL.createObjectURL(new Blob(['﻿' + lines.map((l) => l.map(esc).join(',')).join('\n')], { type: 'text/csv' }))
    el.download = 'kundiya-bookings.csv'; el.click()
  }
  return (
    <>
      <H sub={`${nf(rows.length)} ${t('families match', 'परिवार मिले')}`} right={<Btn variant="ghost" onClick={csv} className="min-h-10 px-4 text-sm"><Download size={16} />{t('Export CSV', 'CSV निकालें')}</Btn>}>{t('Bookings', 'पंजीकरण')}</H>
      <div className="mb-4 flex flex-wrap gap-2">
        <div className="relative min-w-52 flex-1"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('Search name, mobile, pass ID', 'नाम, मोबाइल, पास आईडी खोजें')} className="min-h-10 w-full rounded-lg border border-slate-300 bg-white pl-9 pr-3 text-sm outline-none focus:border-saffron-500" /></div>
        <Sel value={date} onChange={(e) => setDate(e.target.value)}><option value="">{t('All dates', 'सभी तिथियाँ')}</option>{EVENT.dates.map((d) => <option key={d} value={d}>{fmtDate(d, lang)}</option>)}</Sel>
        <Sel value={sess} onChange={(e) => setSess(e.target.value)}><option value="">{t('Both sessions', 'दोनों सत्र')}</option>{Object.keys(EVENT.sessions).map((s) => <option key={s} value={s}>{t(EVENT.sessions[s].en, EVENT.sessions[s].hi)}</option>)}</Sel>
      </div>
      <div className="space-y-2">
        {rows.slice(0, 100).map((b) => (
          <div key={b.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <button onClick={() => setOpen(open === b.id ? null : b.id)} className="flex w-full items-center gap-3 p-4 text-left hover:bg-slate-50">
              <span className="font-mono text-sm font-bold text-maroon-800">{b.id}</span>
              <span className="min-w-0 flex-1"><span className="block truncate font-semibold">{b.coordinator.name}</span><span className="block truncate text-xs text-slate-500">+91 {b.coordinator.mobile} · {b.coordinator.city}</span></span>
              <span className="rounded-full bg-maroon-50 px-2.5 py-1 text-xs font-bold text-maroon-800"><Users size={11} className="mr-1 inline" />{b.members.length}</span>
              <span className={`hidden rounded-full px-2.5 py-1 text-xs font-bold sm:block ${b.slots.every((s) => s.attended) ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>{b.slots.filter((s) => s.attended).length}/{b.slots.length} ✔</span>
              <ChevronDown size={18} className={`text-slate-400 transition ${open === b.id ? 'rotate-180' : ''}`} />
            </button>
            {open === b.id && (
              <div className="grid gap-5 border-t border-slate-100 bg-slate-50/60 p-4 md:grid-cols-2">
                <div>
                  <div className="mb-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">{t('Members', 'सदस्य')}</div>
                  {b.members.map((m, i) => <div key={i} className="flex justify-between border-b border-slate-100 py-1.5 text-sm"><span>{m.name}</span><span className="text-slate-500">{m.age} · {m.relationship}</span></div>)}
                </div>
                <div>
                  <div className="mb-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">{t('Sessions (tap to toggle entry)', 'सत्र (प्रवेश बदलने हेतु दबाएँ)')}</div>
                  {b.slots.map((s) => (
                    <button key={s.date + s.session} onClick={() => { toggleAttended(b.id, s.date, s.session); bump() }} className={`mb-1.5 flex w-full items-center justify-between rounded-lg border px-3 py-2 text-sm font-medium transition ${s.attended ? 'border-emerald-300 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-white hover:bg-slate-50'}`}>
                      <span>{fmtDate(s.date, lang)} · {t(EVENT.sessions[s.session].en, EVENT.sessions[s.session].hi)} · {t('Kund', 'कुंड')} #{s.kund}</span>
                      {s.attended ? <span className="flex items-center gap-1 text-xs"><Check size={14} />{new Date(s.attendedAt).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}{s.by ? ` · ${s.by}` : ''}</span> : <span className="text-xs text-slate-400">{t('Not entered', 'प्रवेश नहीं')}</span>}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
        {rows.length > 100 && <p className="py-3 text-center text-xs text-slate-500">{t('Showing first 100. Narrow the filters or export CSV.', 'पहले 100 दिख रहे हैं। फ़िल्टर बदलें या CSV निकालें।')}</p>}
        {!rows.length && <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">{t('Nothing found', 'कुछ नहीं मिला')}</div>}
      </div>
    </>
  )
}

function KundMap() {
  const { t, lang } = useLang()
  const [, bump] = useTick(5000)
  const [date, setDate] = useState(EVENT.dates[0])
  const [sess, setSess] = useState('morning')
  const [zone, setZone] = useState(0)
  const [sel, setSel] = useState(null)
  const { occ, blocked } = kundMap(date, sess)
  const st = slotStats(date, sess)
  const [a, z] = zoneRange(zone)
  const cells = Array.from({ length: z - a + 1 }, (_, i) => a + i)
  const color = (k) => blocked[k] ? 'bg-slate-800 text-white' : !occ[k] ? 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100' : occ[k] >= EVENT.seats ? 'bg-maroon-700 text-white' : 'bg-saffron-400 text-maroon-950'
  const fams = sel ? kundFamilies(date, sess, sel) : []
  return (
    <>
      <H sub={t('Tap a kund for families; block empty kunds', 'कुंड दबाकर परिवार देखें; खाली कुंड बंद करें')} right={<div className="flex gap-2"><Sel value={date} onChange={(e) => { setDate(e.target.value); setSel(null) }}>{EVENT.dates.map((d) => <option key={d} value={d}>{fmtDate(d, lang)}</option>)}</Sel><Sel value={sess} onChange={(e) => { setSess(e.target.value); setSel(null) }}>{Object.keys(EVENT.sessions).map((s) => <option key={s} value={s}>{t(EVENT.sessions[s].en, EVENT.sessions[s].hi)}</option>)}</Sel></div>}>{t('Kund map', 'कुंड मानचित्र')}</H>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {[[PAL.emerald, t('Empty', 'खाली'), st.empty], [PAL.saffron, t('Partly filled', 'आंशिक'), st.partial], [PAL.maroon, t('Full', 'पूर्ण'), st.full], ['#1e293b', t('Blocked', 'बंद'), st.blocked]].map(([c, l, n]) => <div key={l} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-3"><i className="size-3 rounded-full" style={{ background: c }} /><div><div className="text-lg font-bold tabular-nums leading-none">{nf(n)}</div><div className="text-xs text-slate-500">{l}</div></div></div>)}
      </div>
      <div className="mb-4 flex gap-1.5 overflow-x-auto pb-1">
        {ZONES.map(([en, hi], i) => <button key={en} onClick={() => { setZone(i); setSel(null) }} className={`shrink-0 rounded-full px-3.5 py-2 text-xs font-bold transition ${zone === i ? 'bg-maroon-800 text-white' : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50'}`}>{t(en, hi)}</button>)}
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        <Card className="!p-3">
          <div className="grid grid-cols-[repeat(auto-fill,minmax(40px,1fr))] gap-1.5">
            {cells.map((k) => <button key={k} onClick={() => setSel(k)} title={`${occ[k] || 0}/${EVENT.seats}`} className={`aspect-square rounded-lg text-[10px] font-bold transition active:scale-90 ${color(k)} ${sel === k ? 'ring-2 ring-maroon-900 ring-offset-1' : ''}`}>{k}</button>)}
          </div>
        </Card>
        <Card className="self-start">
          {!sel ? <p className="text-sm text-slate-500">{t('Select a kund.', 'कोई कुंड चुनें।')}</p> : (
            <>
              <div className="text-xl font-bold text-slate-900">{t('Kund', 'कुंड')} #{sel}</div>
              <div className="text-xs text-slate-500">{t(ZONES[Math.min(10, zone)][0], ZONES[Math.min(10, zone)][1])} · {occ[sel] || 0}/{EVENT.seats} {t('seats', 'आसन')}</div>
              <div className="mt-2 flex gap-1">{Array.from({ length: EVENT.seats }, (_, i) => <span key={i} className={`size-5 rounded-full ${i < (occ[sel] || 0) ? 'bg-maroon-700' : 'bg-slate-200'}`} />)}</div>
              <div className="mt-3 space-y-2">{fams.map((b) => <div key={b.id} className="rounded-lg bg-slate-50 p-2.5 text-sm"><b>{b.coordinator.name}</b> · {b.members.length}<div className="text-xs text-slate-500">{b.id}</div></div>)}</div>
              {!occ[sel] && <Btn variant="ghost" className="mt-4 w-full text-sm" onClick={() => { toggleBlock(date, sess, sel); bump() }}><Ban size={16} />{blocked[sel] ? t('Unblock', 'खोलें') : t('Block this kund', 'कुंड बंद करें')}</Btn>}
            </>
          )}
        </Card>
      </div>
    </>
  )
}

function Volunteers() {
  const { t } = useLang()
  const [, bump] = useTick(5000)
  const [name, setName] = useState('')
  const [pin, setPin] = useState('')
  const a = analytics()
  const done = Object.fromEntries(a.staff)
  return (
    <>
      <H sub={t('Volunteers log in at /staff with their PIN and can only scan and mark entry.', 'स्वयंसेवक /staff पर अपने पिन से लॉगिन करते हैं और केवल स्कैन व प्रवेश दर्ज कर सकते हैं।')}>{t('Volunteers', 'स्वयंसेवक')}</H>
      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <Card title={t('Add volunteer', 'स्वयंसेवक जोड़ें')}>
          <form onSubmit={(e) => { e.preventDefault(); if (name.trim() && pin.length >= 4) { addStaff(name.trim(), pin); setName(''); setPin(''); bump() } }} className="space-y-3">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('Name', 'नाम')} className="min-h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-saffron-500" />
            <input value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" placeholder={t('PIN (4–6 digits)', 'पिन (4–6 अंक)')} className="min-h-11 w-full rounded-lg border border-slate-300 px-3 text-sm tracking-widest outline-none focus:border-saffron-500" />
            <Btn type="submit" className="w-full" disabled={!name.trim() || pin.length < 4}><UserPlus size={18} />{t('Add', 'जोड़ें')}</Btn>
          </form>
        </Card>
        <Card title={t('Active volunteers', 'सक्रिय स्वयंसेवक')} sub={`${staffList().length}`}>
          <div className="divide-y divide-slate-100">
            {staffList().map((s) => (
              <div key={s.id} className="flex items-center gap-3 py-3">
                <span className="grid size-10 place-items-center rounded-full bg-maroon-50 font-bold text-maroon-800">{s.name[0]}</span>
                <div className="min-w-0 flex-1"><div className="font-semibold">{s.name}</div><div className="text-xs text-slate-500">PIN <span className="font-mono">{s.pin}</span></div></div>
                <div className="text-right"><div className="text-lg font-bold tabular-nums text-emerald-600">{done[s.name] || 0}</div><div className="text-[11px] text-slate-500">{t('entered', 'प्रवेश')}</div></div>
                <button onClick={() => { removeStaff(s.id); bump() }} className="rounded-lg p-2 text-red-500 hover:bg-red-50" aria-label="remove"><Trash2 size={17} /></button>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  )
}

function Sett() {
  const { t } = useLang()
  const [msg, setMsg] = useState('')
  return (
    <>
      <H>{t('Settings', 'सेटिंग')}</H>
      <Card className="max-w-2xl space-y-5">
        <div><h2 className="font-bold">{t('Demo data', 'डेमो डेटा')}</h2><p className="text-sm text-slate-500">{t('Adds 500 random families with some entries marked, so every chart has data.', '500 नमूना परिवार जोड़ता है (कुछ प्रवेश सहित) ताकि हर चार्ट में डेटा दिखे।')}</p>
          <Btn className="mt-3" onClick={() => { seedDemo(500); setMsg(t('Added 500 families', '500 परिवार जोड़े गए')) }}><Database size={18} />{t('Load demo data', 'डेमो डेटा लोड करें')}</Btn></div>
        <div className="border-t border-slate-100 pt-5"><h2 className="font-bold text-red-700">{t('Danger zone', 'खतरनाक क्षेत्र')}</h2>
          <Btn variant="ghost" className="mt-3 !border-red-300 !text-red-700" onClick={() => { if (confirm(t('Delete ALL bookings on this device?', 'इस डिवाइस के सभी पंजीकरण मिटाएँ?'))) { resetAll(); setMsg(t('All cleared', 'सब मिटा दिया')) } }}><Trash2 size={18} />{t('Clear all bookings', 'सारे पंजीकरण मिटाएँ')}</Btn></div>
        {msg && <p className="text-sm font-bold text-emerald-700">{msg}</p>}
      </Card>
    </>
  )
}
