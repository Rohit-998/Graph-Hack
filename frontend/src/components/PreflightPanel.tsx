import { useEffect, useState } from 'react'
import { api, type Preflight } from '../api'

const KINDS = ['deploy', 'config', 'flag', 'migration']
const FACTOR_LABEL: Record<string, string> = {
  blast_radius: 'Blast radius',
  customer_exposure: 'Customer $ exposed',
  choke_point: 'Choke point (betweenness)',
  incident_history: 'Past incidents here',
  same_kind_broke_before: 'Same kind broke it before',
  change_kind: 'Change kind',
  tier: 'Tier',
  concurrent_changes: 'Changes in flight nearby',
}
const RISK_TONE = { low: 'text-ok border-ok/40 bg-ok/10', medium: 'text-warn border-warn/40 bg-warn/10', high: 'text-bad border-bad/40 bg-bad/10' }

interface Props {
  component: string
  onClose: () => void
  onHighlight: (components: string[]) => void
}

export function PreflightPanel({ component, onClose, onHighlight }: Props) {
  const [kind, setKind] = useState('deploy')
  const [r, setR] = useState<Preflight | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    setError(null)
    api
      .preflight(component, kind)
      .then((res) => {
        if (!live) return
        setR(res)
        onHighlight(res.blast_radius.map((b) => b.component))
      })
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
    // onHighlight is a state setter from the parent
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [component, kind])

  return (
    <div className="absolute right-3 top-3 z-10 max-h-[calc(100%-24px)] w-[340px] overflow-y-auto rounded-lg border border-line bg-panel/95 p-3 text-[12px] shadow-xl">
      <div className="flex items-center">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted">Pre-deploy check</div>
          <h2 className="font-mono text-[13px]">{component}</h2>
        </div>
        <button onClick={onClose} className="ml-auto self-start text-muted hover:text-ink" aria-label="Close pre-deploy check">
          ×
        </button>
      </div>

      <div className="mt-2 flex gap-1" role="radiogroup" aria-label="Change kind">
        {KINDS.map((k) => (
          <button
            key={k}
            role="radio"
            aria-checked={kind === k}
            onClick={() => setKind(k)}
            className={`rounded border px-1.5 py-0.5 text-[11px] ${
              kind === k ? 'border-commander bg-commander/15 text-commander' : 'border-line text-muted hover:text-ink'
            }`}
          >
            {k}
          </button>
        ))}
      </div>

      {error && <p className="mt-2 text-bad">{error}</p>}
      {r && (
        <>
          <div className={`mt-2 flex items-center rounded border px-2 py-1.5 ${RISK_TONE[r.risk]}`}>
            <span className="text-[13px] font-semibold uppercase">{r.risk} risk</span>
            <span className="ml-auto font-mono">{Math.round(r.score * 100)}/100</span>
          </div>

          {r.advice.length > 0 && (
            <ul className="mt-2 space-y-1">
              {r.advice.map((a, i) => (
                <li key={i} className="leading-snug">
                  <span className="text-muted">•</span> {a}
                </li>
              ))}
            </ul>
          )}

          <div className="mt-3 text-[10px] uppercase tracking-wider text-muted">Why this score</div>
          <ul className="mt-1 space-y-0.5">
            {Object.entries(r.factors).map(([k, v]) => (
              <li key={k} className="flex items-center gap-2 text-[11px]">
                <span className="w-40 shrink-0 text-muted">{FACTOR_LABEL[k] ?? k}</span>
                <div className="h-1.5 flex-1 rounded bg-canvas">
                  <div className="h-full rounded bg-warn" style={{ width: `${v * 100}%` }} />
                </div>
                <span className="w-8 text-right font-mono text-[10px] text-muted">×{r.weights[k]}</span>
              </li>
            ))}
          </ul>

          <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted">Exposed</div>
              <div>{r.blast_radius.length} upstream services</div>
              <div>{r.customers.length} customers</div>
              <div className="font-mono">${Math.round(r.gmv_per_hour).toLocaleString()}/hr</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted">Review with</div>
              {r.reviewers.map((p) => (
                <div key={p.id} title={p.reasons.join('\n')}>
                  {p.name}
                </div>
              ))}
            </div>
          </div>

          {r.past_incidents.length > 0 && (
            <>
              <div className="mt-3 text-[10px] uppercase tracking-wider text-muted">What broke here before</div>
              <ul className="mt-1 space-y-0.5 text-[11px]">
                {r.past_incidents.map((p) => (
                  <li key={p.id}>
                    <span className="font-mono text-detective">{p.id}</span> {p.title}
                    <span className="text-muted">
                      {' '}
                      · {p.change_kind ?? 'outage'} · {p.fixes.join('/') || 'manual'}
                      {p.ttm_min != null ? ` in ${p.ttm_min}m` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="mt-2 text-[10px] text-muted">Answered from the graph in {r.duration_ms}ms. Highlighted on the map: the blast radius.</p>
        </>
      )}
    </div>
  )
}
