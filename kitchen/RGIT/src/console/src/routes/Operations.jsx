import { useMemo, useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Map as MapIcon, RotateCcw, Download, Layers, Play, Pause, ArrowRight, ChevronRight
} from 'lucide-react';
import { Badge, Button, Input } from '@/components/ui';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/overlays';
import { useApp } from '@/lib/store.jsx';
import { CANDIDATES, SCENARIO } from '@/data/scenario.js';
import { evidenceFor } from '@/data/graph.js';
import SentinelMap from '@/components/SentinelMap.jsx';
import { cn } from '@/lib/utils';
import { ago } from '@/lib/format.js';

// A layer a connector cannot currently supply is labelled as unavailable rather than drawn
// as an empty overlay that could be read as a zero reading.
const LAYERS = [
  { key: 'incidents', label: 'Incidents', always: true },
  { key: 'candidates', label: 'Candidates', always: true },
  { key: 'assets', label: 'Assets', always: true },
  { key: 'impactZones', label: 'Impact zones', always: true },
  { key: 'dependencies', label: 'Dependencies', always: true },
  { key: 'rainfall', label: 'Rainfall', sourceId: 'openmeteo' }
];

function FilterSelect({ value, onChange, options, label, width = 'w-[150px]' }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className={`h-8 ${width}`} aria-label={label}><SelectValue /></SelectTrigger>
      <SelectContent>
        {options.map(option => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

function severityTone(severity) {
  if (severity === 'CRITICAL' || severity === 'HIGH') return 'critical';
  if (severity === 'MODERATE') return 'degraded';
  return 'neutral';
}

// Full-bleed map. The map owns the viewport and every control floats above it, so no map
// surface is traded away for panel chrome.
export default function Operations() {
  const { store, incidents, sources, layers, dispatch, area } = useApp();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState(params.get('incident') || null);
  const [filters, setFilters] = useState({ severity: 'ALL', status: 'ALL', type: 'ALL' });
  const [query, setQuery] = useState('');
  const [replay, setReplay] = useState(100);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!playing) return undefined;
    const timer = setInterval(() => setReplay(value => (value >= 100 ? 20 : value + 4)), 260);
    return () => clearInterval(timer);
  }, [playing]);

  const scoped = useMemo(() => {
    let rows = area === 'All areas' ? incidents : incidents.filter(item => item.area_name === area);
    if (filters.severity !== 'ALL') rows = rows.filter(item => item.severity === filters.severity);
    if (filters.status !== 'ALL') rows = rows.filter(item => item.status === filters.status);
    if (filters.type !== 'ALL') rows = rows.filter(item => item.type === filters.type);
    if (query.trim()) rows = rows.filter(item => `${item.incident_id} ${item.title} ${item.area_name}`.toLowerCase().includes(query.toLowerCase()));
    return rows;
  }, [incidents, area, filters, query]);

  const selectedIncident = incidents.find(item => item.incident_id === selected);
  const evidence = selectedIncident ? evidenceFor(store, selectedIncident.incident_id) : [];
  const supporting = evidence.filter(edge => edge._type === 'SUPPORTS').length;
  const contradicting = evidence.filter(edge => edge._type === 'CONTRADICTS').length;

  const severityOptions = useMemo(() => [
    { value: 'ALL', label: 'Any severity' },
    ...[...new Set(incidents.map(item => item.severity))].map(value => ({ value, label: value.charAt(0) + value.slice(1).toLowerCase() }))
  ], [incidents]);

  const statusOptions = useMemo(() => [
    { value: 'ALL', label: 'Any status' },
    ...[...new Set(incidents.map(item => item.status))].map(value => ({ value, label: value.replace(/_/g, ' ').toLowerCase() }))
  ], [incidents]);

  const typeOptions = useMemo(() => [
    { value: 'ALL', label: 'Any type' },
    ...[...new Set(incidents.map(item => item.type))].map(value => ({ value, label: value.toLowerCase() }))
  ], [incidents]);

  function choose(id) {
    setSelected(id);
    setParams(prev => {
      const next = new URLSearchParams(prev);
      if (id) next.set('incident', id); else next.delete('incident');
      return next;
    }, { replace: true });
  }

  function reset() { setFilters({ severity: 'ALL', status: 'ALL', type: 'ALL' }); setQuery(''); choose(null); }
  const activeFilters = [filters.severity !== 'ALL', filters.status !== 'ALL', filters.type !== 'ALL', query.trim() !== ''].filter(Boolean).length;

  return (
    <div className="relative h-full min-h-0 w-full overflow-hidden">
      <SentinelMap
        incidents={scoped}
        candidates={CANDIDATES}
        selection={selected}
        onSelect={hit => choose(hit.kind === 'incident' || hit.kind === 'candidate' ? hit.id : null)}
        layers={layers}
        replay={replay}
        height="100%"
        showLegend={false}
        className="h-full w-full"
      />

      {/* Top bars: identity and filters, then layers and the scenario clock. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10">
        <div className="pointer-events-auto flex flex-wrap items-center gap-2 border-b border-border bg-surface/95 px-4 py-2.5 backdrop-blur">
          <div className="mr-1 flex items-baseline gap-2">
            <h1 className="text-[14px] font-semibold text-fg">Live operations</h1>
            <span className="text-[12px] text-fg-subtle tabular-nums">{scoped.length} of {incidents.length}</span>
          </div>
          <div className="relative w-[190px]">
            <IconSearch />
            <Input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search incidents" aria-label="Search incidents" className="h-8 pl-8" />
          </div>
          <FilterSelect label="Severity filter" value={filters.severity} onChange={value => setFilters(prev => ({ ...prev, severity: value }))} options={severityOptions} width="w-[136px]" />
          <FilterSelect label="Status filter" value={filters.status} onChange={value => setFilters(prev => ({ ...prev, status: value }))} options={statusOptions} width="w-[136px]" />
          <FilterSelect label="Type filter" value={filters.type} onChange={value => setFilters(prev => ({ ...prev, type: value }))} options={typeOptions} width="w-[136px]" />
          {activeFilters > 0 && <Button variant="ghost" size="sm" onClick={reset}>Clear {activeFilters}</Button>}
          <Button size="sm" className="ml-auto" onClick={reset}><RotateCcw />Reset</Button>
          <Button variant="primary" size="sm"><Download />Export</Button>
        </div>

        <div className="pointer-events-auto flex flex-wrap items-center gap-2 border-b border-border bg-surface/95 px-4 py-2 backdrop-blur">
          <span className="inline-flex items-center gap-1.5 text-[12px] text-fg-muted">
            <Layers className="size-3.5 text-fg-subtle" />Layers
          </span>
          {LAYERS.map(layer => {
            const source = layer.sourceId ? sources.find(item => item.source_id === layer.sourceId) : null;
            const unavailable = source ? ['OFFLINE', 'DISABLED'].includes(source.health) : false;
            return (
              <button
                key={layer.key}
                disabled={Boolean(layer.always)}
                onClick={() => !layer.always && dispatch({ type: 'toggleLayer', layer: layer.key })}
                title={unavailable
                  ? `${source.name} is ${source.health.toLowerCase()}; this layer has no data and is not drawn`
                  : layer.label}
                className={cn(
                  'inline-flex h-6 items-center gap-1.5 rounded-[6px] border px-2 text-[12px] transition-colors',
                  unavailable
                    ? 'border-dashed border-degraded/40 text-degraded'
                    : layers[layer.key]
                      ? 'border-border bg-surface-2 text-fg'
                      : 'border-border text-fg-subtle hover:text-fg-muted'
                )}
              >
                <span className={cn('size-1.5 rounded-full', layers[layer.key] && !unavailable ? 'bg-accent' : 'bg-border-strong')} />
                {layer.label}
                {unavailable && <span className="text-degraded">unavailable</span>}
              </button>
            );
          })}

          <div className="ml-auto flex items-center gap-2">
            <button onClick={() => setPlaying(value => !value)}
              className="grid size-7 place-items-center rounded-[6px] border border-border text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg"
              aria-label={playing ? 'Pause replay' : 'Play replay'}>
              {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
            </button>
            <input type="range" min="0" max="100" value={replay} onChange={event => setReplay(Number(event.target.value))}
              aria-label="Replay position" className="h-1 w-32 cursor-pointer appearance-none rounded-full bg-surface-3 accent-[var(--accent)]" />
            <span className="text-[12px] text-fg-subtle tabular-nums">
              {SCENARIO.mode.toLowerCase()} · {replay < 40 ? '13:41' : replay < 70 ? '13:52' : '14:05'}
            </span>
          </div>
        </div>
      </div>

      {/* Floating right rail. */}
      <div className="pointer-events-none absolute inset-y-0 right-0 z-10 flex w-[352px] max-w-[86vw] flex-col gap-3 p-4">
        <div className="pointer-events-auto flex min-h-0 flex-1 flex-col overflow-hidden rounded-app border border-border bg-surface/95 backdrop-blur">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <span className="text-[13px] font-medium text-fg">Incidents</span>
            <span className="ml-auto text-[12px] text-fg-subtle tabular-nums">{scoped.length}</span>
          </div>
          {scoped.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 px-5 py-10 text-center">
              <MapIcon className="size-5 text-fg-subtle" />
              <div className="text-[13px] font-medium text-fg">No incidents match</div>
              <p className="text-[12.5px] leading-snug text-fg-muted">
                Clear a filter to widen the set. An empty result does not mean the area is unaffected.
              </p>
              <Button variant="ghost" size="sm" onClick={reset}>Reset filters</Button>
            </div>
          ) : (
            <div className="min-h-0 flex-1 overflow-y-auto">
              {scoped.map(incident => (
                <button key={incident.incident_id} onClick={() => choose(incident.incident_id)}
                  className={cn(
                    'flex w-full flex-col gap-1 border-b border-border px-3 py-2.5 text-left transition-colors last:border-0',
                    selected === incident.incident_id ? 'bg-accent-soft' : 'hover:bg-surface-2'
                  )}>
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] font-medium text-accent tabular-nums">{incident.incident_id}</span>
                    <Badge tone={severityTone(incident.severity)}>{incident.severity.toLowerCase()}</Badge>
                    <span className="ml-auto text-[12px] text-fg-subtle tabular-nums">{ago(incident.updated_at)}</span>
                  </div>
                  <div className="text-[13px] font-medium text-fg">{incident.title}</div>
                  <div className="flex items-center gap-3 text-[12px] text-fg-subtle">
                    <span>{incident.area_name}</span>
                    <span className="text-healthy tabular-nums">
                      {evidenceFor(store, incident.incident_id).filter(item => item._type === 'SUPPORTS').length} support
                    </span>
                    <span className="text-critical tabular-nums">
                      {evidenceFor(store, incident.incident_id).filter(item => item._type === 'CONTRADICTS').length} conflict
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {selectedIncident && (
          <div className="pointer-events-auto rounded-app border border-border bg-surface/95 p-3.5 backdrop-blur">
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-medium text-accent tabular-nums">{selectedIncident.incident_id}</span>
                  <Badge tone="neutral">{selectedIncident.status.replace(/_/g, ' ').toLowerCase()}</Badge>
                </div>
                <div className="mt-1 text-[13.5px] font-medium text-fg">{selectedIncident.title}</div>
              </div>
              <Button variant="ghost" size="iconSm" onClick={() => choose(null)} aria-label="Clear selection"><RotateCcw /></Button>
            </div>
            <p className="mt-1.5 text-[12.5px] leading-snug text-fg-muted">{selectedIncident.summary}</p>
            <div className="mt-2 flex gap-3 text-[12px] text-fg-subtle tabular-nums">
              <span className="text-healthy">{supporting} support</span>
              <span className="text-critical">{contradicting} conflict</span>
              <span>{selectedIncident.area_name}</span>
            </div>
            <div className="mt-2.5 flex gap-2">
              <Button variant="primary" size="sm" className="flex-1" onClick={() => navigate(`/incidents/${selectedIncident.incident_id}`)}>
                Open incident<ArrowRight />
              </Button>
              <Button size="sm" onClick={() => navigate(`/incidents/${selectedIncident.incident_id}/evidence`)}>Evidence</Button>
            </div>
          </div>
        )}

        <div className="pointer-events-auto max-h-[180px] overflow-y-auto rounded-app border border-border bg-surface/95 p-3 backdrop-blur">
          <div className="mb-1 text-[12px] font-medium text-fg-muted">Candidate clusters</div>
          {CANDIDATES.map(candidate => (
            <div key={candidate.candidate_id} className="border-t border-border py-2 first:border-0">
              <div className="flex items-center gap-2">
                <span className="text-[12px] font-medium text-fg tabular-nums">{candidate.candidate_id}</span>
                <Badge tone="neutral">{candidate.event_count} events</Badge>
              </div>
              <p className="mt-1 text-[12px] leading-snug text-fg-subtle">{candidate.reason}</p>
              <div className="mt-1.5 flex gap-1">
                <Button variant="ghost" size="sm">Promote<ChevronRight /></Button>
                <Button variant="ghost" size="sm">Discard</Button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="pointer-events-none absolute bottom-4 left-4 z-10 max-w-[360px]">
        <div className="pointer-events-auto rounded-app border border-border bg-surface/95 px-3 py-2 text-[11.5px] leading-snug text-fg-muted backdrop-blur">
          Locations with approximate precision are drawn as uncertainty areas rather than precise pins,
          and candidate clusters stay visually distinct from operator-reviewed incidents.
        </div>
      </div>
    </div>
  );
}

// Small inline icon so the search field keeps its leading glyph without another import.
function IconSearch() {
  return (
    <svg className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-fg-subtle"
      viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
      <circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5L14 14" />
    </svg>
  );
}