// Seeded scenario: "Monsoon waterlogging - Andheri East".
//
// This dataset is what the UI renders. It is structured to satisfy the PRD QA matrix, so
// each fixture below is tagged with the acceptance scenario it exercises. Nothing here is
// live data: the whole scenario is labelled SYNTHETIC REPLAY in the interface.
//
// Every fixture is deterministic - same input, same ids, same associations - so screens can
// be compared between runs.

import { createStore } from './graph.js';
import { SOURCES } from './sources.js';
import { ASSETS, ASSET_DEPENDENCIES } from './geo.js';

const T = (hour, minute, second = 0) => `2026-10-12T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')}+05:30`;
const ANDHERI = { lat: 19.1197, lon: 72.8464, accuracy_m: 120, area_ref: 'AR-ANDHERI-EAST', precision: 'area' };
const POWAI = { lat: 19.1176, lon: 72.906, accuracy_m: 400, area_ref: 'AR-POWAI', precision: 'area' };
const DADAR = { lat: 19.0178, lon: 72.8478, accuracy_m: 800, area_ref: 'AR-DADAR', precision: 'area' };

let traceStep = 0;
// Processing trace is append-only per the event explorer contract.
function trace(sourceId, from, to, extra = []) {
  traceStep = 0;
  const stages = [
    ['received', 'ok', sourceId],
    ['normalised', 'ok', 'normalizer@2.1.0'],
    ['validated', 'ok', 'validator@2.1.0'],
    ['deduped', 'ok', 'idempotency@1.6.0'],
    ['anomaly_checked', 'ok', 'anomaly@1.9.0'],
    ['matched', 'ok', 'fusion@1.4.0']
  ];
  const built = [];
  for (const [step, result, processor] of stages) {
    built.push({
      step,
      result,
      duration_ms: 6 + ((traceStep++ * 7) % 23),
      reason: null,
      processor_version: processor,
      at: `${from} +${built.length * 3}s`
    });
  }
  return built.concat(extra);
}

function event(properties) {
  return {
    schema_version: '1.4.0',
    source_kind: 'synthetic',
    quality: { status: 'VALID', flags: [] },
    verification_status: 'unverified',
    measurements: [],
    duplicate_of: null,
    qa: [],
    ...properties
  };
}

