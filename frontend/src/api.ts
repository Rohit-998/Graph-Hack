// Typed client for the Firebreak backend. All data comes from FalkorDB via the API.

export type Status = 'healthy' | 'degraded' | 'down'

export interface TopoNode {
  id: string
  kind: string
  tier: number
  status: Status
  lagging: boolean | null
  error_rate: number
  p95_ms: number
  customer_facing: boolean
  description: string
  team: string
}

export interface TopoEdge {
  source: string
  target: string
  mode: 'sync' | 'async'
  protocol: string
}

export interface Topology {
  nodes: TopoNode[]
  edges: TopoEdge[]
  stats: { components: number; people: number; customers: number; incidents: number }
}

export interface Scenario {
  id: string
  title: string
  root: string
  remediation: string
  decoy: string
}

export interface IncidentSummary {
  id: string
  title: string
  severity: string
  status: string
  started_at: number
  resolved_at: number | null
  confidence: number | null
}

export interface AgentStep {
  id: string
  agent: 'commander' | 'detective' | 'responder'
  tool: string
  cypher: string
  summary: string
  duration_ms: number
  model: string
  ts: number
}

export interface Hypothesis {
  id: string
  statement: string
  confidence: number
  status: 'proposed' | 'accepted' | 'rejected'
  proposed_by: string
  breakdown: Record<string, number> | null
  change: string | null
  component: string | null
}

export interface Action {
  id: string
  kind: string
  target: string
  status: string
  reason: string
  proposed_by: string
  approved_by: string | null
  result: string | null
}

export interface Person {
  id: string
  name: string
  title?: string
  level?: number
  score?: number
  reasons?: string[]
}

export interface Responders {
  team: string | null
  channel: string | null
  on_call: Person[]
  escalation: string[]
  experts: Person[]
  author: string | null
}

export interface Impact {
  customers: { id: string; customer: string; tier: string; sla: number; products: string[]; gmv_per_hour: number }[]
  gmv_per_hour: number
  blast_radius: { component: string; tier: number; hops: number; impact: string }[]
}

export interface IncidentDetail {
  id: string
  title: string
  summary: string
  severity: string
  status: string
  started_at: number
  identified_at?: number
  mitigated_at?: number
  resolved_at?: number
  confidence?: number
  breakdown?: Record<string, number>
  evidence_path?: string[]
  impact?: Impact
  responders?: Responders
  alerts: { id: string; component: string; rule: string; value: number; status: string; ts: number }[]
  hypotheses: Hypothesis[]
  steps: AgentStep[]
  actions: Action[]
  narrative?: string
  seen_before?: string | null
  similar?: SimilarIncident[]
  ttrc_ms?: number
  postmortem: { id: string; body: string; model: string } | null
  root_cause: {
    id: string | null
    component: string
    kind: string | null
    summary: string | null
    author: string | null
    confidence: number
  } | null
}

export interface SimilarIncident {
  id: string
  title: string
  score: number
  similarity: number
  overlap_ratio: number
  rc_component: string | null
  rc_change: string | null
  actions: string[]
  ttm_min: number | null
}

export interface LlmStatus {
  enabled: boolean
  provider: string
  model: string
  keys: number
  calls: number
  cached: number
  failures: number
  rate_limited: number
  last_error: string | null
  last_latency_ms: number | null
}

export interface AskSource {
  type: string
  id: string
  title: string
  people: string[]
  components: string[]
  score: number
}

export interface AskAnswer {
  question: string
  query: string
  answer: string
  sources: AskSource[]
  highlight: string[]
  cypher?: string
  model: string
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'content-type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => req<{ ok: boolean; graph: string; llm: LlmStatus; embeddings: string }>('/health'),
  llm: () => req<LlmStatus>('/llm'),
  topology: () => req<Topology>('/topology'),
  scenarios: () => req<Scenario[]>('/scenarios'),
  incidents: () => req<IncidentSummary[]>('/incidents'),
  incident: (id: string) => req<IncidentDetail>(`/incidents/${id}`),
  inject: (scenario: string, with_decoy = true) =>
    req<{ incident?: string }>('/chaos/inject', { method: 'POST', body: JSON.stringify({ scenario, with_decoy }) }),
  reset: () => req<{ unhealthy: Record<string, string> }>('/chaos/reset', { method: 'POST' }),
  approve: (id: string) => req<{ result: string }>(`/actions/${id}/approve`, { method: 'POST', body: '{}' }),
  reject: (id: string) => req<{ status: string }>(`/actions/${id}/reject`, { method: 'POST', body: '{}' }),
  ask: (question: string) => req<AskAnswer>('/ask', { method: 'POST', body: JSON.stringify({ question }) }),
}
