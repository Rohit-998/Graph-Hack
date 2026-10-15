import { useState } from 'react'
import type { Scenario } from '../api'

interface Props {
  scenarios: Scenario[]
  busy: boolean
  onInject: (id: string, decoy: boolean) => void
  onReset: () => void
}

export function ChaosLab({ scenarios, busy, onInject, onReset }: Props) {
  const [decoy, setDecoy] = useState(true)
  return (
    <div className="w-[260px] rounded-lg border border-line bg-panel/95 p-3 shadow-xl backdrop-blur">
      <div className="mb-2 flex items-center">
        <h2 className="text-[12px] font-semibold uppercase tracking-wider">Chaos lab</h2>
        <label className="ml-auto flex cursor-pointer items-center gap-1 text-[11px] text-muted">
          <input type="checkbox" checked={decoy} onChange={(e) => setDecoy(e.target.checked)} className="accent-warn" />
          with decoy
        </label>
      </div>
      <ul className="space-y-1">
        {scenarios.map((s, i) => (
          <li key={s.id}>
            <button
              disabled={busy}
              onClick={() => onInject(s.id, decoy)}
              className="group flex w-full items-center gap-2 rounded border border-line bg-canvas px-2 py-1.5 text-left hover:border-bad disabled:opacity-50"
              title={`Fault on ${s.root}${decoy ? `; decoy change on ${s.decoy}` : ''}. Shortcut: ${i + 1}`}
            >
              <kbd className="rounded border border-line px-1 font-mono text-[9px] text-muted">{i + 1}</kbd>
              <span className="flex-1 text-[12px]">{s.title}</span>
              <span className="text-[10px] text-bad opacity-0 group-hover:opacity-100">inject</span>
            </button>
          </li>
        ))}
      </ul>
      <button
        disabled={busy}
        onClick={onReset}
        className="mt-2 w-full rounded border border-line px-2 py-1 text-[11px] text-muted hover:text-ink disabled:opacity-50"
      >
        Reset world (keeps memory)
      </button>
    </div>
  )
}
