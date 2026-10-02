import React, { useEffect, useState } from 'react'
import { api, ModelVersion } from '../services/api'
import StatusBadge from '../components/StatusBadge'
import { Brain, RefreshCw } from 'lucide-react'
import { format } from 'date-fns'

const STAGE_CARD: Record<string, string> = {
  PRODUCTION: 'border-l-emerald-400 bg-emerald-50/30',
  CANARY:     'border-l-amber-400 bg-amber-50/30',
  CANDIDATE:  'border-l-violet-300 bg-violet-50/20',
  VALIDATED:  'border-l-blue-400 bg-blue-50/20',
  REJECTED:   'border-l-rose-300',
  ROLLED_BACK:'border-l-orange-300',
}

export default function Models() {
  const [models, setModels] = useState<ModelVersion[]>([])
  const [canary, setCanary] = useState<Record<string, unknown>>({})
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const [m, c] = await Promise.all([api.getModels(), api.getCanaryStatus()])
      setModels(m)
      setCanary(c as Record<string, unknown>)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  const f4 = (n: number | null | undefined) => n != null ? n.toFixed(4) : '—'
  const fms = (n: number | null | undefined) => n != null ? `${n.toFixed(1)}ms` : '—'

  const prod = models.find(m => m.stage === 'PRODUCTION')
  const can  = models.find(m => m.stage === 'CANARY')

  return (
    <div className="p-7 space-y-5 max-w-6xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2"><Brain className="w-6 h-6 text-violet-500" />Models</h1>
          <p className="page-subtitle">XGBoost · Adult Income · {models.length} versions</p>
        </div>
        <button onClick={load} className="btn-ghost text-xs"><RefreshCw className="w-3.5 h-3.5" /></button>
      </div>

      {/* Active deployments */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Production */}
        <div className="card border-l-4 border-l-emerald-400 bg-emerald-50/30">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
            <span className="text-sm font-semibold text-emerald-700">Production</span>
          </div>
          {prod ? (
            <>
              <p className="text-3xl font-bold text-slate-800">v{prod.version}</p>
              <p className="text-xs text-slate-500 mt-0.5 font-mono">XGBoost · {prod.dataset_version}</p>
              <div className="grid grid-cols-3 gap-2 mt-3">
                {[['F1', f4(prod.f1_score)], ['ROC-AUC', f4(prod.roc_auc)], ['Latency', fms(prod.avg_latency_ms)]].map(([k, v]) => (
                  <div key={k} className="bg-white rounded-xl p-2 border border-emerald-100">
                    <p className="text-[10px] text-slate-500">{k}</p>
                    <p className="text-sm font-bold text-slate-800">{v}</p>
                  </div>
                ))}
              </div>
            </>
          ) : <p className="text-sm text-slate-400">No production model.</p>}
        </div>

        {/* Canary */}
        <div className={`card border-l-4 ${can ? 'border-l-amber-400 bg-amber-50/30' : 'border-l-slate-200'}`}>
          <div className="flex items-center gap-2 mb-3">
            <div className={`w-2.5 h-2.5 rounded-full ${can ? 'bg-amber-500 animate-pulse' : 'bg-slate-300'}`} />
            <span className={`text-sm font-semibold ${can ? 'text-amber-700' : 'text-slate-400'}`}>Canary</span>
          </div>
          {can ? (
            <>
              <p className="text-3xl font-bold text-slate-800">v{can.version}</p>
              <p className="text-xs text-slate-500 mt-0.5 font-mono">
                {((canary.canary_traffic as number || 0) * 100).toFixed(0)}% traffic
              </p>
              <div className="mt-3 h-2.5 bg-slate-200 rounded-full overflow-hidden flex">
                <div className="h-full bg-emerald-400 transition-all"
                     style={{ width: `${((1 - (canary.canary_traffic as number || 0)) * 100)}%` }} />
                <div className="h-full bg-amber-400 transition-all"
                     style={{ width: `${((canary.canary_traffic as number || 0) * 100)}%` }} />
              </div>
              <div className="flex justify-between text-[10px] text-slate-400 mt-1">
                <span>Production {((1 - (canary.canary_traffic as number || 0)) * 100).toFixed(0)}%</span>
                <span>Canary {((canary.canary_traffic as number || 0) * 100).toFixed(0)}%</span>
              </div>
            </>
          ) : <p className="text-sm text-slate-400">No active canary.</p>}
        </div>
      </div>

      {/* Version history */}
      {loading ? <div className="text-sm text-slate-400">Loading…</div> : (
        <div className="card overflow-hidden p-0">
          <div className="px-5 py-3 border-b border-slate-100">
            <p className="card-title">Version History</p>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                {['Version', 'Stage', 'F1', 'ROC-AUC', 'Latency', 'Dataset', 'Quality Gates', 'Created'].map(h => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {models.map(m => (
                <tr key={m.id} className={`border-l-4 ${STAGE_CARD[m.stage] || 'border-l-transparent'}`}>
                  <td><span className="font-bold text-slate-800">v{m.version}</span></td>
                  <td><StatusBadge value={m.stage} /></td>
                  <td><span className={`font-mono text-sm ${m.f1_score && m.f1_score >= 0.35 ? 'text-emerald-600 font-semibold' : 'text-rose-500'}`}>{f4(m.f1_score)}</span></td>
                  <td className="font-mono text-sm text-slate-600">{f4(m.roc_auc)}</td>
                  <td className="font-mono text-sm text-slate-600">{fms(m.avg_latency_ms)}</td>
                  <td className="text-xs text-slate-500">{m.dataset_version || '—'}</td>
                  <td>
                    {m.quality_gate_passed === true ? <span className="pill-green">PASS</span>
                     : m.quality_gate_passed === false ? <span className="pill-red">FAIL</span>
                     : <span className="text-slate-400 text-xs">—</span>}
                  </td>
                  <td className="text-xs text-slate-500 font-mono">{format(new Date(m.created_at), 'MMM d HH:mm')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
