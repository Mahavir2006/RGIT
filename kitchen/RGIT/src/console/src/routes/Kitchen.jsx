import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import * as THREE from 'three';
import { X, Play, Pause, RotateCcw, ArrowRight, ListChecks, ShieldCheck } from 'lucide-react';
import KitchenFloor from '@/components/KitchenFloor.jsx';
import { useKitchenSnapshot } from '@/lib/kitchenSnapshot.js';
import { AGENT_IDS, AGENT_META, AGENT_LAYOUT, CONNECTED, ORCHESTRATOR, STATUS_LABEL } from '@/lib/agents.js';
import { PageHeader } from '@/lib/Shell.jsx';
import { Badge, Button } from '@/components/ui';
import { KeyValue } from '@/components/overlays';
import { SCENARIO } from '@/data/scenario.js';
import { cn } from '@/lib/utils';

// Status colours are semantic, and every one of them also carries a text label.
const DOT = {
  idle: 'bg-border-strong',
  working: 'bg-accent',
  waiting: 'bg-degraded',
  attention: 'bg-critical',
  complete: 'bg-healthy'
};

const VIEWS = [
  { id: 'overview', label: 'Overview' },
  { id: 'desks', label: 'Desks' },
  { id: 'active', label: 'Active' }
];

// The scenario clock sweeps the 36-minute replay window and then holds.
const SWEEP_MS = 90;