export const EVENTS = [
  // --- Supporting chain for INC-104 -------------------------------------------------
  event({
    event_id: 'evt-0001', source_id: 'openmeteo', source_event_id: 'om-1757678400-01',
    event_type: 'rainfall_high', event_time: T(13, 30, 0), ingest_time: T(13, 30, 6),
    location: ANDHERI, summary: 'Precipitation rate crosses the 25 mm/h alert threshold.',
    measurements: [{ name: 'precipitation_rate', value: 28.4, unit: 'mm/h', period: 'instantaneous' }],
    quality: { status: 'VALID', flags: ['THRESHOLD_BREACH'] },
    payload_ref: 'om://forecast/hourly?lat=19.1197&lon=72.8464', qa: ['SCENARIO_NORMAL'],
    trace: trace('openmeteo', T(13, 30, 6), T(13, 30, 6))
  }),
  event({
    event_id: 'evt-0002', source_id: 'openmeteo', source_event_id: 'om-1757678400-01',
    event_type: 'rainfall_high', event_time: T(13, 30, 0), ingest_time: T(13, 34, 12),
    location: ANDHERI, summary: 'Same provider record delivered a second time.',
    duplicate_of: 'evt-0001', quality: { status: 'VALID', flags: ['DUPLICATE_DELIVERY'] },
    payload_ref: 'om://forecast/hourly?lat=19.1197&lon=72.8464', qa: ['SCENARIO_DUPLICATE'],
    trace: trace('openmeteo', T(13, 34, 12), T(13, 34, 12), [
      { step: 'deduped', result: 'duplicate', duration_ms: 4, reason: 'matched source_event_id om-1757678400-01', processor_version: 'idempotency@1.6.0', at: T(13, 34, 16) }
    ])
  }),
  event({
    event_id: 'evt-0003', source_id: 'openmeteo', source_event_id: 'om-1757678460-02',
    event_type: 'rainfall_high', event_time: T(13, 41, 0), ingest_time: T(13, 41, 7),
    location: ANDHERI, summary: 'Rainfall intensifies to 61.2 mm/h over Andheri East.',
    measurements: [{ name: 'precipitation_rate', value: 61.2, unit: 'mm/h', period: 'instantaneous' },
      { name: 'precipitation_1h', value: 38.7, unit: 'mm', period: 'accumulation_1h' }],
    quality: { status: 'VALID', flags: ['THRESHOLD_BREACH', 'RATE_OF_CHANGE'] },
    payload_ref: 'om://forecast/hourly?lat=19.1197&lon=72.8464&step=1', qa: ['SCENARIO_HEAVY_RAIN'],
    trace: trace('openmeteo', T(13, 41, 7), T(13, 41, 7))
  }),
  event({
    event_id: 'evt-0004', source_id: 'citizen_reports', source_event_id: 'cit-4471',
    event_type: 'citizen_report', event_time: T(13, 47, 0), ingest_time: T(13, 52, 0),
    location: { ...ANDHERI, accuracy_m: 400 }, summary: 'Reports waterlogging at the Andheri station underpass.',
    text: 'Water is knee deep near the Andheri station underpass, cars are taking another route.',
    verification_status: 'unverified', qa: ['SCENARIO_HEAVY_RAIN'],
    payload_ref: 'citizen://report/4471', trace: trace('citizen_reports', T(13, 52, 0), T(13, 52, 0))
  }),
  event({
    event_id: 'evt-0005', source_id: 'citizen_reports', source_event_id: 'cit-4488',
    event_type: 'road_blocked_report', event_time: T(14, 1, 0), ingest_time: T(14, 3, 0),
    location: { ...ANDHERI, accuracy_m: 600 }, summary: 'Second independent report of a blocked road segment.',
    text: 'Road blocked near S-12, cannot reach the metro station from the east side.',
    verification_status: 'unverified', qa: ['SCENARIO_HEAVY_RAIN'],
    payload_ref: 'citizen://report/4488', trace: trace('citizen_reports', T(14, 3, 0), T(14, 3, 0))
  }),
  event({
    event_id: 'evt-0006', source_id: 'cwc_water_gauge', source_event_id: 'wg04-133852',
    event_type: 'water_level_high', event_time: T(13, 52, 0), ingest_time: T(13, 55, 0),
    location: { lat: 19.1204, lon: 72.8469, accuracy_m: 30, area_ref: 'AR-ANDHERI-EAST', precision: 'point' },
    assetRef: 'AST-ANDH-GAUGE-04',
    summary: 'Gauge WG-04 crosses the 9.40 m alert stage.',
    measurements: [{ name: 'water_level', value: 9.62, unit: 'm AMSL', period: 'instantaneous' },
      { name: 'water_level_rate', value: 0.31, unit: 'm/h', period: 'instantaneous' }],
    quality: { status: 'VALID', flags: ['DOMAIN_THRESHOLD', 'RATE_OF_CHANGE'] },
    payload_ref: 'cwc://gauge/WG-04?date=2026-10-12', qa: ['SCENARIO_HEAVY_RAIN'],
    trace: trace('cwc_water_gauge', T(13, 55, 0), T(13, 55, 0))
  }),
  event({
    event_id: 'evt-0007', source_id: 'cwc_water_gauge', source_event_id: 'wg04-135800-corr',
    event_type: 'water_level_high', event_time: T(13, 58, 0), ingest_time: T(14, 6, 30),
    location: { lat: 19.1204, lon: 72.8469, accuracy_m: 30, area_ref: 'AR-ANDHERI-EAST', precision: 'point' },
    assetRef: 'AST-ANDH-GAUGE-04',
    summary: 'Late gauge correction arrives after the congestion event and is reconciled back into the incident.',
    measurements: [{ name: 'water_level', value: 9.81, unit: 'm AMSL', period: 'instantaneous' }],
    quality: { status: 'VALID', flags: ['OUT_OF_ORDER', 'DOMAIN_THRESHOLD'] },
    payload_ref: 'cwc://gauge/WG-04?date=2026-10-12&rev=2', qa: ['SCENARIO_LATE_EVENT'],
    trace: trace('cwc_water_gauge', T(14, 6, 30), T(14, 6, 30), [
      { step: 'matched', result: 'reconciled', duration_ms: 91, reason: 'late arrival; re-ranked candidates for INC-104 and INC-103', processor_version: 'fusion@1.4.0', at: T(14, 6, 42) }
    ])
  }),
  event({
    event_id: 'evt-0008', source_id: 'tomtom_traffic', source_event_id: 'tt-s12-1400',
    event_type: 'traffic_congestion', event_time: T(14, 0, 0), ingest_time: T(14, 1, 0),
    location: { lat: 19.1188, lon: 72.8452, accuracy_m: 50, area_ref: 'AR-ANDHERI-EAST', precision: 'point' },
    assetRef: 'AST-ANDH-ROAD-SEG-12',
    summary: 'Free-flow speed on S-12 drops to 22% of expected for this hour.',
    measurements: [{ name: 'current_speed', value: 7.4, unit: 'km/h', period: 'instantaneous' },
      { name: 'free_flow_speed', value: 33.6, unit: 'km/h', period: 'reference' },
      { name: 'speed_ratio', value: 0.22, unit: 'ratio', period: 'instantaneous' }],
    quality: { status: 'VALID', flags: ['ROBUST_BASELINE'] },
    payload_ref: 'replay://traffic/2026-10-12/s12', qa: ['SCENARIO_HEAVY_RAIN'],
    trace: trace('tomtom_traffic', T(14, 1, 0), T(14, 1, 0))
  }),
  event({
    event_id: 'evt-0009', source_id: 'gdelt', source_event_id: 'gdelt-9915',
    event_type: 'news_report', event_time: T(13, 49, 0), ingest_time: T(13, 51, 0),
    location: ANDHERI, summary: 'Local outlet reports residents wading through water in Andheri.',
    text: 'Residents in Andheri East wade through ankle-deep water as monsoon showers intensify.',
    verification_status: 'unverified', quality: { status: 'SUSPECT', flags: ['UNVERIFIED_CLAIM'] },
    payload_ref: 'https://example-news.in/andheri-waterlogging', qa: ['SCENARIO_HEAVY_RAIN'],
    trace: trace('gdelt', T(13, 51, 0), T(13, 51, 0))
  }),

  // --- Contradictory evidence --------------------------------------------------------
  event({
    event_id: 'evt-0010', source_id: 'cwc_water_gauge', source_event_id: 'wg09-134910',
    event_type: 'water_level_drop', event_time: T(13, 49, 0), ingest_time: T(13, 51, 30),
    location: { lat: 19.1132, lon: 72.8541, accuracy_m: 30, area_ref: 'AR-ANDHERI-EAST', precision: 'point' },
    assetRef: 'AST-ANDH-GAUGE-09',
    summary: 'Neighbouring Sahar gauge is falling while WG-04 rises.',
    measurements: [{ name: 'water_level', value: 8.94, unit: 'm AMSL', period: 'instantaneous' },
      { name: 'water_level_rate', value: -0.08, unit: 'm/h', period: 'instantaneous' }],
    quality: { status: 'VALID', flags: ['CROSS_SIGNAL_DISAGREEMENT'] },
    payload_ref: 'cwc://gauge/WG-09?date=2026-10-12', qa: ['SCENARIO_CONTRADICTION'],
    trace: trace('cwc_water_gauge', T(13, 51, 30), T(13, 51, 30))
  }),
  event({
    event_id: 'evt-0011', source_id: 'gdelt', source_event_id: 'gdelt-9942',
    event_type: 'news_report', event_time: T(13, 58, 0), ingest_time: T(14, 2, 0),
    location: ANDHERI, summary: 'Municipal bulletin reports no significant waterlogging so far.',
    text: 'BMC bulletin states no significant waterlogging has been reported across the city.',
    verification_status: 'unverified', quality: { status: 'SUSPECT', flags: ['UNVERIFIED_CLAIM', 'CONFLICTS_WITH_FIELD_REPORTS'] },
    payload_ref: 'https://example-muni.in/monsoon-bulletin-1210', qa: ['SCENARIO_CONTRADICTION'],
    trace: trace('gdelt', T(14, 2, 0), T(14, 2, 0))
  }),

  // --- Missing-signal intelligence ---------------------------------------------------
  event({
    event_id: 'evt-0012', source_id: 'cwc_water_gauge', source_event_id: 'wg07-heartbeat-1258',
    event_type: 'sensor_offline', event_time: T(12, 58, 0), ingest_time: T(12, 58, 4),
    location: { lat: 19.1261, lon: 72.8398, accuracy_m: 30, area_ref: 'AR-ANDHERI-EAST', precision: 'point' },
    assetRef: 'AST-ANDH-GAUGE-07',
    summary: 'Gauge WG-07 stops sending heartbeats; last valid reading is 67 minutes old.',
    quality: { status: 'STALE', flags: ['SENSOR_HEALTH', 'MISSING_SIGNAL'] },
    payload_ref: 'cwc://gauge/WG-07?heartbeat=missed', qa: ['SCENARIO_OUTAGE', 'SCENARIO_MISSING_SIGNAL'],
    trace: trace('cwc_water_gauge', T(12, 58, 4), T(12, 58, 4))
  }),
  event({
    event_id: 'evt-0013', source_id: 'mseedcl_power', source_event_id: 'msedcl-1310',
    event_type: 'sensor_offline', event_time: T(13, 10, 0), ingest_time: T(13, 10, 0),
    location: { lat: 19.1151, lon: 72.8402, accuracy_m: 50, area_ref: 'AR-ANDHERI-EAST', precision: 'point' },
    assetRef: 'AST-SUBSTATION-ANDH',
    summary: 'Distribution feeder feed is unavailable; pump P-02 operating state becomes unverifiable.',
    quality: { status: 'STALE', flags: ['MISSING_SIGNAL', 'NO_AUTHORIZED_FEED'] },
    payload_ref: 'internal://feed/mseedcl', qa: ['SCENARIO_MISSING_SIGNAL'],
    trace: trace('mseedcl_power', T(13, 10, 0), T(13, 10, 0))
  }),

  // --- Context that neither supports nor contradicts ----------------------------------
  event({
    event_id: 'evt-0014', source_id: 'cwc_water_gauge', source_event_id: 'pump-1358',
    event_type: 'pump_status', event_time: T(13, 58, 0), ingest_time: T(13, 58, 10),
    location: { lat: 19.1181, lon: 72.8491, accuracy_m: 40, area_ref: 'AR-ANDHERI-EAST', precision: 'point' },
    assetRef: 'AST-ANDH-PUMP-02',
    summary: 'Storm-water pump P-02 still reports RUNNING at nominal load.',
    measurements: [{ name: 'pump_load', value: 72, unit: '%', period: 'instantaneous' }],
    payload_ref: 'internal://sensor/pump-02', trace: trace('cwc_water_gauge', T(13, 58, 10), T(13, 58, 10))
  }),
  event({
    event_id: 'evt-0015', source_id: 'cwc_water_gauge', source_event_id: 'tide-1355',
    event_type: 'tide_high', event_time: T(13, 55, 0), ingest_time: T(13, 55, 20),
    location: { lat: 19.0234, lon: 72.8397, accuracy_m: 900, area_ref: 'AR-DADAR', precision: 'area' },
    summary: 'High tide window overlaps the rainfall period.',
    measurements: [{ name: 'tide_height', value: 4.62, unit: 'm', period: 'instantaneous' }],
    payload_ref: 'internal://tide/mumbai', trace: trace('cwc_water_gauge', T(13, 55, 20), T(13, 55, 20))
  }),
  event({
    event_id: 'evt-0016', source_id: 'openaq', source_event_id: 'aq-dadar-1320',
    event_type: 'air_quality_poor', event_time: T(13, 20, 0), ingest_time: T(13, 20, 30),
    location: DADAR,
    summary: 'PM2.5 at the Dadar station reaches 118 ug/m3, elevated against the daily median.',
    measurements: [{ name: 'pm25', value: 118, unit: 'ug/m3', period: '1h_average' }],
    quality: { status: 'SUSPECT', flags: ['PROVIDER_RATE_LIMITED'] },
    payload_ref: 'openaq://stations/dadar', trace: trace('openaq', T(13, 20, 30), T(13, 20, 30))
  }),

  // --- A genuinely separate incident that must not be merged ---------------------------
  event({
    event_id: 'evt-0017', source_id: 'tomtom_traffic', source_event_id: 'tt-pow-1344',
    event_type: 'traffic_congestion', event_time: T(13, 44, 0), ingest_time: T(13, 45, 0),
    location: POWAI, assetRef: 'AST-POW-ROAD-SEG-03',
    summary: 'Powai segment S-03 slows during school-run hours, with no water or rain signal nearby.',
    measurements: [{ name: 'speed_ratio', value: 0.48, unit: 'ratio', period: 'instantaneous' }],
    payload_ref: 'replay://traffic/2026-10-12/s03', qa: ['SCENARIO_UNRELATED_INCIDENTS'],
    trace: trace('tomtom_traffic', T(13, 45, 0), T(13, 45, 0))
  }),
  event({
    event_id: 'evt-0018', source_id: 'citizen_reports', source_event_id: 'cit-4402',
    event_type: 'citizen_report', event_time: T(13, 46, 0), ingest_time: T(13, 47, 0),
    location: POWAI, summary: 'Reports slow traffic on the Powai approach, no mention of water.',
    text: 'Heavy traffic on the Powai bridge approach, just the usual evening jam.',
    verification_status: 'unverified', qa: ['SCENARIO_UNRELATED_INCIDENTS'],
    payload_ref: 'citizen://report/4402', trace: trace('citizen_reports', T(13, 47, 0), T(13, 47, 0))
  }),

  // --- Invalid fixtures: quarantine or reject with a reason, never silent discard -------
  event({
    event_id: 'evt-0019', source_id: 'citizen_reports', source_event_id: 'cit-9999',
    event_type: 'citizen_report', event_time: T(14, 4, 0), ingest_time: T(14, 4, 2),
    location: { lat: 999, lon: 72.8464, accuracy_m: null, area_ref: null, precision: 'invalid' },
    summary: 'Coordinates outside the valid latitude range.',
    quality: { status: 'INVALID', flags: ['COORD_OUT_OF_RANGE'] },
    validation: { outcome: 'QUARANTINED', reasonCode: 'COORD_OUT_OF_RANGE', explanation: 'Latitude 999 is outside [-90, 90]. Record is held for inspection and can be replayed after the form is corrected.' },
    payload_ref: 'citizen://report/9999', qa: ['SCENARIO_INVALID'],
    trace: trace('citizen_reports', T(14, 4, 2), T(14, 4, 2), [
      { step: 'validated', result: 'quarantined', duration_ms: 3, reason: 'COORD_OUT_OF_RANGE', processor_version: 'validator@2.1.0', at: T(14, 4, 5) }
    ])
  }),
  event({
    event_id: 'evt-0020', source_id: 'tomtom_traffic', source_event_id: 'tt-bad-ts',
    event_type: 'traffic_congestion', event_time: 'not-a-timestamp', ingest_time: T(14, 4, 30),
    location: ANDHERI, summary: 'Event time could not be parsed.',
    quality: { status: 'INVALID', flags: ['TIMESTAMP_UNPARSEABLE'] },
    validation: { outcome: 'REJECTED', reasonCode: 'TIMESTAMP_UNPARSEABLE', explanation: 'event_time is not ISO-8601 and cannot be ordered against other signals.' },
    payload_ref: 'replay://traffic/2026-10-12/bad', qa: ['SCENARIO_INVALID'],
    trace: trace('tomtom_traffic', T(14, 4, 30), T(14, 4, 30), [
      { step: 'validated', result: 'rejected', duration_ms: 2, reason: 'TIMESTAMP_UNPARSEABLE', processor_version: 'validator@2.1.0', at: T(14, 4, 32) }
    ])
  }),
  event({
    event_id: 'evt-0021', source_id: 'citizen_reports', source_event_id: 'cit-10004',
    event_type: 'rainfall_high', event_time: T(14, 4, 45), ingest_time: T(14, 4, 50),
    location: ANDHERI, summary: 'Rainfall reported without a recognised unit.',
    measurements: [{ name: 'precipitation_rate', value: 44, unit: 'unknown', period: 'instantaneous' }],
    quality: { status: 'SUSPECT', flags: ['UNIT_UNRECOGNISED'] },
    validation: { outcome: 'QUARANTINED', reasonCode: 'UNIT_UNRECOGNISED', explanation: 'No conversion is defined for this unit, so the reading is held rather than guessed. Original value and unit are preserved.' },
    payload_ref: 'citizen://report/10004', qa: ['SCENARIO_INVALID'],
    trace: trace('citizen_reports', T(14, 4, 50), T(14, 4, 50), [
      { step: 'validated', result: 'quarantined', duration_ms: 5, reason: 'UNIT_UNRECOGNISED', processor_version: 'validator@2.1.0', at: T(14, 4, 55) }
    ])
  }),

  // --- Provider configuration failure --------------------------------------------------
  event({
    event_id: 'evt-0022', source_id: 'newsdata_io', source_event_id: 'nd-run-1330',
    event_type: 'news_report', event_time: T(13, 30, 0), ingest_time: T(13, 30, 1),
    location: null, summary: 'Ingestion attempt aborted: connector credential failed validation.',
    quality: { status: 'INVALID', flags: ['CONNECTOR_MISCONFIGURED'] },
    validation: { outcome: 'REJECTED', reasonCode: 'CREDENTIAL_INVALID', explanation: 'Connector secret reference did not validate. No events were produced by this run. GDELT continues to carry news coverage.' },
    payload_ref: null, qa: ['SCENARIO_CONNECTOR_FAILURE'],
    trace: trace('newsdata_io', T(13, 30, 1), T(13, 30, 1), [
      { step: 'received', result: 'aborted', duration_ms: 188, reason: 'CREDENTIAL_INVALID', processor_version: 'adapter/newsdata@1.0.0', at: T(13, 30, 1) }
    ])
  }),

  // --- Agent failure that must not block ingestion --------------------------------------
  event({
    event_id: 'evt-0023', source_id: 'openaq', source_event_id: 'aq-dadar-1345',
    event_type: 'air_quality_poor', event_time: T(13, 45, 0), ingest_time: T(13, 45, 12),
    location: DADAR, summary: 'Reading ingested normally even though the enrichment agent timed out.',
    measurements: [{ name: 'pm25', value: 104, unit: 'ug/m3', period: '1h_average' }],
    agent_run: { agent: 'signal_intelligence', status: 'TIMEOUT', retries: 2, fallback: 'deterministic_summary', note: 'Agent failure did not block ingestion; the event is shown without enrichment.' },
    payload_ref: 'openaq://stations/dadar?t=2', qa: ['SCENARIO_AGENT_FAILURE'],
    trace: trace('openaq', T(13, 45, 12), T(13, 45, 12))
  })
];

