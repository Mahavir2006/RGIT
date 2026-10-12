// Incident category taxonomy and the shared vocabulary every filter reads from.
//
// Categories are the primary axis of the command map. Each one owns an id, a label, a colour,
// an icon key and the event types that map into it, so a new source only has to declare which
// categories it can contribute to rather than inventing its own vocabulary.

export const CATEGORIES = [
  { id: 'flooding', label: 'Flooding & waterlogging', short: 'Flooding', colour: '#38bdf8', icon: 'droplets', order: 1 },
  { id: 'road_blockage', label: 'Road blockage & damage', short: 'Road', colour: '#f97316', icon: 'construction', order: 2 },
  { id: 'traffic', label: 'Traffic & accidents', short: 'Traffic', colour: '#f59e0b', icon: 'car', order: 3 },
  { id: 'protest', label: 'Protests & gatherings', short: 'Protest', colour: '#a855f7', icon: 'megaphone', order: 4 },
  { id: 'procession', label: 'Processions & crowd congestion', short: 'Crowd', colour: '#c084fc', icon: 'users', order: 5 },
  { id: 'emergency_access', label: 'Ambulance access & route risk', short: 'Access', colour: '#ef4444', icon: 'ambulance', order: 6 },
  { id: 'fire_hazard', label: 'Fire, explosion & hazardous', short: 'Fire', colour: '#fb7185', icon: 'flame', order: 7 },
  { id: 'transit', label: 'Rail, metro & transit disruption', short: 'Transit', colour: '#22d3ee', icon: 'train', order: 8 },
  { id: 'power', label: 'Power outage & signal failure', short: 'Power', colour: '#facc15', icon: 'zap', order: 9 },
  { id: 'drainage', label: 'Drainage, pump & sewage failure', short: 'Drainage', colour: '#2dd4bf', icon: 'waves', order: 10 },
  { id: 'weather', label: 'Extreme weather hazards', short: 'Weather', colour: '#60a5fa', icon: 'cloud-rain', order: 11 },
  { id: 'air_quality', label: 'Air pollution & environment', short: 'Air', colour: '#94a3b8', icon: 'wind', order: 12 },
  { id: 'infrastructure', label: 'Infrastructure & construction', short: 'Infra', colour: '#a3a3a3', icon: 'hard-hat', order: 13 },
  { id: 'reports', label: 'Citizen, news & official alerts', short: 'Reports', colour: '#e879f9', icon: 'newspaper', order: 14 },
  { id: 'sensor_health', label: 'Missing, offline or stale sensors', short: 'Sensors', colour: '#fbbf24', icon: 'sensor-off', order: 15 },
  { id: 'cascade', label: 'Predicted cascade & downstream risk', short: 'Cascade', colour: '#f43f5e', icon: 'git-branch', order: 16 }
];

export const CATEGORY_BY_ID = Object.fromEntries(CATEGORIES.map(category => [category.id, category]));

// Canonical event type -> category. Anything unmapped lands in `reports` rather than being
// dropped, so an unexpected provider payload still shows up somewhere visible.
export const EVENT_TYPE_CATEGORY = {
  waterlogging: 'flooding', flood_forecast: 'flooding', urban_flood: 'flooding',
  road_blocked_report: 'road_blockage', pothole_report: 'road_blockage', road_damage: 'road_blockage',
  traffic_congestion: 'traffic', accident_report: 'traffic',
  protest_report: 'protest', gathering_report: 'protest',
  procession_report: 'procession', crowd_density: 'procession',
  ambulance_delay: 'emergency_access', emergency_route_risk: 'emergency_access',
  fire_report: 'fire_hazard', explosion_report: 'fire_hazard', hazardous_leak: 'fire_hazard',
  rail_disruption: 'transit', metro_disruption: 'transit', transit_feed_delay: 'transit',
  power_outage_report: 'power', signal_failure: 'power',
  drainage_failure: 'drainage', pump_status: 'drainage', sewage_overflow: 'drainage',
  rainfall_high: 'weather', cyclone_warning: 'weather', heatwave: 'weather', weather_warning: 'weather',
  air_quality_poor: 'air_quality', air_quality_spike: 'air_quality',
  infrastructure_damage: 'infrastructure', construction_disruption: 'infrastructure',
  citizen_report: 'reports', news_report: 'reports', official_alert: 'reports',
  sensor_offline: 'sensor_health', sensor_stale: 'sensor_health', sensor_malfunction: 'sensor_health',
  cascade_predicted: 'cascade', downstream_risk: 'cascade',
  // Retained so the existing seeded scenario keeps mapping onto the new vocabulary.
  water_level_high: 'flooding', water_level_drop: 'drainage', tide_high: 'flooding'
};

export function categoryForEventType(eventType) {
  return EVENT_TYPE_CATEGORY[eventType] ?? 'reports';
}

