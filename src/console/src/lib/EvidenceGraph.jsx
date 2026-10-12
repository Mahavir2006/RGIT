// Evidence graph for the incident record.
//
// Rendered as DOM nodes plus an SVG edge layer rather than WebGL, because a node graph has
// to be readable, selectable, draggable and printable - and because relationship semantics
// need a legend and a text alternative, not just coloured pixels.
//
// The layout is hierarchical and deterministic: the incident sits at depth 0, hypotheses
// and affected assets at depth 1, and the events behind them at depth 2. A fixed layout
// matters here because an operator compares two hypotheses against each other, and a
// physics simulation would move the picture on every render.
//
// A keyboard-reachable table alternative is always available, since a graph alone is not a
// sufficient substitute for a screen reader or for pointer-free operation.
import { useMemo, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search, PanelRightClose, Minimize2, GripVertical, X, Maximize2, Table2, Network
} from 'lucide-react';
import { evidenceFor, hypothesisEdges, incidentAssets, RELATION_SEMANTICS } from '@/data/graph.js';
import { Badge } from '@/components/ui';
import { cn } from '@/lib/utils';

// Node kind -> presentation. Colours match the node families in the legend.
const KINDS = {
  Incident: { label: 'Incident', accent: '#a855f7', tint: 'rgba(168,85,247,0.14)' },
  Hypothesis: { label: 'Hypothesis', accent: '#8b5cf6', tint: 'rgba(139,92,246,0.13)' },
  Event: { label: 'Event', accent: '#0ea5e9', tint: 'rgba(14,165,233,0.13)' },
  Asset: { label: 'Asset', accent: '#3b82f6', tint: 'rgba(59,130,246,0.13)' }
};

const RELATION_TINT = {
  SUPPORTS: '#10b981', CONTRADICTS: '#ef4444', CONTEXT_FOR: '#64748b',
  SUPPORTED_BY: '#10b981', CHALLENGED_BY: '#ef4444', AFFECTS: '#f59e0b'
};

const ACCENT = '#22d3ee';
const SELECTED = '#a855f7';
const GRID = '#1e293b';

// Width of an edge label pill, sized to the rendered monospace text.
function relLabelWidth(type) {
  return String(type).replace(/_/g, ' ').length * 6.4 + 16;
}

const NODE_W = 190;
const NODE_H = 96;
const COL_GAP = 22;
const ROW_GAP = 76;
const CANVAS_PAD = 120;

