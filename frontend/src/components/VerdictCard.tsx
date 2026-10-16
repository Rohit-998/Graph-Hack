import { useState } from 'react'
import type { Action, IncidentDetail } from '../api'

const BREAKDOWN_LABEL: Record<string, string> = {
  coverage: 'Alert coverage',
  change: 'Recent change',
  anomaly: 'Own anomaly',
  history: 'Past incidents',
  vendor: 'Vendor signal',
  criticality: 'Criticality',
  memory: 'Seen before',
}

function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="w-28 shrink-0 text-muted">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded bg-canvas">
        <div className="h-full rounded bg-detective transition-all duration-700" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-12 text-right font-mono text-muted">{value.toFixed(3)}</span>
    </div>
  )
}

function ActionRow({ a, onApprove, onReject, busy }: {
  a: Action
  onApprove: () => void
  onReject: () => void
  busy: boolean
}) {
  const done = a.status !== 'proposed'
  return (
    <li className="flex items-center gap-2 rounded border border-line bg-canvas px-2 py-1.5">
      <span className="rounded bg-panel-2 px-1.5 py-0.5 font-mono text-[10px] uppercase text-commander">{a.kind}</span>
      <span className="flex-1 truncate text-[12px]" title={a.reason}>
        {a.reason}
      </span>
      {done ? (
        <span
          className={`text-[10px] font-semibold uppercase ${
            a.status === 'executed' ? 'text-ok' : a.status === 'rejected' ? 'text-bad' : 'text-muted'
          }`}
        >
          {a.status}
          {a.result ? ` · ${a.result}` : ''}
        </span>
      ) : (
        <>
          <button
            disabled={busy}
            onClick={onApprove}
            className="rounded bg-ok px-2 py-0.5 text-[11px] font-semibold text-canvas hover:brightness-110 disabled:opacity-50"
          >
            Approve
          </button>
          <button
            disabled={busy}
            onClick={onReject}
            className="rounded border border-line px-2 py-0.5 text-[11px] text-muted hover:text-ink disabled:opacity-50"
          >
            Reject
          </button>
        </>
      )}
    </li>
  )
}

interface Props {
  incident: IncidentDetail
  showingPath: boolean
  onShowPath: () => void
  onApprove: (id: string) => Promise<void>
  onReject: (id: string) => Promise<void>
}