// Incident type -> primary category.
//
// An incident's category comes from what the incident *is*, not from whichever contributing
// event happens to appear first in its evidence list. A waterlogging incident with a rainfall
// reading attached is still flooding, not weather; deriving it from evidence order would let a
// background signal relabel the incident.
export const INCIDENT_TYPE_CATEGORY = {
  waterlogging: 'flooding', flood: 'flooding', urban_flood: 'flooding',
  'traffic disruption': 'traffic', accident: 'traffic', congestion: 'traffic',
  'road blockage': 'road_blockage', pothole: 'road_blockage', 'road damage': 'road_blockage',
  'air quality': 'air_quality', pollution: 'air_quality',
  'power outage': 'power', 'signal failure': 'power',
  'fire hazard': 'fire_hazard', explosion: 'fire_hazard',
  'rail disruption': 'transit', 'metro disruption': 'transit',
  'protest': 'protest', gathering: 'protest', procession: 'procession',
  'drainage failure': 'drainage', 'pump failure': 'drainage', sewage: 'drainage',
  'infrastructure damage': 'infrastructure', construction: 'infrastructure',
  'extreme weather': 'weather', cyclone: 'weather', rainfall: 'weather',
  'sensor outage': 'sensor_health', 'sensor health': 'sensor_health',
  'emergency access': 'emergency_access', 'ambulance delay': 'emergency_access'
};

export function categoryForIncidentType(incidentType) {
  if (!incidentType) return null;
  const key = String(incidentType).toLowerCase().trim();
  return INCIDENT_TYPE_CATEGORY[key]
    // Unmapped types still resolve to something real rather than a null category.
    ?? INCIDENT_TYPE_CATEGORY[key.replace(/[^a-z ]/g, '').trim()]
    ?? null;
}

export const SEVERITIES = ['CRITICAL', 'HIGH', 'MODERATE', 'LOW'];

export const SEVERITY_COLOUR = {
  CRITICAL: '#ef4444', HIGH: '#f97316', MODERATE: '#f59e0b', LOW: '#4da3ff'
};

// Command-side statuses. Kept separate from the engineering lifecycle in the incident record,
// because an operator triages on "how dangerous is this right now", not on processing stage.
export const STATUSES = ['NEW', 'INVESTIGATING', 'CONFIRMED', 'ESCALATED', 'RESOLVED'];

export const STATUS_COLOUR = {
  NEW: '#a3a3a3', INVESTIGATING: '#60a5fa', CONFIRMED: '#f59e0b',
  ESCALATED: '#ef4444', RESOLVED: '#22c55e'
};

export const SOURCES = [
  { id: 'iot', label: 'IoT sensor', colour: '#2dd4bf' },
  { id: 'cv', label: 'CCTV / vision', colour: '#a855f7' },
  { id: 'weather_api', label: 'Weather API', colour: '#60a5fa' },
  { id: 'news', label: 'News', colour: '#e879f9' },
  { id: 'social', label: 'Social media', colour: '#c084fc' },
  { id: 'citizen', label: 'Citizen report', colour: '#fbbf24' },
  { id: 'official', label: 'Official feed', colour: '#22c55e' }
];

export const SOURCE_BY_ID = Object.fromEntries(SOURCES.map(source => [source.id, source]));

export const DATA_MODES = ['LIVE', 'HISTORICAL', 'SIMULATED'];

export const EVIDENCE_STATES = ['SUPPORTED', 'CONFLICTING', 'INSUFFICIENT', 'STALE'];

export const EVIDENCE_STATE_COLOUR = {
  SUPPORTED: '#2ee6b6', CONFLICTING: '#ff4d5e', INSUFFICIENT: '#ffb02e', STALE: '#8a6a2f'
};

export const TIME_WINDOWS = [
  { id: '15m', label: 'Last 15 min', minutes: 15 },
  { id: '1h', label: 'Last 1 hour', minutes: 60 },
  { id: '6h', label: 'Last 6 hours', minutes: 360 },
  { id: '24h', label: 'Last 24 hours', minutes: 1440 },
  { id: 'custom', label: 'Custom range', minutes: null }
];

// Road passability states for the emergency-access overlay. Each one carries the evidence
// class that justifies it, so a road is never labelled clear just because nothing reported it.
export const ACCESS_STATES = {
  OBSERVED_BLOCKED: { id: 'OBSERVED_BLOCKED', label: 'Observed blocked', colour: '#ef4444', evidence: 'direct observation or instrument reading' },
  REPORTED_BLOCKED: { id: 'REPORTED_BLOCKED', label: 'Reported blocked', colour: '#f97316', evidence: 'citizen, news or official report' },
  PREDICTED_RISK: { id: 'PREDICTED_RISK', label: 'Predicted risk', colour: '#f59e0b', evidence: 'modelled from an upstream dependency' },
  UNKNOWN: { id: 'UNKNOWN', label: 'Insufficient evidence', colour: '#8a6a2f', evidence: 'no usable observation in window' },
  VERIFIED_PASSABLE: { id: 'VERIFIED_PASSABLE', label: 'Verified passable', colour: '#22c55e', evidence: 'confirmed by an authorised check' }
};

export const DEFAULT_FILTERS = {
  categories: CATEGORIES.map(category => category.id),
  severities: [...SEVERITIES],
  statuses: [...STATUSES],
  sources: SOURCES.map(source => source.id),
  evidence: [...EVIDENCE_STATES],
  dataModes: [...DATA_MODES],
  timeWindow: '6h',
  customFrom: null,
  customTo: null,
  confidenceMin: 0,
  area: 'All areas',
  query: ''
};