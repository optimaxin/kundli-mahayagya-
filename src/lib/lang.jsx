import { createContext, useContext, useState, useEffect } from 'react'

const Ctx = createContext({ lang: 'hi', setLang() {}, t: (e) => e })

export function LangProvider({ children }) {
  const [lang, setLang] = useState(() => {
    try { return localStorage.getItem('km_lang2') || 'hi' } catch { return 'hi' }
  })
  useEffect(() => {
    try { localStorage.setItem('km_lang2', lang) } catch {}
    document.documentElement.lang = lang
  }, [lang])
  // t(english, hindi): inline bilingual strings, no dictionary to maintain
  const t = (en, hi) => (lang === 'hi' && hi ? hi : en)
  return <Ctx.Provider value={{ lang, setLang, t }}>{children}</Ctx.Provider>
}
export const useLang = () => useContext(Ctx)
