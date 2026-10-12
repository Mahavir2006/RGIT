import { useMemo, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Play, GitBranch, ShieldCheck, TriangleAlert, ArrowDown } from 'lucide-react';
import { PageHeader, PageBody } from '@/lib/Shell.jsx';
import { Panel, Badge, Button, Metric, EmptyState, Note, stagger, fade } from '@/components/blocks.jsx';
import { KeyValue, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/overlays';
import { useApp } from '@/lib/store.jsx';
import { CASCADE_SCENARIOS, INTERVENTIONS, SCENARIO } from '@/data/scenario.js';
import { RELATION_SEMANTICS } from '@/data/graph.js';
import { cn } from '@/lib/utils';

const SEMANTIC_CLASS = {
  CONFIGURED: 'text-fg-subtle', OBSERVED: 'text-healthy', HYPOTHESIS: 'text-degraded', VALIDATED: 'text-accent'
};
const LEVEL_CLASS = { 1: 'bg-info', 2: 'bg-degraded', 3: 'bg-critical' };

function severityTone(severity) {
  if (severity === 'CRITICAL' || severity === 'HIGH') return 'critical';
  if (severity === 'MODERATE') return 'degraded';
  return 'neutral';
}

export default function Cascade() {
  const { incidentId } = useParams();
  const { store } = useApp();
  const navigate = useNavigate();
  const incident = store.find('Incident', incidentId);
  const [scenarioId, setScenarioId] = useState(CASCADE_SCENARIOS[0].id);
  const [horizon, setHorizon] = useState(CASCADE_SCENARIOS[0].horizon);
  const [running, setRunning] = useState(false);
  const [compared, setCompared] = useState(['IV-BASELINE', 'IV-CLEAR-DRAIN', 'IV-DIVERSION']);

  const scenario = useMemo(() => CASCADE_SCENARIOS.find(item => item.id === scenarioId) ?? CASCADE_SCENARIOS[0], [scenarioId]);
  const selected = INTERVENTIONS.filter(item => compared.includes(item.id));

  if (!incident) {
    return (
      <div className="min-h-full">
        <PageHeader title="Cascade risk" />
        <PageBody><Panel><EmptyState title="Incident not found" body={`${incidentId} has no cascade analysis.`} /></Panel></PageBody>
      </div>
    );
  }

  function runScenario() {
    setRunning(true);
    setTimeout(() => setRunning(false), 900);
  }

  return (
    <div className="min-h-full">
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-2.5">{incidentId} · Cascade risk and what-if</span>}
        description="What could happen next, and which intervention may help — with assumptions and unknowns stated up front."
        actions={<>
          <Button size="md" onClick={() => navigate(`/incidents/${incidentId}/evidence`)}><GitBranch />Evidence</Button>
          <Button variant="primary" size="md" onClick={runScenario} disabled={running}>
            <Play />{running ? 'Running scenario' : 'Run scenario'}
          </Button>
        </>}
      />

      <PageBody className="space-y-4">
        <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-4">
          <div className="flex flex-wrap items-end gap-4">
            <div className="w-[240px]">
              <label className="mb-1.5 block text-[12.5px] font-medium text-fg-muted">Scenario</label>
              <Select value={scenarioId} onValueChange={value => { setScenarioId(value); setHorizon(CASCADE_SCENARIOS.find(item => item.id === value).horizon); }}>
                <SelectTrigger aria-label="Scenario"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {CASCADE_SCENARIOS.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="w-[160px]">
              <label className="mb-1.5 block text-[12.5px] font-medium text-fg-muted">Horizon</label>
              <Select value={horizon} onValueChange={setHorizon}>
                <SelectTrigger aria-label="Horizon"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {['0-3h', '0-6h', '0-12h'].map(option => <SelectItem key={option} value={option}>{option}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <p className="min-w-[260px] flex-1 text-[12.5px] leading-snug text-fg-muted">{scenario.description}</p>
            <Badge tone="degraded">{SCENARIO.mode}</Badge>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <Panel title="Dependency and cascade graph" description={`horizon ${horizon} · ${scenario.status.toLowerCase()}`}>
              {/* Vertical chain. Each arrow states its own semantics so a configured
                  dependency is never presented as an observed or validated fact. */}
              <div className="space-y-0">
                {scenario.nodes.map((node, index) => {
                  const edge = index > 0 ? scenario.edges.find(item => item.to === node.id) : null;
                  return (
                    <div key={node.id}>
                      {edge && (
                        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: index * 0.08 }}
                          className="flex flex-col items-center gap-0.5 py-1.5">
                          <ArrowDown className={cn('size-3.5', SEMANTIC_CLASS[edge.semantics])} />
                          <span className={cn('text-[11.5px]', SEMANTIC_CLASS[edge.semantics])}>
                            {RELATION_SEMANTICS[edge.semantics]}
                          </span>
                        </motion.div>
                      )}
                      <motion.div
                        initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: index * 0.08, duration: 0.32 }}
                        className="flex items-center gap-3 rounded-[8px] border border-border py-2.5 pl-3 pr-4"
                      >
                        <span className={cn('h-7 w-[3px] shrink-0 rounded-full', LEVEL_CLASS[node.level])} />
                        <span className="text-[12px] text-fg-subtle tabular-nums">{node.id}</span>
                        <span className="flex-1 text-[13.5px] font-medium text-fg">{node.label}</span>
                        <span className={cn('font-mono text-[12.5px]', LEVEL_CLASS[node.level].replace('bg-', 'text-'))}>{node.value}</span>
                      </motion.div>
                    </div>
                  );
                })}
              </div>
            </Panel>

            <div className="space-y-4">
              <Panel title="Risk and assumptions" description={scenario.name}>
                <div className="grid grid-cols-2 gap-3 border-b border-border pb-3">
                  <Metric label="Overall cascade risk" value={scenario.baseline_risk.toLowerCase()} tone={severityTone(scenario.baseline_risk)} />
                  <Metric label="Confidence" value={scenario.confidence.toFixed(2)} tone={scenario.confidence >= 0.6 ? 'degraded' : 'critical'} />
                </div>
                <div className="pt-3"><Metric label="Time horizon" value={horizon} /></div>
                <div className="mt-4 border-t border-border pt-3">
                  <div className="mb-1.5 text-[12.5px] font-medium text-fg-muted">Assumptions</div>
                  <ul className="ml-4 list-disc space-y-1 text-[12.5px] leading-snug text-fg-muted">
                    {scenario.assumptions.map(item => <li key={item}>{item}</li>)}
                  </ul>
                </div>
                <div className="mt-4 border-t border-border pt-3">
                  <div className="mb-1.5 text-[12.5px] font-medium text-fg-muted">Unknowns</div>
                  <ul className="ml-4 list-disc space-y-1 text-[12.5px] leading-snug text-degraded">
                    {scenario.unknowns.map(item => <li key={item}>{item}</li>)}
                  </ul>
                  <p className="mt-2 text-[12px] leading-snug text-fg-subtle">
                    Missing dependency data lowers certainty. It is not imputed as safe.
                  </p>
                </div>
              </Panel>

              <Panel title="Infrastructure dependencies" bodyClassName="p-0">
                <dl className="divide-y divide-border">
                  {[
                    { from: 'Rainfall', to: 'Drain DM-04', semantics: 'CONFIGURED' },
                    { from: 'Drain DM-04', to: 'Gauge WG-04', semantics: 'OBSERVED' },
                    { from: 'Underpass', to: 'Hospital approach', semantics: 'CONFIGURED' },
                    { from: 'Road S-13', to: 'Road S-03 Powai', semantics: 'HYPOTHESIS' }
                  ].map(edge => (
                    <div key={`${edge.from}-${edge.to}`} className="flex items-center gap-2 px-4 py-2.5">
                      <span className="text-[12.5px] text-fg">{edge.from}</span>
                      <span className={cn('text-xs', SEMANTIC_CLASS[edge.semantics])}>→</span>
                      <span className="flex-1 text-[12.5px] text-fg-muted">{edge.to}</span>
                      <Badge tone="neutral">{RELATION_SEMANTICS[edge.semantics]}</Badge>
                    </div>
                  ))}
                </dl>
              </Panel>
            </div>
          </div>

          <Panel
            title="Intervention comparison"
            description="Recommendations for review only — nothing is sent to a real control system"
          >
            <div className="mb-4 flex flex-wrap items-center gap-1.5">
              {INTERVENTIONS.map(item => (
                <button key={item.id} onClick={() => setCompared(prev => prev.includes(item.id) ? prev.filter(id => id !== item.id) : [...prev, item.id])}
                  aria-pressed={compared.includes(item.id)}
                  className={cn(
                    'h-7 rounded-[6px] border px-2.5 text-[12.5px] transition-colors',
                    compared.includes(item.id)
                      ? 'border-accent/40 bg-accent-soft font-medium text-accent'
                      : 'border-border text-fg-muted hover:border-border-strong hover:text-fg'
                  )}>
                  {item.name}
                </button>
              ))}
              {compared.length < 3 && <span className="ml-1 text-[12px] text-degraded">Select a baseline plus two interventions to compare.</span>}
            </div>

            {selected.length === 0 ? (
              <EmptyState title="Nothing selected" body="Choose a baseline and at least two interventions to compare." />
            ) : (
              <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${Math.min(selected.length, 4)}, minmax(0, 1fr))` }}>
                {selected.map(item => (
                  <div key={item.id} className={cn(
                    'rounded-[8px] border p-4',
                    item.kind === 'BASELINE' ? 'border-accent/30 bg-accent-soft' : 'border-border'
                  )}>
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-semibold text-fg">{item.name}</span>
                      {item.kind === 'BASELINE' && <Badge tone="accent">baseline</Badge>}
                    </div>
                    <dl className="mt-3">
                      <KeyValue label="Risk band"><Badge tone={severityTone(item.risk_band)}>{item.risk_band.toLowerCase()}</Badge></KeyValue>
                      <KeyValue label="Change vs baseline" mono>
                        <span className={item.risk_delta === null ? 'text-fg-subtle' : item.risk_delta < 0 ? 'text-healthy' : 'text-critical'}>
                          {item.risk_delta === null ? 'reference' : `${item.risk_delta > 0 ? '+' : ''}${item.risk_delta.toFixed(2)}`}
                        </span>
                      </KeyValue>
                      <KeyValue label="Resource cost">{item.resource_cost}</KeyValue>
                      <KeyValue label="Side effects">{item.side_effects}</KeyValue>
                      <KeyValue label="Approval">
                        <span className={item.approval === 'n/a' ? 'text-fg-subtle' : 'text-accent'}>{item.approval}</span>
                      </KeyValue>
                    </dl>
                    {item.assumptions && (
                      <div className="mt-3 border-t border-border pt-3">
                        <div className="mb-1.5 text-[12.5px] font-medium text-fg-muted">Changed assumptions</div>
                        <ul className="ml-4 list-disc space-y-1 text-[12.5px] leading-snug text-fg-muted">
                          {item.assumptions.map(a => <li key={a}>{a}</li>)}
                        </ul>
                      </div>
                    )}
                    {item.kind !== 'BASELINE' && (
                      <Button variant="primary" size="sm" className="mt-4 w-full" onClick={() => navigate('/response')}>
                        <ShieldCheck />Propose action
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}

            <div className="mt-4">
              <Note tone="warning" icon={TriangleAlert}>
                Scenario results are reproducible for identical inputs, configuration and version ({SCENARIO.datasetVersion}).
                This chain is a simulation for this locality and is not asserted to be universally true.
              </Note>
            </div>
          </Panel>
        </motion.div>
      </PageBody>
    </div>
  );
}