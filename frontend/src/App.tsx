import { useCallback, useEffect, useRef, useState } from 'react'
import { ReactFlowProvider, useReactFlow } from '@xyflow/react'
import type { Investigation } from './api'
import { api, type IncidentDetail, type LlmStatus, type Scenario, type Topology } from './api'
import { ServiceMap } from './components/ServiceMap'
import { STATUS_ICON } from './status'
import { KpiStrip, LlmBadge, Logo, WorldSwitch } from './components/ImpactStrip'
import { AgentRoom } from './components/AgentRoom'
import { VerdictCard } from './components/VerdictCard'
import { ChaosLab } from './components/ChaosLab'
import { AskPanel } from './components/AskPanel'
import { MemoryPanel } from './components/MemoryPanel'
import { SpofPanel } from './components/SpofPanel'
import { runDemo } from './demo'
import { PreflightPanel } from './components/PreflightPanel'
import { KnowledgePanel } from './components/KnowledgePanel'

const POLL_MS = 2000
const HOP_MS = 450

function Icon({ d, className = 'h-4 w-4' }: { d: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <path d={d} />
    </svg>
  )
}

/** Floating toolbar: panel toggles + zoom, in the reference's grouped-pill style. */
function Toolbar(props: {
  chaos: boolean
  memory: boolean
  spof: boolean
  knowledge: boolean
  onChaos: () => void
  onMemory: () => void
  onSpof: () => void
  onKnowledge: () => void
  onAsk: () => void
}) {
  const { zoomIn, zoomOut, fitView } = useReactFlow()
  return (
    <nav className="flex items-center gap-2" aria-label="Tools">
      <div className="tool-group">
        <button className="tool-btn" aria-pressed={props.chaos} onClick={props.onChaos} title="Chaos lab">
          <Icon d="M13 2 4 14h7l-1 8 9-12h-7z" /> <span className="hidden xl:inline">Chaos</span>
        </button>
        <button className="tool-btn" aria-pressed={props.spof} onClick={props.onSpof} title="Single points of failure (S)">
          <Icon d="M12 3v4m0 10v4M3 12h4m10 0h4M12 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0-6 0" /> <span className="hidden xl:inline">SPOF</span>
          <kbd className="kbd">S</kbd>
        </button>
      </div>
      <div className="tool-group">
        <button className="tool-btn" onClick={() => zoomIn({ duration: 200 })} aria-label="Zoom in" title="Zoom in">
          <Icon d="M12 5v14M5 12h14" />
        </button>
        <button className="tool-btn" onClick={() => zoomOut({ duration: 200 })} aria-label="Zoom out" title="Zoom out">
          <Icon d="M5 12h14" />
        </button>
        <button className="tool-btn" onClick={() => fitView({ padding: 0.12, duration: 300 })} aria-label="Fit map" title="Fit map">
          <Icon d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
        </button>
      </div>
      <div className="tool-group">
        <button className="tool-btn" aria-pressed={props.memory} onClick={props.onMemory} title="Memory (M)">
          <Icon d="M12 3a7 7 0 0 0-4 12.7V19h8v-3.3A7 7 0 0 0 12 3zM9 22h6" /> <span className="hidden xl:inline">Memory</span>
          <kbd className="kbd">M</kbd>
        </button>
        <button className="tool-btn" aria-pressed={props.knowledge} onClick={props.onKnowledge} title="Knowledge (K)">
          <Icon d="M4 4h12l4 4v12H4zM8 10h8M8 14h8M8 18h5" /> <span className="hidden xl:inline">Knowledge</span>
          <kbd className="kbd">K</kbd>
        </button>
      </div>
      <div className="tool-group">
        <button className="tool-btn" onClick={props.onAsk} title="Ask / Query the graph (Ctrl K)">
          <Icon d="M4 5h16v11H8l-4 4zM8 10h8" /> <span className="hidden xl:inline">Ask</span>
          <kbd className="kbd">⌃K</kbd>
        </button>
      </div>
    </nav>
  )
}

