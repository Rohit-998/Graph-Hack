import type { TopoEdge, TopoNode } from './api'

// Layered left-to-right layout: callers on the left, dependencies to the right.
// Column = longest path from any entry point, so every edge points rightwards.
export const COL_W = 230
export const ROW_H = 74

export function layout(nodes: TopoNode[], edges: TopoEdge[]): Record<string, { x: number; y: number }> {
  const deps = new Map<string, string[]>()
  for (const n of nodes) deps.set(n.id, [])
  for (const e of edges) deps.get(e.source)?.push(e.target)

  const depth = new Map<string, number>()
  const hasCaller = new Set(edges.map((e) => e.target))
  const visit = (id: string, d: number) => {
    if ((depth.get(id) ?? -1) >= d) return
    depth.set(id, d)
    for (const t of deps.get(id) ?? []) visit(t, d + 1)
  }
  const connected = new Set(edges.flatMap((e) => [e.source, e.target]))
  for (const n of nodes) if (connected.has(n.id) && !hasCaller.has(n.id)) visit(n.id, 0)

  // Clusters have no DEPENDS_ON edges; park them in a column past the deepest dependency.
  const maxDepth = Math.max(0, ...depth.values())
  for (const n of nodes) if (!depth.has(n.id)) depth.set(n.id, maxDepth + 1)

  const cols = new Map<number, TopoNode[]>()
  for (const n of nodes) {
    const d = depth.get(n.id)!
    if (!cols.has(d)) cols.set(d, [])
    cols.get(d)!.push(n)
  }

  // Order each column by the mean row of its callers to reduce crossings.
  const row = new Map<string, number>()
  const callers = new Map<string, string[]>()
  for (const e of edges) {
    if (!callers.has(e.target)) callers.set(e.target, [])
    callers.get(e.target)!.push(e.source)
  }
  const pos: Record<string, { x: number; y: number }> = {}
  const tallest = Math.max(...[...cols.values()].map((c) => c.length))
  for (const d of [...cols.keys()].sort((a, b) => a - b)) {
    const col = cols.get(d)!
    const key = (n: TopoNode) => {
      const rs = (callers.get(n.id) ?? []).map((c) => row.get(c)).filter((r): r is number => r !== undefined)
      return rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : n.tier
    }
    col.sort((a, b) => key(a) - key(b) || a.id.localeCompare(b.id))
    const offset = ((tallest - col.length) * ROW_H) / 2
    col.forEach((n, i) => {
      row.set(n.id, i + (tallest - col.length) / 2)
      pos[n.id] = { x: d * COL_W, y: offset + i * ROW_H }
    })
  }
  return pos
}
