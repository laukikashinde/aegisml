import React from 'react'
import { format } from 'date-fns'
import type { TimelineEvent } from '../services/api'
import clsx from 'clsx'

const EVENT_COLORS: Record<string, string> = {
  INCIDENT_CREATED:              'bg-amber-400',
  STATUS_CHANGED_INVESTIGATING:  'bg-blue-400',
  STATUS_CHANGED_DIAGNOSED:      'bg-violet-400',
  DIAGNOSIS_COMPLETE:            'bg-violet-500',
  POLICY_EVALUATED:              'bg-sky-400',
  RETRAINING_STARTED:            'bg-blue-300',
  RETRAINING_COMPLETED:          'bg-blue-500',
  QUALITY_GATES_EVALUATED:       'bg-teal-400',
  CANARY_STARTED:                'bg-amber-500',
  CANARY_TRAFFIC_ADVANCED:       'bg-amber-400',
  DEPLOYMENT_COMPLETED:          'bg-emerald-500',
  STATUS_CHANGED_RESOLVED:       'bg-emerald-400',
  STATUS_CHANGED_ROLLED_BACK:    'bg-orange-400',
  ROLLBACK_EXECUTED:             'bg-orange-500',
  STATUS_CHANGED_FAILED:         'bg-rose-500',
  STATUS_CHANGED_REMEDIATING:    'bg-sky-500',
  DEFAULT:                       'bg-slate-300',
}

export default function IncidentTimeline({ events }: { events: TimelineEvent[] }) {
  if (!events.length) {
    return <p className="text-sm text-slate-400 py-4 text-center">No events yet.</p>
  }
  return (
    <div className="space-y-0">
      {events.map((ev, idx) => {
        const dot = EVENT_COLORS[ev.event_type] || EVENT_COLORS.DEFAULT
        return (
          <div key={ev.id} className="flex gap-3">
            <div className="flex flex-col items-center">
              <div className={clsx('w-2.5 h-2.5 rounded-full flex-shrink-0 mt-1.5', dot)} />
              {idx < events.length - 1 && <div className="w-px flex-1 bg-slate-200 my-1" />}
            </div>
            <div className="pb-3 flex-1 min-w-0">
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="text-[10px] font-mono text-slate-400">
                  {format(new Date(ev.occurred_at), 'HH:mm:ss')}
                </span>
                <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                  {ev.event_type}
                </span>
              </div>
              <p className="text-sm text-slate-700 mt-0.5 leading-snug">{ev.description}</p>
              {ev.details && Object.keys(ev.details).length > 0 && (
                <details className="mt-1">
                  <summary className="text-xs text-slate-400 cursor-pointer hover:text-slate-600">details</summary>
                  <pre className="text-xs text-slate-500 bg-slate-50 rounded-lg p-2 mt-1 overflow-x-auto border border-slate-200">
                    {JSON.stringify(ev.details, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
