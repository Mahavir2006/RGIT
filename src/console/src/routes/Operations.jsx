import { useMemo, useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Map as MapIcon, Download, Play, Pause, Search, Locate } from 'lucide-react';
import { Badge, Button, Input } from '@/components/ui';
import { useApp } from '@/lib/store.jsx';
import SentinelMap from '@/components/SentinelMap.jsx';
import MapFiltersPanel from '@/components/MapFiltersPanel.jsx';
import IncidentInspector from '@/components/IncidentInspector.jsx';
import IndicatorVisual from '@/components/IndicatorVisual.jsx';
import { describeIndicator } from '@/lib/fx/indicatorRegistry.js';
import { useCommandModel } from '@/lib/commandModel.js';
import { useFilters, selectFiltered, summarise, evidenceStateOf } from '@/lib/filters.js';
import { SEVERITY_COLOUR, STATUS_COLOUR, CATEGORY_BY_ID, SOURCE_BY_ID } from '@/data/taxonomy.js';
import { SCENARIO } from '@/data/scenario.js';
import { AREAS } from '@/data/geo.js';
import { ago } from '@/lib/format.js';
import { cn } from '@/lib/utils';

// A layer is only offered when a connector could actually supply it. Layers with no source in
// this build are reported as unavailable rather than drawn as an empty overlay, because an
// empty overlay reads as a zero reading.
const LAYER_REQUIREMENTS = {
  crowd: 'No crowd-density connector is configured in this build.',
  transit: 'No transit feed is configured in this build.',
  power: 'No utility outage connector is configured in this build.',
  airQuality: 'OpenAQ is present but rate-limited; no current window is available.',
  facilities: 'Facility records exist, but no opening-hours or capacity feed is configured.',
  sensorHealth: 'Sensor health is derived from gauge heartbeats already shown with the gauges.',
  cascadePaths: 'Cascade paths require a solved scenario and are not yet drawn as geometry.'
};

function severityTone(severity) {
  if (severity === 'CRITICAL') return 'critical';
  if (severity === 'HIGH') return 'degraded';
  return 'neutral';
}

// Replay is a real time axis, not a cosmetic slider. The scenario window is 13:30-14:06:50 IST,
// and an incident only exists on the map once it has actually been observed, so scrubbing back
// genuinely removes incidents that had not happened yet.
const REPLAY_START = new Date(SCENARIO.windowStart).getTime();
const REPLAY_END = new Date(SCENARIO.windowEnd).getTime();

function replayTimeAt(position) {
  return REPLAY_START + (REPLAY_END - REPLAY_START) * (position / 100);
}

