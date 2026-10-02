import React, { useEffect, useState } from 'react'
import { api } from '../services/api'
import { Activity, RefreshCw } from 'lucide-react'
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { format } from 'date-fns'

const fmt = (ts: unknown) => { try { return format(new Date(ts as string), 'HH:mm') } catch { return '' } }

export default function Monitoring() {
  const [perf, setPerf]   = useState<any[]>([])
  const [drift, setDrift] = useState<any[]>([])
  const [snap, setSnap]   = useState<any>(null)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const [p, d, s] = await Promise.all([
        api.getPerformance(), api.getDrift(), api.getLatestSnapshot(),
      ])
      setPerf((p as any[]).slice(0, 30).reverse())
      setDrift((d as any[]).slice(0, 20).reverse())
      setSnap(s)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  return (
    <div className="p-7 space-y-5 max-w-6xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2"><Activity className="w-6 h-6 text-violet-500" />Monitoring</h1>
          <p className="page-subtitle">Evidently drift detection · XGBoost performance tracking</p>
        </div>
        <button onClick={load} className="btn-ghost text-xs"><RefreshCw className="w-3.5 h-3.5" /></button>
      </div>

      {/* Latest snapshot cards */}
      {snap && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'F1 Score',     val: snap.f1_score?.toFixed(4) ?? '—',   color: (snap.f1_score ?? 0) >= 0.35 ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-rose-50 border-rose-200 text-rose-700' },
            { label: 'Drift Score',  val: snap.drift_score?.toFixed(3) ?? '—', color: snap.drift_detected ? 'bg-amber-50 border-amber-200 text-amber-700' : 'bg-slate-50 border-slate-200 text-slate-600' },
            { label: 'Avg Latency',  val: snap.avg_latency_ms != null ? `${snap.avg_latency_ms.toFixed(1)}ms` : '—', color: 'bg-sky-50 border-sky-200 text-sky-700' },
            { label: 'Data Quality', val: snap.data_quality_status ?? '—',    color: snap.data_quality_status === 'PASSED' ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-rose-50 border-rose-200 text-rose-700' },
          ].map(c => (
            <div key={c.label} className={`rounded-2xl border p-4 ${c.color}`}>
              <p className="text-xs font-medium opacity-70 uppercase tracking-wider">{c.label}</p>
              <p className="text-xl font-bold mt-1">{c.val}</p>
            </div>
          ))}
        </div>
      )}

      {loading ? <div className="text-sm text-slate-400">Loading…</div> : (
        <>
          {/* F1 over time */}
          <div className="card">
            <div className="flex items-center justify-between mb-4">
              <div>
                <p className="card-title">F1 Score History</p>
                <p className="text-xs text-slate-400">XGBoost performance on Adult Income dataset</p>
              </div>
              <span className="text-xs bg-amber-100 text-amber-700 px-2.5 py-1 rounded-full font-medium">
                Threshold: 0.35
              </span>
            </div>
            {perf.length === 0 ? (
              <div className="h-48 flex items-center justify-center text-slate-400 text-sm bg-slate-50 rounded-xl">
                No performance data yet.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={perf} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="perfGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#8b5cf6" stopOpacity={0.15} />
                      <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="timestamp" tickFormatter={fmt} tick={{ fill: '#94a3b8', fontSize: 10 }}
                         axisLine={false} tickLine={false} />
                  <YAxis domain={[0, 1]} tick={{ fill: '#94a3b8', fontSize: 10 }}
                         axisLine={false} tickLine={false} tickFormatter={(v: number) => v.toFixed(1)} />
                  <Tooltip contentStyle={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: 12, fontSize: 12 }}
                           formatter={(v: number | string) => [typeof v === 'number' ? v.toFixed(4) : String(v), 'F1']} />
                  <ReferenceLine y={0.35} stroke="#f59e0b" strokeDasharray="4 4"
                                 label={{ value: 'threshold', fill: '#f59e0b', fontSize: 10 }} />
                  <Area type="monotone" dataKey="f1_score" name="F1"
                        stroke="#8b5cf6" strokeWidth={2} fill="url(#perfGrad)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Drift score + latency side by side */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* Drift */}
            <div className="card">
              <p className="card-title mb-1">Drift Score</p>
              <p className="text-xs text-slate-400 mb-3">Evidently KS/TVD detection · threshold 0.20</p>
              {drift.length === 0 ? (
                <div className="h-36 flex items-center justify-center text-slate-400 text-sm bg-slate-50 rounded-xl">
                  No drift data yet.
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={150}>
                  <AreaChart data={drift} margin={{ top: 5, right: 10, left: -25, bottom: 0 }}>
                    <defs>
                      <linearGradient id="driftGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%"  stopColor="#f59e0b" stopOpacity={0.2} />
                        <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="timestamp" tickFormatter={fmt} tick={{ fill: '#94a3b8', fontSize: 10 }}
                           axisLine={false} tickLine={false} />
                    <YAxis domain={[0, 0.6]} tick={{ fill: '#94a3b8', fontSize: 10 }}
                           axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: 12, fontSize: 12 }}
                             formatter={(v: number | string) => [typeof v === 'number' ? v.toFixed(4) : String(v), 'Drift']} />
                    <ReferenceLine y={0.20} stroke="#f59e0b" strokeDasharray="4 4" />
                    <Area type="monotone" dataKey="drift_score" name="Drift"
                          stroke="#f59e0b" strokeWidth={2} fill="url(#driftGrad)" dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>

            {/* Latency */}
            <div className="card">
              <p className="card-title mb-1">Inference Latency</p>
              <p className="text-xs text-slate-400 mb-3">Per-sample average · SLA 200ms</p>
              {perf.length === 0 ? (
                <div className="h-36 flex items-center justify-center text-slate-400 text-sm bg-slate-50 rounded-xl">
                  No latency data yet.
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={150}>
                  <LineChart data={perf} margin={{ top: 5, right: 10, left: -25, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="timestamp" tickFormatter={fmt} tick={{ fill: '#94a3b8', fontSize: 10 }}
                           axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: 12, fontSize: 12 }}
                             formatter={(v: number | string) => [typeof v === 'number' ? `${v.toFixed(2)}ms` : String(v), 'Latency']} />
                    <ReferenceLine y={200} stroke="#f59e0b" strokeDasharray="4 4" />
                    <Line type="monotone" dataKey="avg_latency_ms" name="Latency"
                          stroke="#34d399" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* Drift history table */}
          {drift.length > 0 && (
            <div className="card overflow-hidden p-0">
              <div className="px-5 py-3 border-b border-slate-100">
                <p className="card-title">Drift Event History</p>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    {['Time', 'Detected', 'Score', 'Features'].map(h => <th key={h}>{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {drift.slice().reverse().map((d, i) => (
                    <tr key={i}>
                      <td className="font-mono text-xs text-slate-500">
                        {d.timestamp ? format(new Date(d.timestamp), 'MMM d HH:mm:ss') : '—'}
                      </td>
                      <td>
                        {d.drift_detected
                          ? <span className="pill-yellow">YES</span>
                          : <span className="pill-green">NO</span>}
                      </td>
                      <td className="font-mono text-sm font-semibold text-slate-700">
                        {d.drift_score?.toFixed(4) ?? '—'}
                      </td>
                      <td className="text-xs text-slate-500">
                        {Array.isArray(d.drifted_features) && d.drifted_features.length > 0
                          ? d.drifted_features.join(', ')
                          : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
