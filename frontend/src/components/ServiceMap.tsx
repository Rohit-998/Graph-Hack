import { useEffect, useMemo, useRef } from 'react'
import {
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { Status, Topology, TopoNode } from '../api'
import { layout } from '../layout'
import { STATUS_ICON } from '../status'

const STATUS_TEXT: Record<Status, string> = { healthy: 'ok', degraded: 'degraded', down: 'down' }
const STATUS_TONE: Record<Status, string> = { healthy: 'text-ok', degraded: 'text-warn', down: 'text-bad' }

const KIND_TAG: Record<string, string> = {
  service: 'svc',
  datastore: 'db',
  queue: 'queue',
  vendor: 'vendor',
  cluster: 'k8s',
}
const ORB_SIZE: Record<number, number> = { 1: 30, 2: 24, 3: 19 }

type Highlight = 'path' | 'cause' | 'cite' | null
// React Flow requires node data to be an indexable record.
type CompData = TopoNode & { highlight: Highlight; alerting: boolean; heat: number } & Record<string, unknown>

function ComponentNode({ data }: NodeProps<Node<CompData>>) {
  const size = ORB_SIZE[data.tier] ?? 22
  const heat = data.heat
  return (
    <div
      className="flex cursor-pointer items-center gap-3"
      title={`${data.description}\nOwner: ${data.team} · tier ${data.tier}\np95 ${data.p95_ms}ms · errors ${(
        data.error_rate * 100
      ).toFixed(1)}%`}
    >
      <Handle type="target" position={Position.Left} />
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        {heat > 0 && (
          <div
            className="halo"
            aria-hidden
            style={{
              inset: -10 - heat * 18,
              background: `radial-gradient(circle, rgb(246 195 91 / ${0.15 + heat * 0.45}) 0%, transparent 70%)`,
            }}
          />
        )}
        {data.customer_facing && <div className="halo halo-facing" aria-hidden />}
        {data.highlight === 'path' && <div className="halo halo-path" aria-hidden />}
        {data.highlight === 'cite' && <div className="halo halo-cite" aria-hidden />}
        {data.highlight === 'cause' && <div className="halo halo-cause" aria-hidden />}
        <div
          className={`orb orb-${data.status} h-full w-full ${data.status === 'down' ? 'pulse-bad' : ''}`}
          aria-hidden
        />
      </div>
      <div className="min-w-0 leading-tight">
        <div className="flex items-center gap-1.5">
          <span
            className={`font-display truncate text-[14px] ${
              data.highlight === 'cause' ? 'text-gold' : 'text-ink'
            } max-w-[150px]`}
          >
            {data.id}
          </span>
          {data.alerting && (
            <span className="chip slant bg-bad/25 font-semibold uppercase text-bad" aria-label="alerting">
              alert
            </span>
          )}
        </div>
        <div className="mt-1 flex items-center gap-1">
          <span className={`chip slant ${STATUS_TONE[data.status]}`} aria-label={`status ${data.status}`}>
            {STATUS_ICON[data.status]} {data.status === 'healthy' ? `T${data.tier}` : `${(data.error_rate * 100).toFixed(0)}%`}
            <span className="text-muted">{data.status === 'healthy' ? '' : STATUS_TEXT[data.status]}</span>
          </span>
          {data.lagging && data.status === 'healthy' && <span className="chip slant text-warn">lag</span>}
          <span className="truncate text-[10px] text-muted">
            {KIND_TAG[data.kind] ?? data.kind} · {data.team}
          </span>
        </div>
      </div>
      <Handle type="source" position={Position.Right} />
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
  heat: Record<string, number>
  onSelect: (name: string) => void
}

export function ServiceMap({ topology, alerting, evidencePath, cause, cited, heat, onSelect }: Props) {
  const wrap = useRef<HTMLDivElement>(null)
  const { fitView } = useReactFlow()

  // Refit whenever the map's container changes size (window resize, panels opening).
  useEffect(() => {
    if (!wrap.current) return
    // Refit on the next frame: resizing inside the observer callback trips the browser's
    // "ResizeObserver loop" warning when panels open and close.
    let raf = 0
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => fitView({ padding: 0.12, duration: 250 }))
    })
    ro.observe(wrap.current)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [fitView])

  const positions = useMemo(
    () => layout(topology.nodes, topology.edges),
    // Layout depends only on structure, not live status.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [topology.nodes.length, topology.edges.length, topology.world?.name],
  )

  // A new company has a different shape: refit once its layout is in.
  useEffect(() => {
    const t = setTimeout(() => fitView({ padding: 0.12, duration: 400 }), 60)
    return () => clearTimeout(t)
  }, [positions, fitView])

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
      heat: heat[n.id] ?? 0,
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
    const stroke = onPath
      ? '#f3d199'
      : carrying
        ? dep === 'down'
          ? '#fb6f8a'
          : '#f6c35b'
        : e.mode === 'sync'
          ? 'rgb(232 189 120 / 0.38)'
          : 'rgb(95 217 204 / 0.4)'
    return {
      id: `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      type: 'default',
      animated: onPath || carrying,
      className: onPath ? 'edge-path' : carrying ? (dep === 'down' ? 'edge-fault' : 'edge-degraded') : undefined,
      style: {
        stroke,
        strokeWidth: onPath ? 3 : carrying ? 2 : 1.1,
        strokeDasharray: e.mode === 'async' && !onPath ? '3 5' : undefined,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 12, height: 12 },
      label: onPath ? e.protocol : undefined,
      labelStyle: { fill: '#f3d199', fontSize: 10 },
      labelBgStyle: { fill: '#081416', fillOpacity: 0.85 },
      labelBgPadding: [4, 2] as [number, number],
      labelBgBorderRadius: 3,
    }
  })

  return (
    <div ref={wrap} className="h-full w-full" aria-label="Service dependency map" role="region">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.15}
        maxZoom={2.2}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        onNodeClick={(_, n) => onSelect(n.id)}
        proOptions={{ hideAttribution: true }}
        colorMode="dark"
        style={{ background: 'transparent' }}
      />
    </div>
  )
}