function replayLabel(position) {
  const at = new Date(replayTimeAt(position));
  const hours = String(at.getHours()).padStart(2, '0');
  const minutes = String(at.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}

function inBounds(item, bounds) {
  if (!bounds) return true;
  return item.lon >= bounds.west && item.lon <= bounds.east && item.lat >= bounds.south && item.lat <= bounds.north;
}

export default function Operations() {
  const { layers, dispatch, sources, liveEvents, fx } = useApp();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState(params.get('incident') || null);
  const [focus, setFocus] = useState({ id: params.get('incident') || null, nonce: 0 });
  const [filters, actions] = useFilters();
  // The panel starts collapsed. Operations is a full-bleed route whose main region is
  // overflow-hidden, so the page itself never scrolls: every extra pixel of chrome is taken
  // directly from the map. The map is the working surface, so it gets the height by default.
  const [panelOpen, setPanelOpen] = useState(false);
  const [replay, setReplay] = useState(100);
  const [playing, setPlaying] = useState(false);
  const [viewportCount, setViewportCount] = useState(null);
  const boundsRef = useRef(null);

  // Live connector events merge into the same projection, so a live record and a replayed one
  // are filtered and displayed by exactly the same code path.
  const model = useCommandModel(liveEvents ?? []);

  useEffect(() => {
    if (!playing) return undefined;
    const timer = setInterval(() => setReplay(value => (value >= 100 ? 20 : value + 4)), 260);
    return () => clearInterval(timer);
  }, [playing]);

  // One selector feeds the map, the statistics and the list, so those three cannot disagree.
  const { items: filtered, total, categoryCounts } = useMemo(
    () => selectFiltered(model.incidents, filters),
    [model.incidents, filters]
  );
  const stats = useMemo(() => summarise(filtered), [filtered]);

  // Replay gating happens after filtering, so the count of what replay is holding back is
  // visible rather than silently swallowed.
  const { shownAtTime, replayTime } = useMemo(() => {
    const time = replayTimeAt(replay);
    return { replayTime: time, shownAtTime: filtered.filter(item => new Date(item.observedAt).getTime() <= time) };
  }, [filtered, replay]);

  const heldBack = filtered.length - shownAtTime.length;

  // The viewport counter is recomputed from the same filtered array the map is drawing, so it
  // can never claim a different count than the map and list show. Pan/zoom updates arrive
  // through onBoundsChange; filter changes land here.
  useEffect(() => {
    setViewportCount(filtered.filter(item => inBounds(item, boundsRef.current)).length);
  }, [filtered]);

  const selectedItem = useMemo(
    () => model.incidents.find(item => item.id === selected) ?? null,
    [model.incidents, selected]
  );

  const areaNames = useMemo(
    () => ['All areas', ...AREAS.map(area => area.name)],
    []
  );

  const choose = useCallback(id => {
    setSelected(id);
    // Any new selection also frames it. `nonce` is bumped so re-selecting the same incident
    // after panning away still re-frames, which is what the operator expects from a click.
    setFocus(prev => ({ id, nonce: (prev?.nonce ?? 0) + 1 }));
    setParams(prev => {
      const next = new URLSearchParams(prev);
      if (id) next.set('incident', id); else next.delete('incident');
      return next;
    }, { replace: true });
  }, [setParams]);

  function handleHit(hit) {
    if (!hit) return;
    if (hit.kind === 'incident' || hit.kind === 'candidate') {
      choose(hit.id);
      return;
    }
    if (hit.kind === 'road') {
      // A road segment frames itself; it has no incident record to look up.
      setFocus(prev => ({ id: hit.id, nonce: (prev?.nonce ?? 0) + 1, lat: hit.lat, lon: hit.lon, radiusM: hit.radiusM }));
      setSelected(null);
      return;
    }
    if (hit.kind === 'asset') navigate(`/assets/${hit.id}`);
  }

  const toggleLayer = useCallback(key => {
    dispatch({ type: 'toggleLayer', layer: key });
  }, [dispatch]);

  const layerAvailability = useMemo(() => Object.fromEntries(
    Object.entries(LAYER_REQUIREMENTS).map(([key, reason]) => [key, { available: false, reason }])
  ), []);

  const accessInView = useMemo(
    () => model.accessStates.filter(entry => entry.state.id !== 'UNKNOWN').length,
    [model.accessStates]
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Identity, search and the replay transport. */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-surface px-4 py-2.5">
        <div className="mr-1 flex items-baseline gap-2">
          <h1 className="text-[14px] font-semibold text-fg">Live operations</h1>
          <span className="text-[12px] text-fg-subtle tabular-nums">{filtered.length} of {total}</span>
        </div>

        <div className="relative w-[200px]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-fg-subtle" />
          <Input
            value={filters.query}
            onChange={event => actions.setQuery(event.target.value)}
            placeholder="Search id, title, area"
            aria-label="Search incidents"
            className="h-8 pl-8"
          />
        </div>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setPlaying(value => !value)}
            className="grid size-7 place-items-center rounded-[6px] border border-border bg-surface text-fg-muted transition-colors hover:bg-surface-3 hover:text-fg"
            aria-label={playing ? 'Pause replay' : 'Play replay'}
          >
            {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
          </button>
          <input
            type="range" min="0" max="100" value={replay}
            onChange={event => setReplay(Number(event.target.value))}
            aria-label="Replay position"
            className="h-1 w-32 cursor-pointer appearance-none rounded-full bg-surface-3 accent-[var(--accent)]"
          />
          <span className="font-mono text-[11.5px] text-fg-subtle tabular-nums">
            {SCENARIO.mode.toLowerCase()} · {replayLabel(replay)}
            {heldBack > 0 && <span className="ml-1 text-degraded">−{heldBack} not yet observed</span>}
          </span>
          <Button variant="primary" size="sm"><Download />Export</Button>
        </div>
      </div>

      {/* The filter and intelligence-layer panel is the single control surface. */}
      <div className="shrink-0 px-4 py-2.5">
        <MapFiltersPanel
          filters={filters}
          actions={actions}
          categoryCounts={categoryCounts}
          total={total}
          shown={filtered.length}
          layerState={layers}
          onToggleLayer={toggleLayer}
          layerAvailability={layerAvailability}
          areas={areaNames}
          expanded={panelOpen}
          onToggleExpanded={() => setPanelOpen(value => !value)}
        />
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="relative min-h-0 min-w-0 flex-1">
          <SentinelMap
            incidents={shownAtTime}
            candidates={layers.candidates ? model.candidates : []}
            roads={model.roads}
            accessStates={layers.emergencyAccess ? model.accessStates : []}
            selection={selected}
            onSelect={handleHit}
            indicators={layers.indicators !== false}
            fxPaused={fx.paused}
            fxLowPerformance={fx.lowPerformance}
            fxHideUnselected={fx.hideUnselected}
            onBoundsChange={bounds => {
              boundsRef.current = bounds;
              setViewportCount(filtered.filter(item => inBounds(item, bounds)).length);
            }}
            focus={focus}
            // The map is its own flex sibling of the rail, so it is already centred within the visible
            // area. Padding only clears the stat chips and the attribution, not the rail.
            fitPadding={{ top: 56, bottom: 32, left: 32, right: 24 }}
            layers={layers}
            replay={replay}
            height="100%"
            showLegend
            className="h-full w-full"
          />

          {/* Live counts read the same filtered set the map is drawing. */}
          <div className="pointer-events-none absolute left-3 top-3 flex flex-wrap gap-2">
            <StatChip label="Critical" value={stats.critical} colour="var(--critical)" />
            <StatChip label="High" value={stats.high} colour="var(--degraded)" />
            <StatChip label="Access risk" value={accessInView} colour="#f97316" />
            {viewportCount !== null && <StatChip label="In view" value={viewportCount} colour="var(--accent)" />}

            {/* Re-frame after panning away. Framing follows selection, not panning, so this
                is how the operator returns to the incident at the right scale. */}
            {selectedItem && (
              <button
                onClick={() => setFocus(prev => ({ ...prev, nonce: (prev?.nonce ?? 0) + 1 }))}
                className="pointer-events-auto inline-flex h-6 items-center gap-1.5 rounded-[6px] border border-border bg-surface/95 px-2 text-[11.5px] text-fg-muted transition-colors hover:text-fg"
                aria-label={`Zoom to ${selectedItem.id}`}
              >
                <Locate className="size-3" />
                Zoom to {selectedItem.id}
              </button>
            )}

            {/* FX controls. Pause freezes the CSS animations in place rather than hiding the
                indicators, so the operator keeps the picture without the motion. */}
            <div className="pointer-events-auto flex items-center gap-1 rounded-[6px] border border-border bg-surface/95 px-1 py-0.5">
              <button
                onClick={() => dispatch({ type: 'toggleFx', key: 'paused' })}
                aria-pressed={fx.paused}
                className={cn('grid size-5 place-items-center rounded text-fg-subtle transition-colors hover:text-fg', fx.paused && 'text-accent')}
                aria-label={fx.paused ? 'Resume indicator animation' : 'Pause indicator animation'}
                title={fx.paused ? 'Resume indicator animation' : 'Pause indicator animation'}
              >
                {fx.paused ? <Play className="size-3" /> : <Pause className="size-3" />}
              </button>
              <button
                onClick={() => dispatch({ type: 'toggleFx', key: 'lowPerformance' })}
                aria-pressed={fx.lowPerformance}
                className={cn('rounded px-1.5 py-0.5 text-[11px] text-fg-subtle transition-colors hover:text-fg', fx.lowPerformance && 'text-accent')}
                aria-label="Toggle low-performance mode"
                title="Low-performance mode: drops orbit particles and the third ring"
              >
                FX
              </button>
              <button
                onClick={() => dispatch({ type: 'toggleFx', key: 'hideUnselected' })}
                aria-pressed={fx.hideUnselected}
                className={cn('rounded px-1.5 py-0.5 text-[11px] text-fg-subtle transition-colors hover:text-fg', fx.hideUnselected && 'text-accent')}
                aria-label="Show only the selected incident"
                title="Show only the selected incident"
              >
                Solo
              </button>
            </div>
          </div>
        </div>

        {/* List and inspection share the rail so selection is visible in both directions. */}
        <AnimatePresence mode="wait" initial={false}>
          {selectedItem ? (
            <motion.div key="inspector" className="flex w-[400px] shrink-0" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <IncidentInspector item={selectedItem} model={model} onClose={() => choose(null)} />
            </motion.div>
          ) : (
            // min-h-0 lets the rail shrink below its content height so it scrolls internally
            // instead of forcing the whole layout taller than the viewport. The page itself never
            // scrolls; the map does not scroll, the side panels do.
            <motion.aside key="list" className="flex min-h-0 w-[360px] shrink-0 flex-col overflow-y-auto border-l border-border bg-surface" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
                <span className="text-[13px] font-medium text-fg">Incidents</span>
                <span className="ml-auto font-mono text-[12px] text-fg-subtle tabular-nums">{filtered.length}</span>
              </div>

              {filtered.length === 0 ? (
                <div className="flex flex-col items-center gap-2 px-5 py-10 text-center">
                  <MapIcon className="size-5 text-fg-subtle" />
                  <div className="text-[13px] font-medium text-fg">No incidents match</div>
                  <p className="text-[12.5px] leading-snug text-fg-muted">
                    Clear a filter to widen the set. An empty result does not mean the area is unaffected.
                  </p>
                  <Button variant="ghost" size="sm" onClick={actions.clearAll}>Reset filters</Button>
                </div>
              ) : (
                <div className="divide-y divide-border">
                  {filtered.map(item => {
                    const evidenceState = evidenceStateOf(item);
                    const category = CATEGORY_BY_ID[item.category];
                    return (
                      <button
                        key={item.id}
                        onClick={() => choose(item.id)}
                        className={cn(
                          'flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors',
                          selected === item.id ? 'bg-accent-soft' : 'hover:bg-surface-2'
                        )}
                      >
                        <div className="flex items-start gap-2">
                          {/* The same animated indicator the map draws, at list scale. This is
                              what lets the operator read the list and the map as one picture
                              instead of two vocabularies. */}
                          <span className="relative mt-0.5 block size-8 shrink-0">
                            <IndicatorVisual
                              descriptor={{ ...describeIndicator(item), showCaption: false }}
                              scale={0.5}
                              className="!absolute left-1/2 top-1/2 size-0 -translate-x-1/2 -translate-y-1/2"
                            />
                          </span>

                          <span className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-[12px] font-medium text-accent tabular-nums">{item.id}</span>
                            <Badge tone={severityTone(item.severity)}>{item.severity.toLowerCase()}</Badge>
                            {item.isPredicted && <Badge tone="accent">predicted</Badge>}
                            <span className="ml-auto text-[11.5px] text-fg-subtle tabular-nums">{ago(item.updatedAt)}</span>
                          </div>

                          <div className="mt-0.5 text-[13px] font-medium text-fg">{item.title}</div>

                          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-fg-subtle">
                            <span className="inline-flex items-center gap-1">
                              <span className="size-1.5 rounded-full" style={{ background: SEVERITY_COLOUR[item.severity] }} />
                              {item.areaName}
                            </span>
                            <span style={{ color: STATUS_COLOUR[item.status] }}>{item.status.toLowerCase()}</span>
                            {category && <span style={{ color: category.colour }}>{category.short}</span>}
                            <span className="text-healthy tabular-nums">{item.supporting} support</span>
                            {item.contradicting > 0 && <span className="text-critical tabular-nums">{item.contradicting} conflict</span>}
                            {evidenceState === 'STALE' && <span className="text-degraded">stale</span>}
                          </div>

                          {/* Sources are named so a claim is never anonymous. */}
                          <div className="mt-0.5 flex flex-wrap gap-1.5 text-[11px]">
                            {(item.sourceTypes ?? []).slice(0, 3).map(source => (
                              <span key={source} style={{ color: SOURCE_BY_ID[source]?.colour }}>
                                {SOURCE_BY_ID[source]?.label ?? source}
                              </span>
                            ))}
                          </div>
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}

              {model.candidates.length > 0 && (
                <div className="border-t border-border p-4">
                  <div className="mb-1 text-[12px] font-medium text-fg-muted">Candidate clusters</div>
                  {model.candidates.map(candidate => (
                    <div key={candidate.candidate_id} className="border-t border-border py-2.5 first:border-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[12px] font-medium text-fg">{candidate.candidate_id}</span>
                        <Badge tone="neutral">{candidate.supporting} events</Badge>
                      </div>
                      <p className="mt-1 text-[12px] leading-snug text-fg-subtle">{candidate.reason}</p>
                      <p className="mt-1 text-[11px] text-fg-subtle">
                        Held for review. Promoting it would create a new incident, so it is not done from here.
                      </p>
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-auto border-t border-border px-4 py-3 text-[11.5px] leading-snug text-fg-subtle">
                Approximate-precision locations are drawn as uncertainty areas rather than precise
                pins. Predicted cascades are drawn and labelled separately from observed incidents,
                and a road with no observation is shown as insufficient evidence rather than passable.
                {sources.length > 0 && (
                  <> Connector health is on the <button className="underline" onClick={() => navigate('/sources')}>Data sources</button> page.</>
                )}
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function StatChip({ label, value, colour }) {
  return (
    <div className="pointer-events-auto flex items-center gap-1.5 rounded-[6px] border border-border bg-surface/95 px-2 py-1 text-[11.5px]">
      <span className="size-1.5 rounded-full" style={{ background: colour }} />
      <span className="text-fg-subtle">{label}</span>
      <span className="font-mono font-medium tabular-nums text-fg">{value}</span>
    </div>
  );
}