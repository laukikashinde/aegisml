import React, { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Search, Wrench, CheckCircle, XCircle, RefreshCw, FileText } from 'lucide-react'
import { api, IncidentDetail as IDetail } from '../services/api'
import StatusBadge from '../components/StatusBadge'
import IncidentTimeline from '../components/IncidentTimeline'
import { format } from 'date-fns'

export default function IncidentDetail() {
  const { id } = useParams<{ id: string }>()
  const [incident, setIncident] = useState<IDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [report, setReport] = useState<Record<string, unknown> | null>(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null)

  const load = useCallback(async () => {
    if (!id) return
    try {
      setIncident(await api.getIncident(id))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    load()
    const t = setInterval(load, 8_000)
    return () => clearInterval(t)
  }, [load])

  const act = async (fn: () => Promise<unknown>, label: string) => {
    setActionLoading(true)
    setMessage(null)
    try {
      await fn()
      setMessage({ text: `${label} succeeded.`, ok: true })
      await load()
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : 'Failed', ok: false })
    } finally {
      setActionLoading(false)
    }
  }

  const loadReport = async () => {
    if (!id) return
    setReportLoading(true)
    try {
      const r = await api.getIncidentReport(id)
      setReport(r as Record<string, unknown>)
    } catch {
      setReport({ error: 'Report unavailable — investigate the incident first.' })
    } finally {
      setReportLoading(false)
    }
  }

  if (loading) return <div className="p-8 text-sm text-slate-400">Loading…</div>
  if (!incident) return <div className="p-8 text-sm text-rose-500">Incident not found.</div>

  const canInvestigate = ['DETECTED'].includes(incident.status)
  const canRemediate   = ['DIAGNOSED'].includes(incident.status)
  const canApprove     = incident.status === 'AWAITING_APPROVAL'
  const isResolved     = ['RESOLVED','ROLLED_BACK'].includes(incident.status)

  const SELF_HEALING_STAGES = [
    { key: 'detected',   label: 'Detected',   done: true },
    { key: 'diagnosed',  label: 'Diagnosed',   done: ['DIAGNOSED','AWAITING_APPROVAL','REMEDIATING','VERIFYING','RESOLVED','ROLLED_BACK'].includes(incident.status) },
    { key: 'remediated', label: 'Remediated',  done: ['REMEDIATING','VERIFYING','RESOLVED','ROLLED_BACK'].includes(incident.status) },
    { key: 'verified',   label: 'Verified',    done: ['VERIFYING','RESOLVED','ROLLED_BACK'].includes(incident.status) },
    { key: 'resolved',   label: isResolved ? (incident.status === 'ROLLED_BACK' ? 'Rolled Back' : 'Resolved') : 'Pending', done: isResolved },
  ]

  return (
    <div className="p-7 space-y-5 max-w-6xl">
      {/* Header */}
      <div className="flex items-start gap-3">
        <Link to="/incidents" className="text-slate-400 hover:text-slate-600 mt-1">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-2 flex-wrap mb-1.5">
            {incident.is_simulation && (
              <span className="px-2.5 py-0.5 text-[10px] font-bold rounded-full bg-violet-100 text-violet-700">
                SIMULATION · {incident.simulation_type}
              </span>
            )}
            <StatusBadge value={incident.severity} type="severity" />
            <StatusBadge value={incident.status} />
            <StatusBadge value={incident.incident_type} />
          </div>
          <h1 className="text-lg font-bold text-slate-800">
            {incident.title.replace('[SIMULATION] ', '')}
          </h1>
          <p className="text-xs text-slate-400 font-mono mt-1">
            {incident.id} · {format(new Date(incident.created_at), 'MMM d HH:mm:ss')}
          </p>
        </div>
        <button onClick={load} className="btn-ghost text-xs"><RefreshCw className="w-3.5 h-3.5" /></button>
      </div>

      {/* Self-healing progress bar */}
      <div className="card">
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Self-Healing Progress</p>
        <div className="flex items-center gap-0">
          {SELF_HEALING_STAGES.map((stage, idx) => (
            <React.Fragment key={stage.key}>
              <div className="flex flex-col items-center gap-1 flex-1">
                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                  stage.done ? 'bg-violet-600 text-white' : 'bg-slate-100 text-slate-400'
                }`}>
                  {stage.done ? '✓' : idx + 1}
                </div>
                <span className={`text-[10px] font-medium ${stage.done ? 'text-violet-700' : 'text-slate-400'}`}>
                  {stage.label}
                </span>
              </div>
              {idx < SELF_HEALING_STAGES.length - 1 && (
                <div className={`h-0.5 flex-1 mb-4 ${stage.done ? 'bg-violet-300' : 'bg-slate-200'}`} />
              )}
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* Message */}
      {message && (
        <div className={`rounded-2xl px-4 py-2.5 text-sm border ${
          message.ok ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                     : 'bg-rose-50 border-rose-200 text-rose-600'
        }`}>
          {message.text}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-2 flex-wrap">
        {canInvestigate && (
          <button onClick={() => act(() => api.investigateIncident(id!), 'Investigation')}
                  disabled={actionLoading} className="btn-primary text-xs">
            <Search className="w-3.5 h-3.5" />
            {actionLoading ? 'Investigating…' : 'Run AI Investigation'}
          </button>
        )}
        {canRemediate && (
          <button onClick={() => act(() => api.remediateIncident(id!), 'Remediation')}
                  disabled={actionLoading} className="btn-secondary text-xs">
            <Wrench className="w-3.5 h-3.5" />
            {actionLoading ? 'Remediating…' : 'Execute Remediation'}
          </button>
        )}
        {canApprove && (
          <>
            <button onClick={() => act(() => api.approveIncident(id!, 'operator'), 'Approval')}
                    disabled={actionLoading} className="btn-success text-xs">
              <CheckCircle className="w-3.5 h-3.5" /> Approve
            </button>
            <button onClick={() => act(() => api.rejectIncident(id!, 'operator', 'Rejected'), 'Rejection')}
                    disabled={actionLoading} className="btn-danger text-xs">
              <XCircle className="w-3.5 h-3.5" /> Reject
            </button>
          </>
        )}
        {isResolved && (
          <button onClick={loadReport} disabled={reportLoading} className="btn-ghost text-xs">
            <FileText className="w-3.5 h-3.5" />
            {reportLoading ? 'Generating…' : 'Generate Report'}
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Left column */}
        <div className="space-y-4">
          {/* Observed metrics */}
          {incident.observed_metrics && (
            <div className="card">
              <p className="section-title">Observed Metrics</p>
              <div className="space-y-1.5">
                {Object.entries(incident.observed_metrics).map(([k, v]) => (
                  <div key={k} className="flex justify-between text-sm">
                    <span className="text-slate-500 font-mono text-xs">{k}</span>
                    <span className="text-slate-700 font-mono text-xs font-medium">{String(v)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Diagnosis */}
          {incident.diagnosis && (
            <div className="card border-violet-200 bg-violet-50/50">
              <p className="section-title text-violet-600">Agent Diagnosis</p>
              <p className="text-sm text-slate-700 mb-3">{incident.diagnosis}</p>
              {incident.root_cause && (
                <div className="bg-white rounded-xl p-3 border border-violet-100">
                  <p className="text-xs font-semibold text-slate-500 mb-1">Root Cause</p>
                  <p className="text-sm text-slate-700 font-mono text-xs leading-relaxed">{incident.root_cause}</p>
                </div>
              )}
              <div className="grid grid-cols-2 gap-3 mt-3">
                <div className="bg-white rounded-xl p-2.5 border border-violet-100">
                  <p className="text-[10px] text-slate-500 uppercase tracking-wider">Confidence</p>
                  <p className="text-xl font-bold text-violet-700 mt-0.5">
                    {incident.confidence != null ? `${(incident.confidence * 100).toFixed(0)}%` : '—'}
                  </p>
                </div>
                <div className="bg-white rounded-xl p-2.5 border border-violet-100">
                  <p className="text-[10px] text-slate-500 uppercase tracking-wider">Risk</p>
                  <div className="mt-0.5">
                    {incident.risk_level ? <StatusBadge value={incident.risk_level} type="severity" /> : '—'}
                  </div>
                </div>
              </div>
              {incident.recommended_action && (
                <div className="mt-3">
                  <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Recommended Action</p>
                  <span className="px-2.5 py-1 text-xs font-bold rounded-lg bg-violet-100 text-violet-700 font-mono">
                    {incident.recommended_action}
                  </span>
                  {incident.requires_human_approval && (
                    <span className="ml-2 px-2.5 py-1 text-xs font-medium rounded-lg bg-amber-100 text-amber-700">
                      Requires Approval
                    </span>
                  )}
                </div>
              )}
              {incident.verification_plan && incident.verification_plan.length > 0 && (
                <div className="mt-3">
                  <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Verification Plan</p>
                  <ol className="list-decimal list-inside space-y-0.5">
                    {incident.verification_plan.map((s, i) => (
                      <li key={i} className="text-xs text-slate-600">{s}</li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          )}

          {/* Evidence */}
          {incident.agent_evidence && incident.agent_evidence.length > 0 && (
            <div className="card">
              <p className="section-title">Evidence ({incident.agent_evidence.length})</p>
              <div className="space-y-1.5">
                {(incident.agent_evidence as Array<{ type?: string; title?: string; data?: unknown; source_tool?: string }>)
                  .map((e, i) => (
                    <details key={i} className="bg-slate-50 rounded-xl border border-slate-200 overflow-hidden">
                      <summary className="px-3 py-2.5 text-xs text-slate-700 cursor-pointer hover:bg-slate-100 flex items-center justify-between">
                        <span className="font-medium">{e.title || e.type || `Evidence ${i + 1}`}</span>
                        <span className="text-slate-400 font-mono">{e.source_tool}</span>
                      </summary>
                      <pre className="px-3 py-2 text-xs font-mono text-slate-500 overflow-x-auto border-t border-slate-200 bg-white">
                        {JSON.stringify(e.data || e, null, 2)}
                      </pre>
                    </details>
                  ))}
              </div>
            </div>
          )}

          {/* LLM Report */}
          {report && (
            <div className="card border-sky-200 bg-sky-50/50">
              <p className="section-title text-sky-600">Incident Report</p>
              {(report as any).error ? (
                <p className="text-sm text-rose-500">{(report as any).error}</p>
              ) : (
                <div className="space-y-3 text-sm text-slate-700">
                  {[
                    ['Summary', (report as any).summary],
                    ['What Happened', (report as any).what_happened],
                    ['Detection Evidence', (report as any).detection_evidence],
                    ['Diagnosis', (report as any).diagnosis],
                    ['Action Taken', (report as any).action_taken],
                    ['Recovery', (report as any).recovery_result],
                  ].map(([label, text]) => text && (
                    <div key={String(label)}>
                      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-0.5">{label}</p>
                      <p className="text-slate-700">{String(text)}</p>
                    </div>
                  ))}
                  {(report as any).recommendations?.length > 0 && (
                    <div>
                      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-0.5">Recommendations</p>
                      <ul className="list-disc list-inside space-y-0.5">
                        {((report as any).recommendations as string[]).map((r, i) => (
                          <li key={i} className="text-xs text-slate-600">{r}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <p className="text-[10px] text-slate-400 italic">
                    Generated by: {(report as any).generated_by} · {(report as any).generated_at}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right column — timeline */}
        <div className="card">
          <p className="section-title">Timeline ({incident.timeline.length} events)</p>
          <div className="overflow-y-auto max-h-[700px]">
            <IncidentTimeline events={incident.timeline} />
          </div>
        </div>
      </div>
    </div>
  )
}
