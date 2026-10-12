// Animated incident legend.
//
// Every entry is a live indicator, not a static swatch. The legend is generated from the same
// registry the map uses, so a category can never appear here with a treatment it does not have
// on the map. Entries for incidents currently present are marked, so the legend doubles as a
// "what is on screen right now" key.
import { useMemo, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import IndicatorVisual from './IndicatorVisual.jsx';
import { describeIndicator } from '../lib/fx/indicatorRegistry.js';
import { CATEGORIES } from '../data/taxonomy.js';
import { cn } from '@/lib/utils';

// States that are not categories but that the operator must be able to tell apart on sight.
const STATE_ENTRIES = [
  {
    key: 'predicted',
    label: 'Predicted cascade',
    note: 'Modelled consequence. Not an observation.',
    item: { id: 'legend-predicted', category: 'cascade', status: 'NEW', isPredicted: true, severity: 'MODERATE', uncertaintyM: 1400, locationPrecision: 'area' }
  },
  {
    key: 'candidate',
    label: 'Candidate cluster',
    note: 'Unreviewed reports awaiting evidence.',
    item: { id: 'legend-candidate', category: 'reports', kind: 'candidate', status: 'NEEDS_REVIEW', radiusM: 900, uncertaintyM: 900, locationPrecision: 'area' }
  },
  {
    key: 'historical',
    label: 'Resolved',
    note: 'Subdued. Retained for history.',
    item: { id: 'legend-resolved', category: 'flooding', status: 'RESOLVED', severity: 'HIGH' }
  },
  {
    key: 'stale',
    label: 'Missing or stale signal',
    note: 'A sensor is not reporting. Not proof of safety.',
    item: { id: 'legend-stale', category: 'sensor_health', status: 'NEW', severity: 'MODERATE' }
  }
];

export default function IncidentLegend({ incidents = [], paused = false, className = '' }) {
  const [open, setOpen] = useState(true);
  const [tab, setTab] = useState('present');

  const presentCategories = useMemo(
    () => new Set(incidents.map(item => item.category)),
    [incidents]
  );

  const entries = useMemo(() => {
    // `cascade` is deliberately excluded from the category list. In this dataset it only ever
    // exists as a prediction, so listing it as a confirmed category would show the operator two
    // identical swatches - one under "All types" and one under "States" - for the same mark.
    const categoryEntries = CATEGORIES
      .filter(category => category.id !== 'cascade')
      .map(category => ({
        key: category.id,
        label: category.label,
        note: null,
        present: presentCategories.has(category.id),
        descriptor: describeIndicator({
          id: `legend-${category.id}`, category: category.id,
          status: 'CONFIRMED', severity: 'MODERATE', uncertaintyM: 0, locationPrecision: 'point'
        })
      }));

    const stateEntries = STATE_ENTRIES.map(entry => ({
      ...entry,
      present: false,
      descriptor: describeIndicator(entry.item)
    }));

    return { categoryEntries, stateEntries };
  }, [presentCategories]);

  const shown = tab === 'present'
    ? entries.categoryEntries.filter(entry => entry.present)
    : tab === 'states'
      ? entries.stateEntries
      : entries.categoryEntries;

  return (
    <div
      className={cn(
        'pointer-events-auto absolute bottom-3 left-3 w-[236px] overflow-hidden rounded-[8px] border border-border bg-surface/95',
        paused && 'us-paused',
        className
      )}
    >
      <button
        onClick={() => setOpen(value => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        aria-expanded={open}
      >
        <span className="text-[12px] font-medium text-fg">Incident indicators</span>
        {open ? <ChevronDown className="ml-auto size-3 text-fg-subtle" /> : <ChevronUp className="ml-auto size-3 text-fg-subtle" />}
      </button>

      {open && (
        <>
          <div className="flex gap-1 border-t border-border px-2 py-1.5">
            {[
              ['present', 'On map'],
              ['states', 'States'],
              ['all', 'All types']
            ].map(([id, label]) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={cn(
                  'rounded-[4px] px-1.5 py-0.5 text-[11px] transition-colors',
                  tab === id ? 'bg-surface-2 font-medium text-fg' : 'text-fg-muted hover:text-fg'
                )}
              >
                {label}
              </button>
            ))}
          </div>

          {/* The legend scrolls on its own. It must never grow tall enough to cover the map
              it is explaining, and it must not scroll the page. */}
          <div className="max-h-[38vh] overflow-y-auto border-t border-border px-2 py-1.5">
            {shown.length === 0 && (
              <p className="px-1 py-2 text-[11px] text-fg-subtle">No incidents on the map.</p>
            )}
            {shown.map(entry => (
              <div
                key={entry.key}
                className="flex items-start gap-2 rounded-[5px] px-1 py-1 hover:bg-surface-2"
              >
                {/* Fixed-size frame so the absolutely positioned rings have a containing block
                    and every entry animates identically regardless of label length. */}
                <span className="relative block size-8 shrink-0 overflow-visible">
                  <IndicatorVisual
                    descriptor={entry.descriptor}
                    scale={0.52}
                    className="!absolute left-1/2 top-1/2 size-0 -translate-x-1/2 -translate-y-1/2"
                  />
                </span>
                <span className="min-w-0 flex-1 pt-0.5">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate text-[11.5px] text-fg-muted">{entry.label}</span>
                    {entry.present && (
                      <span className="size-1.5 shrink-0 rounded-full bg-accent" title="Present on the map" />
                    )}
                  </span>
                  {entry.note && <span className="mt-0.5 block text-[10.5px] leading-snug text-fg-subtle">{entry.note}</span>}
                </span>
              </div>
            ))}
          </div>

          <p className="border-t border-border px-3 py-1.5 text-[10.5px] leading-snug text-fg-subtle">
            Rings are an indication of location and activity, not a measured boundary.
          </p>
        </>
      )}
    </div>
  );
}