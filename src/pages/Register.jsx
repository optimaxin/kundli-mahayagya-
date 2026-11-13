import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowLeft, ArrowRight, Check, ChevronDown, Flame, Plus, Trash2, User, Users, CalendarCheck, ClipboardCheck, Sunrise, Sunset, AlertCircle, Info } from 'lucide-react'
import { useLang } from '../lib/lang.jsx'
import { Btn, Field, inputCls } from '../components/ui.jsx'
import { EVENT, createBooking, describeError, fmtDate, fmtTime, loadSlots, newKey, slotAvailability, slotsError, useSlots } from '../lib/db.js'

const STATES = ['Uttar Pradesh', 'Delhi', 'Rajasthan', 'Madhya Pradesh', 'Haryana', 'Uttarakhand', 'Bihar', 'Gujarat', 'Maharashtra', 'Punjab', 'Himachal Pradesh', 'Jharkhand', 'Chhattisgarh', 'West Bengal', 'Karnataka', 'Tamil Nadu', 'Telangana', 'Andhra Pradesh', 'Kerala', 'Odisha', 'Assam', 'Other']
const RELS = [['Spouse', 'पति / पत्नी'], ['Parent', 'माता / पिता'], ['Child', 'पुत्र / पुत्री'], ['Sibling', 'भाई / बहन'], ['Relative', 'संबंधी'], ['Friend', 'मित्र / साधक']]
const MAX = EVENT.seats
const digits = (s) => s.replace(/\D/g, '').slice(0, 10)

// The kund: 8 seats around the sacred fire; fills as you add family members
function KundPreview({ n }) {
  return (
    <div className="relative mx-auto size-40 shrink-0">
      <div className="absolute inset-[22%] rounded-full bg-gradient-to-br from-saffron-300 to-saffron-500 grid place-items-center shadow-[0_0_40px_rgba(244,123,32,.55)]">
        <Flame className="text-maroon-900 flicker" size={30} />
      </div>
      {Array.from({ length: MAX }, (_, i) => {
        const a = (i / MAX) * Math.PI * 2 - Math.PI / 2
        const on = i < n
        return (
          <motion.span
            key={i}
            animate={{ scale: on ? 1 : .8, backgroundColor: on ? '#7a1a2d' : '#ffffff' }}
            className={`absolute size-7 -ml-3.5 -mt-3.5 rounded-full border-2 grid place-items-center text-[11px] font-bold ${on ? 'border-maroon-900 text-gold-300' : 'border-maroon-200 text-maroon-200'}`}
            style={{ left: `${50 + 42 * Math.cos(a)}%`, top: `${50 + 42 * Math.sin(a)}%` }}
          >{i + 1}</motion.span>
        )
      })}
    </div>
  )
}

