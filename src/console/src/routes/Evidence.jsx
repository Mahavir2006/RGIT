import { useMemo, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowRight, Lock, TriangleAlert, Maximize2, Waypoints, ListChecks } from 'lucide-react';
import { PageHeader, PageBody } from '@/lib/Shell.jsx';
import {
  Panel, Badge, Button, Metric, EmptyState, PermissionDenied, TextArea, stagger, fade, Note
} from '@/components/blocks.jsx';
import { KeyValue } from '@/components/overlays';
import { useApp } from '@/lib/store.jsx';
import EvidenceGraph from '@/lib/EvidenceGraph.jsx';
import { evidenceFor, hypothesisEdges } from '@/data/graph.js';
import { clock, bothTimes, latency, titleFromEventType, relativeLag } from '@/lib/format.js';

const HYPOTHESIS_TONE = { CANDIDATE: 'accent', REVIEWED: 'healthy', REJECTED: 'critical', VALIDATED: 'healthy', INSUFFICIENT_EVIDENCE: 'degraded' };

export default function Evidence() {
  const { incidentId } = useParams();
  const { store, can, dispatch, role, audit } = useApp();
  const navigate = useNavigate();
  const [showContradictions, setShowContradictions] = useState(true);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [activeHypothesis, setActiveHypothesis] = useState(null);
  const [note, setNote] = useState('');
  const [relevance, setRelevance] = useState({});

  const incident = store.find('Incident', incidentId);
  const evidence = useMemo(() => evidenceFor(store, incidentId), [store, incidentId]);
  const withEvents = useMemo(() => evidence.map(edge => ({ edge, event: store.find('Event', edge._from) })).filter(item => item.event), [evidence]);
  const hypotheses = useMemo(() => store.all('Hypothesis').filter(item => item.incident_id === incidentId), [store, incidentId]);
  const event = selectedEvent ? store.find('Event', selectedEvent) : null;

  if (!incident) {
    return (
      <div className="min-h-full">
        <PageHeader title="Evidence and causal analysis" />
        <PageBody><Panel><EmptyState title="Incident not found" body={`${incidentId} has no evidence graph.`} /></Panel></PageBody>
      </div>
    );
  }

  function markRelevant(id, value) {
    setRelevance(prev => ({ ...prev, [id]: value }));
    if (!note.trim()) return;
    dispatch({
      type: 'appendAudit',
      entry: {
        id: `AU-${9300 + audit.length}`, at: '2026-10-12T14:08:00+05:30', actor: 'analyst.andheri', actor_role: role.id,
        object_type: 'Event', object_id: id, action: value === 'relevant' ? 'MARKED_RELEVANT' : 'MARKED_IRRELEVANT',
        summary: note.trim().slice(0, 120), reason: 'Analyst annotation; the source event is unchanged.', request_id: `req-${7900 + audit.length}`
      }
    });
    setNote('');
  }

  return (
    <div className="min-h-full">
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-2.5">{incidentId} · Evidence and causal analysis</span>}
        description="Why do we believe these signals belong together, and what else could explain them?"
        actions={<>
          <Button size="md" onClick={() => navigate(`/incidents/${incidentId}/graph`)}><Maximize2 />Full screen</Button>
          <Button size="md" onClick={() => navigate(`/incidents/${incidentId}/cascade`)}><Waypoints />Cascade risk</Button>
          <Button variant="primary" size="md" onClick={() => navigate('/response')}><ListChecks />Response center</Button>
        </>}
      />

      <PageBody className="space-y-4">
        <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-4">
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-[13px] text-fg-muted">
              <input type="checkbox" checked={showContradictions} onChange={event => setShowContradictions(event.target.checked)} className="accent-[var(--accent)]" />
              Show contradictory evidence
            </label>
            <span className="text-[12.5px] text-fg-subtle tabular-nums">
              {evidence.length} relationships · {hypotheses.length} hypotheses
            </span>
            <span className="ml-auto inline-flex items-center gap-1.5 text-[12.5px] text-degraded">
              <TriangleAlert className="size-3.5" />An edge in this graph is not proof of causation
            </span>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
<Panel bodyClassName="p-0" className="overflow-hidden">
            <EvidenceGraph store={store} incidentId={incidentId} showContradictions={showContradictions}
              selectedEvent={selectedEvent} onSelectEvent={setSelectedEvent} height={560} />
          </Panel>

            <Panel title="Hypothesis comparison" description="Competing explanations" bodyClassName="p-0">
              <div className="divide-y divide-border">
                {hypotheses.map(hypothesis => {
                  const edges = hypothesisEdges(store, hypothesis.hypothesis_id);
                  const support = edges.filter(edge => edge._type === 'SUPPORTED_BY').length;
                  const challenge = edges.filter(edge => edge._type === 'CHALLENGED_BY').length;
                  return (
                    <button key={hypothesis.hypothesis_id} onClick={() => setActiveHypothesis(hypothesis.hypothesis_id)}
                      className={`block w-full px-4 py-3 text-left transition-colors ${activeHypothesis === hypothesis.hypothesis_id ? 'bg-accent-soft' : 'hover:bg-surface-2'}`}>
                      <div className="flex items-center gap-2">
                        <Badge tone={HYPOTHESIS_TONE[hypothesis.status]}>{hypothesis.hypothesis_id.replace('HYP-', 'H')}</Badge>
                        <Badge tone="neutral">{hypothesis.status.replace(/_/g, ' ').toLowerCase()}</Badge>
                        <span className="ml-auto text-[13px] font-medium tabular-nums">{hypothesis.confidence.toFixed(2)}</span>
                      </div>
                      <p className="mt-1.5 text-[12.5px] leading-snug text-fg-muted">{hypothesis.claim}</p>
                      <div className="mt-2 flex flex-wrap gap-1.5 text-[12px]">
                        <span className="text-healthy tabular-nums">{support} support</span>
                        <span className="text-critical tabular-nums">{challenge} conflict</span>
                        <span className="text-fg-subtle tabular-nums">{hypothesis.assumptions.length} assumptions</span>
                        <span className="text-degraded tabular-nums">{hypothesis.unknowns.length} unknowns</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </Panel>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
            <Panel title="Selected evidence" description="Provenance and processing">
              {!event ? (
                <EmptyState title="No event selected"
                  body="Select a node in the graph or a row below. Observation time and ingest time are always shown separately so latency and out-of-order arrival stay visible." />
              ) : (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-medium text-accent tabular-nums">{event.event_id}</span>
                    <Badge tone="neutral">{titleFromEventType(event.event_type)}</Badge>
                    <Badge tone={event.quality.status === 'VALID' ? 'healthy' : 'degraded'}>{event.quality.status.toLowerCase()}</Badge>
                    {event.quality.flags.map(flag => <Badge key={flag} tone="neutral">{flag.replace(/_/g, ' ').toLowerCase()}</Badge>)}
                  </div>

                  <dl>
                    <KeyValue label="Source" mono>{event.source_id}</KeyValue>
                    <KeyValue label="Source event id" mono>{event.source_event_id || '—'}</KeyValue>
                    <KeyValue label="Observed at" mono>{clock(event.event_time)} IST</KeyValue>
                    <KeyValue label="Ingested at" mono>{clock(event.ingest_time)} IST{latency(event)?.late ? ' · late' : ''}</KeyValue>
                    <KeyValue label="Location">
                      {event.location ? `${event.location.lat.toFixed(4)}, ${event.location.lon.toFixed(4)} · ${event.location.precision}` : <span className="text-degraded">not supplied</span>}
                    </KeyValue>
                    <KeyValue label="Verification">{event.verification_status.replace(/_/g, ' ')}</KeyValue>
                    <KeyValue label="Measurements">
                      {event.measurements.length
                        ? event.measurements.map(item => `${item.name} ${item.value} ${item.unit}`).join(' · ')
                        : <span className="text-fg-subtle">none</span>}
                    </KeyValue>
                    {event.duplicate_of && (
                      <KeyValue label="Duplicate of">
                        <span className="text-degraded">{event.duplicate_of} — did not increase corroboration</span>
                      </KeyValue>
                    )}
                  </dl>

                  <details className="rounded-[6px] border border-border px-3 py-2">
                    <summary className="cursor-pointer text-[12.5px] font-medium text-fg">Normalised record</summary>
                    <pre className="mt-2 overflow-x-auto rounded-[4px] bg-surface-2 p-2 font-mono text-[11px] leading-snug text-fg-muted">
                      {JSON.stringify({ ...event, trace: undefined }, null, 2)}
                    </pre>
                  </details>

                  <details className="rounded-[6px] border border-border px-3 py-2">
                    <summary className="cursor-pointer text-[12.5px] font-medium text-fg">
                      Raw payload <span className="font-normal text-fg-subtle">(permission controlled)</span>
                    </summary>
                    {can('inspect') && role.id !== 'VIEWER' ? (
                      <pre className="mt-2 overflow-x-auto rounded-[4px] bg-surface-2 p-2 font-mono text-[11px] text-fg-muted">
                        {JSON.stringify({ payload_ref: event.payload_ref, text: event.text ?? null, secrets: '[redacted]', personal_data: '[minimised]' }, null, 2)}
                      </pre>
                    ) : (
                      <p className="mt-2 flex items-center gap-1.5 text-[12.5px] text-fg-subtle">
                        <Lock className="size-3.5" />Restricted for your role.
                      </p>
                    )}
                  </details>

                  {can('annotate') ? (
                    <div className="space-y-2 border-t border-border pt-3">
                      <TextArea label="Analyst rationale" value={note} onChange={setNote} rows={2}
                        placeholder="Explain why this evidence is or is not relevant. Annotation never mutates the source event." />
                      <div className="flex gap-2">
                        <Button size="sm" onClick={() => markRelevant(event.event_id, 'relevant')} disabled={!note.trim()}>Mark relevant</Button>
                        <Button size="sm" variant="ghost" onClick={() => markRelevant(event.event_id, 'irrelevant')} disabled={!note.trim()}>Mark irrelevant</Button>
                      </div>
                    </div>
                  ) : <PermissionDenied missing="evidence annotation" />}
                </div>
              )}
            </Panel>

            <div className="space-y-4">
              <Panel title="Hypothesis detail" description="Assumptions, unknowns and counter-evidence">
                {!activeHypothesis ? (
                  <EmptyState title="No hypothesis selected" body="Select a hypothesis to inspect its evidence, assumptions and unknowns." />
                ) : (() => {
                  const hypothesis = hypotheses.find(item => item.hypothesis_id === activeHypothesis);
                  if (!hypothesis) return null;
                  return (
                    <div className="space-y-4">
                      <p className="text-[13px] leading-snug text-fg">{hypothesis.claim}</p>
                      <div className="grid grid-cols-3 gap-3 border-y border-border py-3">
                        <Metric label="Confidence" value={hypothesis.confidence.toFixed(2)} />
                        <Metric label="Version" value={`v${hypothesis.version}`} />
                        <Metric label="Generated by" value="causal 1.2.0" />
                      </div>
                      <div>
                        <div className="mb-1.5 text-[12.5px] font-medium text-fg-muted">Supporting evidence</div>
                        <div className="flex flex-wrap gap-1.5">
                          {hypothesis.evidence_for.length
                            ? hypothesis.evidence_for.map(id => <Button key={id} size="sm" variant="ghost" onClick={() => setSelectedEvent(id)}>{id}</Button>)
                            : <span className="text-[12.5px] text-fg-subtle">None recorded.</span>}
                        </div>
                      </div>
                      <div>
                        <div className="mb-1.5 text-[12.5px] font-medium text-fg-muted">Counter-evidence</div>
                        <div className="flex flex-wrap gap-1.5">
                          {hypothesis.evidence_against.length
                            ? hypothesis.evidence_against.map(id => <Button key={id} size="sm" variant="ghost" onClick={() => setSelectedEvent(id)}>{id}</Button>)
                            : <span className="text-[12.5px] text-fg-subtle">None recorded.</span>}
                        </div>
                      </div>
                      <div>
                        <div className="mb-1.5 text-[12.5px] font-medium text-fg-muted">Assumptions</div>
                        {hypothesis.assumptions.length
                          ? <ul className="ml-4 list-disc space-y-1 text-[12.5px] text-fg-muted">{hypothesis.assumptions.map(item => <li key={item}>{item}</li>)}</ul>
                          : <span className="text-[12.5px] text-fg-subtle">No assumptions recorded.</span>}
                      </div>
                      <div>
                        <div className="mb-1.5 text-[12.5px] font-medium text-fg-muted">Unknowns</div>
                        {hypothesis.unknowns.length
                          ? <ul className="ml-4 list-disc space-y-1 text-[12.5px] text-degraded">{hypothesis.unknowns.map(item => <li key={item}>{item}</li>)}</ul>
                          : <span className="text-[12.5px] text-fg-subtle">No unknowns recorded.</span>}
                      </div>
                      {!hypothesis.evidence_for.length && (
                        <Note tone="warning" icon={TriangleAlert}>
                          This hypothesis cannot be promoted. It has no evidence references and is returned as an explicit
                          insufficient-evidence result rather than a fabricated explanation.
                        </Note>
                      )}
                    </div>
                  );
                })()}
              </Panel>
            </div>
          </div>

          <Panel title="Event ledger" description="Click a row to inspect" bodyClassName="p-0">
            <DataTableLedger rows={withEvents} selectedEvent={selectedEvent} onSelect={setSelectedEvent} />
          </Panel>
        </motion.div>
      </PageBody>
    </div>
  );
}

function DataTableLedger({ rows, selectedEvent, onSelect }) {
  if (!rows.length) return <EmptyState title="No evidence linked" body="No events are currently associated with this incident." />;
  return (
    <div className="max-h-[320px] overflow-auto">
      <table className="w-full min-w-[820px] border-collapse">
        <thead className="sticky top-0 bg-surface">
          <tr className="border-b border-border">
            {['Event', 'Relation', 'Source', 'Type', 'Observed to ingested', 'Lag', 'Contribution'].map(heading => (
              <th key={heading} className="px-4 py-2 text-left text-[12px] font-medium text-fg-subtle">{heading}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ edge, event }) => (
            <tr key={edge.link_id} tabIndex={0}
              onClick={() => onSelect(event.event_id)}
              onKeyDown={keyEvent => { if (keyEvent.key === 'Enter') onSelect(event.event_id); }}
              className={`cursor-pointer border-b border-border transition-colors hover:bg-surface-2 ${selectedEvent === event.event_id ? 'bg-accent-soft' : ''}`}>
              <td className="px-4 py-2.5 font-mono text-[12px] text-accent">{event.event_id}</td>
              <td className="px-4 py-2.5">
                <Badge tone={edge._type === 'SUPPORTS' ? 'healthy' : edge._type === 'CONTRADICTS' ? 'critical' : 'neutral'}>
                  {edge._type.replace('_', ' ').toLowerCase()}
                </Badge>
              </td>
              <td className="px-4 py-2.5 font-mono text-[12px]">{event.source_id}</td>
              <td className="px-4 py-2.5 text-[13px]">{titleFromEventType(event.event_type)}</td>
              <td className="px-4 py-2.5 font-mono text-[12px] tabular-nums">{bothTimes(event)}</td>
              <td className="px-4 py-2.5 text-right text-[12.5px] tabular-nums">{relativeLag(latency(event)?.seconds)}</td>
              <td className="px-4 py-2.5 text-right text-[12.5px] tabular-nums">{edge.score.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}