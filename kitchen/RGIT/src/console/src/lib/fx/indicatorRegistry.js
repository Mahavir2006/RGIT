// Incident indicator registry.
//
// One descriptor per incident kind, keyed by category, describing how that incident is drawn
// on the map. The map does not contain any per-category drawing logic; it asks this registry
// what an item should look like and renders whatever comes back.
//
// Two rules keep the registry honest:
//
//  1. A descriptor may never claim an extent the record does not carry. Mode B (affected-area
//     indicator) requires a real polygon. No source in this build provides one, so every
//     incident resolves to Mode A. That is a data fact, not a rendering shortcut.
//
//  2. Predicted, candidate, historical and confirmed effects must never share a look. If they
//     did, an operator could read a modelled consequence as an observation, which is the single
//     worst failure this map can have.
import { CATEGORY_BY_ID } from '../../data/taxonomy.js';
import { categoryGlyphSvg } from '../categoryGlyphs.js';

const FONT_STYLE = { size: 14, colour: '#ffffff', width: 2.1 };

/**
 * Cadence and styling per category. Durations are deliberately different so the map does not
 * pulse in unison: four incidents beating together reads as one heartbeat for the whole city.
 */
const STYLE_BY_CATEGORY = {
  flooding: { colour: '#38bdf8', rings: 3, ringDuration: '3.2s', orbit: true, glow: 0.55 },
  drainage: { colour: '#22d3ee', rings: 3, ringDuration: '3.6s', orbit: true, glow: 0.45 },
  road_blockage: { colour: '#f97316', rings: 3, ringDuration: '2.8s', orbit: false, glow: 0.5 },
  traffic: { colour: '#f59e0b', rings: 2, ringDuration: '2.6s', orbit: false, glow: 0.42 },
  emergency_access: { colour: '#ef4444', rings: 3, ringDuration: '2.4s', orbit: true, glow: 0.55 },
  fire_hazard: { colour: '#fb7185', rings: 3, ringDuration: '2.2s', orbit: true, glow: 0.6 },
  power: { colour: '#facc15', rings: 2, ringDuration: '3s', orbit: false, glow: 0.42 },
  transit: { colour: '#06b6d4', rings: 2, ringDuration: '3.1s', orbit: false, glow: 0.4 },
  // Diffuse environmental conditions: fewer, slower, softer. A fast radar ping on a pollution
  // reading would imply a sudden onset that the data does not show.
  air_quality: { colour: '#a78bfa', rings: 2, ringDuration: '5.6s', orbit: false, glow: 0.34 },
  weather: { colour: '#60a5fa', rings: 3, ringDuration: '4.4s', orbit: true, glow: 0.4 },
  protest: { colour: '#a855f7', rings: 2, ringDuration: '4.2s', orbit: false, glow: 0.38 },
  procession: { colour: '#c084fc', rings: 2, ringDuration: '4.6s', orbit: true, glow: 0.38 },
  infrastructure: { colour: '#a3a3a3', rings: 2, ringDuration: '3.4s', orbit: false, glow: 0.36 },
  reports: { colour: '#e879f9', rings: 2, ringDuration: '3.8s', orbit: false, glow: 0.34 },
  // A silent sensor is grey, not a warning colour: an unread sensor is an absence of information,
// and painting it in the same hue as a predicted cascade would dress missing data up as risk.
sensor_health: { colour: '#8a8fa3', rings: 2, ringDuration: '4s', orbit: false, glow: 0.3, broken: true },
  // A predicted cascade is amber, but a deeper amber than any confirmed category uses, so a
// projection can never be mistaken for an observed blockage of the same hue.
cascade: { colour: '#fbbf24', rings: 3, ringDuration: '3.4s', orbit: false, glow: 0.45, arrows: true }
};

const FALLBACK = { colour: '#94a3b8', rings: 2, ringDuration: '3.6s', orbit: false, glow: 0.34 };

// Candidates sit a step lighter than procession, which is also violet. Shared hue was
// tempting for grouping, but an unreviewed cluster must not be confusable with a confirmed
// crowd condition at a glance.
const CANDIDATE_STYLE = { colour: '#d8b4fe', rings: 2, ringDuration: '6s', orbit: false, glow: 0.24 };

/**
 * Does this record carry a real affected-area boundary?
 *
 * Mode B is only legitimate when a source supplies actual polygon geometry. A radius or a
 * centroid is an approximation and would be shown as a pulse, not as a flooded area. Returns
 * null today because no connector in this build provides an inundation polygon - the day one
 * does, it populates this and Mode B switches on with no rendering change.
 */
export function affectedPolygonFor(item) {
  return item.affectedPolygon ?? null;
}

/** Mode A or Mode B, decided by the record rather than by what would look best. */
export function resolveMode(item) {
  const polygon = affectedPolygonFor(item);
  if (polygon) return 'area';
  return 'pulse';
}

/**
 * Build the full descriptor for one incident.
 *
 * `kind` separates the three states that must never be confused: a confirmed incident, a
 * modelled prediction, and an unreviewed candidate. A resolved incident becomes historical and
 * stops pulsing entirely - an incident that is over should look over.
 */
export function describeIndicator(item) {
  const predicted = Boolean(item.isPredicted);
  const resolved = item.status === 'RESOLVED';
  const category = item.category;

  if (item.kind === 'candidate') {
    return {
      id: item.id, kind: 'candidate', mode: 'pulse',
      colour: CANDIDATE_STYLE.colour,
      rings: CANDIDATE_STYLE.rings,
      ringDuration: CANDIDATE_STYLE.ringDuration,
      glow: CANDIDATE_STYLE.glow,
      icon: categoryGlyphSvg('reports', FONT_STYLE),
      tag: 'CANDIDATE',
      severity: null,
      historical: false,
      // An unreviewed cluster must not be drawn at a confidence it has not earned.
      uncertaintyM: item.radiusM ?? 900,
      orbit: false, arrows: false,
      label: `${item.id} · awaiting evidence`
    };
  }

  const base = predicted ? STYLE_BY_CATEGORY.cascade : (STYLE_BY_CATEGORY[category] ?? FALLBACK);
  const historical = resolved;

  return {
    id: item.id,
    kind: predicted ? 'predicted' : historical ? 'historical' : 'confirmed',
    mode: resolveMode(item),
    colour: historical ? 'var(--fg-subtle)' : base.colour,
    rings: historical ? 0 : base.rings,
    ringDuration: base.ringDuration,
    glow: historical ? 0.18 : base.glow,
    icon: predicted ? categoryGlyphSvg('cascade', FONT_STYLE) : categoryGlyphSvg(category, FONT_STYLE),
    // The tag is the operator's guarantee about what they are looking at.
    tag: predicted ? 'PREDICTED' : historical ? 'RESOLVED' : CATEGORY_BY_ID[category]?.short?.toUpperCase() ?? null,
    severity: item.severity,
    historical,
    // Stated location uncertainty, drawn at its real size. A point-accurate record gets none.
    uncertaintyM: isPointAccurate(item) ? 0 : (item.uncertaintyM ?? 0),
    orbit: !historical && Boolean(base.orbit),
    arrows: predicted,
    broken: !historical && Boolean(base.broken),
    label: predicted
      ? `${item.id} · potential impact`
      : `${item.id}${item.severity ? ` · ${item.severity.toLowerCase()}` : ''}`
  };
}

/** Only a record whose own precision is 'point' may be drawn as a bare pin. */
function isPointAccurate(item) {
  if (item.locationPrecision === 'point') return true;
  if (item.locationPrecision === 'area' || item.location_precision === 'area') return false;
  return false;
}