// Connector catalogue for the Data Sources and Health view.
//
// Access classes come from the Urban Sentinel data-source review:
//   live_keyless - reachable without a credential (safe to enable, still rate limited)
//   keyed        - requires an account or API key; NOT configured in this repository
//   portal       - an official web portal rather than a machine-readable feed
//   internal     - we would have to generate or license the telemetry ourselves
//
// `credential` only ever reports configured / missing / invalid. Secrets are never stored or
// displayed here.

export const SOURCES = [
  {
    source_id: 'openmeteo', name: 'Open-Meteo Forecast', category: 'Weather',
    access: 'live_keyless', endpointClass: 'Public HTTPS API', connector: 'REST',
    mode: 'LIVE_API', health: 'HEALTHY', credential: 'NOT_REQUIRED',
    cadence: '10 min', freshnessSlaMinutes: 15, lastAttempt: '14:04:58', lastSuccess: '14:04:12',
    eventLagSeconds: 46, eventWatermark: '14:03:30', errorClass: null, eventCount: 184,
    dataClass: 'Precipitation, temperature, humidity, wind, observation time',
    units: 'mm/h, degC, %, km/h', reference: 'https://open-meteo.com',
    notes: 'Accumulation window is preserved; period rainfall is never treated as instantaneous intensity.'
  },
  {
    source_id: 'gdelt', name: 'GDELT Project News', category: 'News',
    access: 'live_keyless', endpointClass: 'Public HTTPS API', connector: 'REST',
    mode: 'LIVE_API', health: 'HEALTHY', credential: 'NOT_REQUIRED',
    cadence: '15 min', freshnessSlaMinutes: 30, lastAttempt: '14:03:00', lastSuccess: '14:02:41',
    eventLagSeconds: 190, eventWatermark: '14:01:00', errorClass: null, eventCount: 63,
    dataClass: 'Article link, headline, publication time, source domain, matched location',
    units: 'n/a', reference: 'https://www.gdeltproject.org',
    notes: 'News is a public claim, not verified fact. Article links may point to third-party publishers.'
  },
  {
    source_id: 'cwc_water_gauge', name: 'Water Gauge Network', category: 'Water',
    access: 'portal', endpointClass: 'Official dataset / CSV', connector: 'CSV',
    mode: 'HISTORICAL', health: 'HEALTHY', credential: 'MISSING',
    cadence: '15 min', freshnessSlaMinutes: 20, lastAttempt: '13:55:00', lastSuccess: '13:55:00',
    eventLagSeconds: 780, eventWatermark: '13:52:00', errorClass: null, eventCount: 312,
    dataClass: 'Water level, gauge station, threshold stage, reporting interval',
    units: 'm AMSL', reference: 'https://cwc.gov.in',
    notes: 'Datum and threshold provenance are recorded per reading. River forecast is not a substitute for drain-level telemetry.'
  },
  {
    source_id: 'tomtom_traffic', name: 'Road Network Telemetry', category: 'Traffic',
    access: 'keyed', endpointClass: 'Partner HTTPS API', connector: 'REST',
    mode: 'REPLAY', health: 'HEALTHY', credential: 'MISSING',
    cadence: '2 min', freshnessSlaMinutes: 10, lastAttempt: '14:01:00', lastSuccess: '14:01:00',
    eventLagSeconds: null, eventWatermark: '14:00:00', errorClass: null, eventCount: 240,
    dataClass: 'Current speed, free-flow speed, travel-time ratio, road segment',
    units: 'km/h, ratio', reference: 'https://www.tomtom.com',
    notes: 'Replay adapter. Coverage and quota for Mumbai are unverified. Speed ratio is only computed when the free-flow denominator exists.'
  },
  {
    source_id: 'citizen_reports', name: 'Citizen Report Form', category: 'Citizen',
    access: 'internal', endpointClass: 'Team-built intake', connector: 'MANUAL',
    mode: 'SYNTHETIC', health: 'HEALTHY', credential: 'NOT_REQUIRED',
    cadence: 'event driven', freshnessSlaMinutes: 60, lastAttempt: '14:02:20', lastSuccess: '14:02:20',
    eventLagSeconds: 300, eventWatermark: '13:52:00', errorClass: null, eventCount: 21,
    dataClass: 'Incident type, free text, reported time, submission time, optional coordinates',
    units: 'n/a', reference: null,
    notes: 'Unverified report by definition. Personal data is minimised and reporter identifiers are pseudonymised.'
  },
  {
    source_id: 'openaq', name: 'Air Quality Stations', category: 'Air quality',
    access: 'live_keyless', endpointClass: 'Public HTTPS API', connector: 'REST',
    mode: 'LIVE_API', health: 'DEGRADED', credential: 'NOT_REQUIRED',
    cadence: '30 min', freshnessSlaMinutes: 45, lastAttempt: '13:41:00', lastSuccess: '13:40:00',
    eventLagSeconds: 1200, eventWatermark: '13:20:00', errorClass: 'RATE_LIMITED_429', eventCount: 88,
    dataClass: 'PM2.5, PM10, AQI where supplied, station metadata, averaging period',
    units: 'ug/m3, AQI', reference: 'https://docs.openaq.org',
    notes: 'Provider is rate limiting this deployment. Coverage and station density vary by area.'
  },
  {
    source_id: 'osm_overpass', name: 'OpenStreetMap Extract', category: 'Infrastructure',
    access: 'live_keyless', endpointClass: 'Public HTTPS API', connector: 'REST',
    mode: 'HISTORICAL', health: 'HEALTHY', credential: 'NOT_REQUIRED',
    cadence: 'weekly', freshnessSlaMinutes: 20160, lastAttempt: '2026-10-05T02:10:00', lastSuccess: '2026-10-05T02:10:00',
    eventLagSeconds: null, eventWatermark: '2026-10-05T02:10:00', errorClass: null, eventCount: 0,
    dataClass: 'Road segments, drainage assets, transit stops, emergency facilities',
    units: 'n/a', reference: 'https://wiki.openstreetmap.org/wiki/Overpass_API',
    notes: 'ODbL. Map completeness varies; presence on the map does not prove an asset is operational.'
  },
  {
    source_id: 'bmc_advisories', name: 'Municipal Disaster Notices', category: 'City notices',
    access: 'portal', endpointClass: 'Official web portal', connector: 'MANUAL',
    mode: 'MANUAL', health: 'STALE', credential: 'NOT_REQUIRED',
    cadence: 'manual', freshnessSlaMinutes: 720, lastAttempt: '2026-10-11T18:30:00', lastSuccess: '2026-10-11T18:30:00',
    eventLagSeconds: null, eventWatermark: '2026-10-11T18:30:00', errorClass: 'MANUAL_REFRESH_OVERDUE', eventCount: 6,
    dataClass: 'Published monsoon updates, tide information, public advisories',
    units: 'n/a', reference: 'https://bmc.mumbai.gov.in',
    notes: 'Portal is not a structured feed. Last successful refresh is well outside its freshness target.'
  },
  {
    source_id: 'mseedcl_power', name: 'Distribution Feeder Status', category: 'Utilities',
    access: 'internal', endpointClass: 'Utility portal', connector: 'SYNTHETIC',
    mode: 'SYNTHETIC', health: 'OFFLINE', credential: 'MISSING',
    cadence: '5 min', freshnessSlaMinutes: 20, lastAttempt: '13:10:00', lastSuccess: '12:40:00',
    eventLagSeconds: null, eventWatermark: '12:40:00', errorClass: 'NO_AUTHORIZED_FEED', eventCount: 4,
    dataClass: 'Feeder outage notices, restoration status',
    units: 'n/a', reference: null,
    notes: 'No authorised real-time feed. Absence of data here is an observability gap, not evidence that power is stable.'
  },
  {
    source_id: 'imd_weather', name: 'Meteorological Observations', category: 'Weather',
    access: 'keyed', endpointClass: 'Official API reference', connector: 'REST',
    mode: 'REPLAY', health: 'DISABLED', credential: 'MISSING',
    cadence: '15 min', freshnessSlaMinutes: 30, lastAttempt: null, lastSuccess: null,
    eventLagSeconds: null, eventWatermark: null, errorClass: 'CREDENTIAL_MISSING', eventCount: 0,
    dataClass: 'Station nowcasts, district warnings, rainfall observations',
    units: 'mm, degC', reference: 'https://mausam.imd.gov.in',
    notes: 'Disabled until an account is provisioned. Replay fixtures stand in for this source.'
  },
  {
    source_id: 'newsdata_io', name: 'Headline Keyword Monitor', category: 'News',
    access: 'keyed', endpointClass: 'Partner HTTPS API', connector: 'REST',
    mode: 'REPLAY', health: 'MISCONFIGURED', credential: 'INVALID',
    cadence: '15 min', freshnessSlaMinutes: 30, lastAttempt: '13:30:00', lastSuccess: null,
    eventLagSeconds: null, eventWatermark: null, errorClass: 'CREDENTIAL_INVALID', eventCount: 0,
    dataClass: 'Headline, description, publication time, publisher, category',
    units: 'n/a', reference: 'https://newsdata.io',
    notes: 'Configured credential reference fails validation. GDELT is currently carrying news coverage instead.'
  },
  {
    source_id: 'satellite_imagery', name: 'Sentinel-1 Imagery', category: 'Satellite',
    access: 'live_keyless', endpointClass: 'Public HTTPS API', connector: 'REST',
    mode: 'HISTORICAL', health: 'HEALTHY', credential: 'NOT_REQUIRED',
    cadence: 'on demand', freshnessSlaMinutes: 43200, lastAttempt: '2026-10-11T04:00:00', lastSuccess: '2026-10-11T04:00:00',
    eventLagSeconds: null, eventWatermark: '2026-10-11T04:00:00', errorClass: null, eventCount: 2,
    dataClass: 'SAR acquisition windows, flood extent candidate polygons',
    units: 'n/a', reference: 'https://dataspace.copernicus.eu',
    notes: 'Cloud cover and revisit timing mean imagery is never real time. Used for retrospective extent, not live detection.'
  }
];

export const SOURCE_CATEGORIES = ['Weather', 'Air quality', 'Traffic', 'Water', 'Citizen', 'News', 'City notices', 'Infrastructure', 'Utilities', 'Satellite'];

export function sourceById(id) { return SOURCES.find(source => source.source_id === id); }

// Live keyless connectors are the only ones a deployment may enable without a credential.
export const ENABLEABLE_LIVE = SOURCES.filter(source => source.access === 'live_keyless').map(source => source.source_id);