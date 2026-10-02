import React, { useState, useEffect } from 'react'
import { FlaskConical, CheckCircle, ExternalLink, Play, RotateCcw } from 'lucide-react'
import { api } from '../services/api'
import { Link } from 'react-router-dom'

interface SimCard {
  id: string
  code: string
  title: string
  subtitle: string
  description: string
  colorClass: string
  badgeClass: string
  params: Record<string, unknown>
}

const SIMULATIONS: SimCard[] = [
  {
    id: 'DATA_DRIFT',
    code: 'F1',
    title: 'Covariate Drift',
    subtitle: 'Feature distribution shift',
    description:
      'Shifts age +8 years and hours_per_week ×1.3. ' +
      'Evidently detects distribution change → incident created → agent diagnoses → retraining recommended.',
    colorClass: 'bg-violet-50 border-violet-200',
    badgeClass: 'bg-violet-100 text-violet-700',
    params: { age_shift: 8, hours_scale: 1.3 },
  },
  {
    id: 'MODEL_DEGRADATION',
    code: 'F2',
    title: 'Concept Drift',
    subtitle: 'Feature-target relationship change',
    description:
      'Weakens education/hours → income correlation. ' +
      'Model F1 degrades without feature distribution shift. ' +
      'System distinguishes concept drift from covariate drift.',
    colorClass: 'bg-blue-50 border-blue-200',
    badgeClass: 'bg-blue-100 text-blue-700',
    params: { f1_drop: 0.10 },
  },
  {
    id: 'DEPLOYMENT_FAILURE',
    code: 'F3',
    title: 'Bad Deployment',
    subtitle: 'Canary health gate failure',
    description:
      'Deploys a degraded candidate model (F1 0.58) via canary. ' +
      'Error rate 18%, latency 450ms. ' +
      'Health gates fail → automatic rollback → previous model restored.',
    colorClass: 'bg-rose-50 border-rose-200',
    badgeClass: 'bg-rose-100 text-rose-700',
    params: { error_rate: 0.18, latency_ms: 450 },
  },
  {
    id: 'MISSING_DATA',
    code: 'F4',
    title: 'Data Quality Fault',
    subtitle: 'Malformed production records',
    description:
      '40% missing age, invalid age values (−5, 999), unknown workclass categories. ' +
      'Data validator detects schema violations → DATA_QUALITY incident.',
    colorClass: 'bg-amber-50 border-amber-200',
    badgeClass: 'bg-amber-100 text-amber-700',
    params: { missing_rate: 0.40, invalid_rate: 0.10, unknown_cat_rate: 0.15 },
  },
  {
    id: 'LATENCY_SPIKE',
    code: 'F5',
    title: 'Latency Spike',
    subtitle: 'SLA breach',
    description:
      'Injects 350ms extra inference delay. ' +
      'Average latency breaches 200ms SLA → LATENCY incident → service restart recommended.',
    colorClass: 'bg-sky-50 border-sky-200',
    badgeClass: 'bg-sky-100 text-sky-700',
    params: { extra_latency_ms: 350 },
  },
  {
    id: 'PIPELINE_FAILURE',
    code: 'F6',
    title: 'Pipeline Failure',
    subtitle: 'Training pipeline crash',
    description:
      'Injects a preprocessing failure (40% missing age). ' +
      'Pipeline aborts at validation stage → PIPELINE_FAILURE incident → retry logic triggered.',
    colorClass: 'bg-emerald-50 border-emerald-200',
    badgeClass: 'bg-emerald-100 text-emerald-700',
    params: { error_stage: 'preprocessing' },
  },
]

interface Result {
  simulation_id: string
  type: string
  incident_id?: string
  description: string
}

