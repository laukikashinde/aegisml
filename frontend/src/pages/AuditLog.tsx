import React, { useEffect, useState } from 'react'
import { api, AuditEntry } from '../services/api'
import { ScrollText, RefreshCw, Search } from 'lucide-react'
import { format } from 'date-fns'

const OUTCOME_STYLE: Record<string, string> = {
  SUCCESS:          'pill-green',
  FAILURE:          'pill-red',
  APPROVED:         'pill-green',
  DENIED:           'pill-red',
  REQUIRES_APPROVAL:'pill-yellow',
}

export default function AuditLog() {
  const [logs, setLogs]     = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  const load = async () => {
    setLoading(true)
    try { setLogs(await api.getAuditLogs({ limit: 200 })) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const filtered = search
    ? logs.filter(l =>
        l.description.toLowerCase().includes(search.toLowerCase()) ||
        l.event_type.toLowerCase().includes(search.toLowerCase()) ||
        l.actor.toLowerCase().includes(search.toLowerCase()))
    : logs

  return (
    <div className="p-7 space-y-4 max-w-6xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <ScrollText className="w-6 h-6 text-violet-500" /> Audit Log
          </h1>
          <p className="page-subtitle text-slate-400 text-xs mt-0.5 italic">
            Immutable record — entries cannot be modified or deleted through this interface.
          </p>
        </div>
        <button onClick={load} className="btn-ghost text-xs"><RefreshCw className="w-3.5 h-3.5" /></button>
      </div>

      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search events, actors, descriptions…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-8 pr-3 py-2 text-sm bg-white border border-slate-200 rounded-xl
                       placeholder:text-slate-400 focus:outline-none focus:border-violet-400"
          />
        </div>
        <span className="text-xs text-slate-400">{filtered.length} entries</span>
      </div>

      {loading ? (
        <div className="text-sm text-slate-400 py-8 text-center">Loading…</div>
      ) : (
        <div className="card overflow-hidden p-0">
          <table className="data-table">
            <thead>
              <tr>
                {['Time', 'Event', 'Actor', 'Description', 'Outcome'].map(h => <th key={h}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {filtered.map(l => (
                <tr key={l.id}>
                  <td className="font-mono text-[11px] text-slate-500 whitespace-nowrap">
                    {format(new Date(l.occurred_at), 'MMM d HH:mm:ss')}
                  </td>
                  <td>
                    <span className="text-[11px] font-mono text-violet-600 font-semibold">{l.event_type}</span>
                  </td>
                  <td className="text-xs text-slate-500">{l.actor}</td>
                  <td className="text-sm text-slate-700 max-w-md truncate">{l.description}</td>
                  <td>
                    {l.outcome ? (
                      <span className={OUTCOME_STYLE[l.outcome] || 'pill-gray'}>{l.outcome}</span>
                    ) : <span className="text-slate-400 text-xs">—</span>}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={5} className="text-center text-slate-400 py-8 text-sm">No audit log entries.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
