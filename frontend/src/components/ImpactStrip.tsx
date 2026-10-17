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
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

// Tightest SLA among impacted customers -> allowed downtime per 30-day month.
function slaBudgetMs(slas: number[]) {
  if (!slas.length) return null
  const sla = Math.max(...slas)
  return (1 - sla / 100) * 30 * 24 * 3600 * 1000
}

function Stat({ label, value, tone, title }: { label: string; value: string; tone?: string; title?: string }) {
  return (
    <div className="flex flex-col px-4" title={title}>
      <span className="text-[10px] uppercase tracking-wider text-muted">{label}</span>
      <span className={`font-mono text-[15px] ${tone ?? 'text-ink'}`}>{value}</span>
    </div>
  )
}

function LlmBadge({ llm }: { llm: LlmStatus | null }) {
  if (!llm) return null
  const on = llm.enabled
  const title = on
    ? `${llm.provider} · ${llm.keys} key(s)\n${llm.calls} calls · ${llm.cached} cached · ${llm.rate_limited} rate-limited` +
      (llm.last_error ? `\nlast error: ${llm.last_error}` : '') +
      '\nRoot cause is always decided by the graph; the LLM only writes prose.'
    : 'No LLM configured. Verdicts and prose come from graph engines and templates.'
  return (
    <div className="ml-auto flex items-center gap-2 px-4" title={title}>
      <span className={`h-2 w-2 rounded-full ${on ? (llm.last_error ? 'bg-warn' : 'bg-ok') : 'bg-muted'}`} aria-hidden />
      <span className="font-mono text-[11px] text-muted">{on ? llm.model : 'deterministic'}</span>
      {on && <span className="font-mono text-[10px] text-muted">{llm.calls} calls</span>}
    </div>
  )
}

function WorldSwitch({ topology, onSwitched }: { topology: Topology | null; onSwitched: () => void }) {
  const [worlds, setWorlds] = useState<WorldInfo[]>([])
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api.worlds().then((w) => setWorlds(w.worlds)).catch(() => setWorlds([]))
  }, [])
  const current = topology?.world
  if (worlds.length < 2) {
    return <div className="text-[10px] text-muted">{current?.label ?? '…'} · {current?.graph}</div>
  }
  return (
    <label className="flex items-center gap-1 text-[10px] text-muted" title="Each company lives in its own FalkorDB graph">
      <select
        aria-label="Company graph"
        disabled={busy}
        value={current?.name ?? ''}
        onChange={async (e) => {
          setBusy(true)
          try {
            await api.activateWorld(e.target.value)
            onSwitched()
          } finally {
            setBusy(false)
          }
        }}
        className="rounded border border-line bg-panel-2 px-1 py-0.5 text-[10px] text-ink"
      >
        {worlds.map((w) => (
          <option key={w.name} value={w.name}>
            {w.label}
          </option>
        ))}
      </select>
      <span className="font-mono">{busy ? 'seeding…' : current?.graph}</span>
    </label>
  )
}

export function ImpactStrip({ topology, incident, llm, onWorldSwitched }: {
  topology: Topology | null
  incident: IncidentDetail | null
  llm: LlmStatus | null
  onWorldSwitched: () => void
}) {
  const now = useNow()
  const active = incident && incident.status !== 'resolved'
  const down = topology?.nodes.filter((n) => n.status !== 'healthy').length ?? 0
  const impact = incident?.impact
  const end = incident?.mitigated_at ?? incident?.resolved_at ?? now
  const elapsed = incident ? end - incident.started_at : 0
  const budget = slaBudgetMs(impact?.customers.map((c) => c.sla) ?? [])

  const sevTone = incident?.severity === 'SEV1' ? 'text-bad' : incident?.severity === 'SEV2' ? 'text-warn' : 'text-ink'

  return (
    <header className="flex h-14 items-center border-b border-line bg-panel">
      <div className="flex items-center gap-2 px-4">
        <div className="flex h-7 w-7 items-center justify-center rounded bg-bad/15 text-bad">
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden>
            <path d="M12 2c1 3-1 5-2 6.5S8 12 8 14a4 4 0 0 0 8 0c0-1.5-.6-2.6-1.4-3.6.1 1.5-.6 2.6-1.6 2.6 1-3-1-5 -1-11z" />
          </svg>
        </div>
        <div className="leading-tight">
          <div className="text-[14px] font-semibold">Firebreak</div>
          <WorldSwitch topology={topology} onSwitched={onWorldSwitched} />
        </div>
      </div>
      <div className="mx-2 h-8 w-px bg-line" />

      {active ? (
        <>
          <Stat label="Incident" value={incident.id} />
          <Stat label="Severity" value={incident.severity} tone={sevTone} />
          <Stat label="Status" value={incident.status} tone="text-warn" />
          <Stat label="Unhealthy" value={`${down} / ${topology?.nodes.length ?? 0}`} tone="text-bad" />
          <Stat label="Customers hit" value={String(impact?.customers.length ?? '…')} />
          <Stat
            label="GMV at risk"
            value={impact ? `$${Math.round(impact.gmv_per_hour).toLocaleString()}/hr` : '…'}
            tone="text-bad"
            title="Sum of USES.gmv_per_hour_usd for customers whose products reach the root cause"
          />
          <Stat label="Elapsed" value={clock(elapsed)} />
          {budget !== null && (
            <Stat
              label="SLA budget left"
              value={clock(budget - elapsed)}
              tone={budget - elapsed < budget / 3 ? 'text-bad' : 'text-warn'}
              title="Monthly downtime allowed by the strictest impacted SLA"
            />
          )}
        </>
      ) : (
        <div className="flex items-center gap-2 px-4 text-[13px] text-ok">
          <span aria-hidden>●</span> All systems operational
          {topology && (
            <span className="ml-4 text-muted">
              {topology.stats.components} components · {topology.stats.people} people · {topology.stats.customers}{' '}
              customers · {topology.stats.incidents} incidents in one FalkorDB graph
            </span>
          )}
        </div>
      )}
      <LlmBadge llm={llm} />
    </header>
  )
}
