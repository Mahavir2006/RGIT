import { useMemo, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowRight, GitBranch, Waypoints, ListChecks, Lock, TriangleAlert } from 'lucide-react';
import { PageHeader, PageBody } from '@/lib/Shell.jsx';
import {
  Panel, Tabs, DataTable, Badge, Button, Metric, ConfidenceBar, EmptyState,
  PermissionDenied, TextArea, UncalibratedNote, stagger, fade
} from '@/components/blocks.jsx';
import { KeyValue } from '@/components/overlays';
import { useApp } from '@/lib/store.jsx';
import { evidenceFor, incidentAssets, STATUS_TRANSITIONS } from '@/data/graph.js';
import { ACTIONS } from '@/data/scenario.js';
import { clock, ago, titleFromEventType } from '@/lib/format.js';
import { cn } from '@/lib/utils';

const TABS = [
  { id: 'summary', label: 'Summary' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'assets', label: 'Affected assets' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'actions', label: 'Actions' },
  { id: 'audit', label: 'Audit' }
];

function severityTone(severity) {
  if (severity === 'CRITICAL' || severity === 'HIGH') return 'critical';
  if (severity === 'MODERATE') return 'degraded';
  return 'neutral';
}

export default function IncidentDetail() {
  const { incidentId } = useParams();
  const { store, incidents, audit, can, dispatch, role } = useApp();
  const navigate = useNavigate();
  const [tab, setTab] = useState('summary');
  const [note, setNote] = useState('');
  const [annotations, setAnnotations] = useState([]);

  const incident = incidents.find(item => item.incident_id === incidentId);
  const evidence = useMemo(() => (incident ? evidenceFor(store, incident.incident_id) : []), [store, incident]);
  const withEvents = useMemo(
    () => evidence.map(edge => ({ edge, event: store.find('Event', edge._from) })).filter(item => item.event),
    [evidence]
  );
  const hypotheses = useMemo(() => store.all('Hypothesis').filter(item => item.incident_id === incidentId), [store, incidentId]);
  const assets = useMemo(() => (incident ? incidentAssets(store, incident.incident_id) : []), [store, incident]);
  const actions = useMemo(() => ACTIONS.filter(item => item.incident_id === incidentId), [incidentId]);
  const incidentAudit = useMemo(
    () => audit.filter(entry => entry.object_id === incidentId || evidence.some(edge => edge._from === entry.object_id)),
    [audit, incidentId, evidence]
  );

  if (!incident) {
    return (
      <div className="min-h-full">
        <PageHeader title="Incident not found" />
        <PageBody>
          <Panel>
            <EmptyState
              title="No such incident"
              body={`${incidentId} does not exist in the current scenario dataset. This is a 404, not an absence of incidents in the city.`}
              action={<Button onClick={() => navigate('/incidents')}>Back to incidents</Button>}
            />
          </Panel>
        </PageBody>
      </div>
    );
  }

  const supporting = evidence.filter(edge => edge._type === 'SUPPORTS');
  const contradicting = evidence.filter(edge => edge._type === 'CONTRADICTS');
  const contextual = evidence.filter(edge => edge._type === 'CONTEXT_FOR');
  const seenTypes = new Set(evidence.filter(edge => edge._type !== 'CONTRADICTS').map(edge => store.find('Event', edge._from)?.event_type));
  const missing = incident.expected_signals.filter(type => !seenTypes.has(type));
  const sourceCategories = new Set(evidence.map(edge => store.find('Event', edge._from)?.source_id).filter(Boolean));
  const allowedNext = STATUS_TRANSITIONS[incident.status] || [];

  function recordAudit(action, summary, objectType = 'Incident', objectId = incidentId) {
    dispatch({
      type: 'appendAudit',
      entry: {
        id: `AU-${9100 + audit.length}`, at: '2026-10-12T14:07:30+05:30', actor: 'analyst.andheri', actor_role: role.id,
        object_type: objectType, object_id: objectId, action, summary, reason: null, request_id: `req-${7800 + audit.length}`
      }
    });
  }

  function changeStatus(to) {
    dispatch({ type: 'changeIncidentStatus', incidentId, to });
    recordAudit('STATUS_CHANGED', `Status moved from ${incident.status} to ${to}.`);
  }

  function addAnnotation() {
    if (!note.trim()) return;
    const annotation = { at: '2026-10-12T14:07:10+05:30', actor: role.label, text: note.trim() };
    setAnnotations(prev => [...prev, annotation]);
    recordAudit('ANNOTATION_ADDED', annotation.text.slice(0, 120));
    setNote('');
  }

  return (
    <div className="min-h-full">
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-2.5">{incident.incident_id} · {incident.title}</span>}
        description={incident.summary}
        actions={<>
          <Button size="md" onClick={() => navigate(`/incidents/${incidentId}/evidence`)}><GitBranch />Evidence</Button>
          <Button size="md" onClick={() => navigate(`/incidents/${incidentId}/cascade`)}><Waypoints />Cascade risk</Button>
          <Button variant="primary" size="md" onClick={() => navigate('/response')}><ListChecks />Response center</Button>
        </>}
      />

      <PageBody className="space-y-4">
        <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-4">
          <Panel bodyClassName="p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={severityTone(incident.severity)}>{incident.severity.toLowerCase()}</Badge>
              <Badge tone="neutral">{incident.status.replace(/_/g, ' ').toLowerCase()}</Badge>
              <Badge tone="neutral">{incident.area_name}</Badge>
              <Badge tone="neutral">{incident.location_precision} precision · ±{incident.location_uncertainty_m} m</Badge>
              <Badge tone="neutral">{incident.owner ?? 'Unassigned'}</Badge>
              {incident.tags.map(tag => <Badge key={tag} tone="neutral">#{tag}</Badge>)}
            </div>

            {/* Transitions come from the code-defined graph, not free text. */}
            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3">
              <span className="text-[12.5px] text-fg-subtle">Transition to</span>
              {allowedNext.map(next => (
                <Button key={next} size="sm" disabled={!can('annotate')}
                  title={`Move to ${next}`}
                  onClick={() => changeStatus(next)}>
                  {next.replace(/_/g, ' ').toLowerCase()}
                </Button>
              ))}
              <Button size="sm" variant="ghost" onClick={() => navigate(`/incidents/${incidentId}/cascade`)}>
                Cascade risk<ArrowRight />
              </Button>
              {!can('annotate') && <span className="ml-auto inline-flex items-center gap-1.5 text-[12.5px] text-fg-subtle"><Lock className="size-3.5" />Read-only role</span>}
            </div>
          </Panel>

          <Tabs tabs={TABS} active={tab} onChange={setTab} />

          {tab === 'summary' && (
            <motion.div variants={fade} className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
              <div className="space-y-4">
                <Panel title="Incident summary">
                  <dl>
                    <KeyValue label="Identity" mono>{incident.incident_id} · {incident.type}</KeyValue>
                    <KeyValue label="Created" mono>{clock(incident.created_at)} IST</KeyValue>
                    <KeyValue label="First seen" mono>{clock(incident.first_seen_at)} IST</KeyValue>
                    <KeyValue label="Last updated" mono>{clock(incident.updated_at)} IST</KeyValue>
                    <KeyValue label="Location">{incident.area_name} · {incident.lat.toFixed(4)}, {incident.lon.toFixed(4)}</KeyValue>
                    <KeyValue label="Impacted radius">{incident.impacted_radius_m} m</KeyValue>
                    <KeyValue label="Time horizon">{incident.time_horizon}</KeyValue>
                    <KeyValue label="Impact confidence" mono>{incident.confidence.impact_confidence.toFixed(2)}</KeyValue>
                  </dl>
                </Panel>

                <Panel title="Competing hypotheses" bodyClassName="p-0">
                  <div className="divide-y divide-border">
                    {hypotheses.filter(item => item.status !== 'INSUFFICIENT_EVIDENCE').map(hypothesis => (
                      <div key={hypothesis.hypothesis_id} className="px-4 py-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge tone="accent">{hypothesis.hypothesis_id}</Badge>
                          <Badge tone="neutral">{hypothesis.status.replace(/_/g, ' ').toLowerCase()}</Badge>
                          <span className="ml-auto text-[13px] font-medium tabular-nums">{hypothesis.confidence.toFixed(2)}</span>
                        </div>
                        <p className="mt-1.5 text-[13px] leading-snug text-fg-muted">{hypothesis.claim}</p>
                        <p className="mt-1.5 text-[12px] text-fg-subtle">
                          {hypothesis.evidence_for.length} supporting · {hypothesis.evidence_against.length} conflicting · v{hypothesis.version}
                        </p>
                      </div>
                    ))}
                  </div>
                  <div className="border-t border-border p-4"><UncalibratedNote /></div>
                </Panel>
              </div>

              <div className="space-y-4">
                <Panel title="Confidence and data quality" description="Three distinct dimensions">
                  <ConfidenceBar label="Event validity" value={incident.confidence.validity}
                    hint="Estimate of whether the signals themselves are credible." />
                  <ConfidenceBar label="Incident membership" value={incident.confidence.membership}
                    hint="Estimate that these signals belong to this incident." />
                  <ConfidenceBar label="Cause hypothesis" value={incident.confidence.cause}
                    hint="Estimate supporting the leading explanation. Distinct from membership." />
                  <p className="mt-3 border-t border-border pt-3 text-[12.5px] leading-snug text-fg-muted">
                    {incident.confidence.rationale}
                  </p>
                  <div className="mt-3"><UncalibratedNote /></div>
                </Panel>

                <Panel title="Evidence summary">
                  <div className="grid grid-cols-3 gap-3 border-b border-border pb-3">
                    <Metric label="Supporting" value={supporting.length} tone="healthy" />
                    <Metric label="Contradicting" value={contradicting.length} tone="critical" />
                    <Metric label="Context only" value={contextual.length} />
                  </div>
                  <div className="grid grid-cols-2 gap-3 pt-3">
                    <Metric label="Source categories" value={sourceCategories.size} />
                    <Metric label="Missing signals" value={missing.length} tone={missing.length ? 'degraded' : undefined} />
                  </div>
                  {missing.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {missing.map(type => <Badge key={type} tone="degraded"><TriangleAlert />{titleFromEventType(type)}</Badge>)}
                    </div>
                  )}
                  <p className="mt-3 border-t border-border pt-3 text-[12px] leading-snug text-fg-subtle">
                    A missing signal lowers observability confidence. It is not evidence that conditions are safe.
                  </p>
                </Panel>
              </div>
            </motion.div>
          )}

          {tab === 'timeline' && (
            <motion.div variants={fade}>
              <Panel title="Timeline" description="Observation time and ingest time kept separate" bodyClassName="p-0">
                <div className="divide-y divide-border">
                  {withEvents
                    .sort((a, b) => String(a.event.event_time).localeCompare(String(b.event.event_time)))
                    .map(({ edge, event }) => (
                      <div key={edge.link_id} className="flex gap-4 px-4 py-3">
                        <div className="w-[190px] shrink-0">
                          <div className="text-[12.5px] text-fg tabular-nums">{clock(event.event_time)}</div>
                          <div className="mt-0.5 text-[12px] text-fg-subtle tabular-nums">ingested {clock(event.ingest_time)}</div>
                          {event.quality.flags.includes('OUT_OF_ORDER') && <Badge tone="degraded" className="mt-1">out of order</Badge>}
                        </div>
                        <div className="min-w-0 flex-1 border-l border-border pl-4">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-[12px] font-medium text-accent tabular-nums">{event.event_id}</span>
                            <Badge tone={edge._type === 'SUPPORTS' ? 'healthy' : edge._type === 'CONTRADICTS' ? 'critical' : 'neutral'}>
                              {edge._type.replace('_', ' ').toLowerCase()}
                            </Badge>
                            <span className="text-[13px] font-medium text-fg">{event.summary}</span>
                          </div>
                          <p className="mt-1 text-[12px] text-fg-subtle">
                            {event.source_id} · {titleFromEventType(event.event_type)} · contribution {edge.score.toFixed(2)}
                          </p>
                          <p className="mt-1 text-[12.5px] leading-snug text-fg-muted">{edge.rationale}</p>
                        </div>
                      </div>
                    ))}
                </div>
              </Panel>
            </motion.div>
          )}

          {tab === 'assets' && (
            <motion.div variants={fade}>
              <Panel title="Affected assets" description="(:Incident)-[:AFFECTS]->(:Asset)" bodyClassName="p-0">
                {assets.length === 0
                  ? <EmptyState title="No assets linked" body="No infrastructure is currently associated with this incident." />
                  : (
                    <DataTable
                      rowId={row => row.asset_id}
                      columns={[
                        { key: 'asset_id', label: 'Asset', render: row => <span className="text-[12.5px] font-medium tabular-nums">{row.asset_id}</span> },
                        { key: 'name', label: 'Name' },
                        { key: 'type', label: 'Type', render: row => <Badge tone="neutral">{row.type.replace(/_/g, ' ').toLowerCase()}</Badge> },
                        { key: 'criticality', label: 'Criticality', render: row => <Badge tone={severityTone(row.criticality)}>{row.criticality.toLowerCase()}</Badge> },
                        { key: 'source', label: 'Source', render: row => <span className="font-mono text-[12px] text-fg-subtle">{row.source}</span> },
                        { key: 'freshness', label: 'Data freshness', align: 'right', render: row => <span className="text-[12.5px] tabular-nums">{ago(row.freshness)}</span> },
                        { key: 'impact', label: 'Impact', render: row => (
                          <span className="text-[12.5px] text-fg-muted">{row.impact_type.replace(/_/g, ' ')}
                            <span className="block text-[12px] text-fg-subtle tabular-nums">conf {row.confidence?.toFixed(2)} · {row.time_horizon}</span></span>
                        ) }
                      ]}
                      rows={assets.map(edge => store.find('Asset', edge._to))}
                    />
                  )}
              </Panel>
            </motion.div>
          )}

          {tab === 'evidence' && (
            <motion.div variants={fade}>
              <Panel title="Evidence preview" description="Supporting, contradictory and contextual"
                actions={<Button variant="ghost" size="sm" onClick={() => navigate(`/incidents/${incidentId}/evidence`)}>Full graph<ArrowRight /></Button>}
                bodyClassName="p-0">
                <DataTable
                  rowId={row => row.link_id}
                  columns={[
                    { key: 'event_id', label: 'Event', render: row => <span className="text-[12.5px] font-medium text-accent tabular-nums">{row.event_id}</span> },
                    { key: 'relation', label: 'Relation', render: row => (
                      <Badge tone={row._type === 'SUPPORTS' ? 'healthy' : row._type === 'CONTRADICTS' ? 'critical' : 'neutral'}>
                        {row._type.replace('_', ' ').toLowerCase()}
                      </Badge>
                    ) },
                    { key: 'source', label: 'Source', render: row => <span className="font-mono text-[12px]">{row.source_id}</span> },
                    { key: 'score', label: 'Contribution', align: 'right', render: row => <span className="text-[12.5px] tabular-nums">{row.score.toFixed(2)}</span> },
                    { key: 'rationale', label: 'Why', render: row => <span className="text-[12.5px] text-fg-muted">{row.rationale}</span> }
                  ]}
                  rows={evidence}
                />
              </Panel>
            </motion.div>
          )}

          {tab === 'actions' && (
            <motion.div variants={fade}>
              <Panel title="Response actions" description="Linked to this incident" bodyClassName="p-0">
                <DataTable
                  rowId={row => row.action_id}
                  columns={[
                    { key: 'action_id', label: 'Action', render: row => <span className="text-[12.5px] font-medium text-accent tabular-nums">{row.action_id}</span> },
                    { key: 'type', label: 'Recommended action' },
                    { key: 'priority', label: 'Priority', render: row => <Badge tone={row.priority === 'P1' ? 'critical' : row.priority === 'P2' ? 'degraded' : 'neutral'}>{row.priority}</Badge> },
                    { key: 'status', label: 'Status', render: row => <Badge tone="neutral">{row.status.replace(/_/g, ' ').toLowerCase()}</Badge> },
                    { key: 'owner', label: 'Owner', render: row => row.owner ?? <span className="text-fg-subtle">Unassigned</span> },
                    { key: 'impact', label: 'High impact', render: row => row.high_impact ? <Badge tone="accent">approval required</Badge> : <span className="text-fg-subtle">—</span> }
                  ]}
                  rows={actions}
                />
              </Panel>
            </motion.div>
          )}

          {tab === 'audit' && (
            <motion.div variants={fade} className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
              <Panel title="Audit history" description="Append-only; not editable through the application" bodyClassName="p-0">
                {incidentAudit.length === 0
                  ? <EmptyState title="No audit records" body="Nothing has been recorded against this incident yet." />
                  : (
                    <div className="divide-y divide-border">
                      {incidentAudit.map(entry => (
                        <div key={entry.id} className="px-4 py-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-[12px] text-fg-subtle tabular-nums">{clock(entry.at)}</span>
                            <Badge tone="neutral">{entry.action.replace(/_/g, ' ').toLowerCase()}</Badge>
                            <span className="font-mono text-[12px] text-fg-subtle">{entry.object_type}:{entry.object_id}</span>
                          </div>
                          <p className="mt-1 text-[13px] text-fg">{entry.summary}</p>
                          <p className="mt-0.5 text-[12px] text-fg-subtle">
                            {entry.actor} ({entry.actor_role}){entry.reason ? ` · ${entry.reason}` : ''} · {entry.request_id}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
              </Panel>

              <Panel title="Analyst annotation" description="Changes annotation state only">
                {can('annotate') ? (
                  <div className="space-y-3">
                    <TextArea label="Note" value={note} onChange={setNote} rows={4}
                      placeholder="Record what you observed and why. Annotations never modify the immutable source event." />
                    <Button variant="primary" size="sm" onClick={addAnnotation} disabled={!note.trim()}>Add annotation</Button>
                    {annotations.map(item => (
                      <div key={item.at} className="rounded-[6px] bg-surface-2 px-3 py-2 text-[12.5px]">
                        <span className="font-medium text-fg">{item.actor}</span>
                        <span className="text-fg-subtle"> · {clock(item.at)}</span>
                        <p className="mt-1 text-fg-muted">{item.text}</p>
                      </div>
                    ))}
                  </div>
                ) : <PermissionDenied missing="incident annotation" />}
              </Panel>
            </motion.div>
          )}
        </motion.div>
      </PageBody>
    </div>
  );
}