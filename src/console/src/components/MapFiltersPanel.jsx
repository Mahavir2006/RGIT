// MAP FILTERS & INTELLIGENCE LAYERS
//
// The single control surface for the command map. Every toggle here is wired to the shared
// filter state, so changing a category immediately changes the map markers, the layer overlays,
// the statistics and the incident list - there is no second source of truth to fall out of sync.
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { SlidersHorizontal, ChevronDown, X, RotateCcw, Layers, Activity, ShieldAlert, Building, Bus, Ambulance, CloudRain, Users, Zap, Wind, Droplets, Radio } from 'lucide-react';
import {
  CATEGORIES, CATEGORY_BY_ID, SEVERITIES, SEVERITY_COLOUR, STATUSES, STATUS_COLOUR,
  SOURCES, EVIDENCE_STATES, EVIDENCE_STATE_COLOUR, DATA_MODES, TIME_WINDOWS
} from '../data/taxonomy.js';
import { Badge, Button } from '@/components/ui';
import { categoryGlyphSvg } from '../lib/categoryGlyphs.js';
import { activeFilterChips, removeChip } from '../lib/filters.js';
import { cn } from '@/lib/utils';

// The mark drawn here is the exact artwork the map draws as a badge, so a category learned in
// the panel is the same shape on the map rather than an approximation.
function CategoryRow({ category, enabled, count, onToggle, onOnly }) {
  return (
    <div className={cn(
      'group flex items-center gap-2 rounded-[6px] border px-2 py-1.5 transition-colors',
      enabled ? 'border-border bg-surface-2' : 'border-transparent opacity-55 hover:opacity-90'
    )}>
      <button
        onClick={() => onToggle(category.id)}
        role="switch"
        aria-checked={enabled}
        aria-label={`${category.label}: ${enabled ? 'on' : 'off'}`}
        className="flex min-w-0 flex-1 items-center gap-2 text-left"
      >
        <span
          className="grid size-5 shrink-0 place-items-center rounded-[5px]"
          style={{ background: enabled ? category.colour : `${category.colour}33` }}
          dangerouslySetInnerHTML={{
            __html: categoryGlyphSvg(category.id, { size: 13, colour: enabled ? '#ffffff' : category.colour })
          }}
        />
        <span className={cn('truncate text-[12px]', enabled ? 'text-fg' : 'text-fg-muted')}>{category.label}</span>
      </button>

      <span className="shrink-0 font-mono text-[11px] tabular-nums text-fg-subtle">{count}</span>

      {/* A switch rather than a checkbox, so the on/off state reads at a glance. */}
      <button
        onClick={() => onToggle(category.id)}
        role="switch"
        aria-checked={enabled}
        aria-label={`Toggle ${category.label}`}
        className={cn(
          'relative h-4 w-7 shrink-0 rounded-full transition-colors',
          enabled ? 'bg-accent' : 'bg-surface-3'
        )}
      >
        <span className={cn(
          'absolute top-0.5 size-3 rounded-full bg-white transition-transform',
          enabled ? 'translate-x-3.5' : 'translate-x-0.5'
        )} />
      </button>

      <button
        onClick={() => onOnly(category.id)}
        title={`Show only ${category.label}`}
        aria-label={`Show only ${category.label}`}
        className="shrink-0 rounded-[4px] px-1 text-[10px] text-fg-subtle opacity-0 transition-opacity hover:text-accent focus-visible:opacity-100 group-hover:opacity-100"
      >
        only
      </button>
    </div>
  );
}