export const INCIDENTS = [
  {
    incident_id: 'INC-104', type: 'Waterlogging', title: 'Waterlogging on Andheri East road segment',
    status: 'INVESTIGATING', severity: 'HIGH',
    area_ref: 'AR-ANDHERI-EAST', area_name: 'Andheri East', lat: 19.1197, lon: 72.8464,
    location_precision: 'area', location_uncertainty_m: 600,
    created_at: T(13, 41, 0), first_seen_at: T(13, 41, 0), updated_at: T(14, 6, 30),
    owner: 'analyst.andheri', summary: 'Suspected waterlogging after intense rainfall, with a partially contradicted gauge picture downstream.',
    confidence: {
      validity: 0.93, membership: 0.82, cause: 0.64,
      calibration: 'UNCALIBRATED_HEURISTIC',
      rationale: 'Validity is high because the primary sources are direct instrument readings. Membership is high but not certain because one nearby gauge disagrees. Cause confidence is limited by a competing blocked-drain explanation and one unreachable gauge.'
    },
    expected_signals: ['rainfall_high', 'water_level_high', 'road_blocked_report', 'traffic_congestion', 'pump_status', 'power_outage_report'],
    impacted_radius_m: 900, time_horizon: '1-3 hours', impact_confidence: 0.58,
    tags: ['monsoon', 'andheri', 'underpass', 'emergency-access']
  },
  {
    incident_id: 'INC-103', type: 'Traffic disruption', title: 'Traffic disruption on Powai approach',
    status: 'OPEN', severity: 'MODERATE',
    area_ref: 'AR-POWAI', area_name: 'Powai', lat: 19.1176, lon: 72.906,
    location_precision: 'area', location_uncertainty_m: 800,
    created_at: T(13, 44, 0), first_seen_at: T(13, 44, 0), updated_at: T(13, 47, 0),
    owner: null, summary: 'Recurring congestion on the Powai approach with no accompanying water or rainfall signal.',
    confidence: {
      validity: 0.88, membership: 0.71, cause: 0.35,
      calibration: 'UNCALIBRATED_HEURISTIC',
      rationale: 'Two independent traffic sources agree, but there is no supporting hazard signal. Kept separate from INC-104 because the matcher must not force a merge on time proximity alone.'
    },
    expected_signals: ['traffic_congestion', 'road_blocked_report', 'rainfall_high'],
    impacted_radius_m: 500, time_horizon: '30-60 minutes', impact_confidence: 0.44,
    tags: ['powai', 'congestion']
  },
  {
    incident_id: 'INC-101', type: 'Air quality', title: 'Elevated particulate matter across Dadar',
    status: 'OPEN', severity: 'LOW',
    area_ref: 'AR-DADAR', area_name: 'Dadar', lat: 19.0178, lon: 72.8478,
    location_precision: 'area', location_uncertainty_m: 1500,
    created_at: T(13, 20, 0), first_seen_at: T(13, 20, 0), updated_at: T(13, 45, 12),
    owner: 'dataops.air', summary: 'PM2.5 above the station daily median while the provider is rate limiting this deployment.',
    confidence: {
      validity: 0.61, membership: 0.55, cause: 0.22,
      calibration: 'UNCALIBRATED_HEURISTIC',
      rationale: 'Single provider, currently rate limited, with no corroborating station inside the operating area.'
    },
    expected_signals: ['air_quality_poor'],
    impacted_radius_m: 2500, time_horizon: '6-12 hours', impact_confidence: 0.3,
    tags: ['air-quality', 'dadar']
  }
];

