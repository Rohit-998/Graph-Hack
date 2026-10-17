import type { CypherResult } from '../api'

function cell(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(3)
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

export function CypherResultView({ r }: { r: CypherResult }) {
  if (r.error) {
    return (
      <div className="text-[12px]">
        <p className="text-bad">{r.error}</p>
        {r.attempts?.map((a, i) => (
          <pre key={i} className="mt-1 overflow-x-auto rounded bg-canvas p-2 font-mono text-[10px] text-muted">
            {a.cypher}
            {a.error ? `\n-- rejected: ${a.error}` : ''}
          </pre>
        ))}
      </div>
    )
  }
  const cols = r.columns ?? []
  const rows = r.rows ?? []
  const repaired = (r.attempts?.length ?? 0) > 1
  return (
    <div className="text-[12px]">
      {r.explanation && <p className="text-ink">{r.explanation}</p>}
      <pre className="mt-1 overflow-x-auto rounded bg-canvas p-2 font-mono text-[11px] leading-snug text-detective">
        {r.cypher}
      </pre>
      <div className="mt-1 flex gap-3 text-[10px] text-muted">
        <span>GRAPH.RO_QUERY · read-only enforced by FalkorDB</span>
        <span>
          {r.row_count} row{r.row_count === 1 ? '' : 's'}
          {r.truncated ? ' (truncated)' : ''} · {r.duration_ms}ms
        </span>
        {r.model && <span>written by {r.model}</span>}
        {repaired && <span className="text-warn">repaired after FalkorDB rejected the first attempt</span>}
      </div>
      {rows.length > 0 && (
        <div className="mt-2 max-h-64 overflow-auto rounded border border-line">
          <table className="w-full text-left text-[11px]">
            <thead className="sticky top-0 bg-panel-2">
              <tr>
                {cols.map((c) => (
                  <th key={c} scope="col" className="px-2 py-1 font-mono font-normal text-muted">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className="border-t border-line">
                  {cols.map((c) => (
                    <td key={c} className="px-2 py-1 font-mono">
                      {cell(row[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