function Legend() {
  const Dot = ({ cls }: { cls: string }) => <span className={`orb ${cls} inline-block h-3 w-3`} aria-hidden />
  return (
    <div className="glass-soft w-[196px] p-3 text-[11px]" role="region" aria-label="Legend">
      <div className="mb-2 text-[10px] uppercase tracking-[0.14em] text-muted">Legend</div>
      <ul className="space-y-1.5">
        <li className="flex items-center gap-2"><Dot cls="orb-healthy" /> {STATUS_ICON.healthy} Healthy</li>
        <li className="flex items-center gap-2"><Dot cls="orb-degraded" /> {STATUS_ICON.degraded} Degraded</li>
        <li className="flex items-center gap-2"><Dot cls="orb-down" /> {STATUS_ICON.down} Down</li>
        <li className="flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-full border border-gold/60" aria-hidden /> Customer-facing
        </li>
      </ul>
      <div className="my-2 h-px bg-white/5" />
      <ul className="space-y-1.5">
        <li className="flex items-center gap-2"><span className="inline-block h-px w-6 bg-gold/70" aria-hidden /> sync call</li>
        <li className="flex items-center gap-2">
          <span className="inline-block w-6 border-t border-dashed border-teal/80" aria-hidden /> async (lag only)
        </li>
        <li className="flex items-center gap-2"><span className="inline-block h-0.5 w-6 bg-bad shadow-[0_0_6px_#fb6f8a]" aria-hidden /> carrying fault</li>
        <li className="flex items-center gap-2"><span className="inline-block h-0.5 w-6 bg-[#f3d199] shadow-[0_0_6px_#e8bd78]" aria-hidden /> evidence path</li>
        <li className="flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-full border-2 border-teal" aria-hidden /> cited by an answer
        </li>
        <li className="flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-full bg-[radial-gradient(circle,#f6c35b,transparent_70%)]" aria-hidden /> betweenness heat
        </li>
      </ul>
    </div>
  )
}

function Loading({ error }: { error: string | null }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6" role="status" aria-live="polite">
      <div className="relative h-40 w-40">
        <div className="orbit" />
        <div className="orbit" style={{ inset: 18, animationDirection: 'reverse', animationDuration: '9s' }} />
        <div className="orb orb-degraded absolute inset-12" />
      </div>
      <div className="text-center">
        <div className="font-display text-[22px] text-ink">Waking up the graph…</div>
        <p className="mt-1 max-w-sm text-[12px] text-muted">
          The free server sleeps when idle; the first visit can take about a minute. This page keeps trying.
        </p>
        {error && <p className="mt-2 font-mono text-[11px] text-muted">last attempt: {error}</p>}
      </div>
    </div>
  )
}

function AskBar({ onAsk, onOpen }: { onAsk: (q: string) => void; onOpen: () => void }) {
  const [q, setQ] = useState('')
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (q.trim()) onAsk(q.trim())
        else onOpen()
        setQ('')
      }}
      className="flex items-center gap-2 rounded-full bg-[#e8f1ef] p-1.5 pl-5 shadow-[0_0_30px_rgb(95_217_204_/_0.15)]"
    >
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Ask the company brain, or query the graph…"
        aria-label="Ask a question"
        className="h-9 flex-1 bg-transparent text-[14px] text-[#0b1f22] outline-none placeholder:text-[#5f7a77]"
      />
      <button
        type="submit"
        aria-label="Ask"
        className="flex h-9 w-11 items-center justify-center rounded-full bg-[#0f2f33] text-teal hover:bg-[#143d42]"
      >
        <Icon d="M4 12h14m-5-6 6 6-6 6" />
      </button>
    </form>
  )
}