export default function Kitchen() {
  const navigate = useNavigate();
  const floorApi = useRef({});
  const [selected, setSelected] = useState(null);
  const [replay, setReplay] = useState(100);
  const [playing, setPlaying] = useState(true);
  const [view, setView] = useState('overview');

  const snap = useKitchenSnapshot(replay);

  useEffect(() => {
    if (!playing) return undefined;
    const timer = setInterval(() => {
      setReplay(value => (value >= 100 ? 0 : value + 0.6));
    }, SWEEP_MS);
    return () => clearInterval(timer);
  }, [playing]);

  const activeAgent = AGENT_IDS.find(id => snap.agents[id]?.status === 'working') || 'fuse';
  const busy = AGENT_IDS.filter(id => ['working', 'attention', 'waiting'].includes(snap.agents[id]?.status));

  function focus(which) {
    setView(which);
    const focusOn = floorApi.current.focusOn;
    if (!focusOn) return;
    if (which === 'overview') focusOn(new THREE.Vector3(0, 0.5, 0));
    else if (which === 'desks') focusOn(new THREE.Vector3(0, 0.5, -1.5));
    else {
      const [x, z] = AGENT_LAYOUT[activeAgent];
      focusOn(new THREE.Vector3(x, 0.8, z));
    }
  }

  const inspector = selected && selected !== 'orchestrator' ? snap.agents[selected] : null;

  return (
    <div className="flex min-h-full flex-col">
      <PageHeader
        title="Agent floor"
        description={snap.workflow
          ? `Live intelligence workflow ${snap.workflow.workflow_id} · ${snap.workflow.incident_id || 'incident pending'} · updates automatically`
          : 'Waiting for an intelligence workflow. The four intelligence desks update here as the backend runs each specialist.'}
        actions={<>
          <Button size="md" onClick={() => navigate('/response')}>
            <ShieldCheck />{snap.wall.pending} awaiting approval<ArrowRight />
          </Button>
          <Badge tone={snap.workflow ? 'healthy' : 'degraded'}>{snap.workflow ? `Workflow ${snap.workflow.status}` : 'No live workflow'}</Badge>
        </>}
      />

      {/* The floor is full-bleed; the inspector floats over it rather than stealing width. */}
      <div className="relative flex-1" style={{ minHeight: 580 }}>
        <KitchenFloor snap={snap} onSelect={setSelected} selected={selected} apiRef={floorApi} />

        {/* Left HUD: roster, camera presets, scenario clock. */}
        <div className="pointer-events-none absolute left-4 top-4 w-[268px] max-w-[calc(100%-2rem)]">
          <div className="pointer-events-auto rounded-app border border-border bg-surface/95 p-4 backdrop-blur">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[13px] font-semibold text-fg">Operations floor</span>
              <Badge tone={snap.workflow ? 'healthy' : 'degraded'}>{snap.workflow ? 'Live workflow' : SCENARIO.mode}</Badge>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-1">
              {AGENT_IDS.map(id => (
                <button key={id} onClick={() => setSelected(id)}
                  className={cn(
                    'flex items-center gap-1.5 rounded-[6px] px-2 py-1 text-left transition-colors',
                    selected === id ? 'bg-accent-soft' : 'hover:bg-surface-2'
                  )}>
                  <span className={cn('size-1.5 shrink-0 rounded-full', DOT[snap.agents[id]?.status || 'idle'])} />
                  <span className="truncate text-[11.5px] text-fg-muted">{AGENT_META[id].name}</span>
                </button>
              ))}
            </div>

            <div className="mt-3 flex gap-1.5">
              {VIEWS.map(item => (
                <button key={item.id} onClick={() => focus(item.id)}
                  className={cn(
                    'flex-1 rounded-[6px] border px-2 py-1.5 text-[11.5px] transition-colors',
                    view === item.id ? 'border-accent/40 bg-accent-soft text-accent' : 'border-border text-fg-muted hover:text-fg'
                  )}>
                  {item.label}
                </button>
              ))}
            </div>

            <div className="mt-3 border-t border-border pt-3">
              <div className="mb-1.5 flex items-center gap-2">
                <button onClick={() => setPlaying(value => !value)}
                  className="grid size-7 place-items-center rounded-[6px] border border-border text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg"
                  aria-label={playing ? 'Pause the scenario clock' : 'Play the scenario clock'}>
                  {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
                </button>
                <button onClick={() => { setReplay(0); setPlaying(true); }}
                  className="grid size-7 place-items-center rounded-[6px] border border-border text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg"
                  aria-label="Replay the scenario from the start">
                  <RotateCcw className="size-3.5" />
                </button>
                <span className="text-[11.5px] text-fg-subtle tabular-nums">{Math.round(replay)}% of window</span>
              </div>
              <input type="range" min="0" max="100" value={replay}
                onChange={event => { setReplay(Number(event.target.value)); setPlaying(false); }}
                aria-label="Scenario clock position"
                className="h-1 w-full cursor-pointer appearance-none rounded-full bg-surface-3 accent-[var(--accent)]" />
              <p className="mt-1.5 text-[11.5px] leading-snug text-fg-subtle">
                Scrubbing rewinds what the agents have observed; the counts move with the clock.
              </p>
            </div>
          </div>
        </div>

        {/* Orchestrator inspector. */}
        {selected === 'orchestrator' && (
          <motion.div initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }}
            className="pointer-events-none absolute right-4 top-4 w-[300px] max-w-[calc(100%-2rem)]">
            <div className="pointer-events-auto rounded-app border border-border bg-surface/95 p-4 backdrop-blur">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-[14px] font-semibold text-fg">{ORCHESTRATOR.name}</div>
                  <div className="text-[12px] text-fg-subtle">{ORCHESTRATOR.role}</div>
                </div>
                <button onClick={() => setSelected(null)} aria-label="Close inspector" className="text-fg-subtle hover:text-fg">
                  <X className="size-4" />
                </button>
              </div>
              <dl className="mt-3">
                <KeyValue label="Status">
                  <span className={snap.hub === 'waiting' ? 'text-degraded' : 'text-fg'}>
                    {snap.hub === 'waiting' ? 'Waiting on approval' : 'Idle'}
                  </span>
                </KeyValue>
                <KeyValue label="Events observed" mono>{snap.wall.events}</KeyValue>
                <KeyValue label="Awaiting approval" mono>{snap.wall.pending}</KeyValue>
                <KeyValue label="Workflow">{snap.workflow?.status || 'Waiting'}</KeyValue>
                {snap.workflow?.workflow_id && <KeyValue label="Run ID" mono>{snap.workflow.workflow_id}</KeyValue>}
                {snap.workflow?.incident_id && <KeyValue label="Incident" mono>{snap.workflow.incident_id}</KeyValue>}
              </dl>
              <p className="mt-3 border-t border-border pt-3 text-[11.5px] leading-snug text-fg-subtle">
                {ORCHESTRATOR.guards}
              </p>
            </div>
          </motion.div>
        )}

        {/* Agent inspector. */}
        {inspector && (
          <motion.div initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }}
            className="pointer-events-none absolute right-4 top-4 w-[320px] max-w-[calc(100%-2rem)]">
            <div className="pointer-events-auto rounded-app border border-border bg-surface/95 p-4 backdrop-blur">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={cn('size-1.5 rounded-full', DOT[inspector.status])} />
                    <span className="text-[14px] font-semibold text-fg">{AGENT_META[selected].name}</span>
                  </div>
                  <div className="mt-0.5 text-[12px] leading-snug text-fg-subtle">{AGENT_META[selected].role}</div>
                </div>
                <button onClick={() => setSelected(null)} aria-label="Close inspector" className="text-fg-subtle hover:text-fg">
                  <X className="size-4" />
                </button>
              </div>

              <dl className="mt-3">
                <KeyValue label="Status">
                  <span className={cn(
                    inspector.status === 'attention' ? 'text-critical'
                      : inspector.status === 'waiting' ? 'text-degraded'
                        : inspector.status === 'working' ? 'text-accent' : 'text-fg-muted'
                  )}>{STATUS_LABEL[inspector.status]}</span>
                </KeyValue>
                <KeyValue label="Records handled" mono>{inspector.count}</KeyValue>
              </dl>

              <div className="mt-3 border-t border-border pt-3">
                <div className="text-[12px] font-medium text-fg-muted">Current task</div>
                <p className="mt-1 text-[12.5px] leading-snug text-fg">{inspector.task}</p>
                {inspector.summary && <p className="mt-1 text-[12px] leading-snug text-fg-subtle">{inspector.summary}</p>}
              </div>

              {inspector.events?.length > 0 && (
                <div className="mt-3 border-t border-border pt-3">
                  <div className="text-[12px] font-medium text-fg-muted">Recent activity</div>
                  <div className="mt-1.5 space-y-1">
                    {inspector.events.map((event, index) => (
                      <div key={index} className="text-[11.5px] leading-snug">
                        <span className="text-fg">{event.action}</span>
                        {event.summary && <span className="text-fg-subtle"> — {event.summary}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="mt-3 border-t border-border pt-3 text-[11.5px] text-fg-subtle">
                {AGENT_META[selected].guards}
              </div>

              <div className="mt-2 text-[11.5px] text-fg-subtle">
                Hands off to {CONNECTED[selected]?.length
                  ? CONNECTED[selected].map(id => AGENT_META[id].name).join(', ')
                  : 'nothing downstream — terminal step'}
              </div>

              <div className="mt-3 flex gap-2">
                <Button size="sm" variant="primary" className="flex-1" onClick={() => navigate('/events')}>
                  Event log<ArrowRight />
                </Button>
                <Button size="sm" className="flex-1" onClick={() => navigate('/response')}>
                  <ListChecks />Response
                </Button>
              </div>
            </div>
          </motion.div>
        )}

        {/* Bottom strip: legend and active roster. */}
        <div className="pointer-events-none absolute bottom-4 left-4 right-4 flex flex-wrap items-end justify-between gap-3">
          <div className="pointer-events-auto flex flex-wrap items-center gap-3 rounded-app border border-border bg-surface/95 px-3 py-2 text-[11.5px] text-fg-muted backdrop-blur">
            {Object.entries(STATUS_LABEL).map(([status, label]) => (
              <span key={status} className="inline-flex items-center gap-1.5">
                <span className={cn('size-1.5 rounded-full', DOT[status])} />
                {label}
              </span>
            ))}
          </div>
          <div className="pointer-events-auto max-w-[420px] rounded-app border border-border bg-surface/95 px-3 py-2 backdrop-blur">
            <div className="text-[11px] text-fg-subtle tabular-nums">
              {busy.length} of {AGENT_IDS.length} agents active · {snap.wall.events} events in window
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {busy.map(id => (
                <button key={id} onClick={() => setSelected(id)}
                  className="inline-flex items-center gap-1 rounded-[5px] border border-border px-1.5 py-0.5 text-[11px] text-fg-muted hover:border-border-strong hover:text-fg">
                  <span className={cn('size-1.5 rounded-full', DOT[snap.agents[id].status])} />
                  {AGENT_META[id].name}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
