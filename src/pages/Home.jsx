import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Flame, MapPin, CalendarDays, Users, QrCode, Sunrise, Sunset, ChevronDown, HeartHandshake, Sparkles, ShieldCheck } from 'lucide-react'
import { useLang } from '../lib/lang.jsx'
import { Mandala, Divider, Btn } from '../components/ui.jsx'
import { EVENT, fmtTime } from '../lib/db.js'

// 8:00-11:00 -> '8–11 AM' (fits small phones)
const short = (k) => { const [a, b] = [EVENT.sessions[k].start, EVENT.sessions[k].end].map((x) => +x.slice(0, 2)); const h = (n) => ((n + 11) % 12) + 1; return `${h(a)}–${h(b)} ${b < 12 ? 'AM' : 'PM'}` }
const up = { hidden: { opacity: 0, y: 24 }, show: { opacity: 1, y: 0 } }
const Reveal = ({ children, delay = 0, className = '' }) => (
  <motion.div variants={up} initial="hidden" whileInView="show" viewport={{ once: true, margin: '-60px' }} transition={{ duration: .6, delay }} className={className}>
    {children}
  </motion.div>
)

export default function Home() {
  const { t } = useLang()
  const faqs = [
    [t('How many people can one registration cover?', 'एक पंजीकरण में कितने सदस्य जुड़ सकते हैं?'), t('1 to 8. The whole family sits together at one kund. For more than 8, register a second group.', '1 से 8 सदस्य। पूरा परिवार एक ही कुंड पर साथ बैठेगा। 8 से अधिक हों तो दूसरा समूह पंजीकृत करें।')],
    [t('When does my QR work?', 'मेरा QR कब मान्य होगा?'), t('Only during the session you booked (plus 15 minutes before and after). At any other time the scanner rejects it.', 'केवल आपके चुने सत्र के समय (15 मिनट पहले व बाद सहित)। अन्य समय पर स्कैनर इसे अस्वीकार करेगा।')],
    [t('Is there any fee?', 'क्या कोई शुल्क है?'), t('No. Registration and entry are completely free.', 'नहीं। पंजीकरण व प्रवेश पूर्णतः निःशुल्क हैं।')],
    [t('I lost my pass.', 'मेरा प्रवेश पत्र खो गया।'), t('Open “My pass” and search with your mobile number.', '“प्रवेश पत्र” खोलें और अपने मोबाइल नंबर से खोजें।')],
    [t('Food rules?', 'भोजन संबंधी नियम?'), t('The yagya is strictly sattvik / vegetarian. You confirm this on the last step of registration.', 'यज्ञ पूर्णतः सात्विक/शाकाहारी है। पंजीकरण के अंतिम चरण में आप इसकी पुष्टि करेंगे।')],
  ]
  return (
    <div className="paper">
      {/* HERO: event banner, then register + key details, all inside the first screen */}
      <section className="relative overflow-hidden bg-gradient-to-b from-maroon-950 via-maroon-900 to-maroon-800 text-white">
        <Mandala className="spin-slow absolute -right-40 -top-40 w-[640px] opacity-15" />
        <Mandala className="spin-slower absolute -bottom-56 -left-48 w-[620px] opacity-10" rings={3} />
        <div className="relative mx-auto max-w-6xl px-3 pt-3 sm:px-4 sm:pt-4">
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .6 }} className="rounded-2xl bg-gradient-to-br from-gold-300 to-gold-500 p-1 shadow-[0_20px_50px_-15px_rgba(0,0,0,.6)] sm:rounded-3xl sm:p-1.5">
            <img src="/banner.jpg" width="1600" height="600" fetchpriority="high" alt={t('2151 Kundiya Mrityunjay Maa Pitambara Mahayagya, Agra', 'आगरा में 2151 कुंडीय मृत्युंजय माँ पीतांबरा महायज्ञ')} className="block h-auto w-full rounded-xl sm:rounded-[1.25rem]" />
          </motion.div>

          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .6, delay: .15 }} className="py-4 text-center sm:py-5">
            {/* the banner text is too small on phones, so repeat the title there */}
            <h1 className="font-display gold-text text-xl leading-tight sm:hidden">{t('2151 Kundiya Mrityunjay Maa Pitambara Mahayagya', '2151 कुंडीय मृत्युंजय माँ पीतांबरा महायज्ञ')}</h1>
            <h1 className="sr-only hidden sm:block">{t('2151 Kundiya Mrityunjay Maa Pitambara Mahayagya', '2151 कुंडीय मृत्युंजय माँ पीतांबरा महायज्ञ')}</h1>
            <p className="mx-auto mt-2 max-w-2xl text-sm text-maroon-100/90 sm:mt-0 sm:text-base">{t('Register your whole family once, sit together at one kund, and enter with a single QR pass.', 'पूरे परिवार का एक बार पंजीकरण करें, एक ही कुंड पर साथ बैठें और एक QR पास से प्रवेश पाएँ।')}</p>
            <div className="mt-3 flex flex-col justify-center gap-2.5 sm:mt-4 sm:flex-row">
              <Btn as={Link} to="/register" className="min-h-13 px-8 text-base sm:text-lg"><Users size={20} /> {t('Register family', 'परिवार का पंजीकरण करें')}</Btn>
              <Btn as={Link} to="/find" variant="ghost" className="min-h-13 px-8 text-base sm:text-lg"><QrCode size={20} /> {t('View my pass', 'प्रवेश पत्र देखें')}</Btn>
            </div>
            <ul className="mt-4 grid grid-cols-2 gap-2 text-left sm:grid-cols-4 sm:gap-3">
              {[
                [CalendarDays, t('Dates', 'तिथि'), t('14–21 Dec 2026', '14–21 दिसंबर 2026')],
                [MapPin, t('Venue', 'स्थान'), t('JCB Tiraha, Agra', 'जेसीबी तिराहा, आगरा')],
                [Sunrise, t('Morning', 'प्रातः'), short('morning')],
                [Sunset, t('Afternoon', 'अपराह्न'), short('afternoon')],
              ].map(([Icon, l, v]) => (
                <li key={l} className="flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/5 p-2.5 backdrop-blur sm:p-3">
                  <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-saffron-400 to-saffron-600 text-white"><Icon size={17} /></span>
                  <span className="min-w-0"><span className="block text-[10px] font-bold uppercase text-gold-300">{l}</span><span className="block text-[13px] font-semibold leading-snug sm:text-sm">{v}</span></span>
                </li>
              ))}
            </ul>
          </motion.div>
        </div>
        <svg viewBox="0 0 1440 60" className="relative z-20 -mb-px block h-8 w-full text-[var(--color-cream)] sm:h-10" preserveAspectRatio="none"><path fill="currentColor" d="M0 60V30c120 20 240 20 360 5 160-20 320-30 480-10 200 25 360 20 600-15v50z" /></svg>
      </section>

      {/* NUMBERS */}
      <section className="mx-auto max-w-6xl px-4 -mt-6 relative">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            ['2151', t('Sacred kunds', 'पावन कुंड')],
            ['8', t('Seats per kund', 'प्रति कुंड आसन')],
            ['8', t('Days of yagya', 'यज्ञ दिवस')],
            ['0 ₹', t('Registration fee', 'पंजीकरण शुल्क')],
          ].map(([n, l], i) => (
            <Reveal key={l} delay={i * .08} className="rounded-3xl bg-white border border-gold-300/60 p-5 text-center shadow-[0_10px_30px_-12px_rgba(122,26,45,.25)]">
              <div className="font-display text-4xl md:text-5xl text-maroon-800">{n}</div>
              <div className="mt-1 text-xs md:text-sm font-semibold text-stone-600">{l}</div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section className="mx-auto max-w-6xl px-4 mt-20">
        <Reveal className="text-center">
          <h2 className="font-display text-3xl md:text-5xl text-maroon-900">{t('Four simple steps', 'चार सरल चरण')}</h2>
          <Divider className="mt-3" />
        </Reveal>
        <div className="mt-10 grid gap-4 md:grid-cols-4">
          {[
            [Users, t('Your details', 'आपका विवरण'), t('Name, mobile and city. Takes 30 seconds.', 'नाम, मोबाइल व शहर। केवल 30 सेकंड।')],
            [HeartHandshake, t('Add family', 'परिवार जोड़ें'), t('Up to 8 members. All seat together.', '8 सदस्यों तक। सब साथ बैठेंगे।')],
            [Sunrise, t('Pick day & session', 'दिन व सत्र चुनें'), t('See live seats left. Choose one or many days.', 'शेष आसन लाइव देखें। एक या अनेक दिन चुनें।')],
            [QrCode, t('Get your QR pass', 'QR प्रवेश पत्र पाएँ'), t('Download as PDF. Show it at the gate.', 'PDF डाउनलोड करें। द्वार पर दिखाएँ।')],
          ].map(([Icon, h, p], i) => (
            <Reveal key={h} delay={i * .1} className="group relative rounded-3xl bg-white p-6 border border-maroon-100 hover:border-saffron-400 hover:-translate-y-1 transition shadow-sm hover:shadow-xl">
              <span className="absolute top-4 right-5 font-display text-5xl text-maroon-100 group-hover:text-saffron-100 transition">{i + 1}</span>
              <span className="grid place-items-center size-14 rounded-2xl bg-gradient-to-br from-saffron-400 to-maroon-700 text-white shadow-lg"><Icon size={26} /></span>
              <h3 className="mt-5 text-lg font-bold text-maroon-900">{h}</h3>
              <p className="mt-1.5 text-sm text-stone-600 leading-relaxed">{p}</p>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ASSURANCE + SCHEDULE */}
      <section className="mx-auto max-w-6xl px-4 mt-20 grid gap-5 md:grid-cols-2">
        <Reveal className="relative overflow-hidden rounded-[2rem] bg-gradient-to-br from-maroon-800 to-maroon-950 p-8 text-white">
          <Mandala className="absolute -right-24 -bottom-24 w-72 opacity-20 spin-slow" rings={3} />
          <Sparkles className="text-gold-400" />
          <h3 className="font-display text-3xl mt-3 gold-text">{t('Akhand Parivar Guarantee', 'अखंड परिवार गारंटी')}</h3>
          <p className="mt-3 text-maroon-100 leading-relaxed">{t('Every member of your family is seated together at the same kund. Our smart seating fills partly used kunds first, so no seat goes empty.', 'आपके परिवार के सभी सदस्य एक ही कुंड पर साथ बैठेंगे। स्मार्ट व्यवस्था पहले आंशिक भरे कुंड भरती है, ताकि कोई आसन खाली न रहे।')}</p>
          <div className="mt-6 flex gap-1.5">
            {Array.from({ length: 8 }, (_, i) => (
              <motion.span key={i} initial={{ scale: 0 }} whileInView={{ scale: 1 }} viewport={{ once: true }} transition={{ delay: i * .08, type: 'spring' }} className={`size-8 rounded-full grid place-items-center text-xs font-bold ${i < 5 ? 'bg-gold-400 text-maroon-950' : 'bg-white/15 text-white/60 border border-white/20'}`}>{i < 5 ? '●' : ''}</motion.span>
            ))}
          </div>
          <p className="mt-2 text-xs text-maroon-200">{t('Family of 5 → the 3 left-over seats go to the next family.', '5 सदस्यों का परिवार → शेष 3 आसन अगले परिवार को।')}</p>
        </Reveal>
        <Reveal delay={.1} className="rounded-[2rem] bg-white border border-gold-300/70 p-8">
          <h3 className="font-display text-3xl text-maroon-900">{t('Daily sessions', 'प्रतिदिन सत्र')}</h3>
          <div className="mt-5 space-y-3">
            {[['morning', Sunrise, 'from-saffron-100 to-gold-300/40'], ['afternoon', Sunset, 'from-maroon-100 to-saffron-100']].map(([k, Icon, bg]) => (
              <div key={k} className={`flex items-center gap-4 rounded-2xl bg-gradient-to-r ${bg} p-4`}>
                <Icon size={30} className="text-maroon-800" />
                <div>
                  <div className="font-bold text-maroon-900">{t(EVENT.sessions[k].en, EVENT.sessions[k].hi)}</div>
                  <div className="text-sm text-stone-700">{fmtTime(EVENT.sessions[k].start)} – {fmtTime(EVENT.sessions[k].end)}</div>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-4 text-sm text-stone-600 flex gap-2"><ShieldCheck size={18} className="text-emerald-600 shrink-0" />{t('Your QR opens only in your booked session. Entry is marked automatically.', 'आपका QR केवल आपके चुने सत्र में मान्य है। प्रवेश स्वतः दर्ज होता है।')}</p>
        </Reveal>
      </section>

      {/* FAQ */}
      <section className="mx-auto max-w-3xl px-4 mt-20">
        <Reveal className="text-center">
          <h2 className="font-display text-3xl md:text-5xl text-maroon-900">{t('Good to know', 'जानने योग्य बातें')}</h2>
          <Divider className="mt-3" />
        </Reveal>
        <div className="mt-8 space-y-3">
          {faqs.map(([q, a]) => (
            <details key={q} className="group rounded-2xl bg-white border border-maroon-100 open:border-saffron-400 open:shadow-lg transition">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-5 font-bold text-maroon-900">
                {q}<ChevronDown className="shrink-0 transition group-open:rotate-180 text-saffron-600" />
              </summary>
              <p className="px-5 pb-5 text-stone-600 leading-relaxed">{a}</p>
            </details>
          ))}
        </div>
        <Reveal className="mt-10 text-center">
          <Btn as={Link} to="/register" className="text-lg min-h-14 px-10"><Flame size={20} /> {t('Begin registration', 'पंजीकरण आरंभ करें')}</Btn>
        </Reveal>
      </section>
    </div>
  )
}