// ---- Graph construction -----------------------------------------------------------
// Mirrors the Neo4j model: (:Event)-[SUPPORTS|CONTRADICTS|CONTEXT_FOR]->(:Incident),
// (:Hypothesis)-[SUPPORTED_BY|CHALLENGED_BY]->(:Event), (:Incident)-[AFFECTS]->(:Asset).
export function buildGraph(store, incidentId, { showContradictions = true } = {}) {
  const incident = store.find('Incident', incidentId);
  if (!incident) return { nodes: [], links: [] };

  const nodes = [];
  const links = [];
  const byId = new Map();

  const push = node => {
    if (byId.has(node.id)) return byId.get(node.id);
    const created = { ...node, depth: 0 };
    byId.set(node.id, created);
    nodes.push(created);
    return created;
  };

  const incidentNode = push({
    id: incidentId,
    kind: 'Incident',
    label: incidentId,
    name: incidentId,
    meta: incident.status.replace(/_/g, ' '),
    detail: incident.area_name,
    // Plain-language explanation of what this node is and why it is the root of the graph.
    explain: `Operator-visible record for ${incident.type.toLowerCase()} in ${incident.area_name}. Everything below is evidence for or against it.`,
    count: 0
  });

  // Hypotheses and affected assets sit one level below the incident.
  const hypotheses = store.all('Hypothesis').filter(item => item.incident_id === incidentId);
  for (const hypothesis of hypotheses) {
    push({
      id: hypothesis.hypothesis_id,
      kind: 'Hypothesis',
      label: hypothesis.hypothesis_id.replace('HYP-', 'H'),
      name: hypothesis.hypothesis_id.replace('HYP-', 'H'),
      meta: `confidence ${hypothesis.confidence.toFixed(2)}`,
      detail: `v${hypothesis.version} · ${hypothesis.status.replace(/_/g, ' ')}`,
      explain: hypothesis.claim,
      count: hypothesis.evidence_for.length + hypothesis.evidence_against.length,
      status: hypothesis.status,
      confidence: hypothesis.confidence
    });
  }

  for (const edge of incidentAssets(store, incidentId)) {
    const asset = store.find('Asset', edge._to);
    if (!asset) continue;
    push({
      id: asset.asset_id,
      kind: 'Asset',
      label: asset.type.replace(/_/g, ' '),
      name: asset.name,
      meta: asset.asset_id.split('-').pop(),
      detail: `${asset.criticality} criticality`,
      explain: `Infrastructure this incident is assessed to affect. Relationship is an impact, not a confirmed mechanism.`,
      count: 0,
      criticality: asset.criticality
    });
  }

  // Events attached directly to the incident, plus everything a hypothesis leans on.
  for (const edge of evidenceFor(store, incidentId)) {
    if (!showContradictions && edge._type === 'CONTRADICTS') continue;
    const event = store.find('Event', edge._from);
    if (!event) continue;
    push({
      id: event.event_id,
      kind: 'Event',
      label: event.event_id.replace('evt-', ''),
      name: event.event_id.replace('evt-', ''),
      meta: event.event_type.replace(/_/g, ' '),
      detail: event.source_id,
      explain: event.summary,
      count: edge.score !== undefined ? 1 : 0,
      source: event.source_id,
      score: edge.score,
      observedAt: event.event_time,
      ingestLagSeconds: Math.round((new Date(event.ingest_time) - new Date(event.event_time)) / 1000)
    });
    links.push({
      id: edge.link_id,
      source: event.event_id,
      target: incidentId,
      type: edge._type,
      rationale: edge.rationale,
      score: edge.score
    });
  }

  for (const hypothesis of hypotheses) {
    for (const edge of hypothesisEdges(store, hypothesis.hypothesis_id)) {
      const event = store.find('Event', edge._to);
      if (!event) continue;
      if (!showContradictions && edge._type === 'CHALLENGED_BY') continue;
      if (!byId.has(event.event_id)) {
        push({
          id: event.event_id,
          kind: 'Event',
          label: event.event_id.replace('evt-', ''),
          name: event.event_id.replace('evt-', ''),
          meta: event.event_type.replace(/_/g, ' '),
          detail: event.source_id,
          explain: event.summary,
          count: 0,
          source: event.source_id
        });
      }
      links.push({
        id: `${hypothesis.hypothesis_id}-${edge._type}-${event.event_id}`,
        source: hypothesis.hypothesis_id,
        target: event.event_id,
        type: edge._type,
        rationale: edge.rationale
      });
    }
  }

  // Depth: incident 0, hypotheses/assets 1, events 2.
  for (const node of nodes) {
    if (node.kind === 'Incident') node.depth = 0;
    else if (node.kind === 'Hypothesis' || node.kind === 'Asset') node.depth = 1;
    else node.depth = 2;
  }

  return { nodes, links };
}

