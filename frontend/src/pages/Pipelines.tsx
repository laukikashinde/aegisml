import React, { useEffect, useState } from 'react'
import { api, PipelineRun } from '../services/api'
import StatusBadge from '../components/StatusBadge'
import { GitBranch, RefreshCw, Play } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

// Typed detail so JSX doesn't complain about unknown
interface RunDetail {
  status: string
  trigger: string
  dataset_version: string
  duration_seconds: number | null
  mlflow_run_id: string
  model_version_id: string | number | null
  stages_completed: string[] | null
  error_message: string | null
  logs: string | null
  [key: string]: unknown
}

export default function Pipelines() {
  const [runs, setRuns]         = useState<PipelineRun[]>([])
  const [loading, setLoading]   = useState(true)
  const [triggering, setTriggering] = useState(false)
  const [selected, setSelected] = useState<RunDetail | null>(null)
  const [msg, setMsg]           = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try { setRuns(await api.getPipelines()) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const triggerRetrain = async () => {
    setTriggering(true); setMsg(null)
    try {
      const r = await api.triggerRetrain('v1') as { pipeline_run_id?: string }
      setMsg(`Retraining triggered — run: ${r.pipeline_run_id || 'started'}`)
      await load()
    } catch (e) {
      setMsg(`Failed: ${e instanceof Error ? e.message : 'error'}`)
    } finally { setTriggering(false) }
  }

  const viewDetails = async (id: string) => {
    try {
      const raw = await api.getPipelineRun(id) as Record<string, unknown>
      setSelected({
        status:           String(raw.status ?? '—'),
        trigger:          String(raw.trigger ?? '—'),
        dataset_version:  String(raw.dataset_version ?? '—'),
        duration_seconds: typeof raw.duration_seconds === 'number' ? raw.duration_seconds : null,
        mlflow_run_id:    String(raw.mlflow_run_id ?? '—'),
        model_version_id: raw.model_version_id != null ? String(raw.model_version_id) : '—',
        stages_completed: Array.isArray(raw.stages_completed) ? (raw.stages_completed as string[]) : null,
        error_message:    raw.error_message != null ? String(raw.error_message) : null,
        logs:             raw.logs != null ? String(raw.logs) : null,
      })
    } catch { /* ignore */ }
  }

  const dur = (s: number | null) => s == null ? '—' : s < 60 ? `${s.toFixed(0)}s` : `${(s / 60).toFixed(1)}m`

  return (
    <div className="p-7 space-y-5 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <GitBranch className="w-6 h-6 text-violet-500" />Pipelines
          </h1>
          <p className="page-subtitle">XGBoost training pipeline · Adult Income dataset</p>
        </div>
        <div className="flex gap-2">
          <button onClick={triggerRetrain} disabled={triggering} className="btn-primary text-xs">
            <Play className="w-3.5 h-3.5" />
            {triggering ? 'Triggering…' : 'Trigger Retrain'}
          </button>
          <button onClick={load} className="btn-ghost text-xs"><RefreshCw className="w-3.5 h-3.5" /></button>
        </div>
      </div>

      {msg && (
        <div className="rounded-2xl px-4 py-2.5 text-sm bg-violet-50 border border-violet-200 text-violet-700 font-mono">
          {msg}
        </div>
      )}

      {loading ? <div className="text-sm text-slate-400">Loading…</div> : (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
          {/* Run list */}
          <div className="lg:col-span-2 card overflow-hidden p-0">
            <div className="px-4 py-3 border-b border-slate-100">
              <p className="card-title">Pipeline Runs ({runs.length})</p>
            </div>
            {runs.length === 0 ? (
              <div className="p-5 text-sm text-slate-400">No pipeline runs yet.</div>
            ) : (
              <div className="divide-y divide-slate-100">
                {runs.map(r => (
                  <button
                    key={r.id}
                    onClick={() => viewDetails(r.id)}
                    className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-50 transition-colors text-left"
                  >
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <StatusBadge value={r.status} />
                        <span className="text-xs text-slate-500 font-mono">({r.trigger})</span>
                      </div>
                      <p className="text-xs text-slate-500">
                        {formatDistanceToNow(new Date(r.started_at), { addSuffix: true })}
                        {r.dataset_version && <span className="ml-2 font-mono">{r.dataset_version}</span>}
                      </p>
                      {r.error_stage && <p className="text-xs text-rose-500 mt-0.5">Failed: {r.error_stage}</p>}
                    </div>
                    <span className="text-xs font-mono text-slate-400 ml-3">
                      {dur(r.duration_seconds ?? null)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Detail panel */}
          {selected && (
            <div className="lg:col-span-3 card space-y-3">
              <div className="flex items-center justify-between">
                <p className="card-title">Run Detail</p>
                <button onClick={() => setSelected(null)} className="btn-ghost text-xs">✕</button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {([
                  ['Status',   selected.status],
                  ['Trigger',  selected.trigger],
                  ['Dataset',  selected.dataset_version],
                  ['Duration', dur(selected.duration_seconds)],
                  ['MLflow',   selected.mlflow_run_id],
                  ['Model',    String(selected.model_version_id ?? '—')],
                ] as [string, string][]).map(([k, v]) => (
                  <div key={k} className="bg-slate-50 rounded-xl p-2.5">
                    <p className="text-[10px] text-slate-400 uppercase">{k}</p>
                    <p className="text-xs font-mono text-slate-700 mt-0.5 truncate">{v}</p>
                  </div>
                ))}
              </div>

              {selected.stages_completed && selected.stages_completed.length > 0 && (
                <div>
                  <p className="text-xs text-slate-500 mb-1.5">Completed Stages</p>
                  <div className="flex flex-wrap gap-1.5">
                    {selected.stages_completed.map(s => (
                      <span key={s} className="pill-green text-[10px]">{s}</span>
                    ))}
                  </div>
                </div>
              )}

              {selected.error_message && (
                <div>
                  <p className="text-xs text-rose-500 mb-1">Error</p>
                  <pre className="text-xs font-mono text-rose-600 bg-rose-50 rounded-xl p-3 overflow-x-auto whitespace-pre-wrap border border-rose-100">
                    {selected.error_message}
                  </pre>
                </div>
              )}

              {selected.logs && (
                <div>
                  <p className="text-xs text-slate-400 mb-1">Logs (last 40 lines)</p>
                  <pre className="text-xs font-mono text-slate-500 bg-slate-50 rounded-xl p-3 overflow-x-auto max-h-56 whitespace-pre-wrap border border-slate-200">
                    {selected.logs.split('\n').slice(-40).join('\n')}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
