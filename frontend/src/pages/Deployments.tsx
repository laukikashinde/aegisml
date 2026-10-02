import React, { useEffect, useState } from 'react'
import { api, Deployment, ModelVersion } from '../services/api'
import StatusBadge from '../components/StatusBadge'
import { Rocket, RefreshCw, ShieldCheck } from 'lucide-react'
import { format, parseISO, isValid } from 'date-fns'

function fmtTime(ts: string | null | undefined): string {
  if (!ts) return '—'
  try {
    const d = parseISO(ts)
    return isValid(d) ? format(d, 'MMM d HH:mm') : '—'
  } catch { return '—' }
}

export default function Deployments() {
  const [deployments, setDeployments] = useState<Deployment[]>([])
  const [models, setModels]           = useState<ModelVersion[]>([])
  const [canary, setCanary]           = useState<Record<string, unknown>>({})
  const [loading, setLoading]         = useState(true)
  const [verifying, setVerifying]     = useState(false)
  const [msg, setMsg]                 = useState<{ text: string; ok: boolean } | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [d, m, c] = await Promise.all([
        api.getDeployments(),
        api.getModels(),
        api.getCanaryStatus(),
      ])
      setDeployments(d)
      setModels(m)
      setCanary(c as Record<string, unknown>)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  // Show health check if DB says there's an active canary OR any model is in CANARY stage
  const hasCanary = (canary.has_active_canary as boolean) ||
                    models.some(m => m.stage === 'CANARY')

  const verifyCanary = async () => {
    // Find the canary model
    const canaryMv = models.find(m => m.stage === 'CANARY')
    if (!canaryMv) {
      setMsg({ text: 'No CANARY stage model found. Run a simulation first.', ok: false })
      return
    }
    setVerifying(true); setMsg(null)
    try {
      const r = await api.verifyCanary(canaryMv.id) as Record<string, unknown>
      const status = String(r.status)
      setMsg({
        text: status === 'promoted'    ? '✓ Canary promoted to production!' :
              status === 'rolled_back' ? `⚠ Rolled back: ${String(r.reason || '')}` :
              `Health check passed — traffic at ${
                typeof r.current_traffic === 'number'
                  ? `${(r.current_traffic * 100).toFixed(0)}%`
                  : '?'
              }`,
        ok: status !== 'rolled_back',
      })
      await load()
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : 'Error verifying canary', ok: false })
    } finally { setVerifying(false) }
  }

  const modelMap = Object.fromEntries(models.map(m => [m.id, m]))
  const prod   = deployments.find(d => d.is_production && d.status === 'ACTIVE')
  const active = deployments.find(d => d.is_canary)
  const history = deployments.filter(d =>
    !d.is_canary && !(d.is_production && d.status === 'ACTIVE')
  )

  const cpct = (n: number | null | undefined) =>
    n != null ? `${(n * 100).toFixed(1)}%` : '—'

  return (
    <div className="p-7 space-y-5 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Rocket className="w-6 h-6 text-violet-500" />Deployments
          </h1>
          <p className="page-subtitle">Canary routing · health gates · automatic rollback</p>
        </div>
        <div className="flex gap-2">
          {hasCanary && (
            <button
              onClick={verifyCanary}
              disabled={verifying}
              className="btn-primary text-xs"
            >
              <ShieldCheck className="w-3.5 h-3.5" />
              {verifying ? 'Checking…' : 'Run Health Check'}
            </button>
          )}
          <button onClick={load} className="btn-ghost text-xs">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {msg && (
        <div className={`rounded-2xl px-4 py-2.5 text-sm border ${
          msg.ok
            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
            : 'bg-rose-50 border-rose-200 text-rose-600'
        }`}>
          {msg.text}
        </div>
      )}

      {!hasCanary && !loading && (
        <div className="rounded-2xl px-5 py-3 bg-slate-50 border border-slate-200 text-sm text-slate-500">
          💡 No active canary. Run a <strong>Simulate → F1 Covariate Drift</strong> to trigger retraining and start a canary deployment.
        </div>
      )}

      {loading ? <div className="text-sm text-slate-400">Loading…</div> : (
        <>
          {/* Current deployment cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Production */}
            <div className="card border-l-4 border-l-emerald-400 bg-emerald-50/30">
              <div className="flex items-center gap-2 mb-3">
                <div className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                <span className="text-sm font-semibold text-emerald-700">Production</span>
                <span className="ml-auto text-xs text-emerald-600 font-medium">100% traffic</span>
              </div>
              {prod ? (
                <>
                  <p className="text-3xl font-bold text-slate-800">
                    v{modelMap[prod.model_version_id]?.version ?? '—'}
                  </p>
                  <div className="grid grid-cols-2 gap-2 mt-3 text-xs">
                    <div className="bg-white rounded-xl p-2 border border-emerald-100">
                      <p className="text-slate-400">F1 Score</p>
                      <p className="font-bold text-slate-700">
                        {modelMap[prod.model_version_id]?.f1_score?.toFixed(4) ?? '—'}
                      </p>
                    </div>
                    <div className="bg-white rounded-xl p-2 border border-emerald-100">
                      <p className="text-slate-400">Since</p>
                      <p className="font-bold text-slate-700">{fmtTime(prod.started_at)}</p>
                    </div>
                  </div>
                </>
              ) : (
                <p className="text-sm text-slate-400">No production deployment.</p>
              )}
            </div>

            {/* Canary */}
            <div className={`card border-l-4 ${
              active ? 'border-l-amber-400 bg-amber-50/30' : 'border-l-slate-200'
            }`}>
              <div className="flex items-center gap-2 mb-3">
                <div className={`w-2.5 h-2.5 rounded-full ${
                  active ? 'bg-amber-500 animate-pulse' : 'bg-slate-300'
                }`} />
                <span className={`text-sm font-semibold ${active ? 'text-amber-700' : 'text-slate-400'}`}>
                  Canary
                </span>
                {active && (
                  <span className="ml-auto text-xs text-amber-600 font-medium">
                    {cpct(active.canary_traffic_percent)} traffic
                  </span>
                )}
              </div>
              {active ? (
                <>
                  <p className="text-3xl font-bold text-slate-800">
                    v{modelMap[active.model_version_id]?.version ?? '—'}
                  </p>
                  <div className="mt-3 h-2.5 bg-slate-200 rounded-full overflow-hidden flex">
                    <div
                      className="h-full bg-emerald-400 transition-all"
                      style={{ width: `${(1 - active.canary_traffic_percent) * 100}%` }}
                    />
                    <div
                      className="h-full bg-amber-400 transition-all"
                      style={{ width: `${active.canary_traffic_percent * 100}%` }}
                    />
                  </div>
                  <div className="flex justify-between text-[10px] text-slate-400 mt-1">
                    <span>Production {cpct(1 - active.canary_traffic_percent)}</span>
                    <span>Canary {cpct(active.canary_traffic_percent)}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 mt-3 text-xs">
                    <div className={`rounded-xl p-2 border ${
                      active.canary_error_rate && active.canary_error_rate > 0.05
                        ? 'bg-rose-50 border-rose-200'
                        : 'bg-white border-amber-100'
                    }`}>
                      <p className="text-slate-400">Error Rate</p>
                      <p className={`font-bold ${
                        active.canary_error_rate && active.canary_error_rate > 0.05
                          ? 'text-rose-600' : 'text-slate-700'
                      }`}>
                        {active.canary_error_rate != null ? cpct(active.canary_error_rate) : '—'}
                      </p>
                    </div>
                    <div className={`rounded-xl p-2 border ${
                      active.canary_latency_ms && active.canary_latency_ms > 200
                        ? 'bg-rose-50 border-rose-200'
                        : 'bg-white border-amber-100'
                    }`}>
                      <p className="text-slate-400">Latency</p>
                      <p className={`font-bold ${
                        active.canary_latency_ms && active.canary_latency_ms > 200
                          ? 'text-rose-600' : 'text-slate-700'
                      }`}>
                        {active.canary_latency_ms != null
                          ? `${active.canary_latency_ms.toFixed(0)}ms` : '—'}
                      </p>
                    </div>
                  </div>

                  {/* Health check hint */}
                  <div className="mt-3 text-xs text-amber-600 bg-amber-50 rounded-xl px-3 py-2 border border-amber-200">
                    Click <strong>Run Health Check</strong> above to advance traffic 10% → 25% → 40% → 55% → 70% → 85% → 100%
                  </div>
                </>
              ) : (
                <p className="text-sm text-slate-400">No active canary deployment.</p>
              )}
            </div>
          </div>

          {/* Deployment history */}
          {history.length > 0 && (
            <div className="card overflow-hidden p-0">
              <div className="px-5 py-3 border-b border-slate-100">
                <p className="card-title">Deployment History</p>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    {['Model', 'Status', 'Traffic', 'Error Rate', 'Rollback Reason', 'Started'].map(h => (
                      <th key={h}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {history.map(d => (
                    <tr key={d.id}>
                      <td className="font-bold text-slate-700">
                        v{modelMap[d.model_version_id]?.version ?? d.model_version_id}
                      </td>
                      <td><StatusBadge value={d.status} /></td>
                      <td className="font-mono text-sm">{cpct(d.canary_traffic_percent)}</td>
                      <td className="font-mono text-sm">
                        {d.canary_error_rate != null ? cpct(d.canary_error_rate) : '—'}
                      </td>
                      <td className="text-xs text-slate-500 max-w-xs truncate">
                        {(d as unknown as { rollback_reason?: string }).rollback_reason || '—'}
                      </td>
                      <td className="text-xs text-slate-500 font-mono">{fmtTime(d.started_at)}</td>
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
