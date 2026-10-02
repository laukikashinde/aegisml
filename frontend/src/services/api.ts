import axios, { AxiosInstance } from 'axios'

// In dev mode, use relative URL so Vite proxy handles CORS.
// In production, use the configured base URL.
const API_BASE = import.meta.env.DEV
  ? ''  // empty string = relative, goes through Vite proxy
  : (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000')

const client: AxiosInstance = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': import.meta.env.VITE_API_KEY || 'dev-api-key-change-in-production',
  },
  timeout: 120_000,
})

// ── Types ─────────────────────────────────────────────────────────────────────

export interface IncidentSummary {
  id: string
  title: string
  incident_type: string
  severity: string
  status: string
  source: string
  affected_model: string | null
  affected_feature: string | null
  is_simulation: boolean
  created_at: string
  resolved_at: string | null
}

export interface TimelineEvent {
  id: number
  event_type: string
  description: string
  details: Record<string, unknown> | null
  occurred_at: string
}

export interface IncidentDetail extends IncidentSummary {
  affected_pipeline: string | null
  observed_metrics: Record<string, unknown> | null
  diagnosis: string | null
  root_cause: string | null
  confidence: number | null
  recommended_action: string | null
  risk_level: string | null
  requires_human_approval: boolean
  agent_evidence: unknown[] | null
  verification_plan: string[] | null
  remediation_status: string | null
  verification_status: string | null
  resolution_notes: string | null
  simulation_type: string | null
  timeline: TimelineEvent[]
}

export interface ModelVersion {
  id: number
  model_name: string
  version: number
  stage: string
  f1_score: number | null
  accuracy: number | null
  precision: number | null
  recall: number | null
  roc_auc: number | null
  avg_latency_ms: number | null
  dataset_version: string | null
  quality_gate_passed: boolean | null
  created_at: string
  promoted_at: string | null
}

export interface PipelineRun {
  id: string
  pipeline_name: string
  status: string
  trigger: string
  dataset_version: string | null
  duration_seconds: number | null
  error_stage: string | null
  error_message: string | null
  started_at: string
  completed_at: string | null
}

export interface Approval {
  id: string
  incident_id: string
  action_type: string
  risk_level: string
  status: string
  description: string
  context: Record<string, unknown> | null
  requested_by: string
  decided_by: string | null
  created_at: string
  expires_at: string | null
}

export interface AuditEntry {
  id: number
  event_type: string
  actor: string
  incident_id: string | null
  resource_type: string | null
  description: string
  outcome: string | null
  occurred_at: string
}

export interface DashboardData {
  active_incidents: number
  resolved_today: number
  total_incidents: number
  production_model_version: number | null
  production_f1: number | null
  latest_drift_score: number | null
  drift_detected: boolean
  recent_pipeline_success_rate: number
  mttr_hours: number | null
  mttd_minutes: number | null
  auto_remediation_rate: number
  remediation_success_rate: number
  rollback_rate: number
  open_approvals: number
  recent_incidents: IncidentSummary[]
  recent_actions: Array<{
    event_type: string
    actor: string
    description: string
    outcome: string | null
    occurred_at: string
  }>
}

export interface Deployment {
  id: string
  model_version_id: number
  status: string
  canary_traffic_percent: number
  is_production: boolean
  is_canary: boolean
  canary_error_rate: number | null
  canary_latency_ms: number | null
  started_at: string
  completed_at: string | null
}

// ── API functions ─────────────────────────────────────────────────────────────

