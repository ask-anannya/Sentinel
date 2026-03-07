import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { Shield, AlertTriangle, BookOpen, LayoutDashboard } from 'lucide-react'
import Dashboard from './pages/Dashboard.jsx'
import Violations from './pages/Violations.jsx'
import AuditTrail from './pages/AuditTrail.jsx'

function Sidebar() {
  const navItems = [
    { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
    { to: '/violations', label: 'Violations', icon: AlertTriangle },
    { to: '/audit-trail', label: 'Audit Trail', icon: BookOpen },
  ]

  return (
    <aside className="w-60 min-h-screen bg-slate-900 border-r border-slate-700 flex flex-col">
      {/* Branding */}
      <div className="px-6 py-5 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <Shield className="text-blue-400" size={22} />
          <span className="text-white font-bold text-lg tracking-tight">Sentinel</span>
        </div>
        <p className="text-slate-400 text-xs mt-1">Compliance Monitoring</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-slate-700">
        <p className="text-slate-500 text-xs">Powered by Amazon Nova Act</p>
        <p className="text-slate-600 text-xs">Nova 2 Lite · SOC2 · HIPAA · GDPR</p>
      </div>
    </aside>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex min-h-screen bg-slate-950 text-white">
        <Sidebar />
        <main className="flex-1 overflow-auto">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/violations" element={<Violations />} />
            <Route path="/audit-trail" element={<AuditTrail />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