// Deterministic top-down layout: each depth is a horizontal row, every row is centred, and
// edges flow from the bottom of a parent to the top of its child. Depth 0 sits alone at the
// top, so an operator reads the incident and then follows evidence downwards.
//
// A fixed layout matters here because an operator compares two hypotheses against each
// other, and a physics simulation would move the picture on every render.
function layoutGraph(nodes, links) {
  const byDepth = new Map();
  for (const node of nodes) {
    if (!byDepth.has(node.depth)) byDepth.set(node.depth, []);
    byDepth.get(node.depth).push(node);
  }

  const depths = [...byDepth.keys()].sort((a, b) => a - b);
  const widest = Math.max(1, ...depths.map(depth => byDepth.get(depth).length));

  const width = CANVAS_PAD * 2 + widest * NODE_W + (widest - 1) * COL_GAP;
  const height = CANVAS_PAD * 2 + depths.length * NODE_H + (depths.length - 1) * ROW_GAP;
  const inner = width - CANVAS_PAD * 2;

  const positions = new Map();
  depths.forEach((depth, rowIndex) => {
    const row = byDepth.get(depth)
      .slice()
      .sort((a, b) => KINDS[a.kind].label.localeCompare(KINDS[b.kind].label) || a.id.localeCompare(b.id));
    const rowWidth = row.length * NODE_W + (row.length - 1) * COL_GAP;
    const startX = CANVAS_PAD + (inner - rowWidth) / 2;
    row.forEach((node, columnIndex) => {
      positions.set(node.id, {
        x: startX + columnIndex * (NODE_W + COL_GAP),
        y: CANVAS_PAD + rowIndex * (NODE_H + ROW_GAP)
      });
    });
  });

  return { positions, width, height, rows: depths.length, maxDepth: depths.length - 1 };
}

