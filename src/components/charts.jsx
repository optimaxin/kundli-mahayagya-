// Small dependency-free SVG charts. Colours are passed in so the dashboard owns the palette.

export const PAL = { maroon: '#7a1a2d', saffron: '#f47b20', gold: '#c99a2e', emerald: '#059669', sky: '#0284c7', slate: '#94a3b8', rose: '#e11d48' }

const nice = (m) => { if (m <= 5) return 5; const p = 10 ** Math.floor(Math.log10(m)); const f = m / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p }

export function StackedBars({ data, keys, colors, height = 240, fmt = (v) => v }) {
  // data: [{label, a:..,b:..}] keys: ['a','b']
  const W = 640, H = height, L = 40, B = 28, T = 10
  const max = nice(Math.max(1, ...data.map((d) => keys.reduce((s, k) => s + d[k], 0))))
  const bw = (W - L) / data.length
  const y = (v) => T + (H - T - B) * (1 - v / max)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img">
      {[0, .25, .5, .75, 1].map((p) => (
        <g key={p}><line x1={L} x2={W} y1={y(max * p)} y2={y(max * p)} stroke="#e2e8f0" strokeDasharray={p ? '3 4' : ''} /><text x={L - 6} y={y(max * p) + 4} textAnchor="end" fontSize="15" fill="#94a3b8">{fmt(Math.round(max * p))}</text></g>
      ))}
      {data.map((d, i) => {
        let acc = 0
        return (
          <g key={i}>
            {keys.map((k, j) => {
              const h = (d[k] / max) * (H - T - B), yy = y(acc) - h; acc += d[k]
              return h > 0 ? <rect key={k} x={L + i * bw + bw * .2} y={yy} width={bw * .6} height={h} rx={j === keys.length - 1 ? 6 : 0} fill={colors[j]}><title>{`${d.label} · ${k}: ${d[k]}`}</title></rect> : null
            })}
            <text x={L + i * bw + bw / 2} y={H - 9} textAnchor="middle" fontSize="15" fill="#64748b">{d.label}</text>
          </g>
        )
      })}
    </svg>
  )
}

export function Area({ data, color = PAL.maroon, height = 200 }) {
  const W = 640, H = height, L = 34, B = 26, T = 10
  const max = nice(Math.max(1, ...data.map((d) => d.n)))
  const x = (i) => L + (i * (W - L - 8)) / (data.length - 1)
  const y = (v) => T + (H - T - B) * (1 - v / max)
  const line = data.map((d, i) => `${i ? 'L' : 'M'}${x(i)},${y(d.n)}`).join(' ')
  const id = 'g' + color.slice(1)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      <defs><linearGradient id={id} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".35" /><stop offset="1" stopColor={color} stopOpacity="0" /></linearGradient></defs>
      {[0, .5, 1].map((p) => <g key={p}><line x1={L} x2={W} y1={y(max * p)} y2={y(max * p)} stroke="#e2e8f0" strokeDasharray="3 4" /><text x={L - 6} y={y(max * p) + 4} textAnchor="end" fontSize="15" fill="#94a3b8">{Math.round(max * p)}</text></g>)}
      <path d={`${line} L${x(data.length - 1)},${H - B} L${x(0)},${H - B} Z`} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
      {data.map((d, i) => <circle key={i} cx={x(i)} cy={y(d.n)} r="3.5" fill="#fff" stroke={color} strokeWidth="2"><title>{`${d.date}: ${d.n}`}</title></circle>)}
      {data.map((d, i) => (i % 2 === 0 ? <text key={i} x={x(i)} y={H - 8} textAnchor="middle" fontSize="14" fill="#94a3b8">{d.date.slice(8)}/{d.date.slice(5, 7)}</text> : null))}
    </svg>
  )
}

export function Donut({ parts, size = 170, thick = 22, center, sub }) {
  // parts: [{v, c, l}]
  const total = parts.reduce((s, p) => s + p.v, 0) || 1
  const r = (size - thick) / 2, C = 2 * Math.PI * r
  let off = 0
  return (
    <div className="relative mx-auto" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#f1f5f9" strokeWidth={thick} />
        {parts.map((p, i) => {
          const len = (p.v / total) * C
          const el = <circle key={i} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={p.c} strokeWidth={thick} strokeDasharray={`${Math.max(0, len - 2)} ${C}`} strokeDashoffset={-off} strokeLinecap="round"><title>{`${p.l}: ${p.v}`}</title></circle>
          off += len
          return el
        })}
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center"><div><div className="text-2xl font-bold text-slate-900 tabular-nums">{center}</div>{sub && <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{sub}</div>}</div></div>
    </div>
  )
}

export function HBars({ rows, color = PAL.maroon }) {
  const max = Math.max(1, ...rows.map((r) => r[1]))
  if (!rows.length) return <p className="py-6 text-center text-sm text-slate-400">—</p>
  return (
    <div className="space-y-3">
      {rows.map(([l, v]) => (
        <div key={l}>
          <div className="mb-1 flex justify-between text-xs font-semibold text-slate-600"><span className="truncate">{l}</span><span className="tabular-nums text-slate-900">{v.toLocaleString('en-IN')}</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full" style={{ width: `${(v / max) * 100}%`, background: color }} /></div>
        </div>
      ))}
    </div>
  )
}

export function Columns({ rows, color = PAL.saffron, height = 150 }) {
  const max = Math.max(1, ...rows.map((r) => r[1]))
  return (
    <div className="flex items-end gap-2" style={{ height }}>
      {rows.map(([l, v]) => (
        <div key={l} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
          <span className="text-[11px] font-bold tabular-nums text-slate-700">{v || ''}</span>
          <div className="w-full rounded-t-lg" style={{ height: `${(v / max) * 78}%`, minHeight: v ? 3 : 0, background: color }} title={`${l}: ${v}`} />
          <span className="text-[11px] text-slate-500">{l}</span>
        </div>
      ))}
    </div>
  )
}

export function Heat({ rows, cols, get }) {
  // get(row, col) -> 0..100
  const shade = (p) => `rgba(122,26,45,${.08 + (p / 100) * .85})`
  return (
    <div className="grid gap-1.5" style={{ gridTemplateColumns: `64px repeat(${cols.length}, 1fr)` }}>
      <span />
      {cols.map((c) => <span key={c} className="text-center text-[11px] font-bold text-slate-500">{c}</span>)}
      {rows.map((r) => (
        <div key={r} className="contents">
          <span className="self-center text-xs font-bold text-slate-600">{r}</span>
          {cols.map((c) => { const p = get(r, c); return <div key={c} className="grid h-10 place-items-center rounded-lg text-xs font-bold tabular-nums" style={{ background: shade(p), color: p > 45 ? '#fff' : '#7a1a2d' }} title={`${p}%`}>{p}%</div> })}
        </div>
      ))}
    </div>
  )
}
