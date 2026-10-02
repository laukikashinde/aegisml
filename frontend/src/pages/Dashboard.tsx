import React, { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle, Brain, Activity, CheckCircle2,
  Clock, Zap, TrendingUp, RotateCcw, RefreshCw,
  ArrowRight, Play, Square,
} from 'lucide-react'
import { api, DashboardData } from '../services/api'
import MetricCard from '../components/MetricCard'
import StatusBadge from '../components/StatusBadge'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { format, parseISO, isValid } from 'date-fns'

function fmtTime(ts: string | null | undefined): string {
  if (!ts) return '—'
  try {
    const d = parseISO(ts)
    return isValid(d) ? format(d, 'MMM d HH:mm:ss') : '—'
  } catch { return '—' }
}

const pct = (n: number | null | undefined) =>
  n != null ? `${(n * 100).toFixed(1)}%` : '—'

const SEVERITY_DOT: Record<string, string> = {
  CRITICAL: 'bg-rose-500',
  HIGH:     'bg-orange-400',
  MEDIUM:   'bg-amber-400',
  LOW:      'bg-blue-400',
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-3 shadow-card-hover text-xs">
      <p className="text-slate-500 mb-1">{label}</p>
      {payload.map((p: any) => (
        <div key={p.name} className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{ background: p.color }} />
          <span className="text-slate-700 font-medium">{p.name}: {typeof p.value === 'number' ? p.value.toFixed(3) : p.value}</span>
        </div>
      ))}
    </div>
  )
}