export default function Register() {
  const { t, lang } = useLang()
  const nav = useNavigate()
  const [step, setStep] = useState(0)
  const [dir, setDir] = useState(1)
  const [more, setMore] = useState(false)
  const [errs, setErrs] = useState({})
  const [banner, setBanner] = useState('')
  const [busy, setBusy] = useState(false)
  const [c, setC] = useState({ name: '', mobile: '', city: '', state: 'Uttar Pradesh', alt: '', email: '', address: '', pincode: '', gotra: '', sankalp: '' })
  const [members, setMembers] = useState([{ age: '', gender: 'male', relationship: 'Self', mobile: '' }])
  const [picked, setPicked] = useState([])
  const [ok, setOk] = useState({ satvik: false, consent: false })
  // Family size = the members already entered on the family step (the coordinator is member 1).
  // Availability is asked from the server for exactly this size once the session step is reached, and
  // again whenever the size changes; results for another size are never shown.
  const n = members.length
  const slotsVer = useSlots(30000, step >= 2 ? n : null)
  // One idempotency key per submission attempt; reused if the network drops so a retry never double-books.
  const keyRef = useRef(newKey())

  const setCF = (k) => (e) => setC((p) => ({ ...p, [k]: k === 'mobile' || k === 'alt' ? digits(e.target.value) : e.target.value }))
  const setM = (i, patch) => setMembers((p) => p.map((m, j) => (j === i ? { ...m, ...patch } : m)))
  const avail = useMemo(() => Object.fromEntries(EVENT.dates.flatMap((d) => Object.keys(EVENT.sessions).map((s) => [`${d}|${s}`, slotAvailability(d, s, n)]))), [n, slotsVer])
  const fits = useMemo(() => Object.fromEntries(Object.entries(avail).map(([k, a]) => [k, a.status === 'AVAILABLE'])), [avail])
  // Drop picked sessions the server now says cannot seat this family together (e.g. a member was added
  // after picking, or the last suitable Kund was taken). 'loading' / 'error' are not definitive: keep.
  useEffect(() => {
    const gone = picked.filter((k) => ['NOT_FOR_THIS_FAMILY', 'FULL', 'CLOSED'].includes(avail[k]?.status))
    if (!gone.length) return
    setPicked((p) => p.filter((k) => !gone.includes(k)))
    setBanner(t(`${gone.length} selected session(s) can no longer seat your ${n}-member family together and were removed. Please choose again.`, `${gone.length} चुने गए सत्र में अब आपके ${n} सदस्यीय परिवार के लिए एक साथ स्थान नहीं है, इसलिए उन्हें हटा दिया गया। कृपया पुनः चुनें।`))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [avail])

  const labels = [
    [t('You', 'आप'), User], [t('Family', 'परिवार'), Users], [t('Session', 'सत्र'), CalendarCheck], [t('Confirm', 'पुष्टि'), ClipboardCheck],
  ]

  const validate = (s) => {
    const e = {}
    if (s === 0) {
      if (c.name.trim().length < 2) e.name = t('Enter your full name', 'अपना पूरा नाम लिखें')
      if (c.mobile.length !== 10 || !/^[6-9]/.test(c.mobile)) e.mobile = t('Enter a valid 10-digit mobile number', 'सही 10 अंकों का मोबाइल नंबर लिखें')
      if (c.city.trim().length < 2) e.city = t('Enter your city', 'अपना शहर लिखें')
      if (c.email && !/^\S+@\S+\.\S+$/.test(c.email)) e.email = t('Invalid email', 'ईमेल सही नहीं है')
    }
    if (s === 1) {
      members.forEach((m, i) => {
        if (i > 0 && m.name?.trim().length < 2) e[`n${i}`] = t('Name required', 'नाम आवश्यक है')
        if (!m.age || +m.age < 1 || +m.age > 110) e[`a${i}`] = t('Age 1–110', 'आयु 1–110')
      })
    }
    if (s === 2 && !picked.length) e.slots = t('Pick at least one session', 'कम से कम एक सत्र चुनें')
    if (s === 3) {
      if (!ok.satvik) e.satvik = t('Please confirm', 'कृपया पुष्टि करें')
      if (!ok.consent) e.consent = t('Please confirm', 'कृपया पुष्टि करें')
    }
    setErrs(e)
    return !Object.keys(e).length
  }
  const go = (d) => {
    if (d > 0 && !validate(step)) return
    setErrs({}); setBanner(''); setDir(d); setStep((s) => s + d)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  const toggleSlot = (date, session) => {
    const k = `${date}|${session}`
    // Morning and afternoon are independent: a family may pick either or both sessions of a date.
    setPicked((p) => (p.includes(k) ? p.filter((x) => x !== k) : [...p, k]))
    setErrs({})
  }
  // "All mornings" / "All afternoons" add to the current selection (both together = every session).
  const bulk = (session) => setPicked((p) => [...new Set([...p, ...EVENT.dates.map((d) => `${d}|${session}`).filter((k) => fits[k])])])
  const bothDays = EVENT.dates.filter((d) => Object.keys(EVENT.sessions).every((s) => picked.includes(`${d}|${s}`)))

  const submit = async () => {
    if (!validate(3)) return
    if (!picked.length) { setDir(-1); setStep(2); setErrs({ slots: t('Pick at least one session', 'कम से कम एक सत्र चुनें') }); return }
    setBusy(true)
    setBanner('')
    try {
      const final = members.map((m, i) => (i === 0 ? { ...m, name: c.name.trim(), mobile: c.mobile, relationship: 'Self', self: true } : { ...m, name: m.name.trim() }))
      const b = await createBooking({
        coordinator: { name: c.name.trim(), mobile: c.mobile, city: c.city.trim(), state: c.state, alt: c.alt, email: c.email.trim(), address: c.address.trim(), pincode: c.pincode, gotra: c.gotra.trim(), sankalp: c.sankalp.trim() },
        members: final,
        slots: picked.map((k) => { const [date, session] = k.split('|'); return { date, session } }).sort((a, b) => a.date.localeCompare(b.date) || a.session.localeCompare(b.session)),
      }, keyRef.current)
      nav(`/ticket/${encodeURIComponent(b.token)}?new=1`, { replace: true })
    } catch (err) {
      setBusy(false)
      if (String(err.message).startsWith('FULL:')) {
        keyRef.current = newKey()
        setBanner(t('Sorry, a selected session can no longer seat your whole family together. Please choose another.', 'क्षमा करें, चुने गए सत्र में अब आपके पूरे परिवार के लिए एक साथ स्थान उपलब्ध नहीं है। कृपया दूसरा सत्र चुनें।'))
        setPicked((p) => p.filter((k) => !String(err.message).includes(k)))
        setDir(-1); setStep(2)
        return
      }
      // Keep the same key after network/busy errors (safe retry); a fresh one after the server rejected the data.
      if (!(err.code === 'NETWORK' || err.status === 503)) keyRef.current = newKey()
      setBanner(describeError(err, t))
    }
  }

  const slide = { enter: (d) => ({ x: d * 40, opacity: 0 }), center: { x: 0, opacity: 1 }, exit: (d) => ({ x: d * -40, opacity: 0 }) }

  return (
    <div className="paper min-h-[calc(100vh-4rem)] pb-32 md:pb-16">
      <div className="mx-auto max-w-3xl px-4 pt-6 md:pt-10">
        {/* stepper */}
        <div className="flex items-center justify-between">
          {labels.map(([l, Icon], i) => (
            <div key={l} className="flex flex-1 items-center last:flex-none">
              <div className="flex flex-col items-center gap-1">
                <motion.span animate={{ scale: i === step ? 1.12 : 1 }} className={`grid size-11 place-items-center rounded-full border-2 transition-colors ${i < step ? 'bg-emerald-600 border-emerald-600 text-white' : i === step ? 'bg-maroon-800 border-maroon-800 text-gold-300 shadow-lg' : 'bg-white border-maroon-200 text-maroon-200'}`}>
                  {i < step ? <Check size={20} /> : <Icon size={20} />}
                </motion.span>
                <span className={`text-[11px] font-bold ${i === step ? 'text-maroon-900' : 'text-stone-500'}`}>{l}</span>
              </div>
              {i < 3 && <div className="mx-2 mb-5 h-1 flex-1 rounded-full bg-maroon-100 overflow-hidden"><motion.div className="h-full bg-emerald-500" animate={{ width: i < step ? '100%' : '0%' }} /></div>}
            </div>
          ))}
        </div>

        {banner && <div className="mt-5 flex gap-2 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-700"><AlertCircle size={18} className="shrink-0" />{banner}</div>}

        <div className="relative mt-6 overflow-hidden rounded-[2rem] border border-gold-300/70 bg-white p-4 min-[400px]:p-5 md:p-8 shadow-[0_20px_50px_-20px_rgba(122,26,45,.35)]">
          <AnimatePresence mode="wait" custom={dir}>
            <motion.div key={step} custom={dir} variants={slide} initial="enter" animate="center" exit="exit" transition={{ duration: .25 }}>
              {step === 0 && (
                <div className="space-y-5">
                  <Head h={t('Who is registering?', 'पंजीकरण कौन कर रहा है?')} p={t('Main yagyakarta (coordinator). Only one form for the whole family.', 'मुख्य यज्ञकर्ता (समन्वयक)। पूरे परिवार का एक ही फॉर्म।')} />
                  <Field label={t('Full name *', 'पूरा नाम *')} error={errs.name}><input className={inputCls(errs.name)} value={c.name} onChange={setCF('name')} placeholder={t('e.g. Ramesh Sharma', 'जैसे रमेश शर्मा')} autoComplete="name" /></Field>
                  <Field label={t('Mobile number *', 'मोबाइल नंबर *')} error={errs.mobile} hint={t('Used to find your pass later', 'प्रवेश पत्र दोबारा खोजने हेतु')}>
                    <div className="flex gap-2"><span className="grid min-h-12 shrink-0 place-items-center rounded-xl bg-maroon-50 px-3.5 font-bold text-maroon-800">+91</span><input className={inputCls(errs.mobile) + ' min-w-0'} inputMode="numeric" value={c.mobile} onChange={setCF('mobile')} placeholder="98XXXXXXXX" autoComplete="tel" /></div>
                  </Field>
                  <div className="grid gap-5 sm:grid-cols-2">
                    <Field label={t('City *', 'शहर *')} error={errs.city}><input className={inputCls(errs.city)} value={c.city} onChange={setCF('city')} placeholder={t('e.g. Agra', 'जैसे आगरा')} autoComplete="address-level2" /></Field>
                    <Field label={t('State', 'राज्य')}><select className={inputCls()} value={c.state} onChange={setCF('state')}>{STATES.map((s) => <option key={s}>{s}</option>)}</select></Field>
                  </div>
                  <button type="button" onClick={() => setMore(!more)} className="flex w-full items-center justify-between rounded-2xl bg-saffron-50 px-4 py-3 text-sm font-bold text-saffron-600">
                    {t('More details (optional)', 'अन्य विवरण (वैकल्पिक)')}<ChevronDown className={`transition ${more ? 'rotate-180' : ''}`} />
                  </button>
                  <AnimatePresence>
                    {more && (
                      <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                        <div className="grid gap-5 pt-1 sm:grid-cols-2">
                          <Field label={t('Alternate mobile', 'वैकल्पिक मोबाइल')}><input className={inputCls()} inputMode="numeric" value={c.alt} onChange={setCF('alt')} /></Field>
                          <Field label={t('Email', 'ईमेल')} error={errs.email}><input className={inputCls(errs.email)} type="email" value={c.email} onChange={setCF('email')} /></Field>
                          <Field label={t('Address', 'पता')} className="sm:col-span-2"><input className={inputCls()} value={c.address} onChange={setCF('address')} autoComplete="street-address" /></Field>
                          <Field label={t('Pincode', 'पिनकोड')}><input className={inputCls()} inputMode="numeric" maxLength={6} value={c.pincode} onChange={(e) => setC({ ...c, pincode: e.target.value.replace(/\D/g, '').slice(0, 6) })} /></Field>
                          <Field label={t('Gotra (if known)', 'गोत्र (यदि ज्ञात हो)')}><input className={inputCls()} value={c.gotra} onChange={setCF('gotra')} /></Field>
                          <Field label={t('Sankalp purpose', 'संकल्प उद्देश्य')} className="sm:col-span-2"><input className={inputCls()} value={c.sankalp} onChange={setCF('sankalp')} /></Field>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              )}

              {step === 1 && (
                <div className="space-y-5">
                  <div className="flex flex-col items-center gap-4 sm:flex-row">
                    <KundPreview n={n} />
                    <Head h={t('Your family', 'आपका परिवार')} p={t(`${n} of ${MAX} seats taken. Everyone sits together at one kund.`, `${MAX} में से ${n} आसन। सभी एक ही कुंड पर साथ बैठेंगे।`)} />
                  </div>
                  <AnimatePresence initial={false}>
                    {members.map((m, i) => (
                      <motion.div key={i} layout initial={{ opacity: 0, scale: .96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: .9 }} className="rounded-2xl border border-maroon-100 bg-maroon-50/40 p-4">
                        <div className="mb-3 flex items-center justify-between gap-2">
                          <span className="inline-flex min-w-0 items-center gap-2 text-sm font-bold text-maroon-900"><span className="grid size-7 shrink-0 place-items-center rounded-full bg-maroon-800 text-xs text-gold-300">{i + 1}</span>{i === 0 ? t('You (Yagyakarta)', 'आप (यज्ञकर्ता)') : t('Member', 'सदस्य')}</span>
                          {i > 0 && <button onClick={() => setMembers((p) => p.filter((_, j) => j !== i))} className="grid size-11 shrink-0 place-items-center rounded-full text-red-500 hover:bg-red-50" aria-label={t('Remove member', 'सदस्य हटाएँ')}><Trash2 size={18} /></button>}
                        </div>
                        <div className="grid gap-3 sm:grid-cols-6">
                          <Field label={t('Name', 'नाम')} error={errs[`n${i}`]} className="sm:col-span-3">
                            {i === 0 ? <input className={inputCls() + ' bg-stone-100'} readOnly value={c.name} /> : <input className={inputCls(errs[`n${i}`])} value={m.name || ''} onChange={(e) => setM(i, { name: e.target.value })} />}
                          </Field>
                          <Field label={t('Age', 'आयु')} error={errs[`a${i}`]} className="sm:col-span-1"><input className={inputCls(errs[`a${i}`])} inputMode="numeric" value={m.age} onChange={(e) => setM(i, { age: e.target.value.replace(/\D/g, '').slice(0, 3) })} /></Field>
                          <Field label={t('Gender', 'लिंग')} className="sm:col-span-2">
                            <div className="flex gap-1 rounded-xl bg-white p-1 border border-stone-300">
                              {[['male', t('M', 'पु'), ''], ['female', t('F', 'म'), ''], ['other', t('O', 'अ'), '']].map(([v, l]) => (
                                <button key={v} type="button" onClick={() => setM(i, { gender: v })} className={`flex-1 min-h-10 rounded-lg text-sm font-bold transition ${m.gender === v ? 'bg-maroon-800 text-gold-300' : 'text-stone-500'}`}>{l}</button>
                              ))}
                            </div>
                          </Field>
                          {i > 0 && (
                            <Field label={t('Relation', 'संबंध')} className="sm:col-span-6">
                              <div className="flex flex-wrap gap-2">{RELS.map(([en, hi]) => (
                                <button key={en} type="button" onClick={() => setM(i, { relationship: en })} className={`min-h-10 rounded-full border px-3.5 py-1.5 text-sm font-semibold transition ${m.relationship === en ? 'border-saffron-500 bg-saffron-500 text-white' : 'border-stone-300 bg-white text-stone-600'}`}>{t(en, hi)}</button>
                              ))}</div>
                            </Field>
                          )}
                        </div>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                  {n < MAX ? (
                    <button type="button" onClick={() => setMembers((p) => [...p, { name: '', age: '', gender: 'male', relationship: 'Spouse', mobile: '' }])} className="flex w-full min-h-14 items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-saffron-400 bg-saffron-50 font-bold text-saffron-600 transition hover:bg-saffron-100 active:scale-[.98]">
                      <Plus size={20} /> {t(`Add member (${n}/${MAX})`, `सदस्य जोड़ें (${n}/${MAX})`)}
                    </button>
                  ) : <p className="rounded-2xl bg-emerald-50 p-4 text-center text-sm font-semibold text-emerald-700">{t('Kund full: 8 of 8. For more people, make a second registration.', 'कुंड पूर्ण: 8 में से 8। अधिक लोगों के लिए दूसरा पंजीकरण करें।')}</p>}
                </div>
              )}

              {step === 2 && (
                <div className="space-y-5">
                  <Head h={t('Choose day & session', 'दिन व सत्र चुनें')} p={t(`Availability is shown for your ${n}-member family. On each day you can pick the morning, the afternoon or both sessions, and as many days as you like. Each selected session gets its own Kund.`, `उपलब्धता आपके ${n} सदस्यीय परिवार के अनुसार दिखाई गई है। हर दिन प्रातः, अपराह्न या दोनों सत्र चुन सकते हैं, और जितने चाहें उतने दिन। हर चुने गए सत्र के लिए अलग कुंड आवंटित होगा।`)} />
                  <div className="overflow-hidden rounded-2xl border border-gold-300/70 bg-gradient-to-r from-maroon-800 to-maroon-900 text-white">
                    <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                      <div className="flex items-center gap-3">
                        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-gold-400 text-maroon-950"><Users size={20} /></span>
                        <div>
                          <div className="text-[11px] font-bold uppercase tracking-wider text-gold-300">{t('Your family', 'आपका परिवार')}</div>
                          <div className="font-display text-xl leading-tight">{t(`${n} member${n > 1 ? 's' : ''}`, `${n} सदस्य`)}</div>
                        </div>
                      </div>
                      <button type="button" onClick={() => go(-1)} className="rounded-full border border-gold-300/60 px-3.5 py-1.5 text-xs font-bold text-gold-300 transition hover:bg-white/10 active:scale-95">{t('Edit family', 'परिवार बदलें')}</button>
                    </div>
                    <div className="flex gap-2 border-t border-white/10 bg-black/10 px-4 py-2.5 text-sm text-maroon-50">
                      <Info size={16} className="mt-0.5 shrink-0 text-gold-300" />
                      <span>{t('The same Kund will be allotted to all members of your family.', 'आपके परिवार के सभी सदस्यों के लिए एक ही कुंड आवंटित किया जाएगा।')}</span>
                    </div>
                  </div>
                  {slotsError() && !Object.values(fits).some(Boolean) && (
                    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-700">
                      <AlertCircle size={18} className="shrink-0" />
                      <span className="min-w-0 flex-1">{t('Could not load session availability. Please check your internet connection.', 'सत्र उपलब्धता लोड नहीं हो सकी। कृपया इंटरनेट कनेक्शन जाँचें।')} <span className="font-normal">({describeError(slotsError(), t)})</span></span>
                      <button type="button" onClick={() => loadSlots(n).catch(() => {})} className="rounded-full bg-white px-4 py-2 text-xs font-bold text-red-700 ring-1 ring-red-200 active:scale-95">{t('Try again', 'पुनः प्रयास करें')}</button>
                    </div>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <Chip onClick={() => bulk('morning')}><Sunrise size={15} /> {t('All mornings', 'सभी प्रातः')}</Chip>
                    <Chip onClick={() => bulk('afternoon')}><Sunset size={15} /> {t('All afternoons', 'सभी अपराह्न')}</Chip>
                    <Chip onClick={() => setPicked([])}>{t('Clear', 'हटाएँ')}</Chip>
                  </div>
                  <div className="space-y-2.5">
                    {EVENT.dates.map((d, i) => (
                      <motion.div key={d} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .04 }} className="grid grid-cols-[3.5rem_minmax(0,1fr)_minmax(0,1fr)] items-stretch gap-2 sm:grid-cols-[5.5rem_minmax(0,1fr)_minmax(0,1fr)]">
                        <div className="grid place-items-center rounded-2xl bg-maroon-800 py-2 text-center text-gold-300">
                          <div className="font-display text-2xl leading-none">{d.slice(8)}</div>
                          <div className="mt-0.5 text-[11px] font-bold uppercase leading-tight tracking-wider opacity-80">{fmtDate(d, lang, { weekday: 'short' })}</div>
                        </div>
                        {Object.keys(EVENT.sessions).map((s) => {
                          const k = `${d}|${s}`, st = avail[k], can = fits[k], on = picked.includes(k)
                          const [label, tone] = STATUS[st.status] || STATUS.loading
                          return (
                            <button key={s} type="button" disabled={!can} onClick={() => toggleSlot(d, s)} className={`relative overflow-hidden rounded-2xl border-2 p-2.5 text-left transition active:scale-[.97] ${on ? 'border-saffron-500 bg-saffron-50 shadow-md' : can ? 'border-stone-200 bg-white hover:border-saffron-300' : 'border-stone-200 bg-stone-100 opacity-60'}`}>
                              {/* the tick lives on the time row so it can never clip the session name */}
                              <span className="flex min-w-0 items-center gap-1 text-[13px] font-bold leading-snug text-maroon-900">{s === 'morning' ? <Sunrise size={14} className="hidden shrink-0 min-[400px]:block" /> : <Sunset size={14} className="hidden shrink-0 min-[400px]:block" />}<span className="min-w-0">{t(EVENT.sessions[s].en, EVENT.sessions[s].hi)}</span></span>
                              <div className="mt-0.5 flex items-center justify-between gap-1 text-xs tabular-nums text-stone-500"><span>{fmtTime(EVENT.sessions[s].start)}</span>{on && <Check size={16} className="shrink-0 rounded-full bg-saffron-500 p-0.5 text-white" aria-label={t('Selected', 'चुना गया')} />}</div>
                              <div className={`mt-1.5 flex items-start gap-1.5 text-xs font-bold leading-snug ${tone}`}>
                                <span className="mt-[5px] size-2 shrink-0 rounded-full bg-current" />
                                <span className="min-w-0">{t(...label)}</span>
                              </div>
                            </button>
                          )
                        })}
                      </motion.div>
                    ))}
                  </div>
                  {errs.slots && <p className="text-sm font-bold text-red-600">{errs.slots}</p>}
                  <div className="rounded-2xl border border-maroon-100 bg-white/70 p-3 text-center text-sm text-maroon-800" aria-live="polite">
                    <p className="font-semibold">{t(`${picked.length} session(s) selected · ${n}-member family`, `${picked.length} सत्र चुने गए · ${n} सदस्यीय परिवार`)}</p>
                    {picked.length > 0 && <p className="mt-0.5 text-xs text-stone-600">{t(`Total ${picked.length * n} attendee places (${n} × ${picked.length} sessions)`, `कुल ${picked.length * n} आसन (${n} × ${picked.length} सत्र)`)}</p>}
                    {bothDays.length > 0 && <p className="mt-1.5 text-xs font-semibold text-saffron-600">{t(`Both sessions on ${bothDays.map((d) => fmtDate(d, lang, { day: 'numeric', month: 'short' })).join(', ')}: morning and afternoon are two separate Kund allocations.`, `${bothDays.map((d) => fmtDate(d, lang, { day: 'numeric', month: 'short' })).join(', ')} को दोनों सत्र: प्रातः और अपराह्न के लिए दो अलग कुंड आवंटन होंगे।`)}</p>}
                  </div>
                </div>
              )}

              {step === 3 && (
                <div className="space-y-5">
                  <Head h={t('Review & confirm', 'जाँचें व पुष्टि करें')} p={t('Your kund is allocated automatically when you confirm.', 'पुष्टि करते ही आपका कुंड स्वतः आवंटित होगा।')} />
                  <div className="divide-y divide-maroon-100 overflow-hidden rounded-2xl border border-maroon-100">
                    <Row l={t('Yagyakarta', 'यज्ञकर्ता')} v={`${c.name} · +91 ${c.mobile}`} />
                    <Row l={t('City', 'शहर')} v={`${c.city}, ${c.state}`} />
                    <Row l={t('Family', 'परिवार')} v={members.map((m, i) => (i === 0 ? c.name : m.name)).join(', ')} />
                    <Row l={t('Attendee places', 'कुल आसन')} v={t(`${picked.length * n} (${n} members × ${picked.length} sessions)`, `${picked.length * n} (${n} सदस्य × ${picked.length} सत्र)`)} />
                    <Row l={t('Sessions', 'सत्र')} v={<div className="flex flex-wrap gap-1.5">{[...picked].sort().map((k) => { const [d, s] = k.split('|'); return <span key={k} className="rounded-full bg-saffron-100 px-2.5 py-1 text-xs font-bold text-saffron-600">{fmtDate(d, lang, { day: 'numeric', month: 'long' })} · {t(EVENT.sessions[s].en, EVENT.sessions[s].hi)}</span> })}</div>} />
                  </div>
                  <Check2 on={ok.satvik} err={errs.satvik} onChange={(v) => setOk({ ...ok, satvik: v })}>{t('All members are vegetarian / sattvik and will follow the yagya rules.', 'सभी सदस्य शाकाहारी/सात्विक हैं और यज्ञ के नियमों का पालन करेंगे।')}</Check2>
                  <Check2 on={ok.consent} err={errs.consent} onChange={(v) => setOk({ ...ok, consent: v })}>{t('I agree my details may be used for seating and entry by the organising team.', 'मैं सहमत हूँ कि मेरी जानकारी आसन-व्यवस्था व प्रवेश हेतु आयोजन समिति द्वारा उपयोग की जाएगी।')}</Check2>
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      {/* action bar */}
      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-gold-300/60 glass p-3 pb-[max(.75rem,env(safe-area-inset-bottom))] md:static md:mt-6 md:border-0 md:bg-transparent md:p-0 md:shadow-none md:backdrop-blur-none">
        <div className="mx-auto flex max-w-3xl gap-3 md:px-4">
          {step > 0 && <Btn variant="ghost" onClick={() => go(-1)} disabled={busy} className="px-5"><ArrowLeft size={18} /><span className="hidden sm:inline">{t('Back', 'पीछे')}</span></Btn>}
          {step < 3 ? (
            <Btn className="flex-1" onClick={() => go(1)}>{t(['Continue', 'Add family', 'Review'][step], ['आगे बढ़ें', 'सत्र चुनें', 'समीक्षा करें'][step])} <ArrowRight size={18} /></Btn>
          ) : (
            <Btn variant="maroon" className="flex-1" onClick={submit} disabled={busy}>{busy ? <><Flame className="flicker" size={18} /> {t('Allocating kund…', 'कुंड आवंटित हो रहा है…')}</> : <><Check size={18} /> {t('Confirm & get QR pass', 'पुष्टि करें व QR पाएँ')}</>}</Btn>
          )}
        </div>
      </div>
    </div>
  )
}

// Public status labels for the session picker. Deliberately no seat counts.
const STATUS = {
  AVAILABLE: [['Booking available', 'बुकिंग उपलब्ध'], 'text-emerald-700'],
  NOT_FOR_THIS_FAMILY: [['Fully booked', 'बुकिंग पूर्ण'], 'text-saffron-600'],
  FULL: [['Session full', 'सत्र पूर्ण'], 'text-red-600'],
  CLOSED: [['Booking closed', 'बुकिंग बंद'], 'text-stone-500'],
  error: [['Could not load', 'लोड नहीं हो सका'], 'text-red-600'],
  loading: [['Checking…', 'जाँच हो रही है…'], 'text-stone-400'],
}

const Head = ({ h, p }) => (<div><h2 className="font-display text-2xl text-maroon-900 md:text-3xl">{h}</h2><p className="mt-1 text-sm text-stone-600">{p}</p></div>)
const Chip = (p) => <button type="button" {...p} className="inline-flex min-h-10 items-center gap-1.5 rounded-full border border-maroon-200 bg-white px-3.5 py-2 text-xs font-bold text-maroon-800 transition hover:bg-maroon-50 active:scale-95" />
const Row = ({ l, v }) => (<div className="grid gap-1 p-4 sm:grid-cols-[8.5rem_minmax(0,1fr)] sm:gap-3"><span className="text-xs font-bold uppercase tracking-wider text-stone-500">{l}</span><span className="min-w-0 text-sm font-semibold text-maroon-950 [overflow-wrap:anywhere]">{v}</span></div>)
const Check2 = ({ on, onChange, err, children }) => (
  <button type="button" onClick={() => onChange(!on)} className={`flex w-full gap-3 rounded-2xl border-2 p-4 text-left text-sm transition ${on ? 'border-emerald-500 bg-emerald-50' : err ? 'border-red-400 bg-red-50' : 'border-stone-200'}`}>
    <span className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-md border-2 ${on ? 'border-emerald-600 bg-emerald-600 text-white' : 'border-stone-300 bg-white'}`}>{on && <Check size={15} />}</span>
    <span className="font-medium text-stone-700">{children}</span>
  </button>
)
