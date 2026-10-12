// Canonical event model.
//
// Every adapter, replay fixture and manual submission is normalised into this shape before it
// reaches a view. The rules the product specification insists on are enforced here rather than
// trusted to callers:
//
//   * observed-at (event_time) and received-at (ingest_time) are always separate;
//   * coordinates and timestamps are validated, never assumed;
//   * quality and provenance travel with the record;
//   * a duplicate is linked to its canonical event and never counts as corroboration;
//   * confidence is a heuristic band, never presented as a calibrated probability.
import { categoryForEventType, SEVERITIES, SOURCES, DATA_MODES } from './taxonomy.js';

export const SCHEMA_VERSION = '1.5.0';

export const QUALITY_STATUSES = ['VALID', 'SUSPECT', 'INVALID', 'STALE'];

export const VERIFICATION_STATUSES = ['UNVERIFIED', 'CORROBORATED', 'OFFICIAL_NOTICE', 'HUMAN_REVIEWED'];

export const VALIDATION_OUTCOMES = ['ACCEPTED', 'ACCEPTED_WITH_WARNING', 'QUARANTINED', 'REJECTED'];

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

export function validateCoordinates(location) {
  if (!location) return { ok: false, reason: 'COORD_MISSING', explanation: 'No location was supplied with this record.' };
  const { latitude, longitude } = location;
  if (!isFiniteNumber(latitude) || !isFiniteNumber(longitude)) {
    return { ok: false, reason: 'COORD_NOT_NUMERIC', explanation: 'Latitude and longitude must both be finite numbers.' };
  }
  if (latitude < -90 || latitude > 90) {
    return { ok: false, reason: 'COORD_OUT_OF_RANGE', explanation: `Latitude ${latitude} is outside [-90, 90].` };
  }
  if (longitude < -180 || longitude > 180) {
    return { ok: false, reason: 'COORD_OUT_OF_RANGE', explanation: `Longitude ${longitude} is outside [-180, 180].` };
  }
  return { ok: true };
}

export function validateTimestamp(value) {
  if (!value) return { ok: false, reason: 'TIME_MISSING', explanation: 'An observation time is required.' };
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return { ok: false, reason: 'TIME_UNPARSEABLE', explanation: 'The observation time is not a parseable ISO-8601 timestamp.' };
  }
  return { ok: true };
}

/**
 * Build a canonical event. Validation never throws: an invalid record comes back with an
 * outcome and a machine-readable reason so it can be quarantined and inspected instead of
 * being silently discarded.
 */
export function normalizeEvent(input, context = {}) {
  const eventTime = input.event_time ?? input.observed_at ?? null;
  const timeCheck = validateTimestamp(eventTime);
  const location = normalizeLocation(input.location ?? input);
  const coordCheck = validateCoordinates(location);

  const flags = [...new Set([...(input.quality?.flags ?? []), ...(input.flags ?? [])])];
  const eventType = String(input.event_type ?? input.type ?? 'unknown');
  const category = input.category ?? categoryForEventType(eventType);

  let outcome = 'ACCEPTED';
  let reasonCode = null;
  let explanation = null;

  if (!timeCheck.ok) {
    outcome = 'REJECTED';
    reasonCode = timeCheck.reason;
    explanation = timeCheck.explanation;
  } else if (!coordCheck.ok) {
    // A record with a usable time but a bad location is quarantined rather than rejected:
    // the signal is real, only its position is unusable.
    outcome = 'QUARANTINED';
    reasonCode = coordCheck.reason;
    explanation = coordCheck.explanation;
  } else if (flags.includes('UNIT_UNRECOGNISED')) {
    outcome = 'QUARANTINED';
    reasonCode = 'UNIT_UNRECOGNISED';
    explanation = 'No conversion is defined for this unit, so the reading is held rather than guessed. Original value and unit are preserved.';
  } else if (flags.includes('CROSS_SIGNAL_DISAGREEMENT') || flags.includes('SUSPECT')) {
    outcome = 'ACCEPTED_WITH_WARNING';
  }

  const measurements = normalizeMeasurements(input.measurements);

  const event = {
    schema_version: SCHEMA_VERSION,
    event_id: input.event_id ?? context.eventId ?? null,
    event_type: eventType,
    category,
    source_id: input.source_id ?? null,
    source_type: input.source_type ?? input.sourceType ?? deriveSourceType(input.source_id),
    source_event_id: input.source_event_id ?? null,
    source_url: input.source_url ?? input.sourceUrl ?? null,
    source_mode: normaliseMode(input.source_mode ?? input.source_mode ?? 'SIMULATED'),
    event_time: timeCheck.ok ? new Date(eventTime).toISOString() : eventTime,
    ingest_time: input.ingest_time ?? context.ingestTime ?? new Date().toISOString(),
    location,
    measurements,
    severity: normaliseSeverity(input.severity),
    confidence_score: clamp01(input.confidence_score ?? input.confidence ?? null),
    verification_status: input.verification_status ?? 'UNVERIFIED',
    quality: {
      status: input.quality?.status ?? (flags.includes('SENSOR_HEALTH') || flags.includes('MISSING_SIGNAL') ? 'STALE' : 'VALID'),
      flags
    },
    validation: outcome === 'ACCEPTED' ? null : { outcome, reasonCode, explanation },
    duplicate_of: input.duplicate_of ?? null,
    payload: input.payload ?? {},
    text: input.text ?? null,
    provenance: {
      adapter: input.provenance?.adapter ?? context.adapter ?? null,
      adapter_version: input.provenance?.adapter_version ?? context.adapterVersion ?? null,
      retrieved_at: input.provenance?.retrieved_at ?? context.retrievedAt ?? null,
      licence: input.provenance?.licence ?? null,
      terms_url: input.provenance?.terms_url ?? null,
      raw_ref: input.payload_ref ?? input.provenance?.raw_ref ?? null
    },
    ingested_via: context.adapter ?? input.ingested_via ?? null
  };

  return event;
}

