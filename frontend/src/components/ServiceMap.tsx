import { useMemo } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { Status, Topology, TopoNode } from '../api'
import { layout } from '../layout'

const STATUS_COLOR: Record<Status, string> = {
  healthy: 'var(--color-ok)',
  degraded: 'var(--color-warn)',
  down: 'var(--color-bad)',
}
// Status is never color-only: each state also has an icon and label.
const STATUS_ICON: Record<Status, string> = { healthy: '●', degraded: '▲', down: '✕' }

const KIND_TAG: Record<string, string> = {
  service: 'svc',
  datastore: 'db',
  queue: 'queue',
  vendor: 'vendor',
  cluster: 'k8s',
}

// React Flow requires node data to be an indexable record.
type CompData = TopoNode & { highlight: 'path' | 'cause' | 'cite' | null; alerting: boolean } & Record<string, unknown>

function ComponentNode({ data }: NodeProps<Node<CompData>>) {
  const color = STATUS_COLOR[data.status]
  const ring =
    data.highlight === 'cause'
      ? 'ring-2 ring-white'
      : data.highlight === 'path'
        ? 'ring-2 ring-commander'
        : data.highlight === 'cite'
          ? 'ring-2 ring-detective'
          : ''
  return (
    <div
      className={`w-[190px] rounded-md border bg-panel-2 px-2.5 py-1.5 text-left ${ring} ${
        data.status === 'down' ? 'pulse-bad' : ''
      }`}
      style={{ borderColor: data.status === 'healthy' ? 'var(--color-line)' : color }}
      title={`${data.description}\nOwner: ${data.team}\nTier ${data.tier}\np95 ${data.p95_ms}ms · errors ${(data.error_rate * 100).toFixed(1)}%`}
    >
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-line" />
      <div className="flex items-center gap-1.5">
        <span style={{ color }} aria-label={data.status} className="text-[11px] leading-none">
          {STATUS_ICON[data.status]}
        </span>
        <span className="truncate font-mono text-[12px] text-ink">{data.id}</span>
        {data.alerting && (
          <span className="ml-auto rounded bg-bad/20 px-1 text-[9px] font-semibold uppercase text-bad">alert</span>
        )}
      </div>
      <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted">
        <span className="uppercase">{KIND_TAG[data.kind] ?? data.kind}</span>
        <span>·</span>
        <span>T{data.tier}</span>
        <span>·</span>
        <span className="truncate">{data.team}</span>
        {data.status !== 'healthy' && (
          <span className="ml-auto font-mono" style={{ color }}>
            {(data.error_rate * 100).toFixed(0)}%
          </span>
        )}
        {data.lagging && data.status === 'healthy' && <span className="ml-auto text-warn">lag</span>}
      </div>
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-line" />
    </div>
  )
}

const nodeTypes = { comp: ComponentNode }

interface Props {
  topology: Topology
  alerting: string[]
  evidencePath: string[]
  cause: string | null
  cited: string[]
  onSelect: (name: string) => void
}

export function ServiceMap({ topology, alerting, evidencePath, cause, cited, onSelect }: Props) {
  const positions = useMemo(
    () => layout(topology.nodes, topology.edges),
    // Layout depends only on structure, not live status.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [topology.nodes.length, topology.edges.length],
  )

  const pathEdges = useMemo(() => {
    const s = new Set<string>()
    for (let i = 0; i < evidencePath.length - 1; i++) s.add(`${evidencePath[i]}->${evidencePath[i + 1]}`)
    return s
  }, [evidencePath])

  const nodes: Node<CompData>[] = topology.nodes.map((n) => ({
    id: n.id,
    type: 'comp',
    position: positions[n.id] ?? { x: 0, y: 0 },
    data: {
      ...n,
      alerting: alerting.includes(n.id),
      highlight:
        n.id === cause ? 'cause' : evidencePath.includes(n.id) ? 'path' : cited.includes(n.id) ? 'cite' : null,
    },
  }))

  const status = new Map(topology.nodes.map((n) => [n.id, n.status]))
  const edges: Edge[] = topology.edges.map((e) => {
    const onPath = pathEdges.has(`${e.source}->${e.target}`)
    const dep = status.get(e.target) ?? 'healthy'
    // A failing dependency on a sync edge is how the fault reaches the caller.
    const carrying = e.mode === 'sync' && dep !== 'healthy'
    const stroke = onPath ? 'var(--color-commander)' : carrying ? STATUS_COLOR[dep] : '#2a3446'
    return {
      id: `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      animated: onPath || carrying,
      style: {
        stroke,
        strokeWidth: onPath ? 2.5 : carrying ? 1.8 : 1,
        strokeDasharray: e.mode === 'async' ? '4 4' : undefined,
        opacity: onPath || carrying ? 1 : 0.7,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 14, height: 14 },
      label: onPath ? e.protocol : undefined,
      labelStyle: { fill: 'var(--color-ink)', fontSize: 10 },
      labelBgStyle: { fill: 'var(--color-panel)' },
    }
  })

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.08 }}
      minZoom={0.2}
      nodesDraggable={false}
      nodesConnectable={false}
      onNodeClick={(_, n) => onSelect(n.id)}
      proOptions={{ hideAttribution: true }}
      colorMode="dark"
      style={{ background: 'transparent' }}
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1b2230" />
      <Controls showInteractive={false} />
    </ReactFlow>
  )
}
