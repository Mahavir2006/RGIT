import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Search, RotateCcw, Download, Lock, GitBranch } from 'lucide-react';
import { PageHeader, PageBody } from '@/lib/Shell.jsx';
import { Panel, Badge, Button, Input, DataTable, EmptyState, Metric, stagger, fade } from '@/components/blocks.jsx';
import { KeyValue, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/overlays';
import { useApp } from '@/lib/store.jsx';
import { sourceById } from '@/data/sources.js';
import { VALIDATION_OUTCOMES } from '@/data/graph.js';
import { clock, bothTimes, latency, relativeLag, titleFromEventType } from '@/lib/format.js';

const VALIDATION_TONE = { ACCEPTED: 'healthy', ACCEPTED_WITH_WARNING: 'degraded', QUARANTINED: 'degraded', REJECTED: 'critical' };

export default function Events() {
  const { events, store, role, search } = useApp();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState(params.get('event') || 'evt-0006');
  const [filters, setFilters] = useState({ source: 'ALL', type: 'ALL', validation: 'ALL', flag: 'ALL', query: search });

  const sourceIds = useMemo(() => [...new Set(events.map(event => event.source_id))].sort(), [events]);
  const typeIds = useMemo(() => [...new Set(events.map(event => event.event_type))].sort(), [events]);
  const flagIds = useMemo(() => [...new Set(events.flatMap(event => event.quality.flags))].sort(), [events]);

  const rows = useMemo(() => events.filter(event => {
    if (filters.source !== 'ALL' && event.source_id !== filters.source) return false;
    if (filters.type !== 'ALL' && event.event_type !== filters.type) return false;
    if (filters.flag !== 'ALL' && !event.quality.flags.includes(filters.flag)) return false;
    const outcome = event.validation?.outcome ?? 'ACCEPTED';
    if (filters.validation !== 'ALL' && outcome !== filters.validation) return false;
    if (filters.query && !`${event.event_id} ${event.source_event_id} ${event.summary} ${event.event_type}`.toLowerCase().includes(filters.query.toLowerCase())) return false;
    return true;
  }).map(event => ({
    ...event,
    validationOutcome: event.validation?.outcome ?? 'ACCEPTED',
    incidentIds: [...new Set(store.edges.filter(edge => edge._fromLabel === 'Event' && edge._from === event.event_id && edge._toLabel === 'Incident').map(edge => edge._to))]
  })), [events, store, filters]);

  const event = events.find(item => item.event_id === selected);
  const selectedIncidentIds = event
    ? [...new Set(store.edges.filter(edge => edge._fromLabel === 'Event' && edge._from === event.event_id && edge._toLabel === 'Incident').map(edge => edge._to))]
    : [];
  const activeFilters = Object.entries(filters).filter(([, value]) => value && value !== 'ALL').length;

  function choose(id) {
    setSelected(id);
    setParams(prev => { const next = new URLSearchParams(prev); next.set('event', id); return next; }, { replace: true });
  }

  return (
    <div className="min-h-full">
      <PageHeader
        title="Event explorer"
        description="Every received and normalised signal, with observation time and ingest time kept side by side."
        actions={<>
          <Button size="md" onClick={() => setFilters({ source: 'ALL', type: 'ALL', validation: 'ALL', flag: 'ALL', query: '' })}>
            <RotateCcw />Reset filters{activeFilters ? ` (${activeFilters})` : ''}
          </Button>
          <Button variant="primary" size="md"><Download />Export bounded set</Button>
        </>}
      />

      <PageBody className="space-y-4">
        <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative w-[240px]">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-fg-subtle" />
              <Input value={filters.query} onChange={event => setFilters(prev => ({ ...prev, query: event.target.value }))}
                placeholder="Event id, source id, summary" aria-label="Search events" className="pl-8" />
            </div>
            <div className="w-[190px]">
              <label className="sr-only" htmlFor="source-filter">Source filter</label>
              <Select value={filters.source} onValueChange={value => setFilters(prev => ({ ...prev, source: value }))}>
                <SelectTrigger id="source-filter"><SelectValue placeholder="Any source" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">Any source</SelectItem>
                  {sourceIds.map(id => <SelectItem key={id} value={id}>{sourceById(id)?.name ?? id}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="w-[170px]">
              <label className="sr-only" htmlFor="type-filter">Type filter</label>
              <Select value={filters.type} onValueChange={value => setFilters(prev => ({ ...prev, type: value }))}>
                <SelectTrigger id="type-filter"><SelectValue placeholder="Any type" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">Any type</SelectItem>
                  {typeIds.map(id => <SelectItem key={id} value={id}>{titleFromEventType(id)}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="w-[190px]">
              <label className="sr-only" htmlFor="validation-filter">Validation filter</label>
              <Select value={filters.validation} onValueChange={value => setFilters(prev => ({ ...prev, validation: value }))}>
                <SelectTrigger id="validation-filter"><SelectValue placeholder="Any outcome" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">Any outcome</SelectItem>
                  {VALIDATION_OUTCOMES.map(id => <SelectItem key={id} value={id}>{id.replace(/_/g, ' ').toLowerCase()}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="w-[170px]">
              <label className="sr-only" htmlFor="flag-filter">Flag filter</label>
              <Select value={filters.flag} onValueChange={value => setFilters(prev => ({ ...prev, flag: value }))}>
                <SelectTrigger id="flag-filter"><SelectValue placeholder="Any flag" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">Any flag</SelectItem>
                  {flagIds.map(id => <SelectItem key={id} value={id}>{id.replace(/_/g, ' ').toLowerCase()}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <span className="ml-auto text-[12.5px] text-fg-subtle tabular-nums">{rows.length} of {events.length} events</span>
          </div>

          <Panel bodyClassName="p-0">
            <DataTable
              rowId={row => row.event_id}
              onRowClick={row => choose(row.event_id)}
              selectedId={selected}
              empty={<EmptyState title="No events match"
                body="No canonical event matches every filter. Clear a filter to widen the set — an empty result is not evidence that no signal occurred." />}
              columns={[
                { key: 'event_id', label: 'Event', render: row => (
                  <span><span className="font-mono text-[12.5px] font-medium text-accent">{row.event_id}</span>
                    {row.duplicate_of && <Badge tone="degraded" className="ml-1.5">dup</Badge>}
                    {row.incidentIds.length > 0 && <span className="mt-0.5 block text-[12px] text-fg-subtle">{row.incidentIds.join(', ')}</span>}</span>
                ) },
                { key: 'source_id', label: 'Source', render: row => (
                  <span><span className="block text-[13px] text-fg">{sourceById(row.source_id)?.name ?? row.source_id}</span>
                    <span className="block text-[12px] text-fg-subtle">{row.source_kind}</span></span>
                ) },
                { key: 'event_time', label: 'Observed', align: 'right', render: row => <span className="font-mono text-[12.5px] tabular-nums">{clock(row.event_time)}</span> },
                { key: 'ingest_time', label: 'Ingested', align: 'right', render: row => (
                  <span className="font-mono text-[12.5px] tabular-nums">{clock(row.ingest_time)}{latency(row)?.late && <span className="ml-1 text-degraded">late</span>}</span>
                ) },
                { key: 'lag', label: 'Lag', align: 'right', render: row => <span className="text-[12.5px] tabular-nums">{relativeLag(latency(row)?.seconds)}</span> },
                { key: 'event_type', label: 'Type', render: row => <span className="text-[13px]">{titleFromEventType(row.event_type)}</span> },
                { key: 'validationOutcome', label: 'Validation', render: row => (
                  <Badge tone={VALIDATION_TONE[row.validationOutcome]}>{row.validationOutcome.replace(/_/g, ' ').toLowerCase()}</Badge>
                ) },
                { key: 'flags', label: 'Flags', render: row => (
                  <span className="flex flex-wrap gap-1">{row.quality.flags.slice(0, 2).map(flag => <Badge key={flag} tone="neutral">{flag.replace(/_/g, ' ').toLowerCase()}</Badge>)}
                    {row.quality.flags.length > 2 && <Badge tone="neutral">+{row.quality.flags.length - 2}</Badge>}</span>
                ) }
              ]}
              rows={rows}
            />
          </Panel>

          {event && (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
              <Panel title="Event detail" description={event.event_id}>
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <Badge tone={VALIDATION_TONE[event.validation?.outcome ?? 'ACCEPTED']}>
                    {(event.validation?.outcome ?? 'ACCEPTED').replace(/_/g, ' ').toLowerCase()}
                  </Badge>
                  {event.quality.flags.map(flag => <Badge key={flag} tone="neutral">{flag.replace(/_/g, ' ').toLowerCase()}</Badge>)}
                </div>
                <p className="mb-3 text-[13px] leading-snug text-fg">{event.summary}</p>

                <dl>
                  <KeyValue label="Source" mono>{event.source_id}</KeyValue>
                  <KeyValue label="Source event id" mono>{event.source_event_id || '—'}</KeyValue>
                  <KeyValue label="Observed at" mono>{clock(event.event_time)} IST</KeyValue>
                  <KeyValue label="Ingested at" mono>{clock(event.ingest_time)} IST · {relativeLag(latency(event)?.seconds)}</KeyValue>
                  <KeyValue label="Idempotency key" mono>{event.source_event_id || event.event_id}</KeyValue>
                  <KeyValue label="Schema version" mono>{event.schema_version}</KeyValue>
                  <KeyValue label="Verification">{event.verification_status.replace(/_/g, ' ')}</KeyValue>
                  <KeyValue label="Measurements">
                    {event.measurements.length
                      ? <span className="font-mono text-[12px]">{event.measurements.map(item => `${item.name} ${item.value} ${item.unit}`).join(' · ')}</span>
                      : <span className="text-fg-subtle">none</span>}
                  </KeyValue>
                </dl>

                {event.validation && (
                  <div className="mt-3 rounded-[6px] border border-critical/25 bg-critical-soft px-3 py-2.5">
                    <div className="text-[12.5px] font-medium text-critical">{event.validation.reasonCode}</div>
                    <p className="mt-1 text-[12.5px] leading-snug text-fg-muted">{event.validation.explanation}</p>
                    <p className="mt-1.5 text-[12px] text-fg-subtle">
                      Correct the source mapping, then replay from quarantine. Nothing was silently discarded.
                    </p>
                  </div>
                )}

                {event.duplicate_of && (
                  <div className="mt-3 rounded-[6px] border border-degraded/25 bg-degraded-soft px-3 py-2.5">
                    <p className="text-[12.5px] leading-snug text-fg-muted">
                      Duplicate delivery of <span className="font-mono">{event.duplicate_of}</span>. Linked to the canonical
                      event; it does not increase corroboration or source diversity.
                    </p>
                  </div>
                )}

                <details className="mt-3 rounded-[6px] border border-border px-3 py-2">
                  <summary className="cursor-pointer text-[12.5px] font-medium text-fg">
                    Raw payload <span className="font-normal text-fg-subtle">(permission controlled)</span>
                  </summary>
                  {role.id === 'VIEWER' ? (
                    <p className="mt-2 flex items-center gap-1.5 text-[12.5px] text-fg-subtle">
                      <Lock className="size-3.5" />Raw payloads are not available to the viewer role.
                    </p>
                  ) : (
                    <pre className="mt-2 max-h-56 overflow-auto rounded-[4px] bg-surface-2 p-2 font-mono text-[11px] text-fg-muted">
                      {JSON.stringify({ payload_ref: event.payload_ref, text: event.text ?? null, reporter_id: '[pseudonymised]', authorization: '[redacted]' }, null, 2)}
                    </pre>
                  )}
                </details>

                <div className="mt-3 border-t border-border pt-3">
                  <div className="mb-1.5 text-[12.5px] font-medium text-fg-muted">Linked incidents</div>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedIncidentIds.length
                      ? selectedIncidentIds.map(id => <Button key={id} size="sm" variant="ghost" onClick={() => navigate(`/incidents/${id}`)}>{id}</Button>)
                      : <span className="text-[12.5px] text-fg-subtle">Not associated with any incident.</span>}
                  </div>
                </div>
              </Panel>

              <Panel title="Processing trace" description="Append-only for material steps">
                <div className="divide-y divide-border">
                  {event.trace.map((step, index) => (
                    <div key={`${step.step}-${index}`} className="flex items-baseline gap-3 py-2 first:pt-0">
                      <span className={step.result === 'ok' ? 'text-healthy' : 'text-degraded'}>
                        {step.result === 'ok' ? '●' : '▲'}
                      </span>
                      <span className="w-[150px] shrink-0 text-[12.5px] font-medium text-fg">{step.step.replace(/_/g, ' ')}</span>
                      <span className="min-w-0 flex-1 text-[12.5px] text-fg-muted">
                        {step.processor_version}
                        <span className="text-fg-subtle"> · result <span className={step.result === 'ok' ? 'text-healthy' : 'text-degraded'}>{step.result}</span></span>
                        {step.reason && <span className="text-degraded"> · {step.reason}</span>}
                      </span>
                      <span className="shrink-0 text-[12px] text-fg-subtle tabular-nums">{step.duration_ms} ms</span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 grid grid-cols-3 gap-3 border-t border-border pt-3">
                  <Metric label="Total processing" value={`${event.trace.reduce((sum, step) => sum + step.duration_ms, 0)} ms`} />
                  <Metric label="Steps" value={event.trace.length} />
                  <Metric label="Schema" value={event.schema_version} />
                </div>
                {selectedIncidentIds.length > 0 && (
                  <Button size="sm" className="mt-4" onClick={() => navigate(`/incidents/${selectedIncidentIds[0]}/evidence`)}>
                    <GitBranch />View in evidence graph
                  </Button>
                )}
              </Panel>
            </div>
          )}
        </motion.div>
      </PageBody>
    </div>
  );
}