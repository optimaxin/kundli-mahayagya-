import { useEffect, useRef } from 'react'

// Lightweight canvas fireworks (firecracker bursts). Pointer-transparent, stops when unmounted, skipped for reduced-motion.
const COLORS = ['#ffd24a', '#ff8a1f', '#ff4d4d', '#ffffff', '#f2d27a', '#ff6fb5', '#7be0ff']

export default function Fireworks() {
  const ref = useRef(null)
  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    const cv = ref.current, ctx = cv.getContext('2d')
    let W, H, raf, last = 0, next = 0
    const dpr = Math.min(2, window.devicePixelRatio || 1)
    const resize = () => { W = cv.clientWidth; H = cv.clientHeight; cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0) }
    resize(); window.addEventListener('resize', resize)
    const rockets = [], sparks = []
    const launch = () => rockets.push({ x: W * (.15 + Math.random() * .7), y: H, vy: -(H * (.9 + Math.random() * .35)) / 60 * 1, ty: H * (.12 + Math.random() * .35), c: COLORS[Math.floor(Math.random() * COLORS.length)] })
    const burst = (x, y, c) => {
      const n = 70 + Math.floor(Math.random() * 40), two = Math.random() < .4
      for (let i = 0; i < n; i++) {
        const a = (Math.PI * 2 * i) / n, sp = (two && i % 2 ? 2 : 4.2) * (.6 + Math.random() * .6)
        sparks.push({ x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: 1, d: .012 + Math.random() * .01, c: two && i % 2 ? '#fff' : c })
      }
    }
    const tick = (t) => {
      const dt = Math.min(2, (t - last) / 16.7 || 1); last = t
      ctx.globalCompositeOperation = 'destination-out'; ctx.fillStyle = 'rgba(0,0,0,.22)'; ctx.fillRect(0, 0, W, H)
      ctx.globalCompositeOperation = 'lighter'
      if (t > next) { launch(); if (Math.random() < .5) launch(); next = t + 450 + Math.random() * 500 }
      for (let i = rockets.length - 1; i >= 0; i--) {
        const r = rockets[i]; r.y += r.vy * dt
        ctx.fillStyle = r.c; ctx.beginPath(); ctx.arc(r.x, r.y, 2.2, 0, 7); ctx.fill()
        if (r.y <= r.ty) { burst(r.x, r.y, r.c); rockets.splice(i, 1) }
      }
      for (let i = sparks.length - 1; i >= 0; i--) {
        const s = sparks[i]; s.x += s.vx * dt; s.y += s.vy * dt; s.vy += .07 * dt; s.vx *= .985; s.life -= s.d * dt
        if (s.life <= 0) { sparks.splice(i, 1); continue }
        ctx.globalAlpha = Math.max(0, s.life); ctx.fillStyle = s.c; ctx.beginPath(); ctx.arc(s.x, s.y, 1.8 * s.life + .4, 0, 7); ctx.fill()
      }
      ctx.globalAlpha = 1
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', resize) }
  }, [])
  return <canvas ref={ref} className="pointer-events-none absolute inset-0 z-0 size-full" aria-hidden />
}
