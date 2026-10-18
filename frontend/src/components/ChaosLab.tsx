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
    <div className="glass w-[280px] p-4" role="region" aria-label="Chaos lab">
      <div className="mb-2 flex items-center">
        <h2 className="text-[11px] uppercase tracking-[0.14em] text-teal">Chaos lab</h2>
        <label className="ml-auto flex cursor-pointer items-center gap-1 text-[11px] text-muted">
          <input type="checkbox" checked={decoy} onChange={(e) => setDecoy(e.target.checked)} className="accent-warn" />
          with decoy
        </label>
      </div>
      <p className="-mt-1 mb-2 text-[10px] text-muted">Decoy adds an unrelated recent change off the dependency path.</p>
      <ul className="space-y-1">
        {scenarios.map((s, i) => (
          <li key={s.id}>
            <button
              disabled={busy}
              onClick={() => onInject(s.id, decoy)}
              className="group flex w-full items-center gap-2 tile px-2 py-1.5 text-left hover:border-bad disabled:opacity-50"
              title={`Fault on ${s.root}; fix: ${s.remediation}${decoy ? '; plus an unrelated recent change off the dependency path' : ''}. Shortcut: ${i + 1}`}
            >
              <kbd className="kbd">{i + 1}</kbd>
              <span className="flex-1 text-[12px]">{s.title}</span>
              <span className="text-[10px] text-bad opacity-0 group-hover:opacity-100">inject</span>
            </button>
          </li>
        ))}
      </ul>
      <button
        disabled={busy}
        onClick={onReset}
        className="gold-outline mt-3 w-full px-2 py-1.5 text-[11px] disabled:opacity-50"
      >
        Reset world (keeps memory)
      </button>
    </div>
  )
}
