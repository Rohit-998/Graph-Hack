import { useEffect, useRef, useState } from 'react'
import { api, type AskAnswer, type ConversationSummary, type CypherResult } from '../api'
import { CypherResultView } from './CypherResultView'

const EXAMPLES = [
  'Why does checkout call auth synchronously?',
  'How do I fail over from Stripe?',
  'Who decided the separate ledger database?',
  'What broke search before?',
]
const FOLLOW_UPS = ['Who decided it?', 'What broke there before?', 'Who should I page?']
const QUERY_EXAMPLES = [
  'Which teams own the most tier 1 services?',
  'Which customers use products served by checkout-api, and how much GMV per hour?',
  'Who has authored the most changes to auth-service?',
  'Which components have had more than one incident?',
]

// Demo identities: conversation memory is stored per user in the graph.
const USERS = ['priya', 'marcus', 'guest']
const USER_KEY = 'firebreak.ask.user'

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
  const [user, setUser] = useState(() => localStorage.getItem(USER_KEY) ?? 'priya')
  const [conversation, setConversation] = useState<string | null>(null)
  const [turns, setTurns] = useState<AskAnswer[]>([])
  const [past, setPast] = useState<ConversationSummary[]>([])
  const [mode, setMode] = useState<'ask' | 'query'>('ask')
  const [queries, setQueries] = useState<CypherResult[]>([])
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) setTimeout(() => input.current?.focus(), 0)
  }, [open])

  // Each user sees only their own conversations, loaded from the graph.
  useEffect(() => {
    localStorage.setItem(USER_KEY, user)
    setConversation(null)
    setTurns([])
    if (open) api.conversations(user).then(setPast).catch(() => setPast([]))
  }, [user, open])

  const runQuery = async (question: string) => {
    if (!question.trim()) return
    setBusy(true)
    setError(null)
    try {
      const looksLikeCypher = /^\s*(MATCH|CALL|WITH|UNWIND|RETURN|OPTIONAL)\b/i.test(question)
      const r = await api.cypher(looksLikeCypher ? { cypher: question } : { question })
      setQueries((qs) => [{ ...r, question }, ...qs].slice(0, 5))
      setQ('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const ask = async (question: string) => {
    if (mode === 'query') return runQuery(question)
    if (!question.trim()) return
    setBusy(true)
    setError(null)
    try {
      const a = await api.ask(question, user, conversation)
      setConversation(a.conversation ?? null)
      setTurns((t) => [...t, a])
      onCite(a.highlight)
      setQ('')
      api.conversations(user).then(setPast).catch(() => undefined)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // Reopen a past conversation: replay its turns from the graph.
  const resume = async (id: string) => {
    setBusy(true)
    try {
      const msgs = await api.conversation(id, user)
      const rebuilt: AskAnswer[] = []
      for (let i = 0; i < msgs.length; i++) {
        if (msgs[i].role !== 'user') continue
        const reply = msgs[i + 1]?.role === 'assistant' ? msgs[i + 1] : null
        rebuilt.push({
          question: msgs[i].text,
          query: '',
          answer: reply?.text ?? '',
          sources: (reply?.cites ?? []).map((c) => ({ type: c.split('-')[0], id: c, title: '', people: [], components: [], score: 0 })),
          highlight: [],
          model: 'from graph memory',
          conversation: id,
        })
      }
      setConversation(id)
      setTurns(rebuilt)
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-[8vh]"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Ask Firebreak"
    >
      <div className="w-[720px] rounded-lg border border-line bg-panel shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-line px-3 py-1.5 text-[11px] text-muted">
          <div className="flex rounded border border-line" role="radiogroup" aria-label="Mode">
            {(['ask', 'query'] as const).map((m) => (
              <button
                key={m}
                role="radio"
                aria-checked={mode === m}
                onClick={() => setMode(m)}
                className={`px-2 py-0.5 ${mode === m ? 'bg-detective/20 text-detective' : 'hover:text-ink'}`}
                title={m === 'ask' ? 'Company brain: answers with cited sources' : 'Question to read-only Cypher, run on FalkorDB'}
              >
                {m === 'ask' ? 'Ask' : 'Query the graph'}
              </button>
            ))}
          </div>
          {mode === 'ask' && (
          <label className="flex items-center gap-1">
            Asking as
            <select
              aria-label="User"
              value={user}
              onChange={(e) => setUser(e.target.value)}
              className="rounded border border-line bg-panel-2 px-1 py-0.5 text-ink"
            >
              {USERS.map((u) => (
                <option key={u}>{u}</option>
              ))}
            </select>
          </label>
          )}
          {mode === 'ask' && (
          <span title="Conversations are nodes in the tenant graph, private to each user">
            · memory in graph{conversation ? ` · ${conversation}` : ''}
          </span>
          )}
          {mode === 'ask' && conversation && (
            <button
              onClick={() => {
                setConversation(null)
                setTurns([])
              }}
              className="ml-auto rounded border border-line px-1.5 py-0.5 hover:text-ink"
            >
              New conversation
            </button>
          )}
        </div>

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
            placeholder={
              mode === 'query'
                ? 'Ask a question, or type Cypher (MATCH …)'
                : conversation
                  ? 'Ask a follow-up…'
                  : 'Ask the company brain…'
            }
            aria-label="Question"
            className="h-12 flex-1 bg-transparent text-[14px] outline-none placeholder:text-muted"
          />
          {busy && <span className="text-[11px] text-muted">{mode === 'query' ? 'writing Cypher…' : 'searching graph…'}</span>}
          <kbd className="rounded border border-line px-1 font-mono text-[10px] text-muted">esc</kbd>
        </form>

        <div className="max-h-[62vh] overflow-y-auto p-3">
          {error && <p className="text-[12px] text-bad">{error}</p>}

          {mode === 'query' && (
            <div>
              {queries.length === 0 && (
                <div className="space-y-1">
                  <div className="text-[10px] uppercase tracking-wider text-muted">
                    Try (the LLM sees the live schema; FalkorDB rejects any write)
                  </div>
                  {QUERY_EXAMPLES.map((e) => (
                    <button key={e} onClick={() => runQuery(e)} className="block text-left text-[13px] text-ink hover:text-detective">
                      {e}
                    </button>
                  ))}
                </div>
              )}
              {queries.map((r, i) => (
                <article key={i} className={`step-in ${i > 0 ? 'mt-4 border-t border-line pt-3 opacity-70' : ''}`}>
                  <div className="text-[12px] text-muted">{r.question}</div>
                  <div className="mt-1">
                    <CypherResultView r={r} />
                  </div>
                </article>
              ))}
            </div>
          )}

          {mode === 'ask' && turns.length === 0 && (
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <div className="text-[10px] uppercase tracking-wider text-muted">Try</div>
                {EXAMPLES.map((e) => (
                  <button key={e} onClick={() => ask(e)} className="block text-left text-[13px] text-ink hover:text-detective">
                    {e}
                  </button>
                ))}
              </div>
              <div className="space-y-1">
                <div className="text-[10px] uppercase tracking-wider text-muted">{user}'s past conversations</div>
                {past.length === 0 && <p className="text-[12px] text-muted">None yet.</p>}
                {past.slice(0, 6).map((c) => (
                  <button
                    key={c.id}
                    onClick={() => resume(c.id)}
                    className="block w-full truncate text-left text-[12px] text-ink hover:text-detective"
                    title={`${c.messages} messages`}
                  >
                    {c.title} <span className="text-muted">· {Math.floor(c.messages / 2)} turns</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {mode === 'ask' && turns.map((a, i) => (
            <article key={i} className={`step-in ${i > 0 ? 'mt-4 border-t border-line pt-3' : ''}`}>
              <div className="flex items-center gap-2 text-[12px] text-muted">
                <span>{a.question}</span>
                {a.follow_up_of && (
                  <span
                    className="rounded border border-detective/40 px-1 text-[10px] text-detective"
                    title="Resolved by walking from the previous answer's cited entities in the graph"
                  >
                    follow-up · resolved from graph
                  </span>
                )}
              </div>
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
              {i === turns.length - 1 && a.highlight.length > 0 && (
                <div className="mt-2 text-[10px] text-muted">
                  Highlighted on map: {a.highlight.join(', ')} · {a.model}
                </div>
              )}
            </article>
          ))}

          {mode === 'ask' && turns.length > 0 && !busy && (
            <div className="mt-3 flex flex-wrap gap-1 border-t border-line pt-2">
              {FOLLOW_UPS.map((f) => (
                <button
                  key={f}
                  onClick={() => ask(f)}
                  className="rounded border border-line px-1.5 py-0.5 text-[11px] text-muted hover:border-detective hover:text-ink"
                >
                  {f}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
