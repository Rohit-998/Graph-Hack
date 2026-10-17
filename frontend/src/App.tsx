import { useCallback, useEffect, useRef, useState } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import type { Investigation } from './api'
import { api, type IncidentDetail, type LlmStatus, type Scenario, type Topology } from './api'
import { ServiceMap } from './components/ServiceMap'
import { ImpactStrip } from './components/ImpactStrip'
import { AgentRoom } from './components/AgentRoom'
import { VerdictCard } from './components/VerdictCard'
import { ChaosLab } from './components/ChaosLab'
import { AskPanel } from './components/AskPanel'
import { MemoryPanel } from './components/MemoryPanel'
import { SpofPanel } from './components/SpofPanel'

const POLL_MS = 2000
const HOP_MS = 450

export default function App() {
  const [topology, setTopology] = useState<Topology | null>(null)
  const [llm, setLlm] = useState<LlmStatus | null>(null)
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [incidentId, setIncidentId] = useState<string | null>(null)
  const [incident, setIncident] = useState<IncidentDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [askOpen, setAskOpen] = useState(false)
  const [memoryOpen, setMemoryOpen] = useState(false)
  const [spofOpen, setSpofOpen] = useState(false)
  const [heat, setHeat] = useState<Record<string, number>>({})
  const [secondOpinion, setSecondOpinion] = useState<Investigation | null>(null)
  const [cited, setCited] = useState<string[]>([])
  const [pathShown, setPathShown] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const hopTimer = useRef<number | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [t, list, l] = await Promise.all([api.topology(), api.incidents(), api.llm()])
      setTopology(t)
      setLlm(l)
      // Follow the newest incident that is still open, else keep showing the one we had.
      const live = list.find((i) => i.status !== 'resolved')
      const id = live?.id ?? incidentId
      if (id !== incidentId) setIncidentId(id ?? null)
      if (id) setIncident(await api.incident(id))
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [incidentId])

  useEffect(() => {
    api.scenarios().then(setScenarios).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, POLL_MS)
    return () => clearInterval(t)
  }, [refresh])

  // Betweenness heat for the SPOF overlay; refreshed when it is switched on.
  const toggleHeat = useCallback(async (on: boolean) => {
    if (!on) return setHeat({})
    const rows = await api.spof()
    const max = Math.max(...rows.map((r) => r.betweenness), 1)
    setHeat(Object.fromEntries(rows.map((r) => [r.component, r.betweenness / max])))
  }, [])

  const showPath = useCallback(() => {
    const n = incident?.evidence_path?.length ?? 0
    if (hopTimer.current) clearInterval(hopTimer.current)
    setPathShown(1)
    let k = 1
    hopTimer.current = window.setInterval(() => {
      k += 1
      setPathShown(k)
      if (k >= n && hopTimer.current) clearInterval(hopTimer.current)
    }, HOP_MS)
  }, [incident?.evidence_path?.length])

  // Reset per-incident overlays when the incident changes.
  useEffect(() => {
    setPathShown(0)
    setSecondOpinion(null)
  }, [incidentId])

  const inject = useCallback(
    async (id: string, decoy: boolean) => {
      setBusy(true)
      setCited([])
      try {
        const out = await api.inject(id, decoy)
        if (out.incident) setIncidentId(out.incident)
        await refresh()
      } catch (e) {
        setError((e as Error).message)
      } finally {
        setBusy(false)
      }
    },
    [refresh],
  )

  const reset = useCallback(async () => {
    setBusy(true)
    try {
      await api.reset()
      setIncidentId(null)
      setIncident(null)
      setCited([])
      await refresh()
    } finally {
      setBusy(false)
    }
  }, [refresh])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setAskOpen((o) => !o)
        return
      }
      const typing = (e.target as HTMLElement)?.tagName === 'INPUT'
      if (typing || askOpen || busy) return
      const n = Number(e.key)
      if (n >= 1 && n <= scenarios.length) inject(scenarios[n - 1].id, true)
      if (e.key.toLowerCase() === 'e' && incident?.evidence_path) showPath()
      if (e.key.toLowerCase() === 'm') setMemoryOpen((o) => !o)
      if (e.key.toLowerCase() === 's') setSpofOpen((o) => !o)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [askOpen, busy, scenarios, inject, incident, showPath])

  const alerting = incident && incident.status !== 'resolved' ? incident.alerts.map((a) => a.component) : []
  const path = incident?.evidence_path?.slice(0, pathShown) ?? []
  const cause = pathShown > 0 && pathShown >= (incident?.evidence_path?.length ?? 0) ? incident?.root_cause?.component ?? null : null
  const sel = topology?.nodes.find((n) => n.id === selected)

  return (
    <div className="flex h-full flex-col">
      <ImpactStrip topology={topology} incident={incident} llm={llm} />

      <div className="flex min-h-0 flex-1">
        <main className="relative min-w-0 flex-1">
          {topology ? (
            <ReactFlowProvider>
              <ServiceMap
                topology={topology}
                alerting={alerting}
                evidencePath={path}
                cause={cause}
                cited={cited}
                heat={heat}
                onSelect={setSelected}
              />
            </ReactFlowProvider>
          ) : (
            <div className="flex h-full items-center justify-center text-[13px] text-muted">
              {error ? `Backend unreachable: ${error}` : 'Loading graph…'}
            </div>
          )}

          <div className="absolute left-3 top-3">
            <ChaosLab scenarios={scenarios} busy={busy} onInject={inject} onReset={reset} />
          </div>

          <MemoryPanel open={memoryOpen} onClose={() => setMemoryOpen(false)} />
          <SpofPanel
            open={spofOpen}
            onClose={() => setSpofOpen(false)}
            shade={Object.keys(heat).length > 0}
            onToggleShade={toggleHeat}
            onSelect={setSelected}
          />

          {sel && !memoryOpen && (
            <div className="absolute right-3 top-3 w-[240px] rounded-lg border border-line bg-panel/95 p-3 text-[12px] shadow-xl">
              <div className="flex items-center">
                <span className="font-mono">{sel.id}</span>
                <button onClick={() => setSelected(null)} className="ml-auto text-muted hover:text-ink" aria-label="Close">
                  ×
                </button>
              </div>
              <p className="mt-1 text-muted">{sel.description}</p>
              <dl className="mt-2 grid grid-cols-2 gap-y-0.5 text-[11px]">
                <dt className="text-muted">Owner</dt>
                <dd>{sel.team}</dd>
                <dt className="text-muted">Tier</dt>
                <dd>{sel.tier}</dd>
                <dt className="text-muted">Status</dt>
                <dd>{sel.status}</dd>
                <dt className="text-muted">p95</dt>
                <dd className="font-mono">{sel.p95_ms}ms</dd>
                <dt className="text-muted">Errors</dt>
                <dd className="font-mono">{(sel.error_rate * 100).toFixed(2)}%</dd>
              </dl>
            </div>
          )}

          <div className="absolute bottom-3 right-3 flex gap-2 text-[10px] text-muted">
            <button
              onClick={() => setAskOpen(true)}
              className="rounded border border-line bg-panel px-2 py-1 text-[11px] text-ink hover:border-detective"
            >
              Ask Firebreak <kbd className="ml-1 font-mono text-muted">Ctrl K</kbd>
            </button>
            {cited.length > 0 && (
              <button onClick={() => setCited([])} className="rounded border border-line bg-panel px-2 py-1">
                clear highlight
              </button>
            )}
            <button
              onClick={() => setSpofOpen((o) => !o)}
              className="rounded border border-line bg-panel px-2 py-1 text-[11px] text-ink hover:border-warn"
            >
              SPOF <kbd className="ml-1 font-mono text-muted">S</kbd>
            </button>
            <button
              onClick={() => setMemoryOpen((o) => !o)}
              className="rounded border border-line bg-panel px-2 py-1 text-[11px] text-ink hover:border-ok"
            >
              Memory <kbd className="ml-1 font-mono text-muted">M</kbd>
            </button>
          </div>
        </main>

        <aside className="flex w-[440px] shrink-0 flex-col border-l border-line bg-panel">
          {incident && (incident.root_cause || incident.status !== 'resolved') && (
            <div className="max-h-[58%] shrink-0 overflow-y-auto border-b border-line p-2">
              <VerdictCard
                incident={incident}
                showingPath={pathShown > 0}
                onShowPath={showPath}
                llmEnabled={!!llm?.enabled}
                secondOpinion={secondOpinion}
                onSecondOpinion={async () => {
                  if (incident) setSecondOpinion(await api.llmInvestigate(incident.id))
                }}
                onApprove={async (id) => {
                  await api.approve(id)
                  await refresh()
                }}
                onReject={async (id) => {
                  await api.reject(id)
                  await refresh()
                }}
              />
            </div>
          )}
          <div className="min-h-0 flex-1">
            <AgentRoom steps={incident?.steps ?? []} hypotheses={incident?.hypotheses ?? []} />
          </div>
        </aside>
      </div>

      <AskPanel open={askOpen} onClose={() => setAskOpen(false)} onCite={setCited} />
    </div>
  )
}