export default function Dashboard() {
  const [data, setData]   = useState<DashboardData | null>(null)
  const [perf, setPerf]   = useState<any[]>([])
  const [stream, setStream] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [streamLoading, setStreamLoading] = useState(false)
  const [resetting, setResetting] = useState(false)

  const resetDemo = async () => {
    if (!window.confirm('Reset all demo data and start fresh? This cannot be undone.')) return
    setResetting(true)
    try {
      await api.resetDemoData()
      await load()
    } finally { setResetting(false) }
  }

  const load = useCallback(async () => {
    try {
      const [d, p, s] = await Promise.all([
        api.getDashboard(),
        api.getPerformance(),
        api.getStreamStatus().catch(() => null),
      ])
      setData(d)
      setPerf((p as any[]).slice(-20).reverse())
      setStream(s)
      setError(null)
    } catch {
      setError('Backend unavailable — is the server running?')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 10_000)
    return () => clearInterval(t)
  }, [load])

  const toggleStream = async () => {
    setStreamLoading(true)
    try {
      if (stream?.running) {
        await api.stopStream()
      } else {
        await api.startStream()
      }
      await load()
    } finally {
      setStreamLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-64">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-sm text-slate-400">Loading dashboard…</p>
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="p-8">
        <div className="card border-rose-200 bg-rose-50">
          <p className="text-rose-600 text-sm font-medium">{error || 'No data'}</p>
          <p className="text-rose-400 text-xs mt-1">Ensure the backend is running at port 8000.</p>
          <button onClick={load} className="btn-secondary mt-3 text-xs">Retry</button>
        </div>
      </div>
    )
  }

  const activeIncidents = data.recent_incidents.filter(
    i => !['RESOLVED','ROLLED_BACK','FAILED'].includes(i.status)
  )

  return (
    <div className="p-7 space-y-6 max-w-7xl">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">AegisML-Lite — Autonomous Self-Healing MLOps</p>
        </div>
        <div className="flex items-center gap-2">
          {/* Stream toggle */}
          <button
            onClick={toggleStream}
            disabled={streamLoading}
            className={stream?.running ? 'btn-danger text-xs' : 'btn-success text-xs'}
          >
            {stream?.running
              ? <><Square className="w-3 h-3" /> Stop Stream</>
              : <><Play className="w-3 h-3" /> Start Stream</>
            }
          </button>
          <button
            onClick={resetDemo}
            disabled={resetting}
            className="btn-secondary text-xs gap-1 border-rose-200 text-rose-600 hover:bg-rose-50"
          >
            {resetting ? '…' : '🗑 Reset Demo'}
          </button>
        </div>
      </div>

      {/* Stream status banner */}
      {stream && (
        <div className={`rounded-2xl px-5 py-3 flex items-center justify-between text-sm border ${
          stream.running
            ? 'bg-emerald-50 border-emerald-200'
            : 'bg-slate-50 border-slate-200'
        }`}>
          <div className="flex items-center gap-3">
            <div className={`w-2 h-2 rounded-full ${stream.running ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'}`} />
            <span className="font-medium text-slate-700">
              Stream {stream.running ? 'Running' : 'Stopped'}
            </span>
            {stream.running && (
              <span className="text-slate-500">
                {stream.records_processed?.toLocaleString() || 0} records · Mode:{' '}
                <span className={`font-semibold ${stream.mode === 'NORMAL' ? 'text-emerald-600' : 'text-amber-600'}`}>
                  {stream.mode}
                </span>
              </span>
            )}
          </div>
          {stream.running && stream.mode !== 'NORMAL' && (
            <span className="text-xs font-medium bg-amber-100 text-amber-700 px-2.5 py-1 rounded-full">
              ⚠ Drift Active
            </span>
          )}
        </div>
      )}

      {/* Top metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Active Incidents"
          value={data.active_incidents}
          icon={AlertTriangle}
          color={data.active_incidents > 0 ? 'rose' : 'green'}
          sub={`${data.resolved_today} resolved today`}
        />
        <MetricCard
          label="Production Model"
          value={`v${data.production_model_version ?? '—'}`}
          icon={Brain}
          color="purple"
          sub={data.production_f1 != null ? `F1: ${data.production_f1.toFixed(4)}` : 'XGBoost'}
        />
        <MetricCard
          label="Drift Score"
          value={data.latest_drift_score != null ? data.latest_drift_score.toFixed(3) : '—'}
          icon={Activity}
          color={data.drift_detected ? 'amber' : 'green'}
          sub={data.drift_detected ? '⚠ Drift detected' : 'No drift detected'}
        />
        <MetricCard
          label="Pending Approvals"
          value={data.open_approvals}
          icon={CheckCircle2}
          color={data.open_approvals > 0 ? 'amber' : 'sky'}
          sub="Human-in-the-loop"
        />
      </div>

      {/* Main chart + incidents */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">

        {/* Performance chart — large, spans 3 cols */}
        <div className="lg:col-span-3 card">
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="card-title">Model Health</p>
              <p className="text-xs text-slate-400 mt-0.5">F1 score over recent monitoring windows</p>
            </div>
          </div>
          {perf.length === 0 ? (
            <div className="h-48 flex items-center justify-center text-slate-400 text-sm bg-slate-50 rounded-xl">
              No performance data yet — start the stream and run a simulation.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={perf} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="f1Grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#8b5cf6" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis
                  dataKey="timestamp"
                  tickFormatter={v => { try { return format(new Date(v), 'HH:mm') } catch { return '' } }}
                  tick={{ fill: '#94a3b8', fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis domain={[0, 1]} tick={{ fill: '#94a3b8', fontSize: 10 }}
                       axisLine={false} tickLine={false}
                       tickFormatter={(v: number) => v.toFixed(1)} />
                <Tooltip content={<CustomTooltip />} />
                <Area type="monotone" dataKey="f1_score" name="F1"
                      stroke="#8b5cf6" strokeWidth={2}
                      fill="url(#f1Grad)" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Active incidents — 2 cols */}
        <div className="lg:col-span-2 card">
          <div className="flex items-center justify-between mb-3">
            <p className="card-title">Active Incidents</p>
            <Link to="/incidents" className="text-xs text-violet-600 hover:text-violet-700 font-medium flex items-center gap-1">
              View all <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
          {activeIncidents.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 text-center">
              <div className="w-10 h-10 bg-emerald-100 rounded-xl flex items-center justify-center mb-2">
                <CheckCircle2 className="w-5 h-5 text-emerald-500" />
              </div>
              <p className="text-sm font-medium text-slate-600">All clear</p>
              <p className="text-xs text-slate-400 mt-0.5">No active incidents</p>
            </div>
          ) : (
            <div className="space-y-2">
              {activeIncidents.slice(0, 4).map(i => (
                <Link
                  key={i.id}
                  to={`/incidents/${i.id}`}
                  className="flex items-start gap-3 p-3 rounded-xl hover:bg-slate-50 transition-colors group"
                >
                  <div className={`w-2.5 h-2.5 rounded-full mt-1.5 flex-shrink-0 ${SEVERITY_DOT[i.severity] || 'bg-slate-400'}`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-700 truncate group-hover:text-violet-700">
                      {i.title.replace('[SIMULATION] ', '')}
                    </p>
                    <p className="text-xs text-slate-400 mt-1">
                      <StatusBadge value={i.status} />
                      <span className="ml-2 font-mono">{fmtTime(i.created_at)}</span>
                    </p>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Platform metrics row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="MTTR"
          value={data.mttr_hours != null ? `${data.mttr_hours.toFixed(1)}h` : '—'}
          icon={Clock}
          color="sky"
          sub="Mean Time To Resolve"
        />
        <MetricCard
          label="Auto-Remediation"
          value={pct(data.auto_remediation_rate)}
          icon={Zap}
          color="green"
          sub="Resolved autonomously"
        />
        <MetricCard
          label="Success Rate"
          value={pct(data.remediation_success_rate)}
          icon={TrendingUp}
          color="purple"
          sub="Remediation success"
        />
        <MetricCard
          label="Rollback Rate"
          value={pct(data.rollback_rate)}
          icon={RotateCcw}
          color={data.rollback_rate > 0.3 ? 'rose' : 'amber'}
          sub="Deployments rolled back"
        />
      </div>

      {/* Recent activity + pipeline health */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Activity feed */}
        <div className="card">
          <p className="card-title mb-3">Recent Activity</p>
          {data.recent_actions.length === 0 ? (
            <p className="text-sm text-slate-400">No recent actions.</p>
          ) : (
            <div className="space-y-2">
              {data.recent_actions.slice(0, 8).map((a, idx) => (
                <div key={idx} className="flex items-start gap-3">
                  <div className={`w-1.5 h-1.5 rounded-full mt-2 flex-shrink-0 ${
                    a.outcome === 'SUCCESS'  ? 'bg-emerald-400' :
                    a.outcome === 'FAILURE'  ? 'bg-rose-400' : 'bg-slate-300'
                  }`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-700 leading-snug truncate">{a.description}</p>
                    <p className="text-[10px] text-slate-400 mt-0.5 font-mono">
                        {a.actor} · {fmtTime(a.occurred_at)}
                      </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Pipeline health */}
        <div className="card">
          <p className="card-title mb-3">Pipeline Health</p>
          <div className="mb-3">
            <div className="flex items-center justify-between text-xs text-slate-500 mb-1.5">
              <span>Success rate (last 20 runs)</span>
              <span className={`font-semibold ${
                data.recent_pipeline_success_rate >= 0.9 ? 'text-emerald-600' :
                data.recent_pipeline_success_rate >= 0.7 ? 'text-amber-600' : 'text-rose-600'
              }`}>
                {pct(data.recent_pipeline_success_rate)}
              </span>
            </div>
            <div className="h-2.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  data.recent_pipeline_success_rate >= 0.9 ? 'bg-emerald-400' :
                  data.recent_pipeline_success_rate >= 0.7 ? 'bg-amber-400' : 'bg-rose-400'
                }`}
                style={{ width: `${(data.recent_pipeline_success_rate * 100).toFixed(1)}%` }}
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 mt-4">
            <div className="bg-slate-50 rounded-xl p-3">
              <p className="text-xs text-slate-500">MTTD</p>
              <p className="text-lg font-bold text-slate-700 mt-0.5">
                {data.mttd_minutes != null ? `${data.mttd_minutes.toFixed(1)}m` : '—'}
              </p>
              <p className="text-[10px] text-slate-400">Mean Time To Detect</p>
            </div>
            <div className="bg-slate-50 rounded-xl p-3">
              <p className="text-xs text-slate-500">Total Incidents</p>
              <p className="text-lg font-bold text-slate-700 mt-0.5">{data.total_incidents}</p>
              <p className="text-[10px] text-slate-400">{data.resolved_today} resolved today</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
