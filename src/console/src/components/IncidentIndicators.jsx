// Incident indicator overlay.
//
// Sits on top of the map canvas and draws one indicator per incident.
//
// The split here matters for performance: React renders the indicators, but it does NOT
// re-render when the map moves. Position and zoom-dependent sizing are written straight to the
// DOM in a single pass on every map `move`/`rotate`/`resize`, keyed by ref. A pan therefore
// costs N transform writes, not N React renders, so the map keeps its frame rate with several
// indicators running.
//
// All motion is CSS (see styles/indicators.css). Nothing here animates on a timer.
import { useEffect, useRef, useMemo } from 'react';
import { describeIndicator } from '../lib/fx/indicatorRegistry.js';
import IndicatorVisual from './IndicatorVisual.jsx';
import { cn } from '@/lib/utils';

// Markers stay small when the operator is looking at the whole city and grow as they approach,
// because a fixed size that reads well at street level becomes unreadable clutter at z11.
const FAR_ZOOM = 13;
const MIN_SCALE = 0.62;
const MAX_SCALE = 1.18;
const FAR_LABEL_ZOOM = 12.6;

function scaleForZoom(zoom) {
  if (zoom <= 11) return MIN_SCALE;
  if (zoom >= FAR_ZOOM + 1.5) return MAX_SCALE;
  return MIN_SCALE + ((zoom - 11) / (FAR_ZOOM + 1.5 - 11)) * (MAX_SCALE - MIN_SCALE);
}

export default function IncidentIndicators({
  map, incidents = [], selection, onSelect,
  paused = false, lowPerformance = false, hideUnselected = false
}) {
  const nodes = useRef(new Map());
  const containerRef = useRef(null);

  // Descriptors are recomputed only when the incident set changes - on a filter or selection
  // change, never on a pan.
  const descriptors = useMemo(
    () => incidents.map(item => ({ item, descriptor: describeIndicator(item) })),
    [incidents]
  );

  const byId = useMemo(() => new Map(descriptors.map(entry => [entry.item.id, entry])), [descriptors]);

  // ---- Positioning: one imperative pass per map event ----------------------------
  useEffect(() => {
    if (!map) return undefined;
    const container = containerRef.current;
    if (!container) return undefined;

    const reposition = () => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      const zoom = map.getZoom();
      const scale = scaleForZoom(zoom);

      // Metres per screen pixel, measured from the map itself rather than assumed, so the
      // uncertainty boundary shows the real stated radius at any latitude and zoom.
      const origin = map.unproject([0, 0]);
      const onePixel = map.unproject([1, 0]);
      const metresPerPixel = Math.abs(onePixel[0] - origin[0]) * 111320
        * Math.cos((origin[1] * Math.PI) / 180);

      for (const [id, node] of nodes.current) {
        if (!node) continue;
        const entry = byId.get(id);
        if (!entry) continue;
        const point = map.project([entry.item.lon, entry.item.lat]);

        // Off-screen indicators are hidden rather than transformed, which also stops the
        // compositor promoting a dozen invisible layers.
        const visible = point.x > -180 && point.y > -180 && point.x < width + 180 && point.y < height + 180;
        node.style.display = visible ? '' : 'none';
        if (!visible) continue;

        node.style.transform = `translate3d(${point.x.toFixed(1)}px, ${point.y.toFixed(1)}px, 0) translate(-50%, -50%)`;
        node.style.setProperty('--us-zoom-scale', scale.toFixed(3));

        // The uncertainty ring is sized from the record's own stated uncertainty, clamped so a
        // 800m accuracy does not swallow the map.
        const metres = entry.descriptor.uncertaintyM;
        if (metres > 0) {
          const pixels = Math.max(56, Math.min(360, metres / Math.max(0.5, metresPerPixel)));
          node.style.setProperty('--us-uncertainty-size', `${pixels.toFixed(0)}px`);
        }
        // Distant zoom hides the caption so it cannot cover neighbouring markers.
        node.dataset.far = String(zoom < FAR_LABEL_ZOOM);
      }
    };

    // A container resize invalidates the projection even without a map move.
    const observer = new ResizeObserver(reposition);
    observer.observe(container);
    map.on('move', reposition);
    map.on('rotate', reposition);
    map.on('resize', reposition);

    reposition();

    return () => {
      observer.disconnect();
      map.off('move', reposition);
      map.off('rotate', reposition);
      map.off('resize', reposition);
    };
  }, [map, byId]);

  const visible = hideUnselected && selection
    ? descriptors.filter(({ item }) => item.id === selection)
    : descriptors;

  return (
    <div
      ref={containerRef}
      className={cn(
        'pointer-events-none absolute inset-0 overflow-hidden',
        paused && 'us-paused',
        lowPerformance && 'us-lowperf'
      )}
    >
      {visible.map(({ item, descriptor }) => {
        const selected = item.id === selection;

        return (
          <button
            key={item.id}
            type="button"
            // Transform is owned by the imperative pass above; React supplies structure and
            // data, and only writes the transform before the first map event.
            ref={node => {
              if (node) nodes.current.set(item.id, node);
              else nodes.current.delete(item.id);
            }}
            style={{
              // The uncertainty boundary is sized imperatively from the record's stated radius
              // and the map's metres-per-pixel, so the legend swatch needs no size here.
              '--us-uncertainty-size': '104px'
            }}
            title={`${descriptor.label} - ${item.areaName}`}
            aria-label={`${descriptor.label} in ${item.areaName}`}
            className={cn(
              'us-indicator pointer-events-auto cursor-pointer border-0 bg-transparent p-0',
              descriptor.historical && 'us-indicator--historical'
            )}
            onClick={event => {
              event.stopPropagation();
              onSelect?.(item);
            }}
          >
            <IndicatorVisual
              descriptor={{ ...descriptor, showCaption: true }}
              areaName={item.areaName}
              selected={selected}
            />
          </button>
        );
      })}
    </div>
  );
}