// Unconfirmed candidate cluster. Visually distinct from operator-reviewed incidents.
export const CANDIDATES = [
  {
    candidate_id: 'C-22', title: 'Possible second waterlogging cluster, Vile Parle',
    status: 'NEEDS_REVIEW', severity: 'MODERATE', event_count: 2,
    event_ids: [], formed_at: T(14, 1, 30), lat: 19.099, lon: 72.837,
    reason: 'Two unlinked citizen reports fall inside the spatial and temporal window but share no asset, so the matcher held them as a candidate instead of promoting them.',
    scores: []
  }
];

// EvidenceLink: relation, score contribution and the rationale that produced it.
export const EVIDENCE = [
  { link_id: 'EL-001', event_id: 'evt-0001', incident_id: 'INC-104', relation: 'SUPPORTS', score: 0.42, rationale: 'Rainfall above the alert threshold precedes the incident window by 11 minutes.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-002', event_id: 'evt-0003', incident_id: 'INC-104', relation: 'SUPPORTS', score: 0.86, rationale: 'Highest single contribution: 61.2 mm/h is a strong, direct rainfall signal 0.5 km from the incident centroid.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-003', event_id: 'evt-0004', incident_id: 'INC-104', relation: 'SUPPORTS', score: 0.68, rationale: 'Citizen report names the exact underpass asset, giving asset-level spatial agreement.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-004', event_id: 'evt-0005', incident_id: 'INC-104', relation: 'SUPPORTS', score: 0.51, rationale: 'Second independent reporter on the same segment; counted as a distinct source category, not a repeat.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-005', event_id: 'evt-0006', incident_id: 'INC-104', relation: 'SUPPORTS', score: 0.79, rationale: 'Gauge WG-04 is bound to drain DM-04, which the road segment depends on.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-006', event_id: 'evt-0007', incident_id: 'INC-104', relation: 'SUPPORTS', score: 0.74, rationale: 'Late gauge correction reconciles into the incident and raises the observed level to 9.81 m.', processor: 'fusion@1.4.1' },
  { link_id: 'EL-007', event_id: 'evt-0008', incident_id: 'INC-104', relation: 'SUPPORTS', score: 0.66, rationale: 'Congestion on S-12 is a downstream effect consistent with the reported flooding.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-008', event_id: 'evt-0009', incident_id: 'INC-104', relation: 'SUPPORTS', score: 0.29, rationale: 'News corroboration is weak and unverified; down-weighted because the publisher location precision is coarse.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-009', event_id: 'evt-0010', incident_id: 'INC-104', relation: 'CONTRADICTS', score: 0.44, rationale: 'Sahar gauge WG-09 is falling. Either the waterlogging is local or WG-04 is faulty; both remain open.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-010', event_id: 'evt-0011', incident_id: 'INC-104', relation: 'CONTRADICTS', score: 0.21, rationale: 'Municipal bulletin denies significant waterlogging citywide, which conflicts with two field reports.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-011', event_id: 'evt-0012', incident_id: 'INC-104', relation: 'CONTEXT_FOR', score: 0.12, rationale: 'Gauge WG-07 is silent, reducing observability in the corridor. Absence of data lowers certainty; it is not evidence of safety.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-012', event_id: 'evt-0013', incident_id: 'INC-104', relation: 'CONTEXT_FOR', score: 0.1, rationale: 'Feeder feed unavailable, so pump P-02 state cannot be verified.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-013', event_id: 'evt-0014', incident_id: 'INC-104', relation: 'CONTEXT_FOR', score: 0.15, rationale: 'Pump still running at 72% load, which argues against a total drainage failure.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-014', event_id: 'evt-0015', incident_id: 'INC-104', relation: 'CONTEXT_FOR', score: 0.08, rationale: 'High tide overlaps the window; a contributing factor rather than a trigger.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-015', event_id: 'evt-0017', incident_id: 'INC-103', relation: 'SUPPORTS', score: 0.62, rationale: 'Direct traffic measurement on Powai segment S-03.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-016', event_id: 'evt-0018', incident_id: 'INC-103', relation: 'SUPPORTS', score: 0.41, rationale: 'Citizen report independently describes the same slowdown with no hazard mention.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-017', event_id: 'evt-0016', incident_id: 'INC-101', relation: 'SUPPORTS', score: 0.57, rationale: 'Single station reading above its daily median.', processor: 'fusion@1.4.0' },
  { link_id: 'EL-018', event_id: 'evt-0023', incident_id: 'INC-101', relation: 'SUPPORTS', score: 0.38, rationale: 'Second reading from the same station. Same source category, so it does not count as independent corroboration.', processor: 'fusion@1.4.0' }
];

// Competing hypotheses. None is presented as proven cause.
export const HYPOTHESES = [
  {
    hypothesis_id: 'HYP-104-1', incident_id: 'INC-104', status: 'CANDIDATE', confidence: 0.64, version: 3,
    claim: 'Rainfall above design intensity exceeded the drainage capacity of the DM-04 corridor, producing waterlogging on segment S-12.',
    assumptions: ['DM-04 is the dominant drainage path for S-12 as configured', 'Rain gauge and city gauge are co-located enough to be comparable', 'No upstream reservoir release in this window'],
    unknowns: ['Gauge WG-07 is silent so the corridor is only partially observed', 'Feeder feed is unavailable so pump state is unverified'],
    evidence_for: ['evt-0003', 'evt-0006', 'evt-0007', 'evt-0001'], evidence_against: ['evt-0010'],
    updated_at: T(14, 6, 45), generated_by: 'causal_specialist@1.2.0'
  },
  {
    hypothesis_id: 'HYP-104-2', incident_id: 'INC-104', status: 'CANDIDATE', confidence: 0.48, version: 2,
    claim: 'A blocked drain DM-04 caused local ponding rather than a rainfall-capacity exceedance.',
    assumptions: ['Debris blockage is plausible in this catchment after recent debris load', 'Flooding is spatially confined to the underpass'],
    unknowns: ['No confirmed inspection record for DM-04', 'No maintenance history is available in this dataset'],
    evidence_for: ['evt-0009', 'evt-0005'], evidence_against: ['evt-0006', 'evt-0010', 'evt-0013'],
    updated_at: T(14, 5, 10), generated_by: 'causal_specialist@1.2.0'
  },
  {
    hypothesis_id: 'HYP-104-3', incident_id: 'INC-104', status: 'CANDIDATE', confidence: 0.22, version: 1,
    claim: 'High tide backflow raised the outfall level and contributed to the waterlogging.',
    assumptions: ['Outfall is tide-influenced at this location', 'Tide height materially affects inland head'],
    unknowns: ['No outfall level instrumentation in this dataset'],
    evidence_for: ['evt-0015'], evidence_against: ['evt-0003', 'evt-0010', 'evt-0014'],
    updated_at: T(14, 4, 30), generated_by: 'causal_specialist@1.2.0'
  },
  {
    hypothesis_id: 'HYP-104-4', incident_id: 'INC-104', status: 'INSUFFICIENT_EVIDENCE', confidence: 0, version: 1,
    claim: 'Instrument fault on gauge WG-04 produced an apparent level rise rather than real waterlogging.',
    assumptions: [],
    unknowns: ['WG-07 is offline so no cross-check exists', 'WG-04 has no redundant reading'],
    evidence_for: [], evidence_against: ['evt-0004', 'evt-0005', 'evt-0009'],
    updated_at: T(14, 6, 50), generated_by: 'causal_specialist@1.2.0',
    note: 'Returned as an explicit insufficient-evidence result rather than a fabricated explanation.'
  }
];

export const ANOMALIES = [
  { anomaly_id: 'AN-01', rule_id: 'R-RATE-01', family: 'Rate of change', severity: 'HIGH', event_id: 'evt-0006', source_id: 'cwc_water_gauge', asset_id: 'AST-ANDH-GAUGE-04', observed: 0.31, expected_range: '≤ 0.18 m/h', detected_at: T(13, 55, 4), status: 'OPEN', explanation: 'Water level rising at 0.31 m/h against a 0.18 m/h configured limit over a 30 minute window.' },
  { anomaly_id: 'AN-02', rule_id: 'R-BASE-01', family: 'Robust baseline', severity: 'HIGH', event_id: 'evt-0008', source_id: 'tomtom_traffic', asset_id: 'AST-ANDH-ROAD-SEG-12', observed: 0.22, expected_range: 'median 0.86, MAD 0.09', detected_at: T(14, 1, 2), status: 'OPEN', explanation: 'Robust z = (0.22 - 0.86) / (1.4826 x 0.09) = -4.79 against a 14-day window of 288 samples.' },
  { anomaly_id: 'AN-03', rule_id: 'R-HEALTH-01', family: 'Sensor health', severity: 'MODERATE', event_id: 'evt-0012', source_id: 'cwc_water_gauge', asset_id: 'AST-ANDH-GAUGE-07', observed: 67, expected_range: 'heartbeat ≤ 20 min', detected_at: T(13, 18, 0), status: 'OPEN', explanation: 'No heartbeat from WG-07 for 67 minutes. Last valid reading is 12:51. Check field power and the gateway link.' },
  { anomaly_id: 'AN-04', rule_id: 'R-XSIGNAL-01', family: 'Cross-signal inconsistency', severity: 'HIGH', event_id: 'evt-0010', source_id: 'cwc_water_gauge', asset_id: 'AST-ANDH-GAUGE-09', observed: 0.81, expected_range: '≤ 0.35 m divergence', detected_at: T(13, 51, 34), status: 'OPEN', explanation: 'WG-04 rising and WG-09 falling diverge by 0.81 m across 1.4 km inside a 10 minute window.' },
  { anomaly_id: 'AN-05', rule_id: 'R-DOMAIN-01', family: 'Domain threshold', severity: 'MODERATE', event_id: 'evt-0003', source_id: 'openmeteo', asset_id: null, observed: 61.2, expected_range: '≤ 25 mm/h', detected_at: T(13, 41, 8), status: 'ACKNOWLEDGED', explanation: 'Precipitation rate crosses the configured alert threshold for the Andheri East grid cell.' },
  { anomaly_id: 'AN-06', rule_id: 'R-HEALTH-01', family: 'Sensor health', severity: 'LOW', event_id: 'evt-0022', source_id: 'newsdata_io', asset_id: null, observed: 1, expected_range: '0 failures', detected_at: T(13, 30, 3), status: 'OPEN', explanation: 'Connector run aborted on credential validation failure. Unrelated connectors continued.' },
  { anomaly_id: 'AN-07', rule_id: 'R-DOMAIN-01', family: 'Domain threshold', severity: 'INFO', event_id: 'evt-0019', source_id: 'citizen_reports', asset_id: null, observed: 1, expected_range: 'latitude within [-90, 90]', detected_at: T(14, 4, 5), status: 'QUARANTINED', explanation: 'Record quarantined with reason COORD_OUT_OF_RANGE and held for inspection.' }
];

