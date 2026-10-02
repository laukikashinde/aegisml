import React from 'react'
import clsx from 'clsx'

const SEVERITY: Record<string, string> = {
  LOW:      'bg-blue-100 text-blue-700',
  MEDIUM:   'bg-amber-100 text-amber-700',
  HIGH:     'bg-orange-100 text-orange-700',
  CRITICAL: 'bg-rose-100 text-rose-700',
}

const STATUS: Record<string, string> = {
  DETECTED:          'bg-amber-100 text-amber-700',
  INVESTIGATING:     'bg-blue-100 text-blue-700',
  DIAGNOSED:         'bg-violet-100 text-violet-700',
  AWAITING_APPROVAL: 'bg-purple-100 text-purple-700',
  REMEDIATING:       'bg-sky-100 text-sky-700',
  VERIFYING:         'bg-teal-100 text-teal-700',
  RESOLVED:          'bg-emerald-100 text-emerald-700',
  ROLLED_BACK:       'bg-orange-100 text-orange-700',
  FAILED:            'bg-rose-100 text-rose-700',
  RUNNING:           'bg-blue-100 text-blue-700',
  COMPLETED:         'bg-emerald-100 text-emerald-700',
  CANCELLED:         'bg-slate-100 text-slate-500',
  CANDIDATE:         'bg-violet-100 text-violet-700',
  VALIDATED:         'bg-blue-100 text-blue-700',
  CANARY:            'bg-amber-100 text-amber-700',
  PRODUCTION:        'bg-emerald-100 text-emerald-700',
  REJECTED:          'bg-rose-100 text-rose-700',
  PENDING:           'bg-amber-100 text-amber-700',
  APPROVED:          'bg-emerald-100 text-emerald-700',
  PASSED:            'bg-emerald-100 text-emerald-700',
  WARNING:           'bg-amber-100 text-amber-700',
  ACTIVE:            'bg-emerald-100 text-emerald-700',
}

interface Props {
  value: string
  type?: 'severity' | 'status' | 'generic'
}

export default function StatusBadge({ value, type = 'generic' }: Props) {
  const map = type === 'severity' ? SEVERITY : STATUS
  const cls = map[value] || 'bg-slate-100 text-slate-600'
  return (
    <span className={clsx('inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium', cls)}>
      {value.replace(/_/g, ' ')}
    </span>
  )
}