function Shell() {
  const [topology, setTopology] = useState<Topology | null>(null)
  const [llm, setLlm] = useState<LlmStatus | null>(null)
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [incidentId, setIncidentId] = useState<string | null>(null)
  const [incident, setIncident] = useState<IncidentDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [chaosOpen, setChaosOpen] = useState(true)
  const [askOpen, setAskOpen] = useState(false)
  const [memoryOpen, setMemoryOpen] = useState(false)
  const [spofOpen, setSpofOpen] = useState(false)
  const [knowledgeOpen, setKnowledgeOpen] = useState(false)
  const [heat, setHeat] = useState<Record<string, number>>({})
  const [secondOpinion, setSecondOpinion] = useState<Investigation | null>(null)
  const [caption, setCaption] = useState<{ text: string; sub?: string }>({ text: '' })
  const [demoRunning, setDemoRunning] = useState(false)
  const [pendingAsk, setPendingAsk] = useState<string | null>(null)
  const [preflightFor, setPreflightFor] = useState<string | null>(null)
  const [cited, setCited] = useState<string[]>([])
  const [pathShown, setPathShown] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const demoSignal = useRef({ aborted: false })
  const askDone = useRef<(() => void) | null>(null)
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

  // Scenarios load once the server answers (it may still be waking up on first visit).
  useEffect(() => {
    if (!topology || scenarios.length) return
    api.scenarios().then(setScenarios).catch((e) => setError(e.message))
  }, [topology, scenarios.length])

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

  const showPathRef = useRef(showPath)
  useEffect(() => {
    showPathRef.current = showPath
  }, [showPath])

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
      setSelected(null)
      setPreflightFor(null)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [refresh])

  const onWorldSwitched = useCallback(async () => {
    setIncidentId(null)
    setIncident(null)
    setCited([])
    setHeat({})
    setPreflightFor(null)
    setSelected(null)
    setMemoryOpen(false)
    setSpofOpen(false)
    setKnowledgeOpen(false)
    try {
      setScenarios(await api.scenarios())
    } catch (e) {
      setError((e as Error).message)
    }
    await refresh()
  }, [refresh])

  const openAsk = useCallback((question?: string) => {
    if (question) setPendingAsk(question)
    setAskOpen(true)
  }, [])

  const toggleDemo = useCallback(() => {
    if (demoRunning) {
      demoSignal.current.aborted = true
      setCaption({ text: '' })
      setDemoRunning(false)
      return
    }
    demoSignal.current = { aborted: false }
    setDemoRunning(true)
    setMemoryOpen(false)
    setSpofOpen(false)
    setKnowledgeOpen(false)
    setPreflightFor(null)
    setSelected(null)
    setAskOpen(false)
    runDemo({
      caption: (text, sub) => setCaption({ text, sub }),
      refresh,
      showPath: () => showPathRef.current(),
      openMemory: setMemoryOpen,
      setIncident: setIncidentId,
      onWorld: async () => {
        setScenarios(await api.scenarios())
      },
      openAsk: (question) =>
        new Promise<void>((resolve) => {
          askDone.current = resolve
          setPendingAsk(question)
          setAskOpen(true)
        }),
      closeAsk: () => setAskOpen(false),
      signal: demoSignal.current,
    }).finally(() => setDemoRunning(false))
  }, [demoRunning, refresh])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setAskOpen((o) => !o)
        return
      }
      if (e.key === 'Escape' && askOpen) {
        setAskOpen(false)
        return
      }
      const tag = (e.target as HTMLElement)?.tagName
      const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
      if (typing || askOpen || busy || e.ctrlKey || e.metaKey || e.altKey) return
      const key = e.key.toLowerCase()
      const n = Number(e.key)
      if (n >= 1 && n <= scenarios.length) inject(scenarios[n - 1].id, true)
      if (key === 'e' && incident?.evidence_path) showPath()
      if (key === 'm') setMemoryOpen((o) => !o)
      if (key === 's') setSpofOpen((o) => !o)
      if (key === 'k') setKnowledgeOpen((o) => !o)
      if (key === 'd') toggleDemo()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [askOpen, busy, scenarios, inject, incident, showPath, toggleDemo])

  const alerting = incident && incident.status !== 'resolved' ? incident.alerts.map((a) => a.component) : []
  const path = incident?.evidence_path?.slice(0, pathShown) ?? []
  const cause =
    pathShown > 0 && pathShown >= (incident?.evidence_path?.length ?? 0) ? incident?.root_cause?.component ?? null : null
  const sel = topology?.nodes.find((n) => n.id === selected)
  const rightPanelOpen = memoryOpen || knowledgeOpen || !!preflightFor || !!sel
  const showVerdict = incident && (incident.root_cause || incident.status !== 'resolved')

  return (
    <div className="relative flex h-full flex-col">
      {/* Header: logo · toolbar · company + LLM + demo */}
      <header className="relative z-20 flex items-center gap-4 px-5 pt-4">
        <Logo />
        <div className="flex flex-1 justify-center">
          {topology && (
            <Toolbar
              chaos={chaosOpen}
              memory={memoryOpen}
              spof={spofOpen}
              knowledge={knowledgeOpen}
              onChaos={() => setChaosOpen((o) => !o)}
              onMemory={() => setMemoryOpen((o) => !o)}
              onSpof={() => setSpofOpen((o) => !o)}
              onKnowledge={() => setKnowledgeOpen((o) => !o)}
              onAsk={() => openAsk()}
            />
          )}
        </div>
        <div className="flex items-center gap-2">
          <WorldSwitch topology={topology} onSwitched={onWorldSwitched} />
          <LlmBadge llm={llm} />
          <button
            onClick={toggleDemo}
            disabled={!topology}
            className={`gold-outline flex h-10 items-center gap-2 px-3 text-[12px] ${
              demoRunning ? 'border-bad text-bad' : ''
            }`}
            title="Guided demo (D)"
          >
            {demoRunning ? <Icon d="M6 6h12v12H6z" /> : <Icon d="M7 5v14l11-7z" />}
            {demoRunning ? 'Stop demo' : 'Run demo'}
            <kbd className="kbd">D</kbd>
          </button>
        </div>
      </header>

      <div className="relative flex min-h-0 flex-1">
        <main className="relative min-w-0 flex-1">
          {topology ? (
            <ServiceMap
              topology={topology}
              alerting={alerting}
              evidencePath={path}
              cause={cause}
              cited={cited}
              heat={heat}
              onSelect={(id) => {
                setSelected(id)
                setPreflightFor(null)
                setMemoryOpen(false)
                setKnowledgeOpen(false)
              }}
            />
          ) : (
            <Loading error={error} />
          )}

          {topology && chaosOpen && (
            <div className="absolute left-5 top-4 z-10">
              <ChaosLab scenarios={scenarios} busy={busy} onInject={inject} onReset={reset} />
            </div>
          )}

          {topology && (
            <div className="absolute bottom-5 left-5 z-10">
              <Legend />
            </div>
          )}

          <SpofPanel
            open={spofOpen}
            onClose={() => setSpofOpen(false)}
            shade={Object.keys(heat).length > 0}
            onToggleShade={toggleHeat}
            onSelect={setSelected}
          />
          <MemoryPanel open={memoryOpen} onClose={() => setMemoryOpen(false)} />

          {sel && !memoryOpen && !preflightFor && !knowledgeOpen && (
            <div className="glass absolute right-4 top-4 z-10 w-[280px] p-4 text-[12px]" role="dialog" aria-label={`Component ${sel.id}`}>
              <div className="flex items-start">
                <div>
                  <div className="text-[10px] uppercase tracking-[0.14em] text-teal">{sel.kind} · tier {sel.tier}</div>
                  <h2 className="font-display mt-1 text-[20px] leading-tight">{sel.id}</h2>
                </div>
                <button onClick={() => setSelected(null)} className="ml-auto text-muted hover:text-ink" aria-label="Close component details">
                  ×
                </button>
              </div>
              <p className="mt-1 text-muted">{sel.description}</p>
              <div className="mt-3 grid grid-cols-2 gap-2">
                {[
                  ['Owner', sel.team],
                  ['Status', `${STATUS_ICON[sel.status]} ${sel.status}`],
                  ['p95', `${sel.p95_ms} ms`],
                  ['Errors', `${(sel.error_rate * 100).toFixed(2)}%`],
                ].map(([k, v]) => (
                  <div key={k} className="tile px-3 py-2">
                    <div className="text-[10px] text-muted">{k}</div>
                    <div className="font-display text-[15px]">{v}</div>
                  </div>
                ))}
              </div>
              <button
                onClick={() => {
                  setPreflightFor(sel.id)
                  setSelected(null)
                }}
                className="gold-outline mt-3 w-full px-2 py-2 text-[12px]"
              >
                Check a change here before shipping
              </button>
            </div>
          )}

          <KnowledgePanel
            open={knowledgeOpen && !memoryOpen && !preflightFor}
            onClose={() => setKnowledgeOpen(false)}
            onHighlight={setCited}
          />

          {preflightFor && !memoryOpen && (
            <PreflightPanel
              component={preflightFor}
              onClose={() => {
                setPreflightFor(null)
                setCited([])
              }}
              onHighlight={setCited}
            />
          )}

          {/* Bottom centre: impact KPIs + ask bar */}
          {topology && (
            <div
              className={`absolute bottom-5 left-[236px] right-5 z-10 mx-auto max-w-[780px] ${
                rightPanelOpen ? 'opacity-95' : ''
              }`}
            >
              <div className="glass overflow-hidden p-2 shadow-[0_0_40px_rgb(95_217_204_/_0.12)]">
                <div className="relative">
                  <span className="absolute left-4 top-0 h-0.5 w-10 rounded bg-teal" aria-hidden />
                  <KpiStrip topology={topology} incident={incident} />
                </div>
                <div className="mt-1">
                  <AskBar onAsk={(q) => openAsk(q)} onOpen={() => openAsk()} />
                </div>
                <div className="mt-2 flex items-center gap-2 px-2 pb-1 text-[11px] text-muted">
                  <span className="chip">
                    <Icon d="M12 8v4l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z" className="h-3 w-3" /> polling every 2s
                  </span>
                  {cited.length > 0 && (
                    <button onClick={() => setCited([])} className="chip hover:text-ink">
                      clear highlight ({cited.length})
                    </button>
                  )}
                  {error && <span className="chip text-warn" role="alert">{error}</span>}
                  <span className="ml-auto">1–4 inject · E path · Ctrl K ask</span>
                </div>
              </div>
            </div>
          )}
        </main>

        {/* Right glass panel: verdict on top, agent feed below */}
        {topology && (
          <aside className="glass relative z-10 mb-5 mr-5 mt-4 flex w-[440px] shrink-0 flex-col overflow-hidden" aria-label="Incident">
            {showVerdict ? (
              <div className="max-h-[60%] shrink-0 overflow-y-auto border-b border-white/5 p-5">
                <VerdictCard
                  incident={incident}
                  showingPath={pathShown > 0}
                  onShowPath={showPath}
                  llmEnabled={!!llm?.enabled}
                  secondOpinion={secondOpinion}
                  onSecondOpinion={async () => {
                    try {
                      if (incident) setSecondOpinion(await api.llmInvestigate(incident.id))
                    } catch (e) {
                      setError((e as Error).message)
                    }
                  }}
                  onApprove={async (id) => {
                    try {
                      await api.approve(id)
                    } catch (e) {
                      setError((e as Error).message)
                    }
                    await refresh()
                  }}
                  onReject={async (id) => {
                    try {
                      await api.reject(id)
                    } catch (e) {
                      setError((e as Error).message)
                    }
                    await refresh()
                  }}
                />
              </div>
            ) : (
              <div className="border-b border-white/5 p-5">
                <div className="text-[11px] uppercase tracking-[0.14em] text-gold">Mission control</div>
                <h2 className="font-display mt-2 text-[24px] leading-tight">
                  {topology.world?.label?.split(' · ')[0] ?? 'Firebreak'}
                </h2>
                <p className="mt-1 text-[12px] text-muted">
                  {topology.stats.components} components, {topology.stats.people} people and {topology.stats.incidents} past
                  incidents in one FalkorDB graph. Inject a fault from the Chaos lab, or press{' '}
                  <kbd className="kbd">D</kbd> for the guided tour.
                </p>
              </div>
            )}
            <div className="min-h-0 flex-1">
              <AgentRoom steps={incident?.steps ?? []} hypotheses={incident?.hypotheses ?? []} />
            </div>
          </aside>
        )}
      </div>

      <AskPanel
        open={askOpen}
        onClose={() => setAskOpen(false)}
        onCite={setCited}
        pending={pendingAsk}
        onPendingDone={() => {
          setPendingAsk(null)
          askDone.current?.()
          askDone.current = null
        }}
      />

      {caption.text && (
        <div
          className="glass pointer-events-none fixed left-1/2 top-24 z-[60] w-[min(820px,90vw)] -translate-x-1/2 px-6 py-4 text-center step-in"
          role="status"
          aria-live="polite"
        >
          <div className="font-display text-[24px] leading-snug">{caption.text}</div>
          {caption.sub && <div className="mt-1 text-[14px] text-muted">{caption.sub}</div>}
        </div>
      )}
    </div>
  )
}

export default function App() {
  return (
    <ReactFlowProvider>
      <Shell />
    </ReactFlowProvider>
  )
}
