import React, { useEffect, useState } from 'react'
import { api, Approval } from '../services/api'
import StatusBadge from '../components/StatusBadge'
import { CheckCircle, XCircle, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { format } from 'date-fns'

export default function Approvals() {
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [loading, setLoading]     = useState(true)
  const [acting, setActing]       = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try { setApprovals(await api.getApprovals()) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const decide = async (a: Approval, approve: boolean) => {
    setActing(a.id)
    try {
      approve ? await api.approve(a.id, 'operator') : await api.reject(a.id, 'operator', 'Rejected')
      await load()
    } finally { setActing(null) }
  }

  const pending = approvals.filter(a => a.status === 'PENDING')
  const history = approvals.filter(a => a.status !== 'PENDING')

  return (
    <div className="p-7 space-y-5 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title">Approvals</h1>
          <p className="page-subtitle">Human-in-the-loop decisions</p>
        </div>
        <button onClick={load} className="btn-ghost text-xs"><RefreshCw className="w-3.5 h-3.5" /></button>
      </div>

      {/* Pending */}
      <div>
        <p className="section-title">Pending ({pending.length})</p>
        {loading ? <div className="text-sm text-slate-400">Loading…</div>
         : pending.length === 0 ? (
          <div className="card text-center py-10">
            <CheckCircle className="w-8 h-8 text-emerald-300 mx-auto mb-2" />
            <p className="text-slate-500 text-sm">No pending approvals.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {pending.map(a => (
              <div key={a.id} className="card border-l-4 border-l-amber-400 bg-amber-50/20">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 flex-wrap mb-2">
                      <span className="pill-yellow">PENDING</span>
                      <StatusBadge value={a.risk_level} type="severity" />
                      <span className="px-2.5 py-0.5 text-xs font-bold rounded-lg bg-violet-100 text-violet-700 font-mono">
                        {a.action_type}
                      </span>
                    </div>
                    <p className="text-sm text-slate-700">{a.description}</p>
                    <div className="flex items-center gap-3 mt-2">
                      <Link to={`/incidents/${a.incident_id}`}
                            className="text-xs text-violet-600 hover:text-violet-700 font-medium">
                        View Incident →
                      </Link>
                      <span className="text-xs text-slate-400">
                        Requested {format(new Date(a.created_at), 'MMM d HH:mm')}
                      </span>
                    </div>
                    {a.context && (
                      <details className="mt-2">
                        <summary className="text-xs text-slate-400 cursor-pointer">context</summary>
                        <pre className="text-xs text-slate-500 bg-slate-50 rounded-lg p-2 mt-1 border border-slate-200 overflow-x-auto">
                          {JSON.stringify(a.context, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                  <div className="flex gap-2 flex-shrink-0">
                    <button onClick={() => decide(a, true)} disabled={acting === a.id} className="btn-success text-xs">
                      <CheckCircle className="w-3.5 h-3.5" /> Approve
                    </button>
                    <button onClick={() => decide(a, false)} disabled={acting === a.id} className="btn-danger text-xs">
                      <XCircle className="w-3.5 h-3.5" /> Reject
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* History */}
      {history.length > 0 && (
        <div>
          <p className="section-title">History ({history.length})</p>
          <div className="card overflow-hidden p-0">
            <table className="data-table">
              <thead>
                <tr>{['Action', 'Risk', 'Status', 'Decided By', 'Date'].map(h => <th key={h}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {history.map(a => (
                  <tr key={a.id}>
                    <td className="font-mono text-xs text-violet-700 font-semibold">{a.action_type}</td>
                    <td><StatusBadge value={a.risk_level} type="severity" /></td>
                    <td><StatusBadge value={a.status} /></td>
                    <td className="text-sm text-slate-600">{a.decided_by || '—'}</td>
                    <td className="text-xs text-slate-500 font-mono">{format(new Date(a.created_at), 'MMM d HH:mm')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
