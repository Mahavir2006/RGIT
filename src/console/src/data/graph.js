// In-memory property graph with the same labels, keys and relationship types as the Neo4j
// model. Every traversal helper below maps onto a specific Cypher statement so the seeded
// demo data can be swapped for a live driver without touching a single view component.
//
//   (:Event)-[:SUPPORTS|CONTRADICTS|CONTEXT_FOR]->(:Incident)
//   (:Hypothesis)-[:SUPPORTED_BY|CHALLENGED_BY]->(:Event)
//   (:Asset)-[:DEPENDS_ON|AFFECTS|CONNECTED_TO]->(:Asset)
//   (:Incident)-[:AFFECTS]->(:Asset)

export const LABELS = ['Event', 'Incident', 'Asset', 'Hypothesis', 'Action'];

export const EVENT_TYPES = [
  'rainfall_high', 'water_level_high', 'road_blocked_report', 'traffic_congestion',
  'sensor_offline', 'air_quality_poor', 'citizen_report', 'news_report', 'pump_status',
  'tide_high', 'power_outage_report', 'water_level_drop'
];

export const EVENT_RELATIONS = ['SUPPORTS', 'CONTRADICTS', 'CONTEXT_FOR'];
export const HYPOTHESIS_RELATIONS = ['SUPPORTED_BY', 'CHALLENGED_BY'];
export const ASSET_RELATIONS = ['DEPENDS_ON', 'AFFECTS', 'CONNECTED_TO'];

// Relationship semantics must never imply proven causality from co-occurrence alone.
export const RELATION_SEMANTICS = {
  CONFIGURED: 'Configured dependency',
  OBSERVED: 'Observed association',
  HYPOTHESIS: 'Inferred hypothesis',
  VALIDATED: 'Validated relationship'
};

// Heuristic ranking, not a calibrated probability. The UI must label it as such.
export const CONFIDENCE_DIMENSIONS = [
  { key: 'validity', label: 'Event validity', hint: 'Is this signal itself credible?' },
  { key: 'membership', label: 'Incident membership', hint: 'Does this signal belong to this incident?' },
  { key: 'cause', label: 'Cause hypothesis', hint: 'Does this signal support this explanation?' }
];

export const SEVERITIES = ['CRITICAL', 'HIGH', 'MODERATE', 'LOW', 'INFO'];

export const INCIDENT_STATUSES = [
  'CANDIDATE', 'OPEN', 'ACKNOWLEDGED', 'INVESTIGATING', 'MITIGATING', 'RESOLVED', 'CLOSED'
];

// The allowed transition graph is defined in code so the UI cannot invent a legal jump.
export const STATUS_TRANSITIONS = {
  CANDIDATE: ['OPEN', 'CLOSED'],
  OPEN: ['ACKNOWLEDGED', 'INVESTIGATING', 'CLOSED'],
  ACKNOWLEDGED: ['INVESTIGATING', 'CLOSED'],
  INVESTIGATING: ['MITIGATING', 'ACKNOWLEDGED', 'CLOSED'],
  MITIGATING: ['RESOLVED', 'INVESTIGATING'],
  RESOLVED: ['CLOSED', 'INVESTIGATING'],
  CLOSED: ['OPEN']
};

export const ACTION_STATUSES = [
  'PROPOSED', 'NEEDS_REVIEW', 'APPROVED', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'REJECTED', 'CANCELLED'
];

export const ACTION_TRANSITIONS = {
  PROPOSED: ['NEEDS_REVIEW', 'REJECTED', 'CANCELLED'],
  NEEDS_REVIEW: ['APPROVED', 'REJECTED', 'CANCELLED'],
  APPROVED: ['ASSIGNED', 'CANCELLED'],
  ASSIGNED: ['IN_PROGRESS', 'CANCELLED'],
  IN_PROGRESS: ['COMPLETED', 'CANCELLED'],
  COMPLETED: [],
  REJECTED: [],
  CANCELLED: []
};

