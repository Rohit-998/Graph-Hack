import { useEffect, useRef, useState } from 'react'
import type { AgentStep, Hypothesis } from '../api'

const AGENT_COLOR: Record<string, string> = {
  commander: 'var(--color-commander)',
  detective: 'var(--color-detective)',
  responder: 'var(--color-responder)',
  investigator: 'var(--color-investigator)',
}

function Step({ step }: { step: AgentStep }) {
  const [open, setOpen] = useState(false)
  const color = AGENT_COLOR[step.agent]
  return (
    <li className="step-in border-l-2 py-1.5 pl-3" style={{ borderColor: color }}>
      <div className="flex items-center gap-2 text-[10px]">
        <span className="font-semibold uppercase tracking-wider" style={{ color }}>
          {step.agent}
        </span>
        <span className="font-mono text-muted">{step.tool}</span>
        <span className="ml-auto rounded border border-line px-1 font-mono text-[9px] text-muted" title="Model that produced this step">
          {step.model}
        </span>
        {step.duration_ms > 0 && <span className="font-mono text-muted">{step.duration_ms.toFixed(1)}ms</span>}
      </div>
      <p className="mt-0.5 text-[12px] leading-snug text-ink">{step.summary}</p>
      {step.cypher && step.cypher.length > 25 && (
        <>
          <button
            onClick={() => setOpen((o) => !o)}
            className="mt-0.5 text-[10px] text-muted underline-offset-2 hover:text-ink hover:underline"
          >
            {open ? 'hide Cypher' : 'show Cypher'}
          </button>
          {open && (
            <pre className="mt-1 max-h-48 overflow-auto rounded bg-canvas p-2 font-mono text-[10px] leading-snug text-detective">
              {step.cypher}
            </pre>
          )}
        </>
      )}
    </li>
  )
}

export function Hypotheses({ items }: { items: Hypothesis[] }) {
  if (!items.length) return null
  return (
    <div className="border-b border-line px-3 py-2">
      <div className="mb-1 text-[10px] uppercase tracking-wider text-muted">Hypothesis board (graph blackboard)</div>
      <ul className="space-y-1">
        {items.map((h) => (
          <li key={h.id} className="flex items-center gap-2 text-[11px]">
            <span
              className={`w-16 shrink-0 rounded px-1 text-center text-[9px] font-semibold uppercase ${
                h.status === 'accepted'
                  ? 'bg-ok/15 text-ok'
                  : h.status === 'rejected'
                    ? 'bg-bad/15 text-bad line-through'
                    : 'bg-panel-2 text-muted'
              }`}
            >
              {h.status}
            </span>
            <span className={`flex-1 truncate ${h.status === 'rejected' ? 'text-muted' : ''}`} title={h.statement}>
              {h.statement}
            </span>
            <span className="w-9 text-right font-mono text-muted">{Math.round(h.confidence * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function AgentRoom({ steps, hypotheses }: { steps: AgentStep[]; hypotheses: Hypothesis[] }) {
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth' })
  }, [steps.length])

  return (
    <section className="flex h-full flex-col">
      <div className="flex items-center gap-3 px-4 pb-2 pt-3">
        <h2 className="text-[11px] uppercase tracking-[0.14em] text-teal">Agent room</h2>
        <div className="ml-auto flex gap-2 text-[10px]">
          {Object.entries(AGENT_COLOR).map(([a, c]) => (
            <span key={a} className="flex items-center gap-1 capitalize text-muted">
              <span className="h-2 w-2 rounded-full" style={{ background: c }} />
              {a}
            </span>
          ))}
        </div>
      </div>
      <Hypotheses items={hypotheses} />
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {steps.length === 0 ? (
          <p className="mt-8 text-center text-[12px] text-muted">
            Waiting for an incident.
            <br />
            Inject one from the Chaos lab.
          </p>
        ) : (
          <ul className="space-y-1">
            {steps.map((s) => (
              <Step key={s.id} step={s} />
            ))}
          </ul>
        )}
        <div ref={end} />
      </div>
    </section>
  )
}
