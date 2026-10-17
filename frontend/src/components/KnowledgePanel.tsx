import { useCallback, useEffect, useState } from 'react'
import { api, type IngestResult, type StaleItem } from '../api'

const SAMPLE = {
  kind: 'ticket',
  title: 'Session tokens expiring early on mobile',
  body: 'Since Tuesday auth-service returns 401 for refresh tokens older than 10 minutes. Priya Raman thinks it is the new connection pool. See ADR-014 and INC-2093.',
  author: 'marcus',
}

interface Props {
  open: boolean
  onClose: () => void
  onHighlight: (components: string[]) => void
}

export function KnowledgePanel({ open, onClose, onHighlight }: Props) {
  const [stale, setStale] = useState<StaleItem[]>([])
  const [kind, setKind] = useState(SAMPLE.kind)
  const [title, setTitle] = useState(SAMPLE.title)
  const [body, setBody] = useState(SAMPLE.body)
  const [author, setAuthor] = useState(SAMPLE.author)
  const [last, setLast] = useState<IngestResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api.stale().then(setStale).catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    if (open) load()
  }, [open, load])

  if (!open) return null

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await api.ingest({ kind, title, body, author: author || null })
      setLast(r)
      onHighlight(r.links.components)
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="absolute right-3 top-3 z-10 max-h-[calc(100%-24px)] w-[360px] overflow-y-auto rounded-lg border border-line bg-panel/95 p-3 text-[12px] shadow-xl">
      <div className="flex items-center">
        <h2 className="text-[12px] font-semibold uppercase tracking-wider">Knowledge</h2>
        <button onClick={onClose} className="ml-auto text-muted hover:text-ink" aria-label="Close knowledge panel">
          ×
        </button>
      </div>

      <div className="mt-2 text-[10px] uppercase tracking-wider text-muted">Needs review ({stale.length})</div>
      {stale.length === 0 && <p className="mt-1 text-muted">Everything is current.</p>}
      <ul className="mt-1 space-y-1.5">
        {stale.map((s) => (
          <li key={s.id} className="rounded border border-warn/30 bg-warn/5 px-2 py-1.5">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-muted">{s.type}</span>
              <span className="font-mono text-[11px] text-detective">{s.id}</span>
              <span className="truncate" title={s.title}>
                {s.title}
              </span>
            </div>
            <div className="mt-0.5 text-[11px] text-warn">{s.reason}</div>
            <div className="mt-1 flex items-center text-[10px] text-muted">
              {s.owner && <span>owner: {s.owner}</span>}
              {s.reviewed_days_ago != null && <span className="ml-2">reviewed {s.reviewed_days_ago}d ago</span>}
              <button
                onClick={async () => {
                  await api.markReviewed(s.id, 'priya')
                  load()
                }}
                className="ml-auto rounded border border-line px-1.5 py-0.5 text-ink hover:border-ok"
              >
                Mark reviewed
              </button>
            </div>
          </li>
        ))}
      </ul>

      <div className="mt-3 border-t border-line pt-2 text-[10px] uppercase tracking-wider text-muted">
        Add a doc, ticket or chat
      </div>
      <div className="mt-1 flex gap-1" role="radiogroup" aria-label="Kind">
        {['ticket', 'doc', 'chat'].map((k) => (
          <button
            key={k}
            role="radio"
            aria-checked={kind === k}
            onClick={() => setKind(k)}
            className={`rounded border px-1.5 py-0.5 text-[11px] ${
              kind === k ? 'border-detective bg-detective/15 text-detective' : 'border-line text-muted hover:text-ink'
            }`}
          >
            {k}
          </button>
        ))}
        <input
          value={author}
          onChange={(e) => setAuthor(e.target.value)}
          aria-label="Author id"
          placeholder="author id"
          className="ml-auto w-20 rounded border border-line bg-canvas px-1 text-[11px]"
        />
      </div>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        aria-label="Title"
        className="mt-1 w-full rounded border border-line bg-canvas px-1.5 py-1 text-[12px]"
      />
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        aria-label="Body"
        rows={4}
        className="mt-1 w-full rounded border border-line bg-canvas px-1.5 py-1 text-[12px]"
      />
      <button
        disabled={busy || !title.trim() || !body.trim()}
        onClick={submit}
        className="mt-1 w-full rounded bg-detective/80 px-2 py-1 text-[11px] font-semibold text-canvas hover:bg-detective disabled:opacity-50"
      >
        {busy ? 'Linking into the graph…' : 'Add to the company brain'}
      </button>
      {error && <p className="mt-1 text-bad">{error}</p>}
      {last && (
        <div className="mt-2 rounded border border-line bg-canvas p-2 text-[11px]">
          <div>
            Created <span className="font-mono text-detective">{last.id}</span> ({last.label}). Linked to:
          </div>
          <ul className="mt-1 space-y-0.5 text-muted">
            <li>components: {last.links.components.join(', ') || 'none'}</li>
            <li>people: {last.links.people.join(', ') || 'none'}</li>
            <li>records: {last.links.references.map((r) => r.id).join(', ') || 'none'}</li>
          </ul>
          <div className="mt-1 text-muted">Searchable now; try it in Ask (Ctrl K).</div>
        </div>
      )}
    </div>
  )
}