function deriveSourceType(sourceId) {
  if (!sourceId) return 'unknown';
  if (String(sourceId).includes('citizen')) return 'citizen';
  if (String(sourceId).includes('news') || sourceId === 'gdelt') return 'news';
  if (String(sourceId).includes('weather') || sourceId === 'openmeteo' || sourceId === 'imd_weather') return 'weather_api';
  if (String(sourceId).includes('aq') || sourceId === 'cpbc') return 'weather_api';
  if (String(sourceId).includes('traffic') || sourceId === 'tomtom_traffic') return 'iot';
  return 'iot';
}

export function normaliseMode(mode) {
  const value = String(mode ?? '').toUpperCase().replace(/[\s-]+/g, '_');
  if (DATA_MODES.includes(value)) return value;
  if (['LIVE_API', 'LIVE'].includes(value)) return 'LIVE';
  if (['REPLAY', 'HISTORICAL'].includes(value)) return 'HISTORICAL';
  if (['SYNTHETIC', 'MANUAL', 'SIMULATED'].includes(value)) return 'SIMULATED';
  return 'SIMULATED';
}

export function normaliseSeverity(severity) {
  const value = String(severity ?? '').toUpperCase();
  if (SEVERITIES.includes(value)) return value;
  // Older fixtures used lowercase and a MODERATE/Low mix.
  const mapped = { LOW: 'LOW', MEDIUM: 'MODERATE', MODERATE: 'MODERATE', HIGH: 'HIGH', CRITICAL: 'CRITICAL', INFO: 'LOW' }[value];
  return mapped ?? 'LOW';
}

function clamp01(value) {
  if (!isFiniteNumber(value)) return null;
  return Math.max(0, Math.min(1, value));
}

function normalizeLocation(input) {
  const raw = input?.location ?? input;
  const latitude = raw?.latitude ?? raw?.lat ?? null;
  const longitude = raw?.longitude ?? raw?.lon ?? raw?.lng ?? null;
  return {
    latitude: isFiniteNumber(latitude) ? latitude : null,
    longitude: isFiniteNumber(longitude) ? longitude : null,
    accuracy_m: isFiniteNumber(raw?.accuracy_m ?? raw?.accuracy) ? (raw.accuracy_m ?? raw.accuracy) : null,
    area_ref: raw?.area_ref ?? null,
    precision: raw?.precision ?? 'area',
    label: raw?.label ?? null
  };
}

function normalizeMeasurements(input) {
  if (!Array.isArray(input)) return [];
  return input
    .filter(item => item && isFiniteNumber(Number(item.value)))
    .map(item => ({
      name: String(item.name),
      value: Number(item.value),
      unit: item.unit ?? 'unknown',
      period: item.period ?? 'instantaneous'
    }));
}

/**
 * Deduplicate with the documented hierarchy: provider event id, then explicit idempotency key,
 * then a content fingerprint. The fingerprint is a fallback, not truth - it is recorded so an
 * operator can see why two records were collapsed.
 */
export function idempotencyKey(event) {
  if (event.source_event_id) return `provider:${event.source_id}:${event.source_event_id}`;
  if (event.payload?.idempotency_key) return `explicit:${event.payload.idempotency_key}`;
  return `fingerprint:${fingerprint(event)}`;
}

export function fingerprint(event) {
  const time = event.event_time ? Math.floor(new Date(event.event_time).getTime() / 60000) : 'na';
  const lat = event.location?.latitude != null ? event.location.latitude.toFixed(3) : 'na';
  const lon = event.location?.longitude != null ? event.location.longitude.toFixed(3) : 'na';
  const values = event.measurements.map(item => `${item.name}=${item.value}${item.unit}`).sort().join(',');
  return [event.source_id, event.event_type, time, lat, lon, values].join('|');
}

/**
 * Apply deduplication over an incoming batch. Duplicates are marked and linked, and are
 * excluded from corroboration counting by the caller.
 */
export function deduplicate(incoming, known = new Map()) {
  const accepted = [];
  const duplicates = [];
  const index = new Map(known);

  for (const event of incoming) {
    const key = idempotencyKey(event);
    const existing = index.get(key);
    if (existing) {
      const duplicate = {
        ...event,
        duplicate_of: existing.event_id,
        quality: {
          ...event.quality,
          flags: [...new Set([...event.quality.flags, 'DUPLICATE_DELIVERY'])]
        },
        provenance: { ...event.provenance, duplicate_rule: existing.source_event_id ? 'provider_event_id' : 'content_fingerprint' }
      };
      duplicates.push(duplicate);
      continue;
    }
    const stored = { ...event, event_id: event.event_id ?? `evt-${index.size + 1}` };
    index.set(key, stored);
    accepted.push(stored);
  }
  return { accepted, duplicates, index };
}

/** Human-readable summary used by tooltips, inspector headers and the event table. */
export function describeEvent(event) {
  const measurement = event.measurements?.[0];
  if (measurement) return `${measurement.name} ${measurement.value} ${measurement.unit}`;
  if (event.text) return event.text.slice(0, 120);
  return event.event_type.replace(/_/g, ' ');
}