export const ACTIONS = [
  { action_id: 'ACT-3001', incident_id: 'INC-104', type: 'Inspect drainage', priority: 'P1', status: 'NEEDS_REVIEW', owner: 'team.a', high_impact: true, created_at: T(13, 56, 0), due_at: T(15, 0, 0), updated_at: T(14, 2, 0), rationale: 'Two citizen reports and a gauge threshold breach all point at the DM-04 corridor.', expected_benefit: 'Confirms or eliminates the blocked-drain hypothesis within the current horizon.', uncertainty: 'No inspection record exists for DM-04 in this dataset.', dependencies: ['AST-ANDH-DRAIN-04'], risks: ['Crew exposure to standing water', 'Inspection alone does not restore capacity'], evidence_refs: ['evt-0004', 'evt-0005', 'evt-0006'], requires_approval: true, approved_by: null, similar_to: [] },
  { action_id: 'ACT-3002', incident_id: 'INC-104', type: 'Consider traffic diversion', priority: 'P1', status: 'PROPOSED', owner: null, high_impact: true, created_at: T(14, 1, 30), due_at: T(15, 30, 0), updated_at: T(14, 1, 30), rationale: 'Speed on S-12 is at 22% of free flow and the underpass approach is blocked.', expected_benefit: 'Restores emergency access to Andheri General Hospital via segment S-13.', uncertainty: 'Spillover toward Powai S-03 is an assumption, not an observation.', dependencies: ['AST-ANDH-ROAD-SEG-13'], risks: ['Shifts congestion to Powai', 'Diverted vehicles may not reach the hospital approach'], evidence_refs: ['evt-0008', 'evt-0005'], requires_approval: true, approved_by: null, similar_to: [] },
  { action_id: 'ACT-3003', incident_id: 'INC-104', type: 'Verify gauge WG-04 against WG-09', priority: 'P2', status: 'IN_PROGRESS', owner: 'dataops.gauges', high_impact: false, created_at: T(13, 53, 0), due_at: T(16, 0, 0), updated_at: T(14, 3, 40), rationale: 'Cross-signal divergence is unresolved and WG-07 is offline, so there is no third reference.', expected_benefit: 'Resolves whether the level rise is real or an instrument artefact.', uncertainty: 'Field visit may take longer than the incident horizon.', dependencies: ['AST-ANDH-GAUGE-04', 'AST-ANDH-GAUGE-09'], risks: ['Delays the main response if treated as blocking'], evidence_refs: ['evt-0006', 'evt-0010', 'evt-0012'], requires_approval: false, approved_by: null, similar_to: [] },
  { action_id: 'ACT-3004', incident_id: 'INC-104', type: 'Restore gauge WG-07 heartbeat', priority: 'P2', status: 'PROPOSED', owner: null, high_impact: false, created_at: T(13, 20, 0), due_at: null, updated_at: T(13, 20, 0), rationale: 'A silent gauge removes the cross-check that would discriminate between the competing hypotheses.', expected_benefit: 'Restores partial observability of the corridor.', uncertainty: 'Cause of the outage is unknown; may need physical work.', dependencies: ['AST-ANDH-GAUGE-07'], risks: [], evidence_refs: ['evt-0012'], requires_approval: false, approved_by: null, similar_to: [] },
  { action_id: 'ACT-3005', incident_id: 'INC-103', type: 'Verify traffic feed confidence', priority: 'P3', status: 'OPEN', owner: 'dataops.traffic', high_impact: false, created_at: T(13, 50, 0), due_at: null, updated_at: T(13, 50, 0), rationale: 'The Powai slowdown has only two signals and one is a citizen report.', expected_benefit: 'Confirms whether this is normal recurring congestion or a new disruption.', uncertainty: 'Replay adapter, so current road state is not actually observed.', dependencies: ['AST-POW-ROAD-SEG-03'], risks: [], evidence_refs: ['evt-0017', 'evt-0018'], requires_approval: false, approved_by: null, similar_to: [] },
  { action_id: 'ACT-3006', incident_id: 'INC-101', type: 'Request OpenAQ quota increase or backup station', priority: 'P3', status: 'PROPOSED', owner: null, high_impact: false, created_at: T(13, 46, 0), due_at: null, updated_at: T(13, 46, 0), rationale: 'Provider is returning 429 and a second reading came from the same station.', expected_benefit: 'Restores an independent air-quality channel inside the operating area.', uncertainty: 'No backup station is currently mapped in this dataset.', dependencies: [], risks: [], evidence_refs: ['evt-0016', 'evt-0023'], requires_approval: false, approved_by: null, similar_to: [] }
];

