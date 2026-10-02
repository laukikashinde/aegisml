import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, RefreshCw, Search, Trash2 } from 'lucide-react'
import { api, IncidentSummary } from '../services/api'
import StatusBadge from '../components/StatusBadge'
import { format, parseISO, isValid } from 'date-fns'

function fmtTime(ts: string): string {
  try {
    const d = parseISO(ts)
    if (!isValid(d)) return '—'
    return format(d, 'MMM d HH:mm')
  } catch { return '—' }
}

const TYPE_COLORS: Record<string, string> = {
  DATA_DRIFT:        'bg-violet-100 text-violet-700',
  DATA_QUALITY:      'bg-amber-100 text-amber-700',
  MODEL_DEGRADATION: 'bg-rose-100 text-rose-700',
  LATENCY:           'bg-sky-100 text-sky-700',
  PIPELINE_FAILURE:  'bg-orange-100 text-orange-700',
  DEPLOYMENT_FAILURE:'bg-red-100 text-red-700',
  UNKNOWN:           'bg-slate-100 text-slate-600',
}

const SEVERITY_BORDER: Record<string, string> = {
  CRITICAL: 'border-l-rose-500',
  HIGH:     'border-l-orange-400',
  MEDIUM:   'border-l-amber-400',
  LOW:      'border-l-blue-400',
}

export default function Incidents() {
  const [incidents, setIncidents] = useState<IncidentSummary[]>([])
  const [loading, setLoading]     = useState(true)
  const [search, setSearch]       = useState('')
  const [filter, setFilter]       = useState('')

  const load = async () => {
    setLoading(true)
    try { setIncidents(await api.getIncidents()) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const filtered = incidents.filter(i => {
    const matchSearch = !search || i.title.toLowerCase().includes(search.toLowerCase())
    const matchFilter = !filter ||
      i.status === filter || i.severity === filter || i.incident_type === filter
    return matchSearch && matchFilter
  })

  const filters = [
    { label: 'All',         value: '' },
    { label: 'Active',      value: 'DETECTED' },
    { label: 'Resolved',    value: 'RESOLVED' },
    { label: 'High',        value: 'HIGH' },
    { label: 'Drift',       value: 'DATA_DRIFT' },
    { label: 'Degradation', value: 'MODEL_DEGRADATION' },
  ]

  return (
    <div className="p-7 space-y-5 max-w-6xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title">Incidents</h1>
          <p className="page-subtitle">{incidents.length} total · {incidents.filter(i => !['RESOLVED','ROLLED_BACK','FAILED'].includes(i.status)).length} active</p>
        </div>
        <button onClick={load} className="btn-ghost text-xs">
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Search + filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 max-w-xs">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search incidents…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-8 pr-3 py-2 text-sm bg-white border border-slate-200 rounded-xl
                       text-slate-700 placeholder:text-slate-400 focus:outline-none focus:border-violet-400"
          />
        </div>
        <div className="flex gap-1.5">
          {filters.map(f => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={`px-3 py-1.5 text-xs font-medium rounded-xl transition-colors ${
                filter === f.value
                  ? 'bg-violet-600 text-white'
                  : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="text-sm text-slate-400 py-8 text-center">Loading…</div>
      ) : (
        <div className="space-y-2">
          {filtered.length === 0 ? (
            <div className="card text-center py-12">
              <AlertTriangle className="w-8 h-8 text-slate-300 mx-auto mb-2" />
              <p className="text-slate-500 text-sm">No incidents found.</p>
            </div>
          ) : (
            filtered.map(i => (
              <Link
                key={i.id}
                to={`/incidents/${i.id}`}
                className={`block bg-white border border-slate-200 border-l-4 rounded-2xl p-4
                           hover:shadow-card-hover transition-shadow ${SEVERITY_BORDER[i.severity] || 'border-l-slate-300'}`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-1.5">
                      {i.is_simulation && (
                        <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-violet-100 text-violet-600">SIM</span>
                      )}
                      <span className={`px-2.5 py-0.5 text-[10px] font-semibold rounded-full ${TYPE_COLORS[i.incident_type] || 'bg-slate-100 text-slate-600'}`}>
                        {i.incident_type.replace('_', ' ')}
                      </span>
                    </div>
                    <p className="text-sm font-semibold text-slate-800 truncate">
                      {i.title.replace('[SIMULATION] ', '')}
                    </p>
                    <p className="text-xs text-slate-400 mt-1 font-mono">
                      {fmtTime(i.created_at)}
                      {i.affected_model && <span className="ml-3">{i.affected_model}</span>}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <StatusBadge value={i.severity} type="severity" />
                    <StatusBadge value={i.status} />
                  </div>
                </div>
              </Link>
            ))
          )}
        </div>
      )}
    </div>
  )
}