function ChipGroup({ legend, options, selected, onToggle, colourOf, mono }) {
  return (
    <div>
      <div className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.1em] text-fg-subtle">{legend}</div>
      <div className="flex flex-wrap gap-1.5">
        {options.map(option => {
          const id = typeof option === 'string' ? option : option.id;
          const label = typeof option === 'string' ? option : option.label;
          const on = selected.includes(id);
          const colour = colourOf?.(id);
          return (
            <button
              key={id}
              onClick={() => onToggle(id)}
              aria-pressed={on}
              className={cn(
                'inline-flex h-6 items-center gap-1.5 rounded-[5px] border px-2 text-[11.5px] transition-colors',
                mono && 'font-mono',
                on ? 'border-transparent text-ink' : 'border-border text-fg-muted hover:text-fg'
              )}
              style={on && colour ? { background: colour, borderColor: colour } : undefined}
            >
              {colour && <span className="size-1.5 rounded-full" style={{ background: on ? 'currentColor' : colour }} />}
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// Layer toggles that are genuinely unavailable say why, and refuse to pretend to draw data.
const INTELLIGENCE_LAYERS = [
  { key: 'incidents', label: 'Incidents', always: true },
  { key: 'candidates', label: 'Candidates', always: true },
  { key: 'assets', label: 'Assets', always: true },
  { key: 'impactZones', label: 'Impact zones', always: true },
  { key: 'dependencies', label: 'Dependencies', always: true },
  { key: 'indicators', label: 'Incident indicators', always: true, icon: Radio },
  { key: 'hazard', label: 'Hazard detail', always: true, icon: Droplets },
  { key: 'emergencyAccess', label: 'Emergency access', always: true, icon: Ambulance },
  { key: 'rainfall', label: 'Rainfall', sourceId: 'openmeteo', icon: CloudRain },
  { key: 'crowd', label: 'Crowd concentration', icon: Users },
  { key: 'transit', label: 'Public transport', icon: Bus },
  { key: 'power', label: 'Power outages', icon: Zap },
  { key: 'airQuality', label: 'Air quality', sourceId: 'openaq', icon: Wind },
  { key: 'facilities', label: 'Emergency facilities', icon: Building },
  { key: 'sensorHealth', label: 'Sensor health', sourceId: 'cwc_water_gauge', icon: Activity },
  { key: 'cascadePaths', label: 'Cascade paths', icon: ShieldAlert }
];

export default function MapFiltersPanel({
  filters, actions, categoryCounts, total, shown, layerState, onToggleLayer, layerAvailability = {},
  areas = ['All areas'], expanded, onToggleExpanded
}) {
  const [tab, setTab] = useState('categories');
  const chips = activeFilterChips(filters);
  const windowDefinition = TIME_WINDOWS.find(item => item.id === filters.timeWindow);

  return (
    <div className="overflow-hidden rounded-app border border-border bg-surface">
      <header className="flex flex-wrap items-center gap-2 px-3 py-2.5">
        <button
          onClick={onToggleExpanded}
          aria-expanded={expanded}
          className="inline-flex items-center gap-2 text-[13px] font-semibold text-fg"
        >
          <SlidersHorizontal className="size-3.5 text-fg-subtle" />
          Map filters &amp; intelligence layers
          <ChevronDown className={cn('size-3.5 text-fg-subtle transition-transform', expanded && 'rotate-180')} />
        </button>

        {chips.length > 0 && (
          <Badge tone="accent">{chips.length} active</Badge>
        )}

        <div className="ml-auto flex items-center gap-2">
          <span className="font-mono text-[11.5px] text-fg-subtle tabular-nums">
            {shown} of {total} shown
          </span>
          <Button size="sm" variant="ghost" onClick={actions.clearAll}>
            <RotateCcw />Clear all
          </Button>
        </div>
      </header>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            {/* Active filter chips */}
            {chips.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 border-t border-border px-3 py-2">
                {chips.map(chip => (
                  <button
                    key={chip.key}
                    onClick={() => actions.replace(removeChip(filters, chip))}
                    className="inline-flex h-6 items-center gap-1 rounded-[5px] border border-accent/30 bg-accent-soft px-2 text-[11.5px] text-accent transition-colors hover:border-accent"
                    aria-label={`Remove filter ${chip.label}`}
                  >
                    {chip.label}
                    <X className="size-3" />
                  </button>
                ))}
              </div>
            )}

            <div className="flex gap-1 border-t border-border px-3 py-2">
              {[
                ['categories', 'Categories'],
                ['severity', 'Severity & status'],
                ['sources', 'Sources'],
                ['time', 'Time & confidence'],
                ['layers', 'Layers']
              ].map(([id, label]) => (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={cn(
                    'rounded-[5px] px-2 py-1 text-[12px] transition-colors',
                    tab === id ? 'bg-surface-2 font-medium text-fg' : 'text-fg-muted hover:text-fg'
                  )}
                >
                  {label}
                </button>
              ))}
            </div>

            // Capped against the viewport rather than a fixed pixel height: on a short screen the panel
              // scrolls internally instead of pushing the map out of the remaining space.
              <div className="max-h-[38vh] overflow-y-auto border-t border-border px-3 py-3">
              {tab === 'categories' && (
                <div className="grid gap-1.5 md:grid-cols-2">
                  {CATEGORIES.map(category => (
                    <CategoryRow
                      key={category.id}
                      category={category}
                      enabled={filters.categories.includes(category.id)}
                      count={categoryCounts[category.id] ?? 0}
                      onToggle={actions.toggleCategory}
                      onOnly={actions.onlyCategory}
                    />
                  ))}
                </div>
              )}

              {tab === 'severity' && (
                <div className="grid gap-5 md:grid-cols-2">
                  <ChipGroup
                    legend="Severity"
                    options={SEVERITIES}
                    selected={filters.severities}
                    onToggle={actions.toggleSeverity}
                    colourOf={id => SEVERITY_COLOUR[id]}
                    mono
                  />
                  <ChipGroup
                    legend="Status"
                    options={STATUSES}
                    selected={filters.statuses}
                    onToggle={actions.toggleStatus}
                    colourOf={id => STATUS_COLOUR[id]}
                    mono
                  />
                  <ChipGroup
                    legend="Evidence state"
                    options={EVIDENCE_STATES}
                    selected={filters.evidence}
                    onToggle={actions.toggleEvidence}
                    colourOf={id => EVIDENCE_STATE_COLOUR[id]}
                    mono
                  />
                  <ChipGroup
                    legend="Data mode"
                    options={DATA_MODES}
                    selected={filters.dataModes}
                    onToggle={actions.toggleDataMode}
                    mono
                  />
                </div>
              )}

              {tab === 'sources' && (
                <div className="grid gap-5 md:grid-cols-2">
                  <ChipGroup
                    legend="Source"
                    options={SOURCES.map(source => ({ id: source.id, label: source.label }))}
                    selected={filters.sources}
                    onToggle={actions.toggleSource}
                    colourOf={id => SOURCES.find(source => source.id === id)?.colour}
                  />
                  <div className="grid gap-3">
                    <div>
                      <div className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.1em] text-fg-subtle">Geographic area</div>
                      <div className="flex flex-wrap gap-1.5">
                        {['All areas', ...areas].map(area => {
                          const on = filters.area === area;
                          return (
                            <button
                              key={area}
                              onClick={() => actions.setArea(area)}
                              aria-pressed={on}
                              className={cn(
                                'h-6 rounded-[5px] border px-2 text-[11.5px] transition-colors',
                                on ? 'border-accent/40 bg-accent-soft font-medium text-accent' : 'border-border text-fg-muted hover:text-fg'
                              )}
                            >
                              {area}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    <div className="text-[11.5px] leading-relaxed text-fg-subtle">
                      Source health, credential state and last successful read are on the Data sources page. A connector
                      that is offline is reported as degraded rather than hidden.
                    </div>
                  </div>
                </div>
              )}

              {tab === 'time' && (
                <div className="grid gap-5 md:grid-cols-2">
                  <div>
                    <div className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.1em] text-fg-subtle">Time window</div>
                    <div className="flex flex-wrap gap-1.5">
                      {TIME_WINDOWS.map(option => {
                        const on = filters.timeWindow === option.id;
                        return (
                          <button
                            key={option.id}
                            onClick={() => actions.setTimeWindow(option.id)}
                            aria-pressed={on}
                            className={cn(
                              'h-6 rounded-[5px] border px-2 text-[11.5px] transition-colors',
                              on ? 'border-accent/40 bg-accent-soft font-medium text-accent' : 'border-border text-fg-muted hover:text-fg'
                            )}
                          >
                            {option.label}
                          </button>
                        );
                      })}
                    </div>
                    {filters.timeWindow === 'custom' && (
                      <div className="mt-2 flex items-center gap-2">
                        <input
                          type="datetime-local"
                          value={filters.customFrom ?? ''}
                          onChange={event => actions.setCustomRange(event.target.value, filters.customTo)}
                          aria-label="Range start"
                          className="h-7 rounded-[5px] border border-border bg-surface px-2 text-[11.5px] text-fg"
                        />
                        <span className="text-fg-subtle">→</span>
                        <input
                          type="datetime-local"
                          value={filters.customTo ?? ''}
                          onChange={event => actions.setCustomRange(filters.customFrom, event.target.value)}
                          aria-label="Range end"
                          className="h-7 rounded-[5px] border border-border bg-surface px-2 text-[11.5px] text-fg"
                        />
                      </div>
                    )}
                    <div className="mt-2 text-[11px] text-fg-subtle">
                      Evaluated against the observation time, not the ingest time.
                      {windowDefinition?.minutes ? ` Window ${windowDefinition.label.toLowerCase()}.` : ''}
                    </div>
                  </div>

                  <div>
                    <div className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.1em] text-fg-subtle">
                      Minimum confidence · {filters.confidenceMin.toFixed(2)}
                    </div>
                    <input
                      type="range" min="0" max="1" step="0.05" value={filters.confidenceMin}
                      onChange={event => actions.setConfidence(Number(event.target.value))}
                      aria-label="Minimum confidence"
                      className="h-1 w-full cursor-pointer appearance-none rounded-full bg-surface-3 accent-[var(--accent)]"
                    />
                    <div className="mt-2 text-[11px] leading-relaxed text-fg-subtle">
                      Heuristic ranking, not a calibrated probability. Filtering on it narrows to better-associated
                      records; it does not assert the score is correct.
                    </div>
                  </div>
                </div>
              )}

              {tab === 'layers' && (
                <div>
                  <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.1em] text-fg-subtle">
                    Intelligence layers
                  </div>
                  <div className="grid gap-1.5 md:grid-cols-2">
                    {INTELLIGENCE_LAYERS.map(layer => {
                      const Icon = layer.icon ?? Layers;
                      const availability = layerAvailability[layer.key];
                      const unavailable = availability && availability.available === false;
                      const on = Boolean(layerState[layer.key]);
                      return (
                        <button
                          key={layer.key}
                          onClick={() => !unavailable && onToggleLayer(layer.key)}
                          disabled={Boolean(layer.always) || Boolean(unavailable)}
                          title={unavailable
                            ? `Unavailable: ${availability.reason}`
                            : layer.always ? 'Core layer, always drawn' : layer.label}
                          className={cn(
                            'flex items-center gap-2 rounded-[6px] border px-2 py-1.5 text-left transition-colors',
                            unavailable
                              ? 'border-dashed border-degraded/40 text-degraded'
                              : on
                                ? 'border-border bg-surface-2'
                                : 'border-transparent text-fg-muted opacity-60 hover:opacity-100',
                            layer.always && 'cursor-default'
                          )}
                        >
                          <span className={cn('size-1.5 shrink-0 rounded-full', on && !unavailable ? 'bg-accent' : 'bg-border-strong')} />
                          <Icon className="size-3 shrink-0" />
                          <span className="flex-1 truncate text-[12px]">{layer.label}</span>
                          {unavailable && <span className="shrink-0 text-[10px]">no source</span>}
                        </button>
                      );
                    })}
                  </div>
                  <div className="mt-3 text-[11px] leading-relaxed text-fg-subtle">
                    A layer is only selectable when a source can actually supply it. Unavailable layers state the missing
                    source rather than drawing an empty overlay that reads as a zero reading.
                  </div>
                </div>
              )}
            </div>

            {shown === 0 && total > 0 && (
              <div className="border-t border-border bg-degraded-soft px-3 py-2 text-[12px] text-degraded">
                No incidents match the current filters. Clear one to widen the set — an empty result does not mean the
                area is unaffected.
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}