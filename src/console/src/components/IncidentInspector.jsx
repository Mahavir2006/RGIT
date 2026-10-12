// Incident inspection panel.
//
// Opened by clicking a marker, list row, road segment or affected zone. Everything shown here
// is grounded: each claim carries the event or record it came from, and anything modelled is
// labelled as modelled. There is no path from this panel that dispatches or actuates anything.
import { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
  X, ArrowRight, GitBranch, Waypoints, Clock, MapPin, TriangleAlert, Radio, FileText,
  Users, Wrench, Activity, ShieldQuestionMark
} from 'lucide-react';
import { Badge, Button } from '@/components/ui';
import { KeyValue } from '@/components/overlays';
import {
  CATEGORY_BY_ID, SEVERITY_COLOUR, STATUS_COLOUR, SOURCE_BY_ID, ACCESS_STATES
} from '../data/taxonomy.js';
import { evidenceStateOf } from '../lib/filters.js';
import { clock, ago, relativeLag, latency } from '../lib/format.js';
import { cn } from '@/lib/utils';

const EVIDENCE_TONE = { SUPPORTED: 'var(--healthy)', CONFLICTING: 'var(--critical)', INSUFFICIENT: 'var(--degraded)', STALE: 'var(--stale)' };

export default function IncidentInspector({ item, model, onClose }) {
  const navigate = useNavigate();
  const [section, setSection] = useState('overview');

  if (!item) return null;

  const category = CATEGORY_BY_ID[item.category];
  const evidenceState = evidenceStateOf(item);
  const access = ACCESS_STATES[item.accessEvidence === 'observed' ? 'OBSERVED_BLOCKED'
    : item.accessEvidence === 'reported' ? 'REPORTED_BLOCKED' : 'PREDICTED_RISK'];

  const hypotheses = model.store.all('Hypothesis').filter(node => item.hypothesisIds?.includes(node.hypothesis_id));
  const actions = model.actions.filter(action => item.actionIds?.includes(action.action_id));
  const anomalies = model.anomalies.filter(anomaly => item.anomalyIds?.includes(anomaly.anomaly_id));
  const supportingEvents = item.evidence ?? [];
  const roads = item.roadAssets ?? [];

  const timeline = [...supportingEvents]
    .sort((a, b) => String(a.event_time).localeCompare(String(b.event_time)))
    .slice(-8);

  const tabs = [
    ['overview', 'Overview'],
    ['evidence', `Evidence ${item.supporting + item.contradicting}`],
    ['impacts', 'Impacts'],
    ['timeline', 'Timeline']
  ];

  return (
    <motion.aside
      initial={{ x: 24, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: 24, opacity: 0 }}
      transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
      className="flex min-h-0 w-full flex-col overflow-y-auto border-l border-border bg-surface"
      role="dialog"
      aria-label={`Incident ${item.id}`}
    >
      <header className="sticky top-0 z-10 border-b border-border bg-surface px-4 py-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[12px] font-medium text-accent">{item.id}</span>
              {category && (
                <span className="inline-flex items-center gap-1 text-[11.5px]" style={{ color: category.colour }}>
                  <span className="size-1.5 rounded-full" style={{ background: category.colour }} />
                  {category.short}
                </span>
              )}
              {item.isPredicted && <Badge tone="accent">PREDICTED</Badge>}
              {item.stale && <Badge tone="degraded">STALE EVIDENCE</Badge>}
            </div>
            <h2 className="mt-1 text-[15px] font-semibold leading-snug text-fg">{item.title}</h2>
          </div>
          <button onClick={onClose} aria-label="Close inspector" className="shrink-0 text-fg-subtle hover:text-fg">
            <X className="size-4" />
          </button>
        </div>

        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 text-[12px]" style={{ color: SEVERITY_COLOUR[item.severity] }}>
            <span className="size-1.5 rounded-full" style={{ background: SEVERITY_COLOUR[item.severity] }} />
            {item.severity.toLowerCase()}
          </span>
          <span className="inline-flex items-center gap-1.5 text-[12px]" style={{ color: STATUS_COLOUR[item.status] }}>
            <span className="size-1.5 rounded-full" style={{ background: STATUS_COLOUR[item.status] }} />
            {item.status.toLowerCase()}
          </span>
          <span className="text-[12px]" style={{ color: EVIDENCE_TONE[evidenceState] }}>{evidenceState.toLowerCase()} evidence</span>
          {item.mode !== 'LIVE' && <Badge tone="neutral">{item.mode === 'SIMULATED' ? 'SIMULATED' : item.mode}</Badge>}
        </div>
      </header>

      <nav className="flex gap-1 border-b border-border px-3 py-1.5">
        {tabs.map(([id, label]) => (
          <button
            key={id}
            onClick={() => setSection(id)}
            className={cn(
              'rounded-[5px] px-2 py-1 text-[12px] transition-colors',
              section === id ? 'bg-surface-2 font-medium text-fg' : 'text-fg-muted hover:text-fg'
            )}
          >
            {label}
          </button>
        ))}
      </nav>

      <div className="space-y-4 px-4 py-4">
        {section === 'overview' && (
          <>
            <dl>
              <KeyValue label="Location">
                <span className="inline-flex items-center gap-1.5">
                  <MapPin className="size-3 text-fg-subtle" />
                  {item.areaName} Â· {item.lat.toFixed(4)}, {item.lon.toFixed(4)}
                </span>
              </KeyValue>
              <KeyValue label="Precision">{item.locationPrecision} Â· Â±{item.uncertaintyM} m</KeyValue>
              <KeyValue label="First seen" mono>{clock(item.observedAt)}</KeyValue>
              <KeyValue label="Last update" mono>{ago(item.updatedAt)}</KeyValue>
              <KeyValue label="Sources">
                <span className="flex flex-wrap justify-end gap-1">
                  {(item.sourceTypes ?? []).map(source => (
                    <span key={source} className="text-[11.5px]" style={{ color: SOURCE_BY_ID[source]?.colour }}>
                      {SOURCE_BY_ID[source]?.label ?? source}
                    </span>
                  ))}
                </span>
              </KeyValue>
              <KeyValue label="Confidence">
                <span className="text-accent">{item.confidence?.toFixed(2)}</span>
                <span className="ml-1 text-[11px] text-fg-subtle">heuristic</span>
              </KeyValue>
            </dl>

            <div>
              <SectionTitle icon={FileText} label="Summary" />
              <p className="mt-1 text-[12.5px] leading-relaxed text-fg-muted">{item.summary}</p>
            </div>

            {/* Three confidence dimensions, never blended. */}
            {item.confidenceDimensions && (
              <div>
                <SectionTitle icon={Activity} label="Confidence dimensions" />
                <dl className="mt-1">
                  {[['validity', 'Event validity'], ['membership', 'Membership'], ['cause', 'Cause']].map(([key, label]) => (
                    <KeyValue key={key} label={label} mono>{item.confidenceDimensions[key]?.toFixed(2)}</KeyValue>
                  ))}
                  <KeyValue label="Calibration">{item.confidenceDimensions.calibration?.replace(/_/g, ' ').toLowerCase()}</KeyValue>
                </dl>
              </div>
            )}

            {/* Emergency access: the evidence class is explicit. */}
            <div>
              <SectionTitle icon={Wrench} label="Emergency access impact" />
              <div className="mt-1.5 rounded-[6px] border px-3 py-2"
                style={{ borderColor: `${access.colour}55`, background: `${access.colour}12` }}>
                <div className="flex items-center gap-2 text-[12.5px] font-medium" style={{ color: access.colour }}>
                  <span className="size-1.5 rounded-full" style={{ background: access.colour }} />
                  {access.label}
                </div>
                <p className="mt-1 text-[11.5px] leading-relaxed text-fg-muted">
                  Evidence class: {access.evidence}. {item.accessSource}.
                </p>
                <p className="mt-1 text-[11px] leading-relaxed text-fg-subtle">
                  Last observation {clock(item.accessObservedAt)} IST. A road is never treated as clear because nothing
                  reported it.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2 border-t border-border pt-3">
              <Button variant="primary" size="sm" onClick={() => navigate(`/incidents/${item.id}`)}>
                Open incident<ArrowRight />
              </Button>
              <Button size="sm" onClick={() => navigate(`/incidents/${item.id}/evidence`)}><GitBranch />Evidence</Button>
              <Button size="sm" onClick={() => navigate(`/incidents/${item.id}/cascade`)}><Waypoints />Cascade</Button>
            </div>
          </>
        )}

        {section === 'evidence' && (
          <>
            <div className="grid grid-cols-3 gap-2">
              {[
                ['Supporting', item.supporting, 'var(--healthy)'],
                ['Contradicting', item.contradicting, 'var(--critical)'],
                ['Context', item.contextual, 'var(--fg-subtle)']
              ].map(([label, value, colour]) => (
                <div key={label} className="rounded-[6px] border border-border px-2.5 py-2">
                  <div className="text-[11px] text-fg-subtle">{label}</div>
                  <div className="mt-0.5 font-mono text-[17px] font-semibold" style={{ color }}>{value}</div>
                </div>
              ))}
            </div>

            {item.stale && (
              <div className="flex items-start gap-2 rounded-[6px] border border-degraded/30 bg-degraded-soft px-3 py-2 text-[11.5px] text-degraded">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
                <span>One or more expected signals are missing or stale. Observability is reduced; this is not evidence that conditions are safe.</span>
              </div>
            )}

            <div>
              <SectionTitle icon={Radio} label="Supporting observations" />
              {supportingEvents.length === 0 ? <EmptyNote /> : (
                <div className="mt-1.5 space-y-1.5">
                  {supportingEvents.slice(0, 6).map(event => (
                    <Observation key={event.event_id} event={event} />
                  ))}
                </div>
              )}
            </div>

            {anomalies.length > 0 && (
              <div>
                <SectionTitle icon={TriangleAlert} label="Anomalies" />
                <div className="mt-1.5 space-y-1.5">
                  {anomalies.map(anomaly => (
                    <div key={anomaly.anomaly_id} className="rounded-[6px] border border-border px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[11px] text-fg-subtle">{anomaly.anomaly_id}</span>
                        <Badge tone={anomaly.severity === 'HIGH' || anomaly.severity === 'CRITICAL' ? 'critical' : 'degraded'}>
                          {anomaly.family}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[11.5px] leading-relaxed text-fg-muted">{anomaly.explanation}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {hypotheses.length > 0 && (
              <div>
                <SectionTitle icon={ShieldQuestionMark} label="Potential causes" />
                <div className="mt-1.5 space-y-1.5">
                  {hypotheses.map(hypothesis => (
                    <div key={hypothesis.hypothesis_id} className="rounded-[6px] border border-border px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[11px] text-violet">{hypothesis.hypothesis_id}</span>
                        <span className="ml-auto font-mono text-[11.5px]">{hypothesis.confidence.toFixed(2)}</span>
                      </div>
                      <p className="mt-1 text-[11.5px] leading-relaxed text-fg-muted">{hypothesis.claim}</p>
                      <p className="mt-1 text-[11px] text-fg-subtle">
                        {hypothesis.evidence_for.length} supporting Â· {hypothesis.evidence_against.length} conflicting Â·{' '}
                        {hypothesis.unknowns.length} unknowns
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {section === 'impacts' && (
          <>
            <div>
              <SectionTitle icon={Wrench} label="Affected infrastructure" />
              {(item.assets ?? []).length === 0 ? <EmptyNote label="No asset is currently associated." /> : (
                <div className="mt-1.5 space-y-1">
                  {item.assets.map(asset => (
                    <div key={asset.asset_id} className="flex items-center gap-2 text-[12px]">
                      <span className="font-mono text-[11px] text-cyan">{asset.asset_id}</span>
                      <span className="truncate text-fg-muted">{asset.name}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <SectionTitle icon={MapPin} label="Affected road segments" />
              {roads.length === 0 ? <EmptyNote label="No road segment is currently flagged." /> : (
                <div className="mt-1.5 space-y-1">
                  {roads.map(roadId => {
                    const state = model.accessStates.find(entry => entry.roadId === roadId);
                    return (
                      <div key={roadId} className="rounded-[6px] border border-border px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[11px]">{roadId}</span>
                          {state && (
                            <Badge tone="neutral" className="ml-auto">
                              <span className="size-1.5 rounded-full" style={{ background: state.state.colour }} />
                              {state.state.label}
                            </Badge>
                          )}
                        </div>
                        {state && <p className="mt-1 text-[11px] leading-relaxed text-fg-subtle">{state.note}</p>}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {item.isPredicted && (
              <div className="flex items-start gap-2 rounded-[6px] border border-accent/30 bg-accent-soft px-3 py-2 text-[11.5px] text-accent">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
                <span>This is a modelled downstream consequence, not an observation. It is shown separately so it can never be mistaken for a reported incident.</span>
              </div>
            )}

            {actions.length > 0 && (
              <div>
                <SectionTitle icon={Users} label="Recommended actions" />
                <div className="mt-1.5 space-y-1.5">
                  {actions.map(action => (
                    <div key={action.action_id} className="rounded-[6px] border border-border px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className="text-[12px] font-medium">{action.type}</span>
                        <Badge tone={action.priority === 'P1' ? 'critical' : 'neutral'}>{action.priority}</Badge>
                      </div>
                      <p className="mt-1 text-[11.5px] leading-relaxed text-fg-muted">{action.rationale}</p>
                      <p className="mt-1 text-[11px] text-fg-subtle">
                        {action.requires_approval ? 'Supervisor approval required. ' : ''}Nothing dispatches automatically.
                      </p>
                    </div>
                  ))}
                </div>
                <Button size="sm" className="mt-2" onClick={() => navigate('/response')}>
                  Open response center<ArrowRight />
                </Button>
              </div>
            )}
          </>
        )}

        {section === 'timeline' && (
          <div>
            <SectionTitle icon={Clock} label="How this developed" />
            <div className="mt-2 space-y-2 border-l border-border pl-3">
              {timeline.length === 0 ? <EmptyNote label="No dated observations inside the window." /> : timeline.map(event => (
                <div key={event.event_id} className="relative">
                  <span className="absolute -left-[17px] top-1.5 size-1.5 rounded-full bg-accent" />
                  <div className="font-mono text-[11px] text-fg-subtle tabular-nums">
                    {clock(event.event_time)} observed Â· {clock(event.ingest_time)} ingested
                  </div>
                  <div className="mt-0.5 text-[12px] text-fg">{event.summary ?? event.event_type?.replace(/_/g, ' ')}</div>
                  <div className="mt-0.5 text-[11px] text-fg-subtle">
                    {event.source_id}{latency(event)?.late ? ` Â· ${relativeLag(latency(event).seconds)} late` : ''}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </motion.aside>
  );
}

function SectionTitle({ icon: Icon, label }) {
  return (
    <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.1em] text-fg-subtle">
      <Icon className="size-3" />
      {label}
    </div>
  );
}

function EmptyNote({ label = 'Nothing recorded.' }) {
  return <p className="mt-1 text-[11.5px] text-fg-subtle">{label}</p>;
}

function Observation({ event }) {
  const measurement = event.measurements?.[0];
  return (
    <div className="rounded-[6px] border border-border px-3 py-2">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[11px] text-fg-subtle">{event.event_id}</span>
        <span className="ml-auto text-[11px] text-fg-subtle">{event.source_id}</span>
      </div>
      <div className="mt-0.5 text-[12px] text-fg">{event.summary ?? event.event_type?.replace(/_/g, ' ')}</div>
      {measurement && (
        <div className="mt-0.5 font-mono text-[11px] text-accent">
          {measurement.name} {measurement.value} {measurement.unit}
        </div>
      )}
      {(event.quality?.flags ?? []).length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {event.quality.flags.slice(0, 3).map(flag => (
            <Badge key={flag} tone="neutral">{String(flag).replace(/_/g, ' ').toLowerCase()}</Badge>
          ))}
        </div>
      )}
    </div>
  );
}