import { useEffect, useRef, useState } from 'react'
import { api, type AskAnswer } from '../api'

const HISTORY_KEY = 'firebreak.ask.history'
const EXAMPLES = [
  'Why does checkout call auth synchronously?',
  'How do I fail over from Stripe?',
  'Who decided the separate ledger database?',
  'What broke search before?',
]

function loadHistory(): AskAnswer[] {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]')
  } catch {
    return []
  }
}

interface Props {
  open: boolean
  onClose: () => void
  onCite: (components: string[]) => void
  // Set by the guided demo to ask a question without typing.
  pending?: string | null
  onPendingDone?: () => void
}

export function AskPanel({ open, onClose, onCite, pending, onPendingDone }: Props) {
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<AskAnswer[]>(loadHistory)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) setTimeout(() => input.current?.focus(), 0)
  }, [open])

  useEffect(() => {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, 20)))
  }, [history])

  const ask = async (question: string) => {
    if (!question.trim()) return
    setBusy(true)
    setError(null)
    try {
      const a = await api.ask(question)
      setHistory((h) => [a, ...h])
      onCite(a.highlight)
      setQ('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (open && pending) {
      ask(pending).finally(() => onPendingDone?.())
    }
    // ask is stable enough for this one-shot trigger
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, pending])

  if (!open) return null
  const latest = history[0]

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-[10vh]"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Ask Firebreak"
    >
      <div className="w-[680px] rounded-lg border border-line bg-panel shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            ask(q)
          }}
          className="flex items-center gap-2 border-b border-line px-3"
        >
          <span className="text-detective" aria-hidden>
            ?
          </span>
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Escape' && onClose()}
            placeholder="Ask the company brain…"
            aria-label="Question"
            className="h-12 flex-1 bg-transparent text-[14px] outline-none placeholder:text-muted"
          />
          {busy && <span className="text-[11px] text-muted">searching graph…</span>}
          <kbd className="rounded border border-line px-1 font-mono text-[10px] text-muted">esc</kbd>
        </form>

        <div className="max-h-[60vh] overflow-y-auto p-3">
          {error && <p className="text-[12px] text-bad">{error}</p>}
          {!latest && (
            <div className="space-y-1">
              <div className="text-[10px] uppercase tracking-wider text-muted">Try</div>
              {EXAMPLES.map((e) => (
                <button key={e} onClick={() => ask(e)} className="block text-left text-[13px] text-ink hover:text-detective">
                  {e}
                </button>
              ))}
            </div>
          )}
          {history.slice(0, 5).map((a, i) => (
            <article key={i} className={`step-in ${i > 0 ? 'mt-4 border-t border-line pt-3 opacity-60' : ''}`}>
              <div className="text-[12px] text-muted">{a.question}</div>
              <p className="mt-1 text-[13px] leading-relaxed">{a.answer}</p>
              {a.sources.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {a.sources.map((s) => (
                    <button
                      key={s.id}
                      onClick={() => onCite(s.components)}
                      title={`${s.title}\n${s.people.join(', ')}\nComponents: ${s.components.join(', ')}`}
                      className="rounded border border-line bg-canvas px-1.5 py-0.5 text-[11px] hover:border-detective"
                    >
                      <span className="text-muted">{s.type}</span> <span className="font-mono text-detective">{s.id}</span>
                    </button>
                  ))}
                </div>
              )}
              {i === 0 && a.highlight.length > 0 && (
                <div className="mt-2 text-[10px] text-muted">
                  Highlighted on map: {a.highlight.join(', ')} · {a.model}
                </div>
              )}
            </article>
          ))}
        </div>
      </div>
    </div>
  )
}