export const api = {
  // Dashboard
  getDashboard: () => client.get<DashboardData>('/api/dashboard').then(r => r.data),

  // Incidents
  getIncidents: (params?: Record<string, string>) =>
    client.get<IncidentSummary[]>('/api/incidents', { params }).then(r => r.data),
  getIncident: (id: string) =>
    client.get<IncidentDetail>(`/api/incidents/${id}`).then(r => r.data),
  simulateIncident: (type: string, parameters?: Record<string, unknown>) =>
    client.post('/api/incidents/simulate', { simulation_type: type, parameters }).then(r => r.data),
  investigateIncident: (id: string) =>
    client.post(`/api/incidents/${id}/investigate`).then(r => r.data),
  remediateIncident: (id: string) =>
    client.post(`/api/incidents/${id}/remediate`).then(r => r.data),
  approveIncident: (id: string, decidedBy?: string, reason?: string) =>
    client.post(`/api/incidents/${id}/approve`, {
      decided_by: decidedBy || 'operator',
      reason: reason || '',
    }).then(r => r.data),
  rejectIncident: (id: string, decidedBy?: string, reason?: string) =>
    client.post(`/api/incidents/${id}/reject`, {
      decided_by: decidedBy || 'operator',
      reason: reason || '',
    }).then(r => r.data),

  // Models
  getModels: () => client.get<ModelVersion[]>('/api/models').then(r => r.data),
  getModel: (id: number) => client.get<ModelVersion>(`/api/models/${id}`).then(r => r.data),
  getCanaryStatus: () => client.get('/api/models/canary/status').then(r => r.data),
  getDeployments: () => client.get<Deployment[]>('/api/models/deployments/list').then(r => r.data),
  verifyCanary: (modelId: number) =>
    client.post(`/api/models/${modelId}/verify-canary`).then(r => r.data),

  // Pipelines
  getPipelines: () => client.get<PipelineRun[]>('/api/pipelines').then(r => r.data),
  getPipelineRun: (id: string) =>
    client.get(`/api/pipelines/${id}`).then(r => r.data),
  triggerRetrain: (datasetVersion = 'v1', incidentId?: string) =>
    client.post('/api/pipelines/retrain', {
      dataset_version: datasetVersion,
      incident_id: incidentId || null,
    }).then(r => r.data),

  // Monitoring
  getDrift: () => client.get('/api/monitoring/drift').then(r => r.data),
  getPerformance: () => client.get('/api/monitoring/performance').then(r => r.data),
  getLatestSnapshot: () => client.get('/api/monitoring/snapshots/latest').then(r => r.data),

  // Approvals
  getApprovals: (status?: string) =>
    client.get<Approval[]>('/api/approvals', { params: status ? { status } : {} }).then(r => r.data),
  approve: (id: string, decidedBy?: string, reason?: string) =>
    client.post(`/api/approvals/${id}/approve`, {
      decided_by: decidedBy || 'operator',
      reason: reason || '',
    }).then(r => r.data),
  reject: (id: string, decidedBy?: string, reason?: string) =>
    client.post(`/api/approvals/${id}/reject`, {
      decided_by: decidedBy || 'operator',
      reason: reason || '',
    }).then(r => r.data),

  // Audit
  getAuditLogs: (params?: { incident_id?: string; limit?: number }) =>
    client.get<AuditEntry[]>('/api/audit', { params }).then(r => r.data),

  // Stream simulator
  getStreamStatus: () => client.get('/api/stream/status').then(r => r.data),
  startStream: () => client.post('/api/stream/start').then(r => r.data),
  stopStream: () => client.post('/api/stream/stop').then(r => r.data),
  setStreamMode: (mode: string, drift_config?: Record<string, unknown>) =>
    client.post('/api/stream/mode', { mode, drift_config }).then(r => r.data),
  resetStream: () => client.post('/api/stream/reset').then(r => r.data),

  // Experiments
  getExperimentsSummary: () => client.get('/api/experiments/summary').then(r => r.data),
  getExperimentRuns: () => client.get('/api/experiments/runs').then(r => r.data),
  runS0: (failure_type: string, mttd_seconds: number) =>
    client.post('/api/experiments/s0/simulate', { failure_type, mttd_seconds }).then(r => r.data),
  runS1: (failure_type: string, mttd_seconds: number, schedule_interval_seconds: number, failure_actually_occurred: boolean) =>
    client.post('/api/experiments/s1/simulate', {
      failure_type, mttd_seconds, schedule_interval_seconds, failure_actually_occurred,
    }).then(r => r.data),

  // Incident report
  getIncidentReport: (id: string) =>
    client.get(`/api/reports/incident/${id}`).then(r => r.data),

  // Admin
  resetDemoData: () =>
    client.post('/api/admin/reset').then(r => r.data),
}
