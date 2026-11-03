import { Routes, Route, useLocation } from 'react-router-dom'
import { useEffect, lazy, Suspense } from 'react'
import { Navbar, MobileDock, Footer } from './components/ui.jsx'
import Home from './pages/Home.jsx'
import Register from './pages/Register.jsx'
import Ticket from './pages/Ticket.jsx'
import Find from './pages/Find.jsx'
import Staff from './pages/Staff.jsx'
const Admin = lazy(() => import('./pages/Admin.jsx'))

export default function App() {
  const { pathname } = useLocation()
  useEffect(() => { window.scrollTo(0, 0) }, [pathname])
  const admin = pathname.startsWith('/admin') || pathname.startsWith('/staff')
  const reg = pathname.startsWith('/register')
  return (
    <>
      <Navbar />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/register" element={<Register />} />
        <Route path="/ticket/:id" element={<Ticket />} />
        <Route path="/find" element={<Find />} />
        <Route path="/staff" element={<Staff />} />
        <Route path="/admin" element={<Suspense fallback={null}><Admin /></Suspense>} />
      </Routes>
      {!admin && !reg && <Footer />}
      {!admin && !reg && <MobileDock />}
    </>
  )
}