// Audit records are immutable through the application.
export const AUDIT = [
  { id: 'AU-9001', at: T(14, 6, 50), actor: 'system', actor_role: 'SYSTEM', object_type: 'Hypothesis', object_id: 'HYP-104-4', action: 'CREATED', summary: 'Emitted explicit insufficient-evidence hypothesis for instrument fault.', reason: 'No cross-check available while WG-07 is offline.', request_id: 'req-7741' },
  { id: 'AU-9002', at: T(14, 6, 42), actor: 'system', actor_role: 'SYSTEM', object_type: 'Incident', object_id: 'INC-104', action: 'EVIDENCE_RECONCILED', summary: 'Late event evt-0007 reconciled into the incident and re-ranked candidates.', reason: 'Out-of-order arrival by 6 minutes 30 seconds.', request_id: 'req-7738' },
  { id: 'AU-9003', at: T(14, 6, 31), actor: 'ingest@openmeteo', actor_role: 'SYSTEM', object_type: 'Event', object_id: 'evt-0007', action: 'INGESTED', summary: 'Canonical event created from the gauge correction feed.', reason: null, request_id: 'req-7736' },
  { id: 'AU-9004', at: T(14, 2, 5), actor: 'supervisor.mehta', actor_role: 'SUPERVISOR', object_type: 'Action', object_id: 'ACT-3001', action: 'REVIEW_REQUESTED', summary: 'Requested supervisor review for a high-impact drainage inspection.', reason: 'Inspection is high impact and touches a live asset.', request_id: 'req-7702' },
  { id: 'AU-9005', at: T(14, 4, 5), actor: 'ingest@citizen_reports', actor_role: 'SYSTEM', object_type: 'Event', object_id: 'evt-0019', action: 'QUARANTINED', summary: 'Record quarantined for out-of-range latitude.', reason: 'COORD_OUT_OF_RANGE', request_id: 'req-7711' },
  { id: 'AU-9006', at: T(13, 58, 12), actor: 'analyst.andheri', actor_role: 'ANALYST', object_type: 'Incident', object_id: 'INC-104', action: 'STATUS_CHANGED', summary: 'Status moved from ACKNOWLEDGED to INVESTIGATING.', reason: 'Field team dispatched for drainage inspection.', request_id: 'req-7688' },
  { id: 'AU-9007', at: T(13, 55, 2), actor: 'analyst.andheri', actor_role: 'ANALYST', object_type: 'Incident', object_id: 'INC-104', action: 'ANNOTATION_ADDED', summary: 'Annotated that the citizen report names the exact underpass asset.', reason: null, request_id: 'req-7680' },
  { id: 'AU-9008', at: T(13, 47, 1), actor: 'analyst.andheri', actor_role: 'ANALYST', object_type: 'Incident', object_id: 'INC-103', action: 'SEPARATION_CONFIRMED', summary: 'Confirmed Powai cluster stays separate from the Andheri candidate.', reason: 'No shared asset and no hazard signal within the spatial window.', request_id: 'req-7655' },
  { id: 'AU-9009', at: T(13, 34, 16), actor: 'dedupe@ingest', actor_role: 'SYSTEM', object_type: 'Event', object_id: 'evt-0002', action: 'DUPLICATE_RECEIPT', summary: 'Second delivery linked to canonical evt-0001. Corroboration count unchanged.', reason: 'matched source_event_id', request_id: 'req-7602' },
  { id: 'AU-9010', at: T(13, 30, 3), actor: 'ingest@newsdata_io', actor_role: 'SYSTEM', object_type: 'Source', object_id: 'newsdata_io', action: 'RUN_ABORTED', summary: 'Connector run aborted; unrelated connectors continued.', reason: 'CREDENTIAL_INVALID', request_id: 'req-7590' }
];

// Cascade chain and intervention comparison for the what-if view.
export const CASCADE_SCENARIOS = [
  {
    id: 'SC-HEAVY-RAIN', name: 'Heavy rainfall (observed)', horizon: '0-6h', status: 'REFERENCE',
    description: 'Observed rainfall at 61.2 mm/h continues at the same intensity for the next three hours.',
    baseline_risk: 'HIGH', confidence: 0.61,
    assumptions: ['DM-04 capacity estimate is 12 mm/h before surcharge', 'No upstream reservoir release', 'Rainfall is spatially uniform across the 1.5 km grid cell'],
    unknowns: ['Gauge WG-07 offline removes a corridor observation point', 'Feeder feed unavailable so pump state is unverified', 'No surveyed inflow catchment for S-12'],
    nodes: [
      { id: 'N1', label: 'Rainfall intensity', value: '61.2 mm/h', level: 3 },
      { id: 'N2', label: 'Drainage capacity exceeded', value: 'surcharge', level: 2 },
      { id: 'N3', label: 'Waterlogging on S-12', value: '0.41 m depth', level: 1 },
      { id: 'N4', label: 'Reduced road capacity', value: '22% of free flow', level: 1 },
      { id: 'N5', label: 'Congestion increases', value: 'speed ratio 0.22', level: 2 },
      { id: 'N6', label: 'Emergency access delay', value: '+9 min to hospital', level: 3 }
    ],
    edges: [
      { from: 'N1', to: 'N2', type: 'AFFECTS', semantics: 'CONFIGURED' },
      { from: 'N2', to: 'N3', type: 'AFFECTS', semantics: 'CONFIGURED' },
      { from: 'N3', to: 'N4', type: 'AFFECTS', semantics: 'OBSERVED' },
      { from: 'N4', to: 'N5', type: 'AFFECTS', semantics: 'OBSERVED' },
      { from: 'N5', to: 'N6', type: 'AFFECTS', semantics: 'HYPOTHESIS' }
    ]
  },
  {
    id: 'SC-INTERMITTENT', name: 'Intermittent showers', horizon: '0-6h', status: 'COMPARABLE',
    description: 'Rainfall drops to 18 mm/h for two hours, then returns to 30 mm/h.',
    baseline_risk: 'MODERATE', confidence: 0.44,
    assumptions: ['The drainage network can recover between bursts', 'No change to catchment inputs'],
    unknowns: ['Recovery time for DM-04 is not characterised in this dataset'],
    nodes: [
      { id: 'N1', label: 'Rainfall intensity', value: '18 → 30 mm/h', level: 2 },
      { id: 'N2', label: 'Drainage capacity exceeded', value: 'partial', level: 1 },
      { id: 'N3', label: 'Waterlogging on S-12', value: '0.19 m depth', level: 1 },
      { id: 'N4', label: 'Reduced road capacity', value: '54% of free flow', level: 1 },
      { id: 'N5', label: 'Congestion increases', value: 'speed ratio 0.54', level: 1 },
      { id: 'N6', label: 'Emergency access delay', value: '+4 min to hospital', level: 2 }
    ],
    edges: [
      { from: 'N1', to: 'N2', type: 'AFFECTS', semantics: 'CONFIGURED' },
      { from: 'N2', to: 'N3', type: 'AFFECTS', semantics: 'HYPOTHESIS' },
      { from: 'N3', to: 'N4', type: 'AFFECTS', semantics: 'HYPOTHESIS' },
      { from: 'N4', to: 'N5', type: 'AFFECTS', semantics: 'HYPOTHESIS' },
      { from: 'N5', to: 'N6', type: 'AFFECTS', semantics: 'HYPOTHESIS' }
    ]
  },
  {
    id: 'SC-TIDE-PEAK', name: 'High tide peak', horizon: '0-6h', status: 'COMPARABLE',
    description: 'Tide reaches the high-tide window while rainfall continues unchanged.',
    baseline_risk: 'HIGH', confidence: 0.38,
    assumptions: ['Outfall is tide-influenced', 'No outfall level instrumentation available'],
    unknowns: ['Outfall head above datum is not measured anywhere in this dataset'],
    nodes: [
      { id: 'N1', label: 'Rainfall intensity', value: '61.2 mm/h', level: 3 },
      { id: 'N2', label: 'Drainage capacity exceeded', value: 'surcharge', level: 2 },
      { id: 'N3', label: 'Outfall back-pressure', value: '4.62 m tide', level: 2 },
      { id: 'N4', label: 'Waterlogging on S-12', value: '0.52 m depth', level: 3 },
      { id: 'N5', label: 'Reduced road capacity', value: 'closed', level: 3 },
      { id: 'N6', label: 'Emergency access delay', value: '+18 min to hospital', level: 3 }
    ],
    edges: [
      { from: 'N1', to: 'N2', type: 'AFFECTS', semantics: 'CONFIGURED' },
      { from: 'N2', to: 'N3', type: 'AFFECTS', semantics: 'HYPOTHESIS' },
      { from: 'N3', to: 'N4', type: 'AFFECTS', semantics: 'HYPOTHESIS' },
      { from: 'N4', to: 'N5', type: 'AFFECTS', semantics: 'HYPOTHESIS' },
      { from: 'N5', to: 'N6', type: 'AFFECTS', semantics: 'HYPOTHESIS' }
    ]
  }
];

