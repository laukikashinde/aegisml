import React from 'react'
import clsx from 'clsx'
import type { LucideIcon } from 'lucide-react'

interface Props {
  label: string
  value: string | number
  sub?: string
  icon?: LucideIcon
  color?: 'default' | 'purple' | 'green' | 'amber' | 'rose' | 'blue' | 'sky'
  className?: string
}

const COLOR_MAP = {
  default: { bg: 'bg-white border border-slate-200',       icon: 'text-slate-400', val: 'text-slate-800' },
  purple:  { bg: 'bg-violet-50 border border-violet-200',  icon: 'text-violet-500', val: 'text-violet-800' },
  green:   { bg: 'bg-emerald-50 border border-emerald-200', icon: 'text-emerald-500', val: 'text-emerald-800' },
  amber:   { bg: 'bg-amber-50 border border-amber-200',    icon: 'text-amber-500', val: 'text-amber-800' },
  rose:    { bg: 'bg-rose-50 border border-rose-200',      icon: 'text-rose-500',  val: 'text-rose-800' },
  blue:    { bg: 'bg-blue-50 border border-blue-200',      icon: 'text-blue-500',  val: 'text-blue-800' },
  sky:     { bg: 'bg-sky-50 border border-sky-200',        icon: 'text-sky-500',   val: 'text-sky-800' },
}

export default function MetricCard({ label, value, sub, icon: Icon, color = 'default', className }: Props) {
  const c = COLOR_MAP[color]
  return (
    <div className={clsx('rounded-2xl p-5 shadow-card', c.bg, className)}>
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className={clsx('text-xs font-medium uppercase tracking-wider', c.icon)}>{label}</p>
          <p className={clsx('text-2xl font-bold mt-1 tabular-nums', c.val)}>{value}</p>
          {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
        </div>
        {Icon && <Icon className={clsx('w-5 h-5 mt-0.5 flex-shrink-0', c.icon)} />}
      </div>
    </div>
  )
}