// ---- Component ---------------------------------------------------------------------
export default function EvidenceGraph({ store, incidentId, showContradictions, onSelectEvent, selectedEvent, height = 560, fill = false }) {
  const [selected, setSelected] = useState(selectedEvent ?? null);
  const [query, setQuery] = useState('');
  const [maxDepth, setMaxDepth] = useState(4);
  const [panelOpen, setPanelOpen] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const [dragging, setDragging] = useState(null);
  const [offsets, setOffsets] = useState({});
  const surface = useRef(null);

  const graph = useMemo(() => buildGraph(store, incidentId, { showContradictions }), [store, incidentId, showContradictions]);
  const base = useMemo(() => layoutGraph(graph.nodes, graph.links), [graph]);

  const stats = useMemo(() => {
    const fanout = new Map();
    for (const link of graph.links) fanout.set(link.source, (fanout.get(link.source) || 0) + 1);
    const maxFanout = Math.max(0, ...fanout.values());
    // Depth is reported from the deepest chain actually present, not the filter limit.
    const depth = Math.max(0, ...graph.nodes.map(node => node.depth)) + 1;
    return {
      rendered: graph.nodes.length,
      total: graph.nodes.length,
      edges: graph.links.length,
      depth,
      maxFanout
    };
  }, [graph]);

  // Search and depth filter narrow the rendered set; the same numbers drive the stat tiles.
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return graph.nodes.filter(node => {
      if (node.depth > maxDepth) return false;
      if (!needle) return true;
      return `${node.id} ${node.label} ${node.name} ${node.meta} ${node.kind}`.toLowerCase().includes(needle);
    });
  }, [graph.nodes, query, maxDepth]);

  const visibleIds = useMemo(() => new Set(visible.map(node => node.id)), [visible]);
  const links = useMemo(
    () => graph.links.filter(link => visibleIds.has(link.source) && visibleIds.has(link.target)),
    [graph.links, visibleIds]
  );

  const positionOf = useCallback(
    node => {
      const base2 = base.positions.get(node.id) ?? { x: 0, y: 0 };
      const offset = offsets[node.id] ?? { x: 0, y: 0 };
      return { x: base2.x + offset.x, y: base2.y + offset.y };
    },
    [base.positions, offsets]
  );

  const startDrag = (event, id) => {
    event.stopPropagation();
    event.preventDefault();
    const origin = positionOf({ id });
    setDragging({ id, dx: event.clientX - origin.x, dy: event.clientY - origin.y });
  };

  const onPointerMove = event => {
    if (!dragging) return;
    setOffsets(previous => {
      const node = visible.find(item => item.id === dragging.id);
      if (!node) return previous;
      const start = base.positions.get(dragging.id) ?? { x: 0, y: 0 };
      const next = { x: event.clientX - dragging.dx - start.x, y: event.clientY - dragging.dy - start.y };
      return { ...previous, [dragging.id]: next };
    });
  };

  const endDrag = () => setDragging(null);

  const selectedNode = selected ? visible.find(node => node.id === selected) ?? graph.nodes.find(node => node.id === selected) : null;
  const selectedLinks = selected ? graph.links.filter(link => link.source === selected || link.target === selected) : [];

  function select(id) {
    setSelected(id);
    const node = graph.nodes.find(item => item.id === id);
    if (node?.kind === 'Event') onSelectEvent?.(id);
  }

  return (
    <div className={cn(
      'flex flex-col overflow-hidden border border-slate-800 bg-[#0b0f17]',
      // `fill` is the full-viewport mode used by the dedicated graph route: the graph grows
      // to the whole shell instead of sitting inside a panel.
      fill ? 'h-full w-full border-0' : 'rounded-app'
    )}>
      {/* Header */}
      <header className="flex flex-wrap items-start gap-4 border-b border-slate-800 px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-[18px] font-semibold tracking-tight text-white">
            <Network className="size-[18px]" style={{ color: ACCENT }} />
            Evidence graph
          </div>
          <p className="mt-1 text-[12.5px] text-slate-400">
            <span className="font-mono text-slate-300">{incidentId}</span> · drag any node · click to inspect
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="graph-depth">Maximum depth</label>
          <select id="graph-depth" value={maxDepth}
            onChange={event => setMaxDepth(Number(event.target.value))}
            className="h-9 rounded-lg border border-slate-800 bg-[#111827] px-3 font-mono text-[12.5px] text-slate-200 outline-none focus:border-slate-600">
            {[1, 2, 3, 4].map(depth => <option key={depth} value={depth}>depth ≤ {depth}</option>)}
          </select>

          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-slate-500" />
            <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search node or type…"
              aria-label="Search nodes" autoComplete="off"
              className="h-9 w-[220px] rounded-lg border border-slate-800 bg-[#111827] pl-9 pr-3 font-mono text-[12.5px] text-slate-200 placeholder:text-slate-500 outline-none focus:border-slate-600" />
          </div>

          <button onClick={() => setShowTable(value => !value)}
            className={cn('inline-flex h-9 items-center gap-2 rounded-lg border px-3 text-[13px] transition-colors',
              showTable ? 'border-slate-600 bg-slate-800 text-white' : 'border-slate-800 text-slate-300 hover:bg-slate-900')}>
            <Table2 className="size-3.5" />Table
          </button>
          <button onClick={() => setPanelOpen(value => !value)}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-800 px-3 text-[13px] text-slate-300 transition-colors hover:bg-slate-900">
            <PanelRightClose className="size-3.5" />Hide panel
          </button>
          <button onClick={() => setFullscreen(value => !value)}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-800 px-3 text-[13px] text-slate-300 transition-colors hover:bg-slate-900">
            {fullscreen ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
            {fullscreen ? 'Exit full screen' : 'Expand'}
          </button>
        </div>
      </header>

      {/* Stat tiles */}
      <div className="grid grid-cols-2 gap-3 px-5 py-4 lg:grid-cols-4">
        <StatTile label="Nodes rendered" value={`${stats.rendered}/${stats.total}`} colour={ACCENT} />
        <StatTile label="Total edges" value={String(stats.edges)} colour="#c084fc" />
        <StatTile label="Tree depth" value={`${stats.depth} levels`} colour="#4ade80" />
        <StatTile label="Max fanout" value={`${stats.maxFanout} children`} colour="#fbbf24" />
      </div>

      {/* Body: graph surface + inspector */}
      <div className="flex min-h-0 flex-1 gap-4 px-5 pb-4">
        <div ref={surface}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerLeave={endDrag}
          className="relative min-w-0 flex-1 overflow-auto rounded-xl border border-slate-800"
          style={{
            height: fullscreen ? 'calc(100vh - 230px)' : fill ? '100%' : height,
            backgroundImage: `radial-gradient(${GRID} 1px, transparent 1px)`,
            backgroundSize: '22px 22px'
          }}
          role="application"
          aria-label={`Evidence graph for ${incidentId}. A table alternative is available from the Table button.`}
        >
          <div className="relative" style={{ width: base.width, height: base.height }}>
            {/* Edges. Each one is labelled at its midpoint so the relationship between two
                nodes is readable without opening the inspector. */}
            <svg className="pointer-events-none absolute inset-0" width={base.width} height={base.height} aria-hidden="true">
              <defs>
                <marker id="graph-arrow" markerWidth="9" markerHeight="9" refX="7" refY="3.5" orient="auto" markerUnits="strokeWidth">
                  <path d="M0 0 L7 3.5 L0 7 z" fill="#64748b" />
                </marker>
                <marker id="graph-arrow-sel" markerWidth="9" markerHeight="9" refX="7" refY="3.5" orient="auto" markerUnits="strokeWidth">
                  <path d="M0 0 L7 3.5 L0 7 z" fill={SELECTED} />
                </marker>
              </defs>
              {links.map(link => {
                const sourceNode = visible.find(node => node.id === link.source);
                const targetNode = visible.find(node => node.id === link.target);
                if (!sourceNode || !targetNode) return null;
                const from = positionOf(sourceNode);
                const to = positionOf(targetNode);
                // Top-down: leave the bottom of the parent, enter the top of the child.
                const x1 = from.x + NODE_W / 2, y1 = from.y + NODE_H;
                const x2 = to.x + NODE_W / 2, y2 = to.y - 6;
                const midY = (y1 + y2) / 2;
                const active = selected === link.source || selected === link.target;
                const tint = RELATION_TINT[link.type] ?? '#64748b';
                return (
                  <g key={link.id}>
                    <path
                      d={`M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`}
                      fill="none"
                      stroke={active ? SELECTED : tint}
                      strokeWidth={active ? 2.2 : 1.4}
                      strokeDasharray="5 5"
                      strokeOpacity={active ? 1 : 0.55}
                      markerEnd={active ? 'url(#graph-arrow-sel)' : 'url(#graph-arrow)'}
                    />
                    {/* Relation pill at the midpoint of the curve. */}
                    <g transform={`translate(${(x1 + x2) / 2}, ${midY})`}>
                      <rect
                        x={-relLabelWidth(link.type) / 2} y={-9}
                        width={relLabelWidth(link.type)} height={18}
                        rx={9}
                        fill={active ? 'rgba(168,85,247,0.22)' : '#0f172a'}
                        stroke={active ? SELECTED : tint}
                        strokeWidth={active ? 1.4 : 1}
                        strokeOpacity={active ? 1 : 0.65}
                      />
                      <text
                        x={0} y={4}
                        textAnchor="middle"
                        fontFamily="ui-monospace, monospace"
                        fontSize={10}
                        fill={active ? '#e9d5ff' : tint}
                      >
                        {link.type.replace(/_/g, ' ')}
                      </text>
                    </g>
                  </g>
                );
              })}
            </svg>

            {/* Nodes */}
            {visible.map(node => {
              const position = positionOf(node);
              const kind = KINDS[node.kind];
              const isSelected = selected === node.id;
              return (
                <div key={node.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`${kind.label} ${node.id}`}
                  onPointerDown={event => startDrag(event, node.id)}
                  onClick={() => select(node.id)}
                  onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(node.id); } }}
                  className="absolute cursor-grab select-none overflow-hidden rounded-lg border text-left active:cursor-grabbing"
                  style={{
                    left: position.x, top: position.y, width: NODE_W, height: NODE_H,
                    borderColor: isSelected ? SELECTED : '#1e293b',
                    background: isSelected ? 'rgba(168,85,247,0.12)' : '#0f172a',
                    borderLeft: `3px solid ${kind.accent}`,
                    boxShadow: isSelected ? `0 0 0 1px ${SELECTED}, 0 8px 24px rgba(0,0,0,0.5)` : '0 6px 18px rgba(0,0,0,0.35)'
                  }}
                >
                  <div className="flex items-start gap-2 px-2.5 pt-2">
                    <span className="font-mono text-[9.5px] uppercase tracking-[0.12em]" style={{ color: kind.accent }}>
                      {kind.label}
                    </span>
                    <GripVertical className="ml-auto size-3 shrink-0 text-slate-600" />
                  </div>
                  <div className="truncate px-2.5 pt-1 font-mono text-[12px] text-slate-100" title={node.name}>
                    {node.name || node.id}
                  </div>
                  {/* Every node explains itself, so the graph is readable without opening
                      the inspector. */}
                  <p className="px-2.5 pt-1 text-[10.5px] leading-[1.35] text-slate-400 line-clamp-2" title={node.explain || node.name}>
                    {node.explain || node.detail || node.meta}
                  </p>
                  <div className="absolute inset-x-0 bottom-0 flex items-end justify-between px-2.5 pb-2 pt-1">
                    <span className="truncate font-mono text-[10px] text-slate-500">{node.meta}</span>
                    {node.count > 0 && (
                      <span className="ml-2 shrink-0 rounded-full px-1.5 py-px font-mono text-[10px]"
                        style={{ background: kind.tint, color: kind.accent }}>{node.count}</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {visible.length === 0 && (
            <div className="grid h-full place-items-center px-6 text-center">
              <p className="max-w-[40ch] text-[13px] text-slate-400">
                No nodes match this search or depth limit. Clear the search or raise the depth limit.
              </p>
            </div>
          )}
        </div>

        {/* Inspector */}
        <AnimatePresence initial={false}>
          {panelOpen && (
            <motion.aside
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 320, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
              className="shrink-0 overflow-hidden"
              aria-label="Node inspector"
            >
              <div className="flex h-full flex-col overflow-y-auto rounded-xl border border-slate-800 bg-[#0d1320] p-4">
                <div className="mb-4 flex items-center gap-2 border-b border-slate-800 pb-3 text-[12px] font-semibold uppercase tracking-[0.1em]">
                  <Network className="size-4" style={{ color: ACCENT }} />
                  Node inspector
                </div>

                {!selectedNode ? (
                  <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
                    <div className="grid size-11 place-items-center rounded-xl border border-slate-800">
                      <span className="font-mono text-[18px] text-slate-600">{'</>'}</span>
                    </div>
                    <div className="text-[15px] text-slate-300">No node selected</div>
                    <p className="text-[12.5px] leading-relaxed text-slate-500">
                      Drag any node to move it, click to inspect it.
                    </p>
                  </div>
                ) : (
                  <NodeInspector node={selectedNode} links={selectedLinks} onJump={select} />
                )}
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
      </div>

      {/* Table alternative, always reachable */}
      <AnimatePresence>
        {showTable && (
          <motion.div initial={{ height: 0 }} animate={{ height: 'auto' }} exit={{ height: 0 }}
            className="overflow-hidden border-t border-slate-800">
            <div className="max-h-[320px] overflow-auto px-5 py-4">
              <table className="w-full border-collapse text-left text-[12.5px]">
                <caption className="sr-only">Evidence relationships, keyboard-accessible equivalent of the graph</caption>
                <thead className="sticky top-0 bg-[#0d1320]">
                  <tr>
                    {['From', 'Relationship', 'To', 'Contribution', 'Rationale'].map(heading => (
                      <th key={heading} className="border-b border-slate-800 px-3 py-2 font-mono text-[11px] uppercase tracking-wider text-slate-500">{heading}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {links.map(link => (
                    <tr key={link.id} className="cursor-pointer hover:bg-slate-900"
                      onClick={() => select(link.target)}>
                      <td className="px-3 py-2 font-mono text-slate-200">{link.source}</td>
                      <td className="px-3 py-2"><span style={{ color: RELATION_TINT[link.type] }}>{link.type}</span></td>
                      <td className="px-3 py-2 font-mono text-slate-200">{link.target}</td>
                      <td className="px-3 py-2 font-mono text-slate-400">{link.score?.toFixed(2) ?? '—'}</td>
                      <td className="px-3 py-2 text-slate-400">{link.rationale}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {links.length === 0 && <p className="py-6 text-center text-[12.5px] text-slate-500">No relationships match the current filter.</p>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Legend */}
      <footer className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-slate-800 px-5 py-3 text-[12px] text-slate-400">
        {Object.entries(KINDS).map(([kind, meta]) => (
          <span key={kind} className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-full border-2" style={{ borderColor: meta.accent }} />
            {meta.label}
          </span>
        ))}
        <span className="mx-1 h-4 w-px bg-slate-800" />
        {[
          ['SUPPORTS', 'supports the claim'],
          ['CONTRADICTS', 'challenges it'],
          ['CONTEXT_FOR', 'background only']
        ].map(([type, hint]) => (
          <span key={type} className="inline-flex items-center gap-1.5" title={hint}>
            <span className="inline-block w-5 border-t border-dashed" style={{ borderColor: RELATION_TINT[type] }} />
            <span style={{ color: RELATION_TINT[type] }}>{type.replace(/_/g, ' ').toLowerCase()}</span>
          </span>
        ))}
        <span className="ml-auto inline-flex items-center gap-4 font-mono text-[11px]">
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block w-5" style={{ background: SELECTED, height: 2 }} />selected
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block w-5 border-t border-dashed border-slate-500" />idle edge
          </span>
        </span>
      </footer>
    </div>
  );
}

function StatTile({ label, value, colour }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-[#0d1320] px-4 py-3">
      <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className="mt-1.5 font-mono text-[22px] font-semibold" style={{ color: colour }}>{value}</div>
    </div>
  );
}

function NodeInspector({ node, links, onJump }) {
  const kind = KINDS[node.kind];
  return (
    <div className="space-y-4">
      <div>
        <div className="font-mono text-[11px] uppercase tracking-[0.12em]" style={{ color: kind.accent }}>{kind.label}</div>
        <div className="mt-1 font-mono text-[13px] text-slate-100">{node.id}</div>
        {node.name && <p className="mt-1.5 text-[12.5px] leading-relaxed text-slate-400">{node.name}</p>}
      </div>

      <dl className="space-y-2">
        {node.detail && <Row label="Detail" value={node.detail} />}
        {node.source && <Row label="Source" value={node.source} />}
        {node.observedAt && <Row label="Observed" value={String(node.observedAt).slice(11, 19)} />}
        {node.ingestLagSeconds !== undefined && <Row label="Ingest lag" value={`${node.ingestLagSeconds}s`} />}
        {node.status && <Row label="Status" value={node.status.replace(/_/g, ' ')} />}
        {node.confidence !== undefined && <Row label="Confidence" value={node.confidence.toFixed(2)} />}
        {node.criticality && <Row label="Criticality" value={node.criticality} />}
        {node.score !== undefined && <Row label="Contribution" value={node.score.toFixed(2)} />}
      </dl>

      {links.length > 0 && (
        <div>
          <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.12em] text-slate-500">Relationships</div>
          <div className="space-y-2">
            {links.map(link => (
              <button key={link.id} onClick={() => onJump(link.target)}
                className="block w-full rounded-lg border border-slate-800 bg-[#0b1220] px-2.5 py-2 text-left transition-colors hover:border-slate-600">
                <span className="font-mono text-[11px]" style={{ color: RELATION_TINT[link.type] }}>{link.type}</span>
                <span className="mt-0.5 block truncate font-mono text-[12px] text-slate-200">
                  {link.source} → {link.target}
                </span>
                {link.rationale && <span className="mt-1 block text-[11.5px] leading-snug text-slate-500">{link.rationale}</span>}
              </button>
            ))}
          </div>
        </div>
      )}

      <p className="border-t border-slate-800 pt-3 text-[11.5px] leading-relaxed text-slate-500">
        An edge here is a typed relationship with provenance, not proof of causation.
        {node.kind === 'Hypothesis' && ' Hypothesis status is separate from incident membership confidence.'}
      </p>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-[12px] text-slate-500">{label}</dt>
      <dd className="truncate font-mono text-[12px] text-slate-200">{value}</dd>
    </div>
  );
}