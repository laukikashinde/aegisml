import React, { useEffect, useState } from 'react'
import { BarChart3, RefreshCw, Play } from 'lucide-react'
import { api } from '../services/api'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend,
} from 'recharts'

const SYSTEM_COLORS = { S0: '#f87171', S1: '#fbbf24', S2: '#34d399' }
const SYSTEM_LABELS = {
  S0: 'No Healing',
  S1: 'Scheduled Retrain',
  S2: 'AegisML-Lite',
}
const SYSTEM_DESCRIPTIONS = {
  S0: 'Detects failures but takes no automated remediation action.',
  S1: 'Retrains on a fixed schedule regardless of failure state.',
  S2: 'Full self-healing: detection → diagnosis → targeted remediation → validation → canary → promote/rollback.',
}

export default function Experiments() {
  const [summary, setSummary] = useState<any>(null)
  const [loading, setLoading]   = useState(true)
  const [running, setRunning]   = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try { setSummary(await api.getExperimentsSummary()) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const runS0 = async (failureType: string) => {
    setRunning(`s0-${failureType}`)
    try {
      await api.runS0(failureType, 45 + Math.random() * 30)
      await load()
    } finally { setRunning(null) }
  }

  const runS1 = async (failureType: string, occurred: boolean) => {
    setRunning(`s1-${failureType}`)
    try {
      await api.runS1(failureType, 45 + Math.random() * 30, 300, occurred)
      await load()
    } finally { setRunning(null) }
  }

  const systems = summary?.systems || {}
  const systemKeys = ['S0', 'S1', 'S2'].filter(k => systems[k])

  // Build chart data
  const chartData = [
    {
      metric: 'Recovery Rate',
      ...Object.fromEntries(systemKeys.map(k => [k, (systems[k]?.recovery_rate ?? 0) * 100])),
    },
    {
      metric: 'False Alarm Rate',
      ...Object.fromEntries(systemKeys.map(k => [k, (systems[k]?.false_alarm_rate ?? 0) * 100])),
    },
    {
      metric: 'Correct Remediation',
      ...Object.fromEntries(systemKeys.map(k => [k, (systems[k]?.remediation_correct_rate ?? 0) * 100])),
    },
  ]

  const mttrData = systemKeys.map(k => ({
    name: k,
    label: SYSTEM_LABELS[k as keyof typeof SYSTEM_LABELS],
    mttr: systems[k]?.avg_mttr_seconds ?? null,
    mttd: systems[k]?.avg_mttd_seconds ?? null,
    wasted: systems[k]?.wasted_retrain_count ?? 0,
    runs: systems[k]?.total_runs ?? 0,
  }))

  return (
    <div className="p-7 space-y-6 max-w-6xl">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-violet-500" />
            Experiments
          </h1>
          <p className="page-subtitle">Baseline comparison — S0, S1, S2 self-healing systems</p>
        </div>
        <button onClick={load} className="btn-ghost text-xs">
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* System cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {(['S0', 'S1', 'S2'] as const).map(sys => {
          const d = systems[sys]
          const color = SYSTEM_COLORS[sys]
          return (
            <div key={sys} className="card">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full" style={{ background: color }} />
                    <span className="text-base font-bold text-slate-800">{sys}</span>
                  </div>
                  <p className="text-sm font-medium text-slate-700 mt-0.5">
                    {SYSTEM_LABELS[sys]}
                  </p>
                </div>
                <span className="text-xs text-slate-400">{d?.total_runs ?? 0} runs</span>
              </div>
              <p className="text-xs text-slate-500 mb-3">{SYSTEM_DESCRIPTIONS[sys]}</p>

              {d ? (
                <div className="grid grid-cols-2 gap-2">
                  {[
                    ['Recovery',   `${((d.recovery_rate ?? 0) * 100).toFixed(0)}%`],
                    ['MTTR',       d.avg_mttr_seconds ? `${d.avg_mttr_seconds.toFixed(0)}s` : 'N/A'],
                    ['MTTD',       d.avg_mttd_seconds ? `${d.avg_mttd_seconds.toFixed(0)}s` : '—'],
                    ['Wasted',     String(d.wasted_retrain_count ?? 0)],
                  ].map(([label, val]) => (
                    <div key={label} className="bg-slate-50 rounded-xl p-2.5">
                      <p className="text-[10px] text-slate-500">{label}</p>
                      <p className="text-sm font-bold text-slate-800 mt-0.5">{val}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-slate-400 italic">No runs recorded yet.</div>
              )}

              {/* Simulate buttons */}
              {sys !== 'S2' && (
                <div className="mt-3 flex gap-2 flex-wrap">
                  {['F1', 'F2', 'F3', 'F4'].map(f => (
                    <button
                      key={f}
                      disabled={running !== null}
                      onClick={() => sys === 'S0' ? runS0(f) : runS1(f, true)}
                      className="btn-ghost text-xs px-2.5 py-1 rounded-lg"
                    >
                      <Play className="w-3 h-3" />
                      {running === `${sys.toLowerCase()}-${f}` ? '…' : f}
                    </button>
                  ))}
                </div>
              )}
              {sys === 'S2' && (
                <p className="text-[10px] text-slate-400 mt-3 italic">
                  S2 runs are recorded automatically when AegisML-Lite resolves incidents.
                </p>
              )}
            </div>
          )
        })}
      </div>

      {loading ? (
        <div className="text-sm text-slate-400 py-4 text-center">Loading experiment data…</div>
      ) : systemKeys.length === 0 ? (
        <div className="card text-center py-10">
          <BarChart3 className="w-10 h-10 text-slate-300 mx-auto mb-2" />
          <p className="text-slate-500 text-sm">No experiment runs yet.</p>
          <p className="text-slate-400 text-xs mt-1">
            Run S0/S1 simulations above, then run incidents via Simulations page for S2 data.
          </p>
        </div>
      ) : (
        <>
          {/* Comparison chart */}
          <div className="card">
            <p className="card-title mb-4">System Comparison (%)</p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={chartData} margin={{ left: -10, right: 10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="metric" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: 12, fontSize: 12 }}
                  formatter={(v: number) => [`${v.toFixed(1)}%`]}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {systemKeys.map(k => (
                  <Bar key={k} dataKey={k} name={SYSTEM_LABELS[k as keyof typeof SYSTEM_LABELS]}
                       fill={SYSTEM_COLORS[k as keyof typeof SYSTEM_COLORS]} radius={[4, 4, 0, 0]} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* MTTR comparison table */}
          <div className="card">
            <p className="card-title mb-3">Detailed Metrics</p>
            <table className="data-table">
              <thead>
                <tr>
                  {['System', 'Runs', 'Avg MTTD', 'Avg MTTR', 'Recovery Rate', 'Correct Remediation', 'Wasted Retrains'].map(h => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {mttrData.map(row => (
                  <tr key={row.name}>
                    <td>
                      <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full"
                             style={{ background: SYSTEM_COLORS[row.name as keyof typeof SYSTEM_COLORS] }} />
                        <span className="font-semibold text-slate-700">{row.name}</span>
                        <span className="text-slate-400">{row.label}</span>
                      </div>
                    </td>
                    <td className="font-mono text-slate-700">{row.runs}</td>
                    <td className="font-mono text-slate-700">{row.mttd != null ? `${row.mttd.toFixed(1)}s` : '—'}</td>
                    <td className="font-mono text-slate-700">{row.mttr != null ? `${row.mttr.toFixed(1)}s` : 'N/A'}</td>
                    <td>
                      <span className={`pill-${systems[row.name]?.recovery_rate > 0.7 ? 'green' : 'yellow'}`}>
                        {((systems[row.name]?.recovery_rate ?? 0) * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td>
                      <span className="font-mono text-slate-700">
                        {((systems[row.name]?.remediation_correct_rate ?? 0) * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td>
                      <span className={row.wasted > 0 ? 'pill-yellow' : 'pill-green'}>
                        {row.wasted}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Insight callouts */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[
              {
                title: 'S0 vs S2 Recovery',
                text: 'AegisML-Lite (S2) achieves targeted automated recovery. S0 never recovers — demonstrates the value of self-healing.',
                color: 'bg-violet-50 border-violet-200',
              },
              {
                title: 'S1 Wasted Retrains',
                text: 'Scheduled retraining (S1) wastes compute on healthy intervals. S2 retrains only when diagnosis confirms a trigger.',
                color: 'bg-amber-50 border-amber-200',
              },
              {
                title: 'MTTR Improvement',
                text: 'S2 targets remediation to the specific failure type, reducing MTTR versus the fixed schedule of S1.',
                color: 'bg-emerald-50 border-emerald-200',
              },
            ].map(c => (
              <div key={c.title} className={`rounded-2xl border p-4 ${c.color}`}>
                <p className="text-sm font-semibold text-slate-700 mb-1">{c.title}</p>
                <p className="text-xs text-slate-600 leading-relaxed">{c.text}</p>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