export const INTERVENTIONS = [
  { id: 'IV-BASELINE', name: 'Baseline (no intervention)', kind: 'BASELINE', risk_band: 'HIGH', risk_delta: null, resource_cost: 'none', side_effects: 'Emergency access to Andheri General Hospital degrades to roughly 9 minutes over normal.', assumptions: ['Current state persists for the horizon'], approval: 'n/a' },
  { id: 'IV-CLEAR-DRAIN', name: 'Clear drain DM-04', kind: 'PHYSICAL', risk_band: 'MODERATE', risk_delta: -0.28, resource_cost: '2 crews, ~90 min', side_effects: 'Partial closure of S-13 during works; no effect on Powai spillover.', assumptions: ['Blockage is removable within one crew cycle', 'Post-clear capacity returns to the 12 mm/h design figure'], approval: 'Supervisor approval required', evidence_refs: ['evt-0006', 'evt-0010'] },
  { id: 'IV-DIVERSION', name: 'Traffic diversion via S-13', kind: 'TRAFFIC', risk_band: 'MODERATE', risk_delta: -0.19, resource_cost: '1 supervisor, 1 hour', side_effects: 'Displaces congestion toward Powai segment S-03.', assumptions: ['S-13 has remaining capacity', 'Spillover assumption is unvalidated'], approval: 'Supervisor approval required', evidence_refs: ['evt-0008', 'evt-0005'] },
  { id: 'IV-INSPECT', name: 'Inspect site and gauge', kind: 'INVESTIGATIVE', risk_band: 'HIGH', risk_delta: -0.04, resource_cost: '1 team, 45 min', side_effects: 'No direct risk reduction; improves observability so later decisions rest on data.', assumptions: ['Inspection resolves the blocked-drain question'], approval: 'Supervisor approval required', evidence_refs: ['evt-0010', 'evt-0012'] }
];

// Candidate-match score breakdown. Never expose the composite without its components.
export const CANDIDATE_SCORES = [
  { event_id: 'evt-0003', incident_id: 'INC-104', rule: 'S=0.28T+0.22G+0.14K+0.24A+0.12Q', version: 'fusion@1.4.0', components: { time: 0.95, space: 0.9, type: 1, asset: 0.3, quality: 0.88 }, score: 0.86 },
  { event_id: 'evt-0006', incident_id: 'INC-104', rule: 'S=0.28T+0.22G+0.14K+0.24A+0.12Q', version: 'fusion@1.4.0', components: { time: 0.9, space: 0.98, type: 1, asset: 0.86, quality: 0.94 }, score: 0.79 },
  { event_id: 'evt-0004', incident_id: 'INC-104', rule: 'S=0.28T+0.22G+0.14K+0.24A+0.12Q', version: 'fusion@1.4.0', components: { time: 0.82, space: 0.7, type: 0.9, asset: 0.62, quality: 0.52 }, score: 0.68 },
  { event_id: 'evt-0010', incident_id: 'INC-104', rule: 'S=0.28T+0.22G+0.14K+0.24A+0.12Q', version: 'fusion@1.4.0', components: { time: 0.88, space: 0.81, type: 0.95, asset: 0.4, quality: 0.9 }, score: 0.44 },
  { event_id: 'evt-0007', incident_id: 'INC-103', rule: 'S=0.28T+0.22G+0.14K+0.24A+0.12Q', version: 'fusion@1.4.1', components: { time: 0.2, space: 0.05, type: 0.5, asset: 0, quality: 0.94 }, score: 0.07 }
];

export function buildStore() {
  const store = createStore();
  for (const asset of ASSETS) store.upsertNode('Asset', asset);
  for (const incident of INCIDENTS) store.upsertNode('Incident', incident);
  for (const event of EVENTS) store.upsertNode('Event', event);
  for (const hypothesis of HYPOTHESES) store.upsertNode('Hypothesis', hypothesis);
  for (const action of ACTIONS) store.upsertNode('Action', action);

  for (const link of EVIDENCE) {
    store.relationship('Event', link.event_id, link.relation, 'Incident', link.incident_id, { ...link, from_label: 'Event', to_label: 'Incident' });
  }
  for (const hypothesis of HYPOTHESES) {
    for (const id of hypothesis.evidence_for) {
      store.relationship('Hypothesis', hypothesis.hypothesis_id, 'SUPPORTED_BY', 'Event', id, {
        strength: 1, provenance: 'derived', rationale: hypothesis.claim.slice(0, 90), hypothesis_id: hypothesis.hypothesis_id, event_id: id
      });
    }
    for (const id of hypothesis.evidence_against) {
      store.relationship('Hypothesis', hypothesis.hypothesis_id, 'CHALLENGED_BY', 'Event', id, {
        strength: 1, provenance: 'derived', rationale: 'Counter-evidence recorded against this hypothesis.', hypothesis_id: hypothesis.hypothesis_id, event_id: id
      });
    }
  }
  for (const edge of ASSET_DEPENDENCIES) {
    store.relationship('Asset', edge.from, edge.type, 'Asset', edge.to, { ...edge, asset_id: edge.from, target_asset_id: edge.to });
  }
  for (const incident of INCIDENTS) {
    const seen = new Set();
    for (const evidence of EVIDENCE.filter(link => link.incident_id === incident.incident_id && link.relation === 'SUPPORTS')) {
      const evt = EVENTS.find(item => item.event_id === evidence.event_id);
      const assetId = evt?.assetRef;
      if (!assetId || seen.has(assetId)) continue;
      seen.add(assetId);
      store.relationship('Incident', incident.incident_id, 'AFFECTS', 'Asset', assetId, {
        incident_id: incident.incident_id, asset_id: assetId,
        impact_type: evt.event_type, confidence: incident.confidence.impact_confidence,
        time_horizon: incident.time_horizon, relationship_type: 'AFFECTS', semantics: 'HYPOTHESIS'
      });
    }
  }
  return store;
}

export const SCENARIO = {
  id: 'SCEN-MONSOON-ANDHERI-2026-10-12',
  name: 'Monsoon waterlogging · Andheri East',
  mode: 'SYNTHETIC REPLAY',
  clock: '2026-10-12T14:05:00+05:30',
  windowStart: '2026-10-12T13:30:00+05:30',
  windowEnd: '2026-10-12T14:06:50+05:30',
  datasetVersion: '2026-10-12.1',
  connectorVersion: '1.4.1',
  disclaimer: 'Synthetic replay dataset. No live provider data is represented on any screen.'
};

export { SOURCES };