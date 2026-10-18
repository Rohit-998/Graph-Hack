import { useEffect, useState } from 'react'
import { api, type WorldInfo } from '../api'
import type { IncidentDetail, LlmStatus, Topology } from '../api'

function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(t)
  }, [ms])
  return now
}

function clock(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(s / 3600)
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

// Tightest SLA among impacted customers -> allowed downtime per 30-day month.
function slaBudgetMs(slas: number[]) {
  if (!slas.length) return null
  const sla = Math.max(...slas)
  return (1 - sla / 100) * 30 * 24 * 3600 * 1000
}

export function Logo() {
  return (
    <div className="flex items-center gap-3">
      <svg viewBox="0 0 40 40" className="h-9 w-9" aria-hidden>
        <path
          d="M14 4h12v6h6a4 4 0 0 1 4 4v12a4 4 0 0 1-4 4h-6v6H14v-6H8a4 4 0 0 1-4-4V14a4 4 0 0 1 4-4h6z"
          fill="none"
          stroke="#e8bd78"
          strokeWidth="2"
        />
        <path d="M20 11c1.5 4-1.5 6-2.5 8s-1 4 .5 5.5c-2.5-.5-4-2.5-4-5 0-4 4-5.5 6-8.5zm1 5c3 2 5 4.5 5 7.5a6 6 0 0 1-6 6c2.5-2 3.5-5 1-13.5z" fill="#f3d199" />
      </svg>
      <div className="leading-tight">
        <div className="text-[15px] font-semibold text-gold">Firebreak</div>
        <div className="text-[12px] text-ink">Incident Commander</div>
      </div>
    </div>
  )
}

export function LlmBadge({ llm }: { llm: LlmStatus | null }) {
  if (!llm) return null
  const on = llm.enabled
  const title = on
    ? `${llm.provider} · ${llm.keys} key(s)\n${llm.calls} calls · ${llm.cached} cached · ${llm.rate_limited} rate-limited` +
      (llm.last_error ? `\nlast error: ${llm.last_error}` : '') +
      '\nThe graph decides root causes; the LLM only writes prose.'
    : 'No LLM configured. Verdicts and prose come from graph engines and templates.\nThe graph decides root causes either way.'
  return (
    <div className="tool-group items-center px-3" title={title} role="status" aria-label="LLM status">
      <span
        className={`h-2 w-2 rounded-full ${on ? (llm.last_error ? 'bg-warn' : 'bg-ok') : 'bg-muted'}`}
        aria-hidden
      />
      <span className="ml-2 font-mono text-[11px] text-ink">{on ? llm.model : 'deterministic'}</span>
      {on && <span className="ml-2 font-mono text-[10px] text-muted">{llm.calls} calls</span>}
    </div>
  )
}

export function WorldSwitch({ topology, onSwitched }: { topology: Topology | null; onSwitched: () => void }) {
  const [worlds, setWorlds] = useState<WorldInfo[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    api.worlds().then((w) => setWorlds(w.worlds)).catch(() => setWorlds([]))
  }, [topology?.world?.name])
  const current = topology?.world
  return (
    <div className="tool-group items-center gap-2 px-3" title="Each company lives in its own FalkorDB graph">
      <svg viewBox="0 0 24 24" className="h-4 w-4 text-teal" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" />
      </svg>
      {worlds.length > 1 ? (
        <select
          aria-label="Company graph"
          disabled={busy}
          value={current?.name ?? ''}
          onChange={async (e) => {
            setBusy(true)
            setErr(null)
            try {
              await api.activateWorld(e.target.value)
              onSwitched()
            } catch (x) {
              setErr((x as Error).message)
            } finally {
              setBusy(false)
            }
          }}
          className="bg-transparent text-[12px] text-ink outline-none [&>option]:bg-panel"
        >
          {worlds.map((w) => (
            <option key={w.name} value={w.name}>
              {w.label}
            </option>
          ))}
        </select>
      ) : (
        <span className="text-[12px]">{current?.label ?? '…'}</span>
      )}
      <span className="font-mono text-[10px] text-muted" aria-live="polite">
        {busy ? 'switching…' : err ? <span className="text-bad">{err}</span> : current?.graph}
      </span>
    </div>
  )
}

function Kpi({ label, value, tone, title, icon }: { label: string; value: string; tone?: string; title?: string; icon?: string }) {
  return (
    <div className="min-w-0 flex-1 px-3 py-1.5" title={title}>
      <div className="truncate text-[11px] text-muted">{label}</div>
      <div className={`font-display mt-0.5 flex items-baseline gap-1 whitespace-nowrap text-[18px] ${tone ?? 'text-ink'}`}>
        {icon && <span className="text-[12px] text-gold" aria-hidden>{icon}</span>}
        {value}
      </div>
    </div>
  )
}

/** The impact strip: incident KPIs while something is burning, graph stats otherwise. */
export function KpiStrip({ topology, incident }: { topology: Topology | null; incident: IncidentDetail | null }) {
  const now = useNow()
  const active = incident && incident.status !== 'resolved'
  const down = topology?.nodes.filter((n) => n.status !== 'healthy').length ?? 0
  const impact = incident?.impact
  const end = incident?.mitigated_at ?? incident?.resolved_at ?? now
  const elapsed = incident ? end - incident.started_at : 0
  const budget = slaBudgetMs(impact?.customers.map((c) => c.sla) ?? [])
  const sevTone = incident?.severity === 'SEV1' ? 'text-bad' : incident?.severity === 'SEV2' ? 'text-warn' : 'text-ink'

  if (!active) {
    return (
      <div className="flex items-center divide-x divide-white/5" role="status" aria-live="polite">
        <div className="flex items-center gap-2 px-4 py-2 text-[13px] text-ok">
          <span aria-hidden>●</span> All systems operational
        </div>
        {topology && (
          <>
            <Kpi label="Components" value={String(topology.stats.components)} icon="◉" />
            <Kpi label="People" value={String(topology.stats.people)} icon="◎" />
            <Kpi label="Customers" value={String(topology.stats.customers)} icon="◈" />
            <Kpi
              label="Incidents"
              value={String(topology.stats.incidents)}
              icon="◇"
              title="…all in one FalkorDB graph"
            />
          </>
        )}
      </div>
    )
  }
  return (
    <div className="grid grid-cols-4 gap-y-1 [&>*]:border-white/5 [&>*:not(:nth-child(4n+1))]:border-l" role="status" aria-live="polite">
      <Kpi label="Incident" value={incident.id} />
      <Kpi label="Severity" value={incident.severity} tone={sevTone} />
      <Kpi label="Status" value={incident.status} tone="text-warn" />
      <Kpi label="Unhealthy" value={`${down} / ${topology?.nodes.length ?? 0}`} tone="text-bad" />
      <Kpi label="Customers hit" value={String(impact?.customers.length ?? '…')} />
      <Kpi
        label="GMV at risk"
        value={impact ? `$${Math.round(impact.gmv_per_hour).toLocaleString()}/h` : '…'}
        tone="text-bad"
        title="Sum of USES.gmv_per_hour_usd for customers whose products reach the root cause"
      />
      <Kpi label="Elapsed" value={clock(elapsed)} />
      {budget !== null && (
        <Kpi
          label="SLA budget left"
          value={clock(budget - elapsed)}
          tone={budget - elapsed < budget / 3 ? 'text-bad' : 'text-warn'}
          title="Monthly downtime allowed by the strictest impacted customer SLA, minus elapsed"
        />
      )}
    </div>
  )
}