export function VerdictCard({ incident, showingPath, onShowPath, onApprove, onReject }: Props) {
  const [busy, setBusy] = useState(false)
  const rc = incident.root_cause
  const bd = incident.breakdown ?? {}
  const team = incident.responders
  const max = Math.max(...Object.entries(bd).filter(([k]) => k !== 'coverage').map(([, v]) => v), 0.0001)
  const seen = incident.similar?.find((s) => s.id === incident.seen_before)
  const narrativeModel = incident.steps.find((s) => s.tool === 'narrate')?.model ?? 'deterministic'

  const run = (fn: (id: string) => Promise<void>) => async (id: string) => {
    setBusy(true)
    try {
      await fn(id)
    } finally {
      setBusy(false)
    }
  }

  if (!rc) {
    return (
      <div className="rounded-lg border border-line bg-panel p-3 text-[12px] text-muted">
        Investigating {incident.id}…
      </div>
    )
  }

  return (
    <div className="step-in rounded-lg border border-commander/40 bg-panel-2 p-3">
      <div className="flex items-start gap-2">
        <div className="flex-1">
          <div className="text-[10px] uppercase tracking-wider text-commander">Commander verdict · {incident.id}</div>
          <h3 className="mt-0.5 text-[14px] font-semibold leading-snug">{incident.summary}</h3>
          {rc.summary && <p className="mt-0.5 text-[11px] text-muted">"{rc.summary}"</p>}
        </div>
        <div className="text-right">
          <div className="font-mono text-[26px] leading-none text-ok">{Math.round((incident.confidence ?? 0) * 100)}%</div>
          <div className="text-[9px] uppercase tracking-wider text-muted">confidence</div>
        </div>
      </div>

      {seen && (
        <div className="mt-2 rounded border border-ok/40 bg-ok/10 px-2 py-1.5 text-[11px]">
          <span className="font-semibold text-ok">Seen before: </span>
          <span className="font-mono">{seen.id}</span> "{seen.title}" ·{' '}
          {seen.actions.join('/') || 'manual fix'} resolved it{seen.ttm_min != null ? ` in ${seen.ttm_min} min` : ''}
          <span className="text-muted"> · similarity {seen.score.toFixed(2)}</span>
        </div>
      )}

      {incident.narrative && (
        <p className="mt-2 text-[12px] leading-relaxed text-ink">
          {incident.narrative}
          <span className="ml-1 rounded border border-line px-1 font-mono text-[9px] text-muted">
            {narrativeModel}
          </span>
        </p>
      )}

      <div className="mt-3 space-y-1">
        <div className="flex items-center gap-2 text-[11px]">
          <span className="w-28 shrink-0 text-muted">Alert coverage</span>
          <span className="font-mono">{Math.round((bd.coverage ?? 0) * (incident.alerts.length || 1))}/{incident.alerts.length} alerts explained</span>
        </div>
        {Object.entries(bd)
          .filter(([k, v]) => k !== 'coverage' && v > 0)
          .map(([k, v]) => (
            <Bar key={k} label={BREAKDOWN_LABEL[k] ?? k} value={v} max={max} />
          ))}
      </div>

      {incident.evidence_path && (
        <div className="mt-3">
          <button
            onClick={onShowPath}
            className={`rounded border px-2 py-1 text-[11px] ${
              showingPath ? 'border-commander bg-commander/15 text-commander' : 'border-line text-ink hover:border-commander'
            }`}
          >
            {showingPath ? 'Showing evidence path' : 'Show evidence path'}
          </button>
          <div className="mt-1.5 flex flex-wrap items-center gap-1 font-mono text-[11px]">
            {incident.evidence_path.map((n, i) => (
              <span key={n} className="flex items-center gap-1">
                {i > 0 && <span className="text-muted">→</span>}
                <span className={i === incident.evidence_path!.length - 1 ? 'text-bad' : 'text-ink'}>{n}</span>
              </span>
            ))}
            {rc.id && (
              <>
                <span className="text-muted">←</span>
                <span className="text-warn">{rc.id}</span>
                {rc.author && <span className="text-muted">by {rc.author}</span>}
              </>
            )}
          </div>
        </div>
      )}

      {team && (
        <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-responder">On-call · {team.team}</div>
            {team.on_call.map((p) => (
              <div key={p.id}>
                {p.name} <span className="text-muted">L{p.level}</span>
              </div>
            ))}
            {team.escalation.length > 0 && <div className="text-muted">↑ {team.escalation.join(' → ')}</div>}
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-responder">Who knows this</div>
            {team.experts.map((p) => (
              <div key={p.id} title={p.reasons?.join('\n')}>
                {p.name} <span className="text-muted">{p.reasons?.[0]}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {incident.actions.length > 0 && (
        <ul className="mt-3 space-y-1">
          {incident.actions.map((a) => (
            <ActionRow
              key={a.id}
              a={a}
              busy={busy}
              onApprove={() => run(onApprove)(a.id)}
              onReject={() => run(onReject)(a.id)}
            />
          ))}
        </ul>
      )}

      {incident.status === 'resolved' && (
        <div className="mt-3 border-t border-line pt-2">
          <div className="flex items-center text-[10px] uppercase tracking-wider text-muted">
            Scribe · postmortem written to graph
            {incident.postmortem && (
              <span className="ml-auto rounded border border-line px-1 font-mono normal-case">
                {incident.postmortem.model}
              </span>
            )}
          </div>
          {incident.postmortem ? (
            <p className="mt-1 whitespace-pre-line text-[11px] leading-relaxed text-ink">{incident.postmortem.body}</p>
          ) : (
            <p className="mt-1 text-[11px] text-muted">Writing postmortem…</p>
          )}
        </div>
      )}
    </div>
  )
}
