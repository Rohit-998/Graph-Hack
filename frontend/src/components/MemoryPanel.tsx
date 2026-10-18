import { useEffect, useState } from 'react'
import { api, type LearningPoint, type PlaybookStat } from '../api'

interface Props {
  open: boolean
  onClose: () => void
}

export function MemoryPanel({ open, onClose }: Props) {
  const [playbooks, setPlaybooks] = useState<PlaybookStat[]>([])
  const [curve, setCurve] = useState<LearningPoint[]>([])

  useEffect(() => {
    if (!open) return
    Promise.all([api.playbooks(), api.learningCurve()]).then(([p, c]) => {
      setPlaybooks(p)
      setCurve(c)
    })
  }, [open])

  if (!open) return null

  // Group verdict times by incident class (root-cause component), oldest first.
  const byClass = new Map<string, LearningPoint[]>()
  for (const p of curve) {
    if (!byClass.has(p.component)) byClass.set(p.component, [])
    byClass.get(p.component)!.push(p)
  }

  return (
    <div className="absolute right-3 top-3 z-10 w-[340px] glass p-4 text-[12px]">
      <div className="flex items-center">
        <h2 className="text-[11px] uppercase tracking-[0.14em] text-teal">Memory</h2>
        <button onClick={onClose} className="ml-auto text-muted hover:text-ink" aria-label="Close memory panel">
          ×
        </button>
      </div>

      <div className="mt-2 text-[10px] uppercase tracking-wider text-muted">Investigations by incident class</div>
      {byClass.size === 0 ? (
        <p className="mt-1 text-muted">No investigations yet. Inject a scenario twice to see recall.</p>
      ) : (
        <ul className="mt-1 space-y-1.5">
          {[...byClass.entries()].map(([comp, pts]) => (
            <li key={comp}>
              <div className="font-mono text-[11px]">{comp}</div>
              <div className="flex flex-wrap gap-1">
                {pts.map((p) => (
                  <span
                    key={p.id}
                    title={`${p.id}: verdict ${(p.ttrc_ms / 1000).toFixed(1)}s after first alert, ${Math.round(
                      (p.confidence ?? 0) * 100,
                    )}% confidence${p.seen_before ? `, recalled ${p.seen_before}` : ''}`}
                    className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                      p.seen_before ? 'bg-ok/15 text-ok' : 'bg-panel-2 text-muted'
                    }`}
                  >
                    {Math.round((p.confidence ?? 0) * 100)}%{p.seen_before ? ' ↺' : ''}
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-[10px] text-muted">↺ = recalled a similar past incident</p>

      <div className="mt-3 text-[10px] uppercase tracking-wider text-muted">Playbooks (procedural memory)</div>
      <ul className="mt-1 max-h-48 space-y-0.5 overflow-y-auto">
        {playbooks.map((p) => {
          const total = p.success + p.failure
          return (
            <li key={p.id} className="flex items-center gap-2 text-[11px]">
              <span className="w-16 shrink-0 font-mono text-commander">{p.kind}</span>
              <span className="flex-1 truncate font-mono">{p.component}</span>
              <span className="font-mono text-muted">
                {p.success}/{total}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
