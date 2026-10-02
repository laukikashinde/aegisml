import React from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, AlertTriangle, Brain, Activity,
  Rocket, GitBranch, CheckSquare, ScrollText,
  FlaskConical, BarChart3, Shield,
} from 'lucide-react'
import clsx from 'clsx'

const nav = [
  { to: '/',            label: 'Overview',    icon: LayoutDashboard },
  { to: '/incidents',   label: 'Incidents',   icon: AlertTriangle },
  { to: '/models',      label: 'Models',      icon: Brain },
  { to: '/monitoring',  label: 'Monitoring',  icon: Activity },
  { to: '/deployments', label: 'Deployments', icon: Rocket },
  { to: '/pipelines',   label: 'Pipelines',   icon: GitBranch },
  { to: '/approvals',   label: 'Approvals',   icon: CheckSquare },
  { to: '/experiments', label: 'Experiments', icon: BarChart3 },
  { to: '/simulations', label: 'Simulate',    icon: FlaskConical },
  { to: '/audit',       label: 'Audit Log',   icon: ScrollText },
]

export default function Sidebar() {
  return (
    <aside className="w-52 bg-white border-r border-slate-200 flex flex-col h-screen sticky top-0 shadow-sm">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-slate-100">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-gradient-to-br from-violet-500 to-purple-600 rounded-xl flex items-center justify-center shadow-sm">
            <Shield className="w-4 h-4 text-white" />
          </div>
          <div>
            <div className="text-sm font-bold text-slate-800 leading-none">AegisML</div>
            <div className="text-[10px] text-slate-400 mt-0.5">Self-Healing MLOps</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        {nav.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm transition-all duration-100',
                isActive
                  ? 'bg-violet-50 text-violet-700 font-semibold'
                  : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50 font-medium'
              )
            }
          >
            <Icon className="w-4 h-4 flex-shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-slate-100">
        <div className="text-[10px] text-slate-400 font-mono">v0.1.0-lite</div>
        <div className="text-[10px] text-slate-400 mt-0.5">Adult Income · XGBoost</div>
      </div>
    </aside>
  )
}