export default function Simulations() {
  const [running, setRunning] = useState<string | null>(null)
  const [results, setResults] = useState<Result[]>([])
  const [error, setError] = useState<string | null>(null)
  const [stream, setStream] = useState<any>(null)

  useEffect(() => {
    api.getStreamStatus().then(setStream).catch(() => null)
  }, [])

  const resetStream = async () => {
    await api.resetStream()
    const s = await api.getStreamStatus()
    setStream(s)
  }

  const run = async (sim: SimCard) => {
    setRunning(sim.id)
    setError(null)
    try {
      const result = await api.simulateIncident(sim.id, sim.params)
      setResults(prev => [{ type: sim.id, ...result }, ...prev])
      const s = await api.getStreamStatus()
      setStream(s)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Simulation failed')
    } finally {
      setRunning(null)
    }
  }

  return (
    <div className="p-7 space-y-6 max-w-6xl">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <FlaskConical className="w-6 h-6 text-violet-500" />
            Failure Simulations
          </h1>
          <p className="page-subtitle">
            Controlled failure injection — all simulations trigger real AegisML-Lite workflows.
          </p>
        </div>
        {stream?.mode !== 'NORMAL' && (
          <button onClick={resetStream} className="btn-secondary text-xs gap-1.5">
            <RotateCcw className="w-3.5 h-3.5" />
            Reset Stream
          </button>
        )}
      </div>

      {/* Simulation mode banner */}
      <div className="rounded-2xl px-5 py-3 bg-violet-50 border border-violet-200 flex items-center gap-3">
        <span className="w-2 h-2 rounded-full bg-violet-500" />
        <span className="text-sm font-medium text-violet-800">SIMULATION MODE</span>
        <span className="text-sm text-violet-600">— All incidents are labeled as simulations and trigger real self-healing workflows.</span>
        {stream && (
          <span className={`ml-auto text-xs font-semibold px-2.5 py-1 rounded-full ${
            stream.mode === 'NORMAL'
              ? 'bg-emerald-100 text-emerald-700'
              : 'bg-amber-100 text-amber-700'
          }`}>
            Stream: {stream.mode}
          </span>
        )}
      </div>

      {error && (
        <div className="rounded-2xl px-4 py-3 bg-rose-50 border border-rose-200 text-rose-600 text-sm">
          {error}
        </div>
      )}

      {/* Simulation cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {SIMULATIONS.map(sim => (
          <div key={sim.id} className={`rounded-2xl border p-5 space-y-3 ${sim.colorClass}`}>
            <div className="flex items-start justify-between">
              <div>
                <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold ${sim.badgeClass}`}>
                  {sim.code}
                </span>
                <h3 className="text-base font-semibold text-slate-800 mt-1.5">{sim.title}</h3>
                <p className="text-xs text-slate-500">{sim.subtitle}</p>
              </div>
            </div>

            <p className="text-sm text-slate-600 leading-relaxed">{sim.description}</p>

            <div className="bg-white/60 rounded-xl p-2.5">
              {Object.entries(sim.params).map(([k, v]) => (
                <div key={k} className="flex justify-between text-xs">
                  <span className="text-slate-500 font-mono">{k}</span>
                  <span className="text-slate-700 font-mono font-medium">{String(v)}</span>
                </div>
              ))}
            </div>

            <button
              onClick={() => run(sim)}
              disabled={running !== null}
              className={`w-full btn text-sm justify-center rounded-xl font-semibold ${
                running === sim.id
                  ? 'bg-slate-100 text-slate-400 cursor-wait'
                  : 'bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 shadow-sm hover:shadow-card-hover'
              }`}
            >
              {running === sim.id ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-slate-400 border-t-transparent rounded-full animate-spin" />
                  Running…
                </>
              ) : (
                <><Play className="w-3.5 h-3.5" /> Inject {sim.code}</>
              )}
            </button>
          </div>
        ))}
      </div>

      {/* Results */}
      {results.length > 0 && (
        <div className="card">
          <p className="card-title mb-3">Simulation Results</p>
          <div className="space-y-2">
            {results.map((r, i) => (
              <div key={i} className="flex items-start justify-between p-3 rounded-xl bg-slate-50 border border-slate-200">
                <div className="flex items-start gap-2.5">
                  <CheckCircle className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-sm font-medium text-slate-700">{r.type}</p>
                    <p className="text-xs text-slate-500 mt-0.5">{r.description}</p>
                  </div>
                </div>
                {r.incident_id && (
                  <Link
                    to={`/incidents/${r.incident_id}`}
                    className="btn-ghost text-xs ml-3 flex-shrink-0 text-violet-600"
                  >
                    <ExternalLink className="w-3 h-3" />
                    Incident
                  </Link>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
