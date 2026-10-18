import { useEffect, useState } from 'react'
import { api, type SpofRow } from '../api'

interface Props {
  open: boolean
  onClose: () => void
  shade: boolean
  onToggleShade: (on: boolean) => void
  onSelect: (component: string) => void
}

export function SpofPanel({ open, onClose, shade, onToggleShade, onSelect }: Props) {
  const [rows, setRows] = useState<SpofRow[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    api
      .spof()
      .then(setRows)
      .catch((e: Error) => setError(e.message))
  }, [open])

  if (!open) return null
  const max = Math.max(...rows.map((r) => r.betweenness), 1)

  return (
    <div className="absolute left-3 top-[280px] z-10 w-[300px] glass p-4 text-[12px]">
      <div className="flex items-center">
        <h2 className="text-[11px] uppercase tracking-[0.14em] text-teal">Single points of failure</h2>
        <button onClick={onClose} className="ml-auto text-muted hover:text-ink" aria-label="Close SPOF panel">
          ×
        </button>
      </div>
      <p className="mt-0.5 text-[10px] text-muted">
        Betweenness centrality over <span className="font-mono">DEPENDS_ON</span>, computed by FalkorDB
        (<span className="font-mono">algo.betweenness</span>). High score = many dependency paths run through it.
      </p>

      {error && <p className="mt-1 text-[11px] text-bad">{error}</p>}
      <ul className="mt-2 space-y-1">
        {rows.map((r) => (
          <li key={r.component}>
            <button
              onClick={() => onSelect(r.component)}
              className="w-full rounded px-1 py-0.5 text-left hover:bg-panel-2"
              title={`Owned by ${r.team}; on-call ${r.on_call.join(', ')}`}
            >
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[11px]">{r.component}</span>
                <span className="ml-auto font-mono text-[10px] text-muted">{r.betweenness.toFixed(1)}</span>
              </div>
              <div className="mt-0.5 h-1 rounded bg-canvas">
                <div className="h-full rounded bg-warn" style={{ width: `${(r.betweenness / max) * 100}%` }} />
              </div>
              <div className="text-[10px] text-muted">
                {r.team} · {r.dependents} dependents
              </div>
            </button>
          </li>
        ))}
      </ul>

      <label className="mt-2 flex cursor-pointer items-center gap-2 border-t border-line pt-2 text-[11px] text-muted">
        <input type="checkbox" checked={shade} onChange={(e) => onToggleShade(e.target.checked)} className="accent-warn" />
        Shade the map by betweenness
      </label>
    </div>
  )
}