export const SOURCE_HEALTH_STATES = [
  'HEALTHY', 'DEGRADED', 'STALE', 'OFFLINE', 'MISCONFIGURED', 'DISABLED'
];

// Operating mode is deliberately independent of health: a REPLAY source can be perfectly
// healthy while telling you nothing about the live city.
export const SOURCE_MODES = ['LIVE_API', 'HISTORICAL', 'REPLAY', 'SYNTHETIC', 'MANUAL'];

export const VALIDATION_OUTCOMES = ['ACCEPTED', 'ACCEPTED_WITH_WARNING', 'QUARANTINED', 'REJECTED'];

export const ANOMALY_RULES = [
  { id: 'R-DOMAIN-01', family: 'Domain threshold', example: 'Water level crosses configured alert threshold.' },
  { id: 'R-BASE-01', family: 'Robust baseline', example: 'Traffic speed unusually low vs recent history (robust z-score).' },
  { id: 'R-RATE-01', family: 'Rate of change', example: 'Water level rises faster than configured rate.' },
  { id: 'R-HEALTH-01', family: 'Sensor health', example: 'Flatline, impossible jump, stale heartbeat, repeated payload.' },
  { id: 'R-XSIGNAL-01', family: 'Cross-signal inconsistency', example: 'Nearby sensors disagree beyond tolerance.' }
];

// Primary key per label, matching the Neo4j property names in the product schema.
const ID_KEYS = {
  Event: 'event_id', Incident: 'incident_id', Asset: 'asset_id',
  Hypothesis: 'hypothesis_id', Action: 'action_id'
};

export function createStore() {
  const nodes = new Map();
  const edges = [];
  let edgeSequence = 0;

  function upsertNode(label, properties) {
    const idKey = ID_KEYS[label];
    if (!idKey) throw new Error(`unknown label ${label}`);
    const id = properties[idKey];
    if (id === undefined) throw new Error(`${label} requires ${idKey}`);
    const existing = nodes.get(`${label}:${id}`);
    if (existing) return Object.assign(existing, properties);
    const node = { _label: label, _id: id, ...properties };
    nodes.set(`${label}:${id}`, node);
    return node;
  }

  // relationship(fromLabel, fromId, type, toLabel, toId, properties)
  // Keeping labels explicit lets outgoing() resolve nodes the same way Cypher resolves them.
  function relationship(fromLabel, fromId, type, toLabel, toId, properties = {}) {
    const edge = {
      _id: `rel-${++edgeSequence}`, _type: type,
      _fromLabel: fromLabel, _from: fromId,
      _toLabel: toLabel, _to: toId,
      ...properties
    };
    edges.push(edge);
    return edge;
  }

  const find = (label, id) => nodes.get(`${label}:${id}`) || null;
  const all = label => [...nodes.values()].filter(node => node._label === label);

  // MATCH (a)-[r:TYPE]->(b) WHERE a:<label>
  const outgoing = (label, type) => edges.filter(edge =>
    edge._fromLabel === label && edge._from && (!type || edge._type === type));

  return { upsertNode, relationship, find, all, outgoing, edges, nodes };
}

// MATCH (e:Event)-[r]->(i:Incident) WHERE e.event_id = $id
export function evidenceFor(store, incidentId) {
  return store.outgoing('Event', null).filter(edge =>
    edge._toLabel === 'Incident' && edge._to === incidentId);
}

export function hypothesisEdges(store, hypothesisId) {
  return store.outgoing('Hypothesis').filter(edge => edge._from === hypothesisId);
}

export function assetEdges(store, assetId) {
  return store.outgoing('Asset').filter(edge => edge._from === assetId);
}

export function incidentAssets(store, incidentId) {
  return store.outgoing('Incident', 'AFFECTS').filter(edge => edge._from === incidentId);
